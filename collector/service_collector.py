"""Service facts collector orchestrator for Spring Boot repositories."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from publisher.repository import RepositoryInfo, inspect_repository
from publisher.repository_tools import BINARY_EXTENSIONS, IGNORED_DIRS, RepositoryTools

from .build_extractor import BuildExtractor
from .config_extractor import ConfigExtractor
from .database_extractor import DatabaseExtractor
from .deployment_extractor import DeploymentExtractor
from .downstream_extractor import DownstreamExtractor
from .health_extractor import HealthExtractor
from .java_parser import JavaParsedFile, JavaParser
from .kafka_extractor import KafkaExtractor
from .models import (
    BuildFacts,
    ConfigEntry,
    DatastoreFacts,
    DeploymentFacts,
    HealthAndMetricsFacts,
    KafkaFacts,
    ScanManifest,
    ServiceFacts,
    ServiceMeta,
)
from .spring_extractor import SpringExtractor

LOGGER = logging.getLogger(__name__)


class ServiceFactsCollector:
    """Deterministic, non-AI collector that extracts mechanically provable facts from a Spring Boot repository."""

    def __init__(self, repo_path: str) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.tools = RepositoryTools(str(self.repo_path))
        self.java_parser = JavaParser()

    def collect(
        self,
        service_name: str | None = None,
        branch: str | None = None,
        commit_sha: str | None = None,
    ) -> ServiceFacts:
        repo_info = inspect_repository(str(self.repo_path))

        service_name_val = service_name or repo_info.service_name
        branch_val = branch if branch is not None else repo_info.branch
        commit_val = commit_sha or repo_info.commit_sha

        service_meta = ServiceMeta(
            name=service_name_val,
            repository_name=Path(repo_info.path).name,
            branch=branch_val,
            commit_sha=commit_val,
            origin_url=repo_info.origin_url,
            working_tree_clean=repo_info.working_tree_clean,
        )

        warnings: list[str] = []
        status = "COMPLETE"

        # List all files
        all_eligible_files = self.tools.list_files(max_results=10000)
        files_considered = len(all_eligible_files)
        files_read = 0

        # Count ignored files roughly for manifest
        files_ignored = 0
        try:
            for root, dirs, files in os.walk(self.repo_path):
                # Prune ignored directories
                dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
                for f in files:
                    if any(f.endswith(ext) for ext in BINARY_EXTENSIONS):
                        files_ignored += 1
        except Exception:
            pass

        # 1. Parse all Java source files
        parsed_java_files: list[JavaParsedFile] = []
        java_files = [f for f in all_eligible_files if f.endswith(".java")]

        for jf in java_files:
            try:
                content = self.tools.read_file(jf)
                files_read += 1
                parsed = self.java_parser.parse(jf, content)
                parsed_java_files.append(parsed)
                if parsed.warnings:
                    warnings.extend(parsed.warnings)
            except Exception as exc:
                LOGGER.warning("Error reading or parsing Java file %s: %s", jf, exc)
                warnings.append(f"Failed to read/parse {jf}: {exc}")
                status = "PARTIAL"

        # 2. Extract Build Facts
        build_extractor = BuildExtractor(self.tools)
        build_facts = build_extractor.extract()
        if build_facts.evidence:
            files_read += 1

        # 3. Extract APIs and Validation Rules
        spring_extractor = SpringExtractor(self.java_parser)
        apis = spring_extractor.extract_apis(parsed_java_files)
        validation_rules = spring_extractor.extract_validation_rules(parsed_java_files)

        # 4. Extract Kafka Facts
        kafka_extractor = KafkaExtractor()
        kafka_facts = kafka_extractor.extract(parsed_java_files)

        # 5. Extract Datastore / Database / Aerospike Facts
        database_extractor = DatabaseExtractor(self.tools)
        datastore_facts = database_extractor.extract(parsed_java_files)

        # 6. Extract Downstream Dependencies
        downstream_extractor = DownstreamExtractor()
        downstream_facts = downstream_extractor.extract(parsed_java_files)

        # 7. Extract Health and Metrics
        config_extractor = ConfigExtractor(self.tools)
        all_configs = config_extractor.get_all_entries()
        files_read += len({c.source_file for c in all_configs if c.source_file})

        health_extractor = HealthExtractor()
        health_facts = health_extractor.extract(build_facts, all_configs, parsed_java_files)

        # 8. Extract Deployment Facts
        deployment_extractor = DeploymentExtractor(self.tools)
        deployment_facts = deployment_extractor.extract()
        if deployment_facts.evidence:
            files_read += 1

        # Collect custom referenced config keys
        referenced_keys: set[str] = set()
        for kc in kafka_facts.consumers:
            if kc.topic_config_key:
                referenced_keys.add(kc.topic_config_key)
            if kc.group_config_key:
                referenced_keys.add(kc.group_config_key)
        for kp in kafka_facts.producers:
            if kp.topic_config_key:
                referenced_keys.add(kp.topic_config_key)
        for dd in downstream_facts:
            if dd.url_config_key:
                referenced_keys.add(dd.url_config_key)
            if dd.timeout_config_key:
                referenced_keys.add(dd.timeout_config_key)
            for res in dd.resilience:
                if res.config_key:
                    referenced_keys.add(res.config_key)
                if res.property_key:
                    referenced_keys.add(res.property_key)
        for aero in datastore_facts.aerospike:
            if aero.namespace_config_key:
                referenced_keys.add(aero.namespace_config_key)
            if aero.set_config_key:
                referenced_keys.add(aero.set_config_key)

        # Filter prioritized configuration
        filtered_config = config_extractor.extract(referenced_keys)

        # Enrich downstream resilience from configs
        downstream_extractor._enrich_resilience_from_config(filtered_config, downstream_facts)

        scan_manifest = ScanManifest(
            status=status,
            files_considered=files_considered,
            files_read=files_read,
            files_ignored=files_ignored,
            warnings=warnings,
        )

        return ServiceFacts(
            schema_version="1.0",
            service=service_meta,
            build=build_facts,
            apis=apis,
            validation_rules=validation_rules,
            configuration=filtered_config,
            kafka=kafka_facts,
            datastores=datastore_facts,
            downstream_dependencies=downstream_facts,
            health_and_metrics=health_facts,
            deployment=deployment_facts,
            scan=scan_manifest,
        )


def collect_service_facts(
    repo_path: str,
    service_name: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
) -> ServiceFacts:
    """Convenience helper to run deterministic service fact collection on a local Git repository."""
    collector = ServiceFactsCollector(repo_path)
    return collector.collect(service_name=service_name, branch=branch, commit_sha=commit_sha)


def save_service_facts(facts: ServiceFacts, output_dir: Path | None = None) -> Path:
    """
    Serialize service facts to JSON deterministically without secret leakage.
    Defaults to output/<service-name>/<commit-sha-short>/service-facts.json
    """
    if output_dir is None:
        short_sha = facts.service.commit_sha[:16] if facts.service.commit_sha else "unknown"
        safe_service = "".join(c if c.isalnum() or c in "-_" else "_" for c in facts.service.name)
        target_dir = Path("output") / safe_service / short_sha
    else:
        target_dir = output_dir

    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / "service-facts.json"

    data = facts.to_dict()
    with target_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    LOGGER.info("Saved service facts to %s", target_file)
    return target_file
