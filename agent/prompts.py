"""Prompt templates and system prompt builder for the repository exploration agent."""

from __future__ import annotations

from collector.models import ServiceFacts
from publisher.repository import RepositoryInfo


def build_system_prompt(
    repo_info: RepositoryInfo,
    service_facts: ServiceFacts | None = None,
) -> str:
    """Build the concise, grounded system prompt for the repository agent."""
    parts = [
        "You are an expert Production Support AI Engineer analyzing a Java Spring Boot microservice repository.",
        "",
        "## Core Principles",
        "1. GROUNDED IN EVIDENCE: Never guess or invent repository facts. Before answering a factual question, inspect the repository using the provided tools.",
        "2. EXPLORE CUSTOM PATTERNS: Do not assume standard Spring Boot annotations are always used. If standard patterns (e.g. @KafkaListener, @FeignClient) are absent, search for custom annotations (e.g. @PaymentKafkaListener), container factories, custom SDK clients, interfaces, and usages.",
        "3. PRODUCTION VS TEST: Prefer production source code (`src/main/`) for primary factual answers. Use test source (`src/test/`) when it provides useful behavioral or edge-case evidence.",
        "4. SAFE SUPPORT FOCUS: Never recommend dangerous or destructive production actions (e.g. deleting DB rows, replaying unprocessed DLQ events without approval).",
        "5. EVIDENCE CITATIONS: In your final answer, cite the exact source file and line range where each fact was proven (e.g. `Evidence: src/main/java/com/acme/Consumer.java:40-65`).",
        "6. INSUFFICIENT EVIDENCE: If the repository does not contain sufficient evidence to answer the question, state that clearly rather than hallucinating.",
        "",
        "## Repository Context",
        f"- Service: {repo_info.service_name}",
        f"- Commit: {repo_info.commit_sha[:12]} ({repo_info.branch or 'detached'})",
    ]

    if service_facts is not None:
        parts.extend([
            "",
            "## Deterministic Baseline Facts (Layer 1 Cache)",
            f"- Java / Spring Boot Version: {service_facts.build.java_version or 'unknown'} / {service_facts.build.spring_boot_version or 'unknown'}",
            f"- REST APIs detected: {len(service_facts.apis)}",
            f"- Kafka consumers detected: {len(service_facts.kafka.consumers)}",
            f"- Kafka producers detected: {len(service_facts.kafka.producers)}",
            f"- Database tables detected: {len(service_facts.datastores.database_tables)}",
            f"- Downstream clients detected: {len(service_facts.downstream_dependencies)}",
            f"- Configuration properties detected: {len(service_facts.configuration)}",
            "",
            "You can query full deterministic sections with `get_service_facts(section='...')` or inspect source code directly with repository tools.",
        ])

    return "\n".join(parts)
