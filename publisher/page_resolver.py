"""Exact serviceId -> pageId Confluence page resolvers for LOCAL vs PIPELINE execution."""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from publisher.execution_mode import ModeEnforcementError, PipelineExecutionError
from publisher.repository import RepositoryInfo

LOGGER = logging.getLogger(__name__)


@runtime_checkable
class ConfluencePageResolver(Protocol):
    """Protocol for resolving exact Confluence pageId for a service."""

    def resolve_page_id(self, repo_info: RepositoryInfo) -> str:
        """Resolve the exact Confluence pageId for the given service."""
        ...

    def is_production(self) -> bool:
        """Return whether this resolver targets production Confluence space/pages."""
        ...

    # Compatibility methods
    def resolve_parent_page_id(self, repo_info: RepositoryInfo) -> str:
        ...

    def resolve_page_title(self, repo_info: RepositoryInfo) -> str:
        ...


class LocalConfluencePageResolver:
    """
    Page resolver for LOCAL developer mode.
    Strictly resolves configured local test page mappings:
    local.confluence.pages.<serviceId> -> exact TEST pageId.
    Must NEVER receive or resolve production page mappings.
    """

    def __init__(
        self,
        pages: dict[str, str] | None = None,
        config: dict[str, Any] | None = None,
        prohibited_production_pages: dict[str, str] | set[str] | None = None,
        test_parent_page_id: str | None = None,
    ) -> None:
        self.pages: dict[str, str] = {}
        if pages:
            self.pages.update({str(k).strip(): str(v).strip() for k, v in pages.items() if v})
        elif config:
            local_cfg = config.get("local", {}).get("confluence", {}).get("pages")
            if isinstance(local_cfg, dict):
                self.pages.update({str(k).strip(): str(v).strip() for k, v in local_cfg.items() if v})
            elif "local_confluence_pages" in config and isinstance(config["local_confluence_pages"], dict):
                self.pages.update({str(k).strip(): str(v).strip() for k, v in config["local_confluence_pages"].items() if v})
            elif "confluence_pages" in config and isinstance(config["confluence_pages"], dict):
                self.pages.update({str(k).strip(): str(v).strip() for k, v in config["confluence_pages"].items() if v})
            elif "confluence" in config and isinstance(config["confluence"].get("pages"), dict):
                self.pages.update({str(k).strip(): str(v).strip() for k, v in config["confluence"]["pages"].items() if v})

        self.prohibited_production_pages = set(prohibited_production_pages or [])
        self.test_parent_page_id = test_parent_page_id

    def resolve_page_id(self, repo_info: RepositoryInfo) -> str:
        """Resolve the exact TEST pageId for the service."""
        service_id = repo_info.service_name
        repo_name = repo_info.repo_name

        page_id = self.pages.get(service_id) or self.pages.get(repo_name) or ""
        page_id = page_id.strip()

        if not page_id:
            raise ModeEnforcementError(
                f"LOCAL_CONFLUENCE_PAGE_NOT_CONFIGURED: No local test Confluence pageId configured for service '{service_id}'."
            )

        if page_id in self.prohibited_production_pages:
            raise ModeEnforcementError(
                f"LOCAL execution cannot target production Confluence pageId '{page_id}' for service '{service_id}'."
            )

        return page_id

    def is_production(self) -> bool:
        return False

    def resolve_parent_page_id(self, repo_info: RepositoryInfo) -> str:
        return self.test_parent_page_id or self.resolve_page_id(repo_info)

    def resolve_page_title(self, repo_info: RepositoryInfo) -> str:
        return f"[TEST] {repo_info.repo_name or repo_info.service_name}"


class ProductionConfluencePageResolver:
    """
    Page resolver for PIPELINE CI/CD mode.
    Strictly resolves configured production page mappings:
    pipeline.confluence.pages.<serviceId> -> exact PRODUCTION pageId.
    Does NOT use local mappings.
    """

    def __init__(
        self,
        pages: dict[str, str] | None = None,
        config: dict[str, Any] | None = None,
        prod_parent_page_id: str | None = None,
    ) -> None:
        self.pages: dict[str, str] = {}
        if pages:
            self.pages.update({str(k).strip(): str(v).strip() for k, v in pages.items() if v})
        elif config:
            pipe_cfg = config.get("pipeline", {}).get("confluence", {}).get("pages")
            if isinstance(pipe_cfg, dict):
                self.pages.update({str(k).strip(): str(v).strip() for k, v in pipe_cfg.items() if v})
            elif "pipeline_confluence_pages" in config and isinstance(config["pipeline_confluence_pages"], dict):
                self.pages.update({str(k).strip(): str(v).strip() for k, v in config["pipeline_confluence_pages"].items() if v})
            elif "confluence_pages" in config and isinstance(config["confluence_pages"], dict):
                self.pages.update({str(k).strip(): str(v).strip() for k, v in config["confluence_pages"].items() if v})
            elif "confluence" in config and isinstance(config["confluence"].get("pages"), dict):
                self.pages.update({str(k).strip(): str(v).strip() for k, v in config["confluence"]["pages"].items() if v})

        self.prod_parent_page_id = prod_parent_page_id

    def resolve_page_id(self, repo_info: RepositoryInfo) -> str:
        """Resolve the exact PRODUCTION pageId for the service."""
        service_id = repo_info.service_name
        repo_name = repo_info.repo_name

        page_id = self.pages.get(service_id) or self.pages.get(repo_name) or ""
        page_id = page_id.strip()

        if not page_id:
            raise PipelineExecutionError(
                f"PRODUCTION_CONFLUENCE_PAGE_NOT_CONFIGURED: No production Confluence pageId configured for service '{service_id}'."
            )

        return page_id

    def is_production(self) -> bool:
        return True

    def resolve_parent_page_id(self, repo_info: RepositoryInfo) -> str:
        return self.prod_parent_page_id or self.resolve_page_id(repo_info)

    def resolve_page_title(self, repo_info: RepositoryInfo) -> str:
        return repo_info.repo_name or repo_info.service_name
