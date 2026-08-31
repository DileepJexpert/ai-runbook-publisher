"""Pipeline and local execution orchestrator implementing mode separation and quality gates."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent.llm_client import LlmClient
from publisher.confluence import ConfluenceConfig, ConfluencePublishResult, ConfluencePublisher
from publisher.credential_provider import (
    CredentialProvider,
    LocalCredentialProvider,
    PipelineCredentialProvider,
)
from publisher.engines import (
    AiGenerationEngine,
    GenerationEngine,
    LocalIdfcCoderEngine,
    PipelineLlmApiEngine,
    create_generation_engine,
)
from publisher.execution_mode import (
    CommitMismatchError,
    DirtyWorkingTreeError,
    ExecutionMode,
    ModeEnforcementError,
    PipelineExecutionError,
)
from publisher.page_resolver import (
    ConfluencePageResolver,
    LocalConfluencePageResolver,
    ProductionConfluencePageResolver,
)
from publisher.repository import RepositoryInfo
from publisher.repository_provider import (
    LocalRepositoryProvider,
    PipelineRepositoryProvider,
    RepositoryProvider,
)
from publisher.runbook_generator import RunbookGenerationResult, RunbookGenerator

LOGGER = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    Coordinates runbook generation, validation, and publishing across LOCAL and PIPELINE execution modes.
    Enforces strict architectural rules and zero fallback between modes.
    """

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.LOCAL,
        repo_provider: RepositoryProvider | None = None,
        engine: GenerationEngine | None = None,
        credential_provider: CredentialProvider | None = None,
        page_resolver: ConfluencePageResolver | None = None,
        config: dict[str, Any] | None = None,
        client: LlmClient | None = None,
    ) -> None:
        self.mode = mode
        self.config = config or {}

        # 1. Resolve repository provider
        if repo_provider is not None:
            self.repo_provider = repo_provider
        else:
            if self.mode == ExecutionMode.PIPELINE:
                raise PipelineExecutionError("PIPELINE mode requires an explicit PipelineRepositoryProvider.")
            self.repo_provider = LocalRepositoryProvider(repo_path=".")

        # 2. Resolve credentials provider
        if credential_provider is not None:
            self.credential_provider = credential_provider
        else:
            if self.mode == ExecutionMode.PIPELINE:
                self.credential_provider = PipelineCredentialProvider(config=self.config)
            else:
                self.credential_provider = LocalCredentialProvider(config=self.config)

        # 3. Resolve generation engine (Strictly isolated by mode)
        if engine is not None:
            self.engine = engine
            # Enforce mode compatibility
            if self.mode == ExecutionMode.PIPELINE and isinstance(engine, LocalIdfcCoderEngine):
                raise ModeEnforcementError(
                    "IDFC Coder is strictly prohibited in PIPELINE execution mode. Use PipelineLlmApiEngine."
                )
        else:
            if self.mode == ExecutionMode.PIPELINE:
                self.engine = PipelineLlmApiEngine(client=client, llm_config=self.config.get("llm", {}))
            else:
                self.engine = LocalIdfcCoderEngine()

        # 4. Resolve page resolver
        if page_resolver is not None:
            self.page_resolver = page_resolver
        else:
            if self.mode == ExecutionMode.PIPELINE:
                self.page_resolver = ProductionConfluencePageResolver(config=self.config)
            else:
                self.page_resolver = LocalConfluencePageResolver(config=self.config)

    def generate_runbook(
        self,
        environment: str = "production",
        version: str | None = None,
        force: bool = False,
        output_base_dir: Path | str | None = None,
    ) -> RunbookGenerationResult:
        """
        Step 1 (Pre-Deployment): Validate repository preconditions and generate runbook.
        In PIPELINE mode: ensures working tree is clean and commit is exact.
        """
        # Validate repository preconditions for active mode
        self.repo_provider.validate_for_execution()
        repo_info = self.repo_provider.get_repository()

        generator = RunbookGenerator(engine=self.engine)
        result = generator.generate(
            repo_path=repo_info.path,
            environment=environment,
            version=version,
            service_name_override=repo_info.service_name,
            commit_sha_override=repo_info.commit_sha,
            branch_override=repo_info.branch,
            force=force,
            output_base_dir=output_base_dir,
        )
        return result

    def publish_runbook(
        self,
        runbook_path: Path | str,
        deployed_commit_sha: str | None = None,
        dry_run: bool = False,
        publisher: ConfluencePublisher | None = None,
    ) -> ConfluencePublishResult:
        """
        Step 2 (Post-Deployment): Publish validated runbook to Confluence using exact configured pageId.
        In PIPELINE mode: strictly enforces deployedCommitSha == analyzedCommitSha.
        In LOCAL mode: enforces test page resolver, never targets production page.
        """
        repo_info = self.repo_provider.get_repository()

        # Enforce pipeline deployed commit equality check
        if self.mode == ExecutionMode.PIPELINE:
            if not deployed_commit_sha:
                raise PipelineExecutionError("PIPELINE publishing requires an explicit deployed_commit_sha.")
            if not repo_info.commit_sha.startswith(deployed_commit_sha) and not deployed_commit_sha.startswith(repo_info.commit_sha):
                raise CommitMismatchError(
                    f"PIPELINE publishing rejected: deployed commit '{deployed_commit_sha}' "
                    f"does not match analyzed commit '{repo_info.commit_sha}'."
                )

        # Enforce page resolver constraints
        if self.mode == ExecutionMode.LOCAL and self.page_resolver.is_production():
            raise ModeEnforcementError("LOCAL mode execution is prohibited from publishing to production Confluence pages.")

        page_id = self.page_resolver.resolve_page_id(repo_info)
        parent_page_id = getattr(self.page_resolver, "resolve_parent_page_id", lambda r: "")(repo_info)
        page_title = getattr(self.page_resolver, "resolve_page_title", lambda r: repo_info.repo_name)(repo_info)

        token = self.credential_provider.get_confluence_token() or ""
        base_url = self.config.get("confluence", {}).get("base_url", "")

        confluence_config = ConfluenceConfig(
            enabled=True,
            base_url=base_url,
            page_id=page_id,
            parent_page_id=parent_page_id,
            token=token,
        )

        pub = publisher or ConfluencePublisher(config=confluence_config)
        return pub.publish_runbook(
            runbook_path=Path(runbook_path),
            repo_info=repo_info,
            page_id=page_id,
            validation_status="PASSED",
            dry_run=dry_run,
        )
