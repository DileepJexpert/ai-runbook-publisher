"""Generation identity, source/prompt fingerprinting, attempts, and caching metadata."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import uuid

from publisher.repository_tools import RepositoryTools

LOGGER = logging.getLogger(__name__)

DEFAULT_CONTRACT_VERSION = "2.1"
DEFAULT_PLATFORM_CONTEXT = "idfc-spring-boot-v1"


@dataclass
class GenerationMetadata:
    """Metadata representing a logical runbook generation and its execution state."""

    service_id: str
    generation_key: str
    generation_key_full: str
    source_fingerprint: str
    commit_sha: str
    branch: str | None
    working_tree_clean: bool
    prompt_fingerprint: str
    contract_version: str
    platform_context_fingerprint: str
    status: str  # "IN_PROGRESS", "COMPLETE", "FAILED"
    created_at: str
    completed_at: str | None = None
    latest_attempt_id: str | None = None
    engine: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to camelCase JSON-friendly dictionary."""
        return {
            "serviceId": self.service_id,
            "generationKey": self.generation_key,
            "generationKeyFull": self.generation_key_full,
            "sourceFingerprint": self.source_fingerprint,
            "commitSha": self.commit_sha,
            "branch": self.branch,
            "workingTreeClean": self.working_tree_clean,
            "promptFingerprint": self.prompt_fingerprint,
            "contractVersion": self.contract_version,
            "platformContextFingerprint": self.platform_context_fingerprint,
            "status": self.status,
            "createdAt": self.created_at,
            "completedAt": self.completed_at,
            "latestAttemptId": self.latest_attempt_id,
            "engine": self.engine,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenerationMetadata:
        """Parse camelCase or snake_case dictionary into GenerationMetadata."""
        return cls(
            service_id=data.get("serviceId") or data.get("service_id", ""),
            generation_key=data.get("generationKey") or data.get("generation_key", ""),
            generation_key_full=data.get("generationKeyFull") or data.get("generation_key_full", ""),
            source_fingerprint=data.get("sourceFingerprint") or data.get("source_fingerprint", ""),
            commit_sha=data.get("commitSha") or data.get("commit_sha", ""),
            branch=data.get("branch"),
            working_tree_clean=bool(data.get("workingTreeClean", data.get("working_tree_clean", True))),
            prompt_fingerprint=data.get("promptFingerprint") or data.get("prompt_fingerprint", ""),
            contract_version=data.get("contractVersion") or data.get("contract_version", DEFAULT_CONTRACT_VERSION),
            platform_context_fingerprint=data.get("platformContextFingerprint") or data.get("platform_context_fingerprint", ""),
            status=data.get("status", "IN_PROGRESS"),
            created_at=data.get("createdAt") or data.get("created_at", ""),
            completed_at=data.get("completedAt") or data.get("completed_at"),
            latest_attempt_id=data.get("latestAttemptId") or data.get("latest_attempt_id"),
            engine=data.get("engine"),
            error=data.get("error"),
        )


def calculate_source_fingerprint(repo_path: Path | str) -> str:
    """
    Deterministically hash all relevant repository source, configuration, and resource files.
    Works consistently for clean Git commits and dirty/uncommitted local modifications.
    Excludes non-source noise (.git, build, target, node_modules, IDE files, virtual environments, outputs).
    File ordering does not affect the output.
    """
    path = Path(repo_path).resolve()
    tools = RepositoryTools(str(path))
    # List all eligible files up to 100,000 files in sorted alphabetical order
    eligible_files = tools.list_files(max_results=100000)

    hasher = hashlib.sha256()
    for rel_file in eligible_files:
        file_path = path / rel_file
        try:
            content_bytes = file_path.read_bytes()
            hasher.update(rel_file.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(content_bytes)
            hasher.update(b"\x00")
        except Exception as exc:
            LOGGER.debug("Error hashing file %s for source fingerprint: %s", rel_file, exc)

    return hasher.hexdigest()


def calculate_prompt_fingerprint(
    discovery_prompt_path: Path | str | None = None,
    runbook_prompt_path: Path | str | None = None,
    discovery_content: str | None = None,
    runbook_content: str | None = None,
) -> str:
    """
    Calculate deterministic hash of authoritative generation prompts and instructions.
    Changes whenever prompts, templates, or instructions change.
    """
    hasher = hashlib.sha256()

    if discovery_content is not None:
        hasher.update(discovery_content.encode("utf-8"))
    elif discovery_prompt_path:
        p = Path(discovery_prompt_path)
        if p.exists():
            hasher.update(p.read_bytes())

    hasher.update(b"\x00")

    if runbook_content is not None:
        hasher.update(runbook_content.encode("utf-8"))
    elif runbook_prompt_path:
        p = Path(runbook_prompt_path)
        if p.exists():
            hasher.update(p.read_bytes())

    return hasher.hexdigest()


def calculate_context_fingerprint(
    contract_version: str = DEFAULT_CONTRACT_VERSION,
    platform_context: str | dict | None = DEFAULT_PLATFORM_CONTEXT,
) -> str:
    """
    Calculate deterministic hash of contract version and platform context rules.
    """
    hasher = hashlib.sha256()
    hasher.update(contract_version.encode("utf-8"))
    hasher.update(b"\x00")

    if isinstance(platform_context, dict):
        hasher.update(json.dumps(platform_context, sort_keys=True).encode("utf-8"))
    elif platform_context:
        hasher.update(str(platform_context).encode("utf-8"))

    return hasher.hexdigest()


def calculate_generation_key(
    service_id: str,
    source_fingerprint: str,
    prompt_fingerprint: str,
    contract_version: str = DEFAULT_CONTRACT_VERSION,
    platform_context_fingerprint: str = "",
) -> tuple[str, str]:
    """
    Calculate deterministic generationKey for a logical runbook generation.
    Returns (generation_key_short, generation_key_full).
    generation_key_short (16 chars) is used for directory naming.
    generation_key_full (64 chars) is preserved in metadata.
    """
    raw_payload = f"{service_id}:{source_fingerprint}:{prompt_fingerprint}:{contract_version}:{platform_context_fingerprint}"
    full_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
    short_key = full_hash[:16]
    return short_key, full_hash


def create_attempt_id() -> str:
    """Generate a unique attempt identifier for diagnostic and retry tracking."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6]
    return f"att-{ts}-{rand_suffix}"


def load_generation_metadata(output_dir: Path) -> GenerationMetadata | None:
    """Load generation-metadata.json from output_dir if it exists."""
    meta_file = output_dir / "generation-metadata.json"
    if not meta_file.exists() or not meta_file.is_file():
        return None
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        return GenerationMetadata.from_dict(data)
    except Exception as exc:
        LOGGER.debug("Could not parse %s: %s", meta_file, exc)
        return None


def save_generation_metadata(output_dir: Path, metadata: GenerationMetadata) -> None:
    """Save generation-metadata.json to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    meta_file = output_dir / "generation-metadata.json"
    meta_file.write_text(json.dumps(metadata.to_dict(), indent=2), encoding="utf-8")


def record_attempt(
    output_dir: Path,
    attempt_id: str,
    status: str,
    engine: str,
    error: str | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    agent_log: str | None = None,
) -> Path:
    """Record an execution attempt in output_dir/attempts/<attempt_id>/."""
    attempt_dir = output_dir / "attempts" / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=True)

    attempt_meta = {
        "attemptId": attempt_id,
        "status": status,
        "engine": engine,
        "recordedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "error": error,
    }
    (attempt_dir / "attempt-metadata.json").write_text(json.dumps(attempt_meta, indent=2), encoding="utf-8")

    if stdout is not None:
        (attempt_dir / "stdout.log").write_text(stdout, encoding="utf-8")
    if stderr is not None:
        (attempt_dir / "stderr.log").write_text(stderr, encoding="utf-8")
    if agent_log is not None:
        (attempt_dir / "agent.log").write_text(agent_log, encoding="utf-8")

    return attempt_dir
