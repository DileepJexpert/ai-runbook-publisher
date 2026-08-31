"""Generation engine models, protocols, and errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


class UnsupportedGenerationEngineError(Exception):
    """Raised when an unrecognized engine is requested."""
    pass


class EngineConfigurationError(Exception):
    """Raised when an engine is missing required configuration or dependencies."""
    pass


@dataclass(frozen=True)
class GenerationContext:
    """Shared contextual input for all generation engines across both passes."""

    repo_path: str
    service_name: str
    commit_sha: str
    branch: str | None
    environment: str
    version: str | None

    discovery_prompt: str
    runbook_prompt: str
    service_facts_path: str
    output_dir: str

    findings_filename: str = "REPOSITORY_FINDINGS.md"
    runbook_filename: str = "RUNBOOK.md"
    agent_debug: bool = False
    output_suffix: str | None = None


@dataclass
class EngineGenerationResult:
    """The result produced by a GenerationEngine across discovery and runbook passes."""

    status: str  # "SUCCESS", "DISCOVERY_PREPARED", "RUNBOOK_PREPARED", "PREPARED", "FAILED", "CANCELLED"
    runbook_path: str | None = None
    findings_path: str | None = None
    evidence_path: str | None = None
    tool_calls: int | None = None
    engine: str = "unknown"
    error: str | None = None
    runbook_content: str = ""
    findings_content: str = ""
    discovery_status: str = "UNKNOWN"
    runbook_status: str = "UNKNOWN"


@runtime_checkable
class GenerationEngine(Protocol):
    """Protocol implemented by all generation engines."""

    def generate(self, context: GenerationContext) -> EngineGenerationResult:
        """Execute discovery and runbook generation for the given context."""
        ...


# Shared interface alias
AiGenerationEngine = GenerationEngine

