"""Repository inspection and metadata extraction for local Spring Boot services."""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
import yaml

LOGGER = logging.getLogger(__name__)


class RepositoryAccessError(Exception):
    """Raised when repository validation or path resolution fails."""
    pass


@dataclass(frozen=True)
class RepositoryInfo:
    path: str
    service_name: str
    branch: str | None
    commit_sha: str
    origin_url: str | None
    working_tree_clean: bool = True
    repo_name: str = ""


def _run_git_cmd(repo_path: Path, args: list[str]) -> str:
    """Execute a read-only git command within repo_path and return stripped stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as exc:
        LOGGER.debug("Git command 'git %s' failed: %s", " ".join(args), exc)
    return ""


def validate_git_repo(repo_path: Path) -> None:
    """Validate that repo_path exists, is a directory, and is a valid Git repository."""
    resolved = repo_path.resolve()
    if not resolved.exists():
        raise RepositoryAccessError(f"Repository path does not exist: {resolved}")
    if not resolved.is_dir():
        raise RepositoryAccessError(f"Repository path is not a directory: {resolved}")

    # Check git repository
    is_git = _run_git_cmd(resolved, ["rev-parse", "--is-inside-work-tree"])
    if is_git.lower() != "true" and not (resolved / ".git").exists():
        raise RepositoryAccessError(f"Path is not a valid Git repository: {resolved}")

    # Check HEAD resolves
    head = _run_git_cmd(resolved, ["rev-parse", "HEAD"])
    if not head:
        LOGGER.warning("Could not resolve HEAD for Git repository at %s", resolved)


def _parse_properties_file(content: str) -> dict[str, str]:
    """Parse standard Java .properties file content into key-value pairs safely."""
    props: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            props[key.strip()] = val.strip()
        elif ":" in line:
            key, val = line.split(":", 1)
            props[key.strip()] = val.strip()
    return props


def resolve_service_name(repo_path: Path) -> str:
    """
    Resolve service name by checking Spring Boot configuration files for spring.application.name.
    Uses YAML parser for YAML files and safe properties parser for .properties files.
    Falls back to the repository directory name.
    """
    resolved = repo_path.resolve()
    
    # Priority config file locations
    candidate_files = [
        resolved / "src" / "main" / "resources" / "application.yml",
        resolved / "src" / "main" / "resources" / "application.yaml",
        resolved / "src" / "main" / "resources" / "application.properties",
        resolved / "src" / "main" / "resources" / "bootstrap.yml",
        resolved / "src" / "main" / "resources" / "bootstrap.yaml",
        resolved / "src" / "main" / "resources" / "bootstrap.properties",
        resolved / "application.yml",
        resolved / "application.yaml",
        resolved / "application.properties",
        resolved / "bootstrap.yml",
        resolved / "bootstrap.yaml",
        resolved / "bootstrap.properties",
    ]

    for config_file in candidate_files:
        if not config_file.is_file():
            continue
        try:
            content = config_file.read_text(encoding="utf-8", errors="ignore")
            if config_file.suffix in (".yml", ".yaml"):
                # Use YAML parser as primary parser
                try:
                    parsed = yaml.safe_load(content)
                    if isinstance(parsed, dict):
                        # Nested spring.application.name
                        app_name = parsed.get("spring", {}).get("application", {}).get("name")
                        if app_name and isinstance(app_name, str) and app_name.strip():
                            return app_name.strip()
                        # Flattened key in YAML
                        flat_name = parsed.get("spring.application.name")
                        if flat_name and isinstance(flat_name, str) and flat_name.strip():
                            return flat_name.strip()
                except Exception as yaml_exc:
                    LOGGER.debug("YAML parsing failed for %s: %s", config_file, yaml_exc)
            elif config_file.suffix == ".properties":
                props = _parse_properties_file(content)
                if "spring.application.name" in props and props["spring.application.name"].strip():
                    return props["spring.application.name"].strip()
        except Exception as exc:
            LOGGER.debug("Failed to read %s: %s", config_file, exc)

    # Fallback to folder name
    return resolved.name


def resolve_repo_name(repo_path: Path, origin_url: str | None = None) -> str:
    """
    Derive repository name preferably from Git origin URL (HTTPS or SSH),
    or fall back to the repository root directory name.
    """
    if origin_url and origin_url.strip():
        url = origin_url.strip()
        # Strip trailing .git and slashes
        if url.endswith(".git"):
            url = url[:-4]
        url = url.rstrip("/")
        # Handle SSH scp-like syntax: git@github.com:org/repo
        if ":" in url and "@" in url and not url.startswith("ssh://") and not url.startswith("http"):
            parts = url.split(":")[-1].split("/")
            if parts and parts[-1].strip():
                return parts[-1].strip()
        # Handle standard URLs (https://..., ssh://..., file://...)
        parts = url.split("/")
        if parts and parts[-1].strip():
            return parts[-1].strip()

    resolved = repo_path.resolve()
    return resolved.name


def resolve_branch(repo_path: Path) -> str | None:
    """Resolve current git branch. Returns None if in detached HEAD state or no branch."""
    resolved = repo_path.resolve()
    branch = _run_git_cmd(resolved, ["branch", "--show-current"])
    return branch.strip() if branch and branch.strip() else None


def resolve_commit_sha(repo_path: Path) -> str:
    """Resolve current commit SHA."""
    resolved = repo_path.resolve()
    commit = _run_git_cmd(resolved, ["rev-parse", "HEAD"])
    return commit if commit else "unknown"


def resolve_origin_url(repo_path: Path) -> str | None:
    """Resolve remote origin URL if available, else None."""
    resolved = repo_path.resolve()
    origin = _run_git_cmd(resolved, ["remote", "get-url", "origin"])
    return origin.strip() if origin and origin.strip() else None


def resolve_working_tree_clean(repo_path: Path) -> bool:
    """Check whether working tree has any uncommitted changes using read-only git command."""
    resolved = repo_path.resolve()
    status_output = _run_git_cmd(resolved, ["status", "--porcelain"])
    return len(status_output.strip()) == 0


def inspect_repository(repo_path: str) -> RepositoryInfo:
    """
    Validate repository and resolve metadata.
    Read-only inspection: never modifies Git state or checks out revisions.
    """
    path = Path(repo_path).resolve()
    validate_git_repo(path)

    service_name = resolve_service_name(path)
    branch = resolve_branch(path)
    commit_sha = resolve_commit_sha(path)
    origin_url = resolve_origin_url(path)
    working_tree_clean = resolve_working_tree_clean(path)
    repo_name = resolve_repo_name(path, origin_url)

    LOGGER.info(
        "Inspected repository metadata for %s: service=%s, repo=%s, branch=%s, commit=%s, clean=%s",
        path,
        service_name,
        repo_name,
        branch,
        commit_sha[:8] if commit_sha else "none",
        working_tree_clean,
    )

    return RepositoryInfo(
        path=str(path),
        service_name=service_name,
        branch=branch,
        commit_sha=commit_sha,
        origin_url=origin_url,
        working_tree_clean=working_tree_clean,
        repo_name=repo_name,
    )


def resolve_repository(
    repo_path: str | Path,
    service_override: str | None = None,
    branch_override: str | None = None,
    commit_override: str | None = None,
) -> RepositoryInfo:
    """
    Resolve repository metadata with optional overrides (for pipeline/CLI compatibility).
    """
    info = inspect_repository(str(repo_path))
    repo_name = info.repo_name or resolve_repo_name(Path(info.path), info.origin_url)

    return RepositoryInfo(
        path=info.path,
        service_name=service_override.strip() if service_override else info.service_name,
        branch=branch_override.strip() if branch_override else info.branch,
        commit_sha=commit_override.strip() if commit_override else info.commit_sha,
        origin_url=info.origin_url,
        working_tree_clean=info.working_tree_clean,
        repo_name=repo_name,
    )
