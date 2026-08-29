"""Read-only repository access tools for deterministic collectors and AI agents."""

from __future__ import annotations

import fnmatch
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .repository import RepositoryAccessError, inspect_repository, validate_git_repo

LOGGER = logging.getLogger(__name__)

# Standard non-code, build, and metadata directories to always ignore
IGNORED_DIRS = {
    ".git",
    "target",
    "build",
    "node_modules",
    "generated-sources",
    "generated",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
}

# Binary and archive file extensions to ignore
BINARY_EXTENSIONS = {
    ".class",
    ".jar",
    ".war",
    ".ear",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".pyc",
    ".pyo",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
}


@dataclass(frozen=True)
class SearchResult:
    file: str
    line: int
    text: str


class RepositoryTools:
    """
    Provides safe, strictly read-only access to a local Git repository.
    Guarantees no file modification, no arbitrary shell execution, and no full-repo concatenation.
    """

    def __init__(self, repo_path: str) -> None:
        self.repo_path = Path(repo_path).resolve()
        validate_git_repo(self.repo_path)

    def _resolve_secure_path(self, relative_path: str, must_exist: bool = True) -> Path:
        """
        Validate and resolve a repository-relative path.
        Prevents path traversal, absolute path injections, and symlink escapes.
        """
        if not relative_path or not relative_path.strip():
            raise RepositoryAccessError("Path cannot be empty.")

        rel = relative_path.strip().replace("\\", "/")

        # Reject absolute paths (Unix '/' or Windows 'C:')
        if rel.startswith("/") or (len(rel) > 1 and rel[1] == ":"):
            raise RepositoryAccessError(f"Absolute paths are rejected: {relative_path}")

        # Check for symlink escape first
        raw_path = self.repo_path / rel
        if raw_path.is_symlink():
            try:
                raw_path.resolve().relative_to(self.repo_path)
            except ValueError:
                raise RepositoryAccessError(f"Symlink escapes repository: {relative_path}")

        target = raw_path.resolve()

        # Ensure resolved path is strictly within the repository root
        try:
            target.relative_to(self.repo_path)
        except ValueError:
            raise RepositoryAccessError(f"Path traversal escape detected: {relative_path}")

        if must_exist and not target.exists():
            raise RepositoryAccessError(f"File not found: {relative_path}")

        return target

    def list_files(
        self,
        path: str = "",
        pattern: str | None = None,
        max_results: int = 200,
    ) -> list[str]:
        """
        Recursively list eligible text files in deterministic alphabetical order.
        Respects directory exclusions and glob filtering without excluding src/test.
        """
        if path and path.strip():
            start_dir = self._resolve_secure_path(path)
            if not start_dir.is_dir():
                raise RepositoryAccessError(f"Path is not a directory: {path}")
        else:
            start_dir = self.repo_path

        eligible_files: list[str] = []

        for root, dirs, files in os.walk(start_dir):
            # Exclude ignored directory names in-place
            dirs[:] = [
                d for d in dirs
                if d not in IGNORED_DIRS
                and not d.startswith(".")
                and not (Path(root) / d).is_symlink()
            ]

            for file_name in files:
                suffix = Path(file_name).suffix.lower()
                if suffix in BINARY_EXTENSIONS:
                    continue

                full_file_path = Path(root) / file_name
                
                # Check symlink escapes
                if full_file_path.is_symlink():
                    try:
                        full_file_path.resolve().relative_to(self.repo_path)
                    except ValueError:
                        continue

                rel_posix = full_file_path.relative_to(self.repo_path).as_posix()

                # Apply glob pattern if provided
                if pattern:
                    if not (fnmatch.fnmatch(rel_posix, pattern) or fnmatch.fnmatch(file_name, pattern)):
                        continue

                eligible_files.append(rel_posix)

        eligible_files.sort()
        return eligible_files[:max_results]

    def search_code(
        self,
        query: str,
        file_glob: str | None = None,
        max_results: int = 50,
        case_sensitive: bool = True,
    ) -> list[SearchResult]:
        """
        Literal text search across repository text files.
        Returns deterministic results with relative path, 1-based line number, and matching text.
        """
        if not query:
            return []

        results: list[SearchResult] = []
        candidate_files = self.list_files(pattern=file_glob, max_results=10000)

        for rel_file in candidate_files:
            abs_path = self.repo_path / rel_file
            try:
                with abs_path.open("r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, start=1):
                        match = (query in line) if case_sensitive else (query.lower() in line.lower())
                        if match:
                            results.append(SearchResult(
                                file=rel_file,
                                line=line_num,
                                text=line.rstrip("\r\n"),
                            ))
                            if len(results) >= max_results:
                                return results
            except Exception as exc:
                LOGGER.debug("Error searching file %s: %s", rel_file, exc)

        return results

    def read_file(
        self,
        relative_path: str,
        max_chars: int = 30000,
    ) -> str:
        """
        Safely read a text file, enforcing path bounds and maximum character limits.
        """
        abs_path = self._resolve_secure_path(relative_path, must_exist=True)

        if abs_path.is_dir():
            raise RepositoryAccessError(f"Path is a directory: {relative_path}")

        if abs_path.suffix.lower() in BINARY_EXTENSIONS:
            raise RepositoryAccessError(f"Cannot read binary file: {relative_path}")

        try:
            raw_bytes = abs_path.read_bytes()
            if b"\x00" in raw_bytes[:4096]:
                raise RepositoryAccessError(f"File contains binary data: {relative_path}")
            content = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            try:
                content = raw_bytes.decode("latin-1")
            except Exception:
                raise RepositoryAccessError(f"Failed to decode text file: {relative_path}")
        except OSError as exc:
            raise RepositoryAccessError(f"Failed to read file {relative_path}: {exc}")

        if len(content) > max_chars:
            return content[:max_chars] + "\n[TRUNCATED]"
        return content

    def read_lines(
        self,
        relative_path: str,
        start_line: int,
        end_line: int,
    ) -> str:
        """
        Read a specified range of lines from a file with 1-based line numbering prefix.
        Limits range to a maximum of 500 lines.
        """
        if start_line < 1:
            raise RepositoryAccessError(f"start_line must be >= 1 (got {start_line})")
        if end_line < start_line:
            raise RepositoryAccessError(f"end_line ({end_line}) cannot be less than start_line ({start_line})")
        
        line_count = end_line - start_line + 1
        if line_count > 500:
            raise RepositoryAccessError(f"Requested line range ({line_count}) exceeds maximum allowed (500 lines).")

        content = self.read_file(relative_path, max_chars=1_000_000)
        lines = content.splitlines()

        total_lines = len(lines)
        if start_line > total_lines:
            return ""

        effective_end = min(end_line, total_lines)
        selected_lines = lines[start_line - 1:effective_end]

        formatted = [
            f"{start_line + idx} | {line}"
            for idx, line in enumerate(selected_lines)
        ]
        return "\n".join(formatted)

    def git_metadata(self) -> dict:
        """Return standardized repository Git and service metadata."""
        info = inspect_repository(str(self.repo_path))
        return {
            "serviceName": info.service_name,
            "branch": info.branch,
            "commitSha": info.commit_sha,
            "originUrl": info.origin_url,
            "repositoryName": Path(info.path).name,
            "repositoryPath": info.path,
            "workingTreeClean": info.working_tree_clean,
        }

    def git_file_history(
        self,
        relative_path: str,
        max_commits: int = 10,
    ) -> list[dict]:
        """Return recent commit history for a specific file using predefined git commands."""
        abs_path = self._resolve_secure_path(relative_path, must_exist=True)
        try:
            result = subprocess.run(
                [
                    "git",
                    "log",
                    f"-n{max(1, max_commits)}",
                    "--format=%H%x1f%aI%x1f%an%x1f%s",
                    "--",
                    str(abs_path),
                ],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return []

            commits: list[dict] = []
            for line in result.stdout.strip().splitlines():
                parts = line.split("\x1f")
                if len(parts) >= 4:
                    commits.append({
                        "commitSha": parts[0],
                        "date": parts[1],
                        "author": parts[2],
                        "subject": parts[3],
                    })
            return commits
        except Exception as exc:
            LOGGER.debug("Git file history query failed for %s: %s", relative_path, exc)
            return []
