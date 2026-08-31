"""Data models for Confluence publishing."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


class ConfluenceError(Exception):
    """Base exception for Confluence publishing errors."""
    pass


class ConfluenceConfigurationError(ConfluenceError):
    """Raised when Confluence is enabled but required configuration is missing or invalid."""
    pass


class ConfluenceDuplicatePageError(ConfluenceError):
    """Raised when multiple child pages match the exact repository name under the parent."""
    pass


class ConfluenceManualNotesError(ConfluenceError):
    """Raised when parsing or extracting manual support notes is ambiguous."""
    pass


@dataclass
class ConfluenceConfig:
    """Deterministic configuration for Confluence."""
    enabled: bool = False
    base_url: str = ""
    parent_page_id: str = ""
    token: str = ""
    timeout_seconds: int = 30
    preserve_manual_notes: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ConfluenceConfig:
        """Create ConfluenceConfig from dict with environment variable overrides."""
        data = data or {}

        # Environment variable overrides
        enabled_val = os.environ.get("CONFLUENCE_ENABLED")
        if enabled_val is not None:
            enabled = enabled_val.strip().lower() in ("true", "1", "yes")
        else:
            raw_enabled = data.get("enabled", False)
            if isinstance(raw_enabled, str):
                enabled = raw_enabled.strip().lower() in ("true", "1", "yes")
            else:
                enabled = bool(raw_enabled)

        base_url = (
            os.environ.get("CONFLUENCE_BASE_URL")
            or data.get("base_url")
            or data.get("base-url")
            or ""
        ).strip().rstrip("/")

        parent_page_id = str(
            os.environ.get("CONFLUENCE_PARENT_PAGE_ID")
            or data.get("parent_page_id")
            or data.get("parent-page-id")
            or ""
        ).strip()

        token = str(
            os.environ.get("CONFLUENCE_TOKEN")
            or os.environ.get("CONFLUENCE_API_TOKEN")
            or data.get("token")
            or data.get("api_token")
            or data.get("api-token")
            or ""
        ).strip()

        timeout_env = os.environ.get("CONFLUENCE_TIMEOUT_SECONDS")
        if timeout_env:
            try:
                timeout_seconds = int(timeout_env.strip())
            except ValueError:
                timeout_seconds = 30
        else:
            raw_timeout = data.get("timeout_seconds", data.get("timeout-seconds", 30))
            try:
                timeout_seconds = int(raw_timeout)
            except (ValueError, TypeError):
                timeout_seconds = 30

        preserve_env = os.environ.get("CONFLUENCE_PRESERVE_MANUAL_NOTES")
        if preserve_env is not None:
            preserve_manual_notes = preserve_env.strip().lower() in ("true", "1", "yes")
        else:
            raw_preserve = data.get(
                "preserve_manual_notes",
                data.get("preserve-manual-notes", True),
            )
            if isinstance(raw_preserve, str):
                preserve_manual_notes = raw_preserve.strip().lower() in ("true", "1", "yes")
            else:
                preserve_manual_notes = bool(raw_preserve)

        return cls(
            enabled=enabled,
            base_url=base_url,
            parent_page_id=parent_page_id,
            token=token,
            timeout_seconds=timeout_seconds,
            preserve_manual_notes=preserve_manual_notes,
        )


@dataclass
class ConfluencePage:
    """Represents a Confluence page record."""
    id: str
    title: str
    version: int
    parent_id: str | None = None
    body_storage: str = ""
    space_id: str | None = None


@dataclass
class ConfluencePublishResult:
    """Result of a Confluence create or update publication attempt."""
    action: str  # "CREATED", "UPDATED", "DRY_RUN", "SKIPPED", "FAILED"
    success: bool
    page_id: str | None = None
    page_title: str = ""
    parent_page_id: str = ""
    version: int | None = None
    planned_action: str | None = None  # "CREATE" or "UPDATE" during DRY_RUN
    error: str | None = None
    manual_notes_preserved: bool = False
    page_url: str | None = None

    def to_summary_dict(self, enabled: bool) -> dict[str, Any]:
        """Format non-sensitive dictionary for generation-summary.json."""
        if not enabled:
            return {
                "enabled": False,
                "published": False,
            }

        res: dict[str, Any] = {
            "enabled": True,
            "action": self.action,
            "pageTitle": self.page_title,
            "parentPageId": self.parent_page_id,
            "published": self.success and self.action in ("CREATED", "UPDATED"),
        }

        if self.page_id:
            res["pageId"] = self.page_id
        if self.version is not None:
            res["version"] = self.version
        if self.planned_action:
            res["plannedAction"] = self.planned_action
        if self.manual_notes_preserved:
            res["manualNotesPreserved"] = True
        if self.error:
            res["error"] = self.error
        if self.page_url:
            res["pageUrl"] = self.page_url

        return res
