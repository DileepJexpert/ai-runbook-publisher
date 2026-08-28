"""Collect the operationally relevant portions of a Spring Boot repository."""

from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)
EXCLUDED_DIRS = {".git", "target", "node_modules", "generated-sources", "src/test"}
EXCLUDED_SUFFIXES = {".class", ".jar", ".war", ".png", ".jpg", ".jpeg", ".ico"}


@dataclass(frozen=True)
class CollectionStats:
    included: int
    skipped_budget: int
    skipped_excluded: int
    coverage: str


_last_stats = CollectionStats(0, 0, 0, "COMPLETE")


def get_last_collection_stats() -> CollectionStats:
    return _last_stats


def find_files_containing(repo_path: str, pattern: str) -> list[str]:
    """Return repository-relative, readable text files containing *pattern*."""
    root = Path(repo_path)
    matches: list[str] = []
    for path in _walk_files(root):
        try:
            if pattern in path.read_text(encoding="utf-8", errors="ignore"):
                matches.append(path.relative_to(root).as_posix())
        except OSError:
            LOGGER.warning("Could not read %s while searching", path)
    return matches


def collect_repo(repo_path: str, max_tokens: int) -> str:
    """Return prioritized repository content, limited by the approximate token budget."""
    global _last_stats
    root = Path(repo_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Repository path does not exist or is not a directory: {repo_path}")
    if max_tokens <= 0:
        raise ValueError("repo_max_tokens must be greater than zero")

    LOGGER.info("Starting repository collection from %s", root)
    excluded = 0
    candidates: list[tuple[int, str, str]] = []
    for path in _walk_files(root):
        relative = path.relative_to(root).as_posix()
        if _is_excluded(relative):
            excluded += 1
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            excluded += 1
            continue
        priority = _priority(relative, content)
        if priority is not None:
            candidates.append((priority, relative, content))

    candidates.sort(key=lambda item: (item[0], item[1]))
    selected: list[str] = []
    used_tokens = 0
    skipped_budget = 0
    for _, relative, content in candidates:
        file_tokens = max(1, len(content) // 4)
        if used_tokens + file_tokens > max_tokens:
            skipped_budget += 1
            continue
        selected.append(f"=== FILE: {relative} ===\n{content}\n=== END FILE ===")
        used_tokens += file_tokens

    coverage = "PARTIAL" if skipped_budget else "COMPLETE"
    _last_stats = CollectionStats(len(selected), skipped_budget, excluded, coverage)
    manifest = (
        "=== REPOSITORY MANIFEST ===\n"
        f"Files included: {len(selected)}\n"
        f"Files skipped (budget): {skipped_budget}\n"
        f"Files skipped (excluded): {excluded}\n"
        f"Scan coverage: {coverage}\n"
        "=== END REPOSITORY MANIFEST ==="
    )
    LOGGER.info("Repository collection complete: %d files, approximately %d/%d tokens", len(selected), used_tokens, max_tokens)
    if coverage == "PARTIAL":
        LOGGER.warning("Repository scan coverage is PARTIAL; %d relevant files did not fit", skipped_budget)
    return manifest + ("\n\n" + "\n\n".join(selected) if selected else "")


def _walk_files(root: Path):
    for directory, subdirs, files in os.walk(root):
        rel_dir = Path(directory).relative_to(root).as_posix()
        subdirs[:] = [d for d in subdirs if f"{rel_dir}/{d}".strip("/") not in EXCLUDED_DIRS and d not in EXCLUDED_DIRS]
        for filename in files:
            yield Path(directory) / filename


def _is_excluded(relative: str) -> bool:
    path = relative.lower()
    return any(path.endswith(suffix) for suffix in EXCLUDED_SUFFIXES)


def _priority(relative: str, content: str) -> int | None:
    name = Path(relative).name
    lower = relative.lower()
    critical_names = (
        fnmatch.fnmatch(name, "application*.yml") or fnmatch.fnmatch(name, "application*.yaml")
        or fnmatch.fnmatch(name, "application*.properties") or name in {"bootstrap.yml", "bootstrap.yaml", "bootstrap.properties", "pom.xml", "build.gradle", "build.gradle.kts"}
    )
    if critical_names or "@RestController" in content or "@KafkaListener" in content or "@SpringBootApplication" in content or ("helm" in lower and fnmatch.fnmatch(name, "values*.yaml")) or (lower.endswith(".sql") and ("migration" in lower or "flyway" in lower)):
        return 0
    if any(marker in content for marker in ("@Service", "@Entity", "@ConfigurationProperties", "@ControllerAdvice", "KafkaTemplate", "RestClient", "WebClient", "Feign", "@Scheduled")) or any(word in name for word in ("DTO", "Request", "Response")):
        return 1
    if "repository" in lower or any(word in name.lower() for word in ("mapper", "converter")) or name.endswith("Enum.java"):
        return 2
    return None
