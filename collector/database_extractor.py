"""Database, JPA, Flyway, and Aerospike fact extractor."""

from __future__ import annotations

import logging
import re
from typing import Any

from publisher.repository_tools import RepositoryTools

from .config_extractor import parse_placeholder
from .java_parser import JavaAnnotation, JavaClass, JavaParsedFile
from .models import AerospikeFact, DatabaseTableFact, DatastoreFacts, RepositoryInterfaceFact, SourceEvidence

LOGGER = logging.getLogger(__name__)

SPRING_DATA_REPO_INTERFACES = {
    "JpaRepository",
    "CrudRepository",
    "PagingAndSortingRepository",
    "Repository",
    "ListCrudRepository",
    "ListPagingAndSortingRepository",
    "AerospikeRepository",
}


class DatabaseExtractor:
    """Extracts JPA entities, repository interfaces, Flyway/Liquibase migration tables, and Aerospike usage."""

    def __init__(self, tools: RepositoryTools) -> None:
        self.tools = tools

    def extract(self, parsed_files: list[JavaParsedFile]) -> DatastoreFacts:
        tables: dict[str, DatabaseTableFact] = {}
        repositories: list[RepositoryInterfaceFact] = []
        aerospike_facts: list[AerospikeFact] = []

        # 1. Extract JPA Entities
        for pfile in parsed_files:
            for cls in pfile.classes:
                is_entity = any(a.name == "Entity" for a in cls.annotations)
                if is_entity:
                    table_fact = self._extract_jpa_entity(pfile.file_path, cls)
                    tables[table_fact.table_name.upper()] = table_fact

                # Check for Spring Data Repository interfaces
                if cls.class_type == "interface":
                    repo_fact = self._extract_repository_interface(pfile.file_path, cls)
                    if repo_fact:
                        repositories.append(repo_fact)

        # 2. Extract Flyway / Liquibase SQL migration tables
        sql_tables = self._extract_sql_migrations()
        for st in sql_tables:
            k = st.table_name.upper()
            if k not in tables:
                tables[k] = st
            else:
                # Merge columns or update source type
                existing = tables[k]
                merged_cols = sorted(list(set(existing.columns + st.columns)))
                merged_ids = sorted(list(set(existing.identifier_columns + st.identifier_columns)))
                tables[k] = DatabaseTableFact(
                    table_name=existing.table_name,
                    schema_name=existing.schema_name or st.schema_name,
                    entity_class=existing.entity_class,
                    source_type="JPA+FLYWAY" if existing.source_type == "JPA" else existing.source_type,
                    identifier_columns=merged_ids,
                    columns=merged_cols,
                    observed_access=existing.observed_access,
                    evidence=existing.evidence,
                )

        # 3. Observe technical database access (e.g. save, findById, delete)
        self._observe_database_access(parsed_files, tables, repositories)

        # 4. Aerospike detection
        aerospike = self._extract_aerospike(parsed_files)
        if aerospike:
            aerospike_facts.append(aerospike)

        return DatastoreFacts(
            database_tables=list(tables.values()),
            repositories=repositories,
            aerospike=aerospike_facts,
        )

    def _extract_jpa_entity(self, file_path: str, cls: JavaClass) -> DatabaseTableFact:
        table_name = cls.name
        schema_name = None

        for anno in cls.annotations:
            if anno.name == "Table":
                t_val = anno.get_attr("name") or anno.get_attr("value")
                if t_val:
                    table_name = str(t_val).strip('"\'')
                s_val = anno.get_attr("schema")
                if s_val:
                    schema_name = str(s_val).strip('"\'')

        identifiers: list[str] = []
        columns: list[str] = []

        for field in cls.fields:
            col_name = field.name
            is_id = False
            for a in field.annotations:
                if a.name in {"Id", "EmbeddedId"}:
                    is_id = True
                if a.name == "Column":
                    c_name = a.get_attr("name") or a.get_attr("value")
                    if c_name:
                        col_name = str(c_name).strip('"\'')

            columns.append(col_name)
            if is_id:
                identifiers.append(col_name)

        evidence = SourceEvidence(file=file_path, line_start=cls.line_start, line_end=cls.line_end)

        return DatabaseTableFact(
            table_name=table_name,
            schema_name=schema_name,
            entity_class=cls.name,
            source_type="JPA",
            identifier_columns=identifiers,
            columns=columns,
            evidence=evidence,
        )

    def _extract_repository_interface(self, file_path: str, cls: JavaClass) -> RepositoryInterfaceFact | None:
        extends_all = [cls.extends_class] if cls.extends_class else []
        extends_all.extend(cls.implements_interfaces)

        for ext in extends_all:
            if not ext:
                continue
            for repo_type in SPRING_DATA_REPO_INTERFACES:
                if ext.startswith(repo_type) or f"<{repo_type}>" in ext:
                    # Extract entity from generic type e.g. JpaRepository<Payment, String>
                    entity_match = re.search(r"<\s*([A-Za-z0-9_]+)", ext)
                    entity_name = entity_match.group(1) if entity_match else None
                    evidence = SourceEvidence(file=file_path, line_start=cls.line_start, line_end=cls.line_end)
                    return RepositoryInterfaceFact(
                        interface_name=cls.name,
                        entity_class=entity_name,
                        repository_type=repo_type,
                        evidence=evidence,
                    )
        return None

    def _extract_sql_migrations(self) -> list[DatabaseTableFact]:
        tables: list[DatabaseTableFact] = []

        try:
            files = self.tools.list_files(max_results=1000)
        except Exception:
            files = []

        migration_files = [f for f in files if "migration" in f.lower() and f.endswith(".sql")]

        for mf in migration_files:
            try:
                content = self.tools.read_file(mf)
                lines = content.splitlines()

                # Search for CREATE TABLE [IF NOT EXISTS] [schema.]table_name ( ... )
                create_table_regex = re.compile(
                    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:([A-Za-z0-9_]+)\.)?([A-Za-z0-9_]+)\s*\((.*?)\);",
                    re.IGNORECASE | re.DOTALL,
                )

                for match in create_table_regex.finditer(content):
                    schema_name = match.group(1)
                    tbl_name = match.group(2)
                    cols_block = match.group(3)

                    line_start = content[: match.start()].count("\n") + 1
                    line_end = content[: match.end()].count("\n") + 1

                    cols: list[str] = []
                    ids: list[str] = []

                    # Parse columns inside parenthesis
                    for line in cols_block.splitlines():
                        clean = line.strip().strip(",")
                        if not clean or clean.upper().startswith(("PRIMARY KEY", "CONSTRAINT", "FOREIGN KEY", "UNIQUE", "CHECK", "INDEX", "--", "/*")):
                            # Check if inline PRIMARY KEY (col_name)
                            pk_match = re.search(r"PRIMARY\s+KEY\s*\(\s*([A-Za-z0-9_]+)\s*\)", clean, re.IGNORECASE)
                            if pk_match:
                                ids.append(pk_match.group(1))
                            continue

                        parts = clean.split()
                        if parts:
                            c_name = parts[0].strip('"`[]')
                            cols.append(c_name)
                            if "PRIMARY KEY" in clean.upper():
                                ids.append(c_name)

                    evidence = SourceEvidence(file=mf, line_start=line_start, line_end=line_end)
                    tables.append(
                        DatabaseTableFact(
                            table_name=tbl_name,
                            schema_name=schema_name,
                            source_type="FLYWAY",
                            identifier_columns=ids,
                            columns=cols,
                            evidence=evidence,
                        )
                    )
            except Exception as exc:
                LOGGER.warning("Could not parse SQL migration file %s: %s", mf, exc)

        return tables

    def _observe_database_access(
        self,
        parsed_files: list[JavaParsedFile],
        tables: dict[str, DatabaseTableFact],
        repositories: list[RepositoryInterfaceFact],
    ) -> None:
        # Build map of repository bean names to entity/table
        repo_to_entity = {}
        for repo in repositories:
            if repo.entity_class:
                repo_to_entity[repo.interface_name] = repo.entity_class
                # Also decapitalized name e.g. paymentRepository
                decap = repo.interface_name[0].lower() + repo.interface_name[1:]
                repo_to_entity[decap] = repo.entity_class

        entity_to_access: dict[str, set[str]] = {}

        for pfile in parsed_files:
            for cls in pfile.classes:
                for method in cls.methods:
                    body = method.body
                    for repo_name, entity in repo_to_entity.items():
                        if repo_name in body:
                            if entity not in entity_to_access:
                                entity_to_access[entity] = set()
                            if f"{repo_name}.save" in body or f"{repo_name}.saveAll" in body:
                                entity_to_access[entity].add("SAVE")
                            if f"{repo_name}.delete" in body or f"{repo_name}.deleteById" in body:
                                entity_to_access[entity].add("DELETE")
                            if f"{repo_name}.find" in body:
                                entity_to_access[entity].add("FIND")

        # Apply observed access to tables
        for entity_name, accesses in entity_to_access.items():
            for tbl_key, tbl in list(tables.items()):
                if tbl.entity_class == entity_name or tbl.table_name.upper() == entity_name.upper():
                    merged = sorted(list(set(tbl.observed_access + list(accesses))))
                    tables[tbl_key] = DatabaseTableFact(
                        table_name=tbl.table_name,
                        schema_name=tbl.schema_name,
                        entity_class=tbl.entity_class,
                        source_type=tbl.source_type,
                        identifier_columns=tbl.identifier_columns,
                        columns=tbl.columns,
                        observed_access=merged,
                        evidence=tbl.evidence,
                    )

    def _extract_aerospike(self, parsed_files: list[JavaParsedFile]) -> AerospikeFact | None:
        aerospike_detected = False
        client_usages: list[str] = []
        set_name = None
        evidence = None

        for pfile in parsed_files:
            for cls in pfile.classes:
                for a in cls.annotations:
                    if a.name == "Document" and ("collection" in a.attributes or "set" in a.attributes):
                        aerospike_detected = True
                        set_name = str(a.get_attr("collection") or a.get_attr("set")).strip('"\'')
                        evidence = SourceEvidence(file=pfile.file_path, line_start=a.line_start, line_end=a.line_end)

                if "AerospikeTemplate" in cls.raw_content or "AerospikeClient" in cls.raw_content:
                    aerospike_detected = True
                    client_usages.append(cls.name)
                    if not evidence:
                        evidence = SourceEvidence(file=pfile.file_path, line_start=cls.line_start, line_end=cls.line_end)

        if aerospike_detected:
            return AerospikeFact(
                detected=True,
                client_usage=list(set(client_usages)),
                set_name=set_name,
                evidence=evidence,
            )
        return None
