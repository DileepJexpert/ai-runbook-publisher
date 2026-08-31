"""Repository providers for LOCAL developer execution vs PIPELINE CI/CD execution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

from publisher.execution_mode import (
    CommitMismatchError,
    DirtyWorkingTreeError,
    PipelineExecutionError,
)
from publisher.repository import (
    RepositoryAccessError,
    RepositoryInfo,
    inspect_repository,
    resolve_repository,
)

LOGGER = logging.getLogger(__name__)


@runtime_checkable
class RepositoryProvider(Protocol):
    """Protocol implemented by all repository providers."""

    def get_repository(self) -> RepositoryInfo:
        """Inspect and return repository metadata."""
        ...

    def validate_for_execution(self) -> None:
        """Validate repository preconditions for the active execution mode."""
        ...


class LocalRepositoryProvider:
    """
    Repository provider for LOCAL developer mode.
    Allows uncommitted changes (dirty worktrees) and local file inspection without requiring an exact pipeline commit.
    """

    def __init__(
        self,
        repo_path: str | Path,
        service_override: str | None = None,
        branch_override: str | None = None,
        commit_override: str | None = None,
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.service_override = service_override
        self.branch_override = branch_override
        self.commit_override = commit_override

    def get_repository(self) -> RepositoryInfo:
        """Inspect and return repository metadata, applying any local overrides."""
        return resolve_repository(
            repo_path=self.repo_path,
            service_override=self.service_override,
            branch_override=self.branch_override,
            commit_override=self.commit_override,
        )

    def validate_for_execution(self) -> None:
        """Local mode validation: ensures repository exists and is accessible."""
        info = self.get_repository()
        LOGGER.info(
            "LocalRepositoryProvider validated: service=%s (dirty_allowed=True, clean=%s)",
            info.service_name,
            info.working_tree_clean,
        )


class PipelineRepositoryProvider:
    """
    Repository provider for PIPELINE CI/CD mode.
    Enforces exact commit SHA, clean working tree, and verifies deployed vs analyzed commit match.
    """

    def __init__(
        self,
        repo_path: str | Path,
        expected_commit_sha: str,
        deployed_commit_sha: str | None = None,
        service_override: str | None = None,
        branch_override: str | None = None,
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.expected_commit_sha = (expected_commit_sha or "").strip()
        self.deployed_commit_sha = (deployed_commit_sha or "").strip() if deployed_commit_sha else None
        self.service_override = service_override
        self.branch_override = branch_override

        if not self.expected_commit_sha:
            raise PipelineExecutionError("PIPELINE mode requires an explicit, non-empty expected_commit_sha.")

    def get_repository(self) -> RepositoryInfo:
        """Inspect repository and return metadata with exact commit checks."""
        return resolve_repository(
            repo_path=self.repo_path,
            service_override=self.service_override,
            branch_override=self.branch_override,
        )

    def validate_for_execution(self) -> None:
        """
        Enforce strict pipeline preconditions:
        1. Repository working tree must be clean.
        2. Repository commit must match expected commit SHA.
        3. If deployed commit SHA is supplied, it must equal analyzed commit SHA.
        """
        info = self.get_repository()

        # 1. Clean working tree check
        if not info.working_tree_clean:
            raise DirtyWorkingTreeError(
                f"PIPELINE execution rejected: working tree in {self.repo_path} contains uncommitted modifications."
            )

        # 2. Exact commit SHA check
        if not info.commit_sha.startswith(self.expected_commit_sha) and not self.expected_commit_sha.startswith(info.commit_sha):
            raise CommitMismatchError(
                f"PIPELINE execution rejected: expected commit SHA '{self.expected_commit_sha}' "
                f"does not match actual repository commit SHA '{info.commit_sha}'."
            )

        # 3. Deployed commit match (if post-deployment publishing)
        if self.deployed_commit_sha:
            if not info.commit_sha.startswith(self.deployed_commit_sha) and not self.deployed_commit_sha.startswith(info.commit_sha):
                raise CommitMismatchError(
                    f"PIPELINE publishing rejected: deployed commit SHA '{self.deployed_commit_sha}' "
                    f"does not match analyzed commit SHA '{info.commit_sha}'."
                )

        LOGGER.info(
            "PipelineRepositoryProvider validated: service=%s commit=%s clean=True",
            info.service_name,
            info.commit_sha[:12],
        )
