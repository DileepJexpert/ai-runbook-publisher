"""Credential providers for LOCAL developer execution vs PIPELINE CI/CD execution."""

from __future__ import annotations

import logging
import os
from typing import Any, Protocol, runtime_checkable

from publisher.execution_mode import PipelineExecutionError

LOGGER = logging.getLogger(__name__)


@runtime_checkable
class CredentialProvider(Protocol):
    """Protocol implemented by all credential providers."""

    def get_confluence_token(self) -> str | None:
        """Resolve Confluence API authentication token."""
        ...

    def get_llm_api_key(self) -> str | None:
        """Resolve LLM API key."""
        ...

    def get_llm_base_url(self) -> str | None:
        """Resolve LLM endpoint URL."""
        ...


class LocalCredentialProvider:
    """
    Credential provider for LOCAL developer mode.
    Reads developer credentials from local config or environment variables (e.g. CONFLUENCE_API_TOKEN, LLM_API_KEY).
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.confluence_cfg = self.config.get("confluence", {})
        self.llm_cfg = self.config.get("llm", {})

    def get_confluence_token(self) -> str | None:
        return (
            os.environ.get("CONFLUENCE_TOKEN")
            or os.environ.get("CONFLUENCE_API_TOKEN")
            or self.confluence_cfg.get("token")
            or self.confluence_cfg.get("api_token")
            or None
        )

    def get_llm_api_key(self) -> str | None:
        return (
            os.environ.get("LLM_API_KEY")
            or self.llm_cfg.get("api_key")
            or None
        )

    def get_llm_base_url(self) -> str | None:
        return (
            os.environ.get("LLM_BASE_URL")
            or self.llm_cfg.get("base_url")
            or None
        )


class PipelineCredentialProvider:
    """
    Credential provider for PIPELINE CI/CD mode.
    Reads machine/service account credentials from pipeline environment secrets.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.confluence_cfg = self.config.get("confluence", {})
        self.llm_cfg = self.config.get("llm", {})

    def get_confluence_token(self) -> str | None:
        token = (
            os.environ.get("PIPELINE_CONFLUENCE_TOKEN")
            or os.environ.get("CONFLUENCE_MACHINE_TOKEN")
            or os.environ.get("CONFLUENCE_TOKEN")
            or self.confluence_cfg.get("pipeline_token")
            or self.confluence_cfg.get("token")
            or None
        )
        return token

    def get_llm_api_key(self) -> str | None:
        key = (
            os.environ.get("PIPELINE_LLM_API_KEY")
            or os.environ.get("LLM_MACHINE_KEY")
            or os.environ.get("LLM_API_KEY")
            or self.llm_cfg.get("pipeline_api_key")
            or self.llm_cfg.get("api_key")
            or None
        )
        return key

    def get_llm_base_url(self) -> str | None:
        url = (
            os.environ.get("PIPELINE_LLM_BASE_URL")
            or os.environ.get("LLM_BASE_URL")
            or self.llm_cfg.get("pipeline_base_url")
            or self.llm_cfg.get("base_url")
            or None
        )
        return url
