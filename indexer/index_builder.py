"""Index builder: orchestrates all splitters and produces a CodeIndexStore.

No LLM. No embeddings. Local deterministic indexing only.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from publisher.repository_tools import RepositoryTools

from collector.java_parser import JavaParser

from .code_splitter import JavaCodeSplitter
from .config_splitter import (
    MarkdownSplitter,
    PropertiesSplitter,
    SqlSplitter,
    XmlSplitter,
    YamlSplitter,
)
from .index_store import CodeIndexStore, _SCHEMA_VERSION
from .models import (
    CodeChunk,
    IndexManifest,
    SOURCE_SCOPE_PRODUCTION,
    SOURCE_SCOPE_TEST,
    SymbolReference,
    _compute_content_hash,
)

LOGGER = logging.getLogger(__name__)

# File classification
_JAVA_EXTS = {".java"}
_YAML_EXTS = {".yml", ".yaml"}
_PROPS_EXTS = {".properties"}
_SQL_EXTS = {".sql"}
_XML_EXTS = {".xml"}
_MD_EXTS = {".md", ".markdown"}

# YAML files that represent configuration (not all YAML is Spring config)
_CONFIG_YAML_NAMES = {
    "application.yml", "application.yaml",
    "bootstrap.yml", "bootstrap.yaml",
    "values.yaml", "values.yml",
    "Chart.yaml", "Chart.yml",
}
_CONFIG_YAML_PREFIXES = ("application-", "bootstrap-")


def _is_config_yaml(file_path: str) -> bool:
    name = Path(file_path).name
    return name in _CONFIG_YAML_NAMES or any(name.startswith(p) for p in _CONFIG_YAML_PREFIXES)


def _is_migration_sql(file_path: str) -> bool:
    posix = file_path.replace("\\", "/")
    return "/migration" in posix or "/migrations" in posix or "/db/" in posix


def _is_useful_xml(file_path: str) -> bool:
    name = Path(file_path).name.lower()
    return name in {"pom.xml"} or "liquibase" in name or "flyway" in name or "changelog" in name


def _is_useful_markdown(file_path: str) -> bool:
    name = Path(file_path).name.lower()
    posix = file_path.replace("\\", "/").lower()
    # Include README and docs/
    return (
        name.startswith("readme")
        or "/docs/" in posix
        or "/doc/" in posix
        or "/adr/" in posix
        or "/architecture" in posix
    )


class CodeIndexBuilder:
    """Builds a deterministic, searchable CodeIndexStore from a Java Spring Boot repository."""

    def __init__(self, max_chunk_chars: int = 20_000) -> None:
        self.max_chunk_chars = max_chunk_chars

    def build(
        self,
        repo_path: str,
        service_name: str,
        commit_sha: str,
    ) -> CodeIndexStore:
        """Build a complete code index for the given repository snapshot."""
        t0 = time.time()
        repo_root = Path(repo_path).resolve()

        tools = RepositoryTools(str(repo_root))
        java_parser = JavaParser()
        java_splitter = JavaCodeSplitter(java_parser=java_parser, max_chunk_chars=self.max_chunk_chars)
        yaml_splitter = YamlSplitter()
        props_splitter = PropertiesSplitter()
        sql_splitter = SqlSplitter()
        xml_splitter = XmlSplitter()
        md_splitter = MarkdownSplitter()

        all_files = tools.list_files(max_results=10_000)

        all_chunks: list[CodeChunk] = []
        all_refs: list[SymbolReference] = []
        warnings: list[str] = []
        files_indexed = 0

        for rel_path in all_files:
            ext = Path(rel_path).suffix.lower()

            try:
                content = tools.read_file(rel_path, max_chars=500_000)
            except Exception as exc:
                LOGGER.debug("Skipping unreadable file %s: %s", rel_path, exc)
                warnings.append(f"Unreadable: {rel_path}: {exc}")
                continue

            chunks: list[CodeChunk] = []
            refs: list[SymbolReference] = []

            if ext in _JAVA_EXTS:
                try:
                    chunks, refs = java_splitter.split_file(rel_path, content)
                    files_indexed += 1
                except Exception as exc:
                    LOGGER.warning("Java split error for %s: %s", rel_path, exc)
                    warnings.append(f"Java split error {rel_path}: {exc}")

            elif ext in _YAML_EXTS and _is_config_yaml(rel_path):
                try:
                    chunks = yaml_splitter.split_file(rel_path, content)
                    files_indexed += 1
                except Exception as exc:
                    LOGGER.debug("YAML split error for %s: %s", rel_path, exc)
                    warnings.append(f"YAML split error {rel_path}: {exc}")

            elif ext in _PROPS_EXTS:
                try:
                    chunks = props_splitter.split_file(rel_path, content)
                    files_indexed += 1
                except Exception as exc:
                    LOGGER.debug("Properties split error for %s: %s", rel_path, exc)

            elif ext in _SQL_EXTS and _is_migration_sql(rel_path):
                try:
                    chunks = sql_splitter.split_file(rel_path, content)
                    files_indexed += 1
                except Exception as exc:
                    LOGGER.debug("SQL split error for %s: %s", rel_path, exc)

            elif ext in _XML_EXTS and _is_useful_xml(rel_path):
                try:
                    chunks = xml_splitter.split_file(rel_path, content)
                    files_indexed += 1
                except Exception as exc:
                    LOGGER.debug("XML split error for %s: %s", rel_path, exc)

            elif ext in _MD_EXTS and _is_useful_markdown(rel_path):
                try:
                    chunks = md_splitter.split_file(rel_path, content)
                    files_indexed += 1
                except Exception as exc:
                    LOGGER.debug("Markdown split error for %s: %s", rel_path, exc)

            all_chunks.extend(chunks)
            all_refs.extend(refs)

        # Deduplicate by (chunk_id) — keep first occurrence
        seen_ids: set[str] = set()
        deduped: list[CodeChunk] = []
        for c in all_chunks:
            if c.chunk_id not in seen_ids:
                seen_ids.add(c.chunk_id)
                deduped.append(c)
            else:
                # Same chunk_id but different location → append location suffix
                suffix_id = f"{c.chunk_id}__L{c.start_line}"
                if suffix_id not in seen_ids:
                    seen_ids.add(suffix_id)
                    import dataclasses
                    deduped.append(dataclasses.replace(c, chunk_id=suffix_id))

        all_chunks = deduped

        # Build indexes
        symbol_index: dict[str, list[str]] = defaultdict(list)
        annotation_index: dict[str, list[str]] = defaultdict(list)
        config_key_index: dict[str, list[str]] = defaultdict(list)

        for chunk in all_chunks:
            # Symbol index
            if chunk.symbol_name:
                symbol_index[chunk.symbol_name].append(chunk.chunk_id)
                # Also index short name (last segment after '.')
                parts = chunk.symbol_name.split(".")
                if len(parts) > 1:
                    symbol_index[parts[-1]].append(chunk.chunk_id)
            if chunk.class_name:
                symbol_index[chunk.class_name].append(chunk.chunk_id)
            if chunk.method_name:
                symbol_index[chunk.method_name].append(chunk.chunk_id)

            # Annotation index
            for anno in chunk.annotations:
                norm = anno if anno.startswith("@") else f"@{anno}"
                annotation_index[norm].append(chunk.chunk_id)

            # Config key index
            if chunk.language in ("yaml", "properties") and chunk.symbol_name:
                config_key_index[chunk.symbol_name].append(chunk.chunk_id)
                # Also add individual key segments
                for seg in chunk.symbol_name.split("."):
                    if seg:
                        config_key_index[seg].append(chunk.chunk_id)

        # Chunk-type summary
        chunk_type_counts: dict[str, int] = defaultdict(int)
        prod_count = 0
        test_count = 0
        for c in all_chunks:
            chunk_type_counts[c.chunk_type] += 1
            if c.source_scope == SOURCE_SCOPE_TEST:
                test_count += 1
            else:
                prod_count += 1

        elapsed = time.time() - t0
        LOGGER.info(
            "Index built for %s@%s: %d files → %d chunks in %.2fs",
            service_name, commit_sha[:12], files_indexed, len(all_chunks), elapsed,
        )

        manifest = IndexManifest(
            schema_version=_SCHEMA_VERSION,
            service_name=service_name,
            commit_sha=commit_sha,
            created_at=datetime.now(timezone.utc).isoformat(),
            chunk_count=len(all_chunks),
            production_chunk_count=prod_count,
            test_chunk_count=test_count,
            file_count=files_indexed,
            chunk_types=dict(chunk_type_counts),
            warnings=warnings[:50],
        )

        return CodeIndexStore(
            manifest=manifest,
            chunks=all_chunks,
            symbol_index=dict(symbol_index),
            annotation_index=dict(annotation_index),
            config_key_index=dict(config_key_index),
            references=all_refs,
        )
