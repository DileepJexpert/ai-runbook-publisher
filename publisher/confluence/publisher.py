"""Confluence Runbook Publisher (Phase 5).

Deterministically creates or updates a single child page beneath the configured parent page.
Child page title is EXACTLY the repository name.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from publisher.repository import RepositoryInfo
from .client import ConfluenceClient
from .models import (
    ConfluenceConfig,
    ConfluenceConfigurationError,
    ConfluenceDuplicatePageError,
    ConfluenceError,
    ConfluenceManualNotesError,
    ConfluencePage,
    ConfluencePublishResult,
)

LOGGER = logging.getLogger(__name__)

# Markers for Manual Support Notes
MANUAL_NOTES_START = "<!-- MANUAL SUPPORT NOTES START -->"
MANUAL_NOTES_END = "<!-- MANUAL SUPPORT NOTES END -->"


def extract_manual_notes(page_content: str) -> str:
    """
    Extract manual support notes from existing page content (HTML or Markdown).
    Returns empty string if no manual notes section is found.
    Raises ConfluenceManualNotesError if markers are corrupted/ambiguous.
    """
    if not page_content:
        return ""

    # 1. Check for explicit comment markers
    has_start = MANUAL_NOTES_START in page_content
    has_end = MANUAL_NOTES_END in page_content

    if has_start and has_end:
        pattern = re.compile(
            re.escape(MANUAL_NOTES_START) + r"(.*?)" + re.escape(MANUAL_NOTES_END),
            re.DOTALL,
        )
        match = pattern.search(page_content)
        if match:
            return match.group(1).strip()
        return ""
    elif has_start or has_end:
        raise ConfluenceManualNotesError(
            "Ambiguous manual support notes: found unclosed or mismatched markers in existing page."
        )

    # 2. Check for Markdown / HTML heading "Manual Support Notes"
    # Matches ## Manual Support Notes or <h2>Manual Support Notes</h2> or <h3>Manual Support Notes</h3>
    heading_pattern = re.compile(
        r"(?:<h[2-4][^>]*>\s*Manual Support Notes\s*</h[2-4]>|##+\s*Manual Support Notes)\s*(.*)",
        re.DOTALL | re.IGNORECASE,
    )
    match = heading_pattern.search(page_content)
    if match:
        extracted = match.group(1).strip()
        # Clean out any closing tags if present
        return extracted

    return ""


def inject_manual_notes(runbook_markdown: str, manual_notes: str) -> str:
    """
    Append preserved manual support notes to generated runbook Markdown.
    """
    clean_markdown = runbook_markdown.rstrip()
    if not manual_notes or not manual_notes.strip():
        return clean_markdown

    notes_section = (
        "\n\n## Manual Support Notes\n"
        f"{MANUAL_NOTES_START}\n"
        f"{manual_notes.strip()}\n"
        f"{MANUAL_NOTES_END}\n"
    )
    return f"{clean_markdown}{notes_section}"


class ConfluencePublisher:
    """Orchestrates deterministic create-or-update publishing of RUNBOOK.md to Confluence."""

    def __init__(
        self,
        config: ConfluenceConfig,
        client: ConfluenceClient | None = None,
    ) -> None:
        self.config = config
        self.client = client or ConfluenceClient.from_config(config)

    def publish_runbook(
        self,
        runbook_path: Path | str,
        repo_info: RepositoryInfo,
        validation_status: str,
        dry_run: bool = True,
        page_id: str | None = None,
    ) -> ConfluencePublishResult:
        """
        Publish validated RUNBOOK.md to Confluence using exact configured pageId.
        """
        repo_name = repo_info.repo_name or repo_info.service_name
        target_page_id = (page_id or self.config.page_id or "").strip()
        parent_page_id = self.config.parent_page_id

        # 1. Validation check: must be PASSED
        if validation_status != "PASSED":
            LOGGER.warning(
                "repoName=%s confluencePublishStatus=SKIPPED reason=VALIDATION_NOT_PASSED",
                repo_name,
            )
            return ConfluencePublishResult(
                action="SKIPPED",
                success=False,
                page_title=repo_name,
                page_id=target_page_id or None,
                parent_page_id=parent_page_id,
                error="Runbook validation did not pass. Confluence publishing skipped.",
            )

        # 2. Enabled check
        if not self.config.enabled:
            LOGGER.info(
                "repoName=%s confluencePublishStatus=SKIPPED reason=CONFLUENCE_DISABLED",
                repo_name,
            )
            return ConfluencePublishResult(
                action="SKIPPED",
                success=True,
                page_title=repo_name,
                page_id=target_page_id or None,
                parent_page_id=parent_page_id,
                error=None,
            )

        # 3. Required configuration check
        missing = []
        if not self.config.base_url:
            missing.append("base-url")
        if not target_page_id and not self.config.parent_page_id:
            missing.append("page-id (or parent-page-id)")
        if not self.config.token:
            missing.append("token")

        if missing:
            err_msg = f"Confluence is enabled but missing required configuration: {', '.join(missing)}"
            LOGGER.error("repoName=%s confluencePublishStatus=FAILED reason=%s", repo_name, err_msg)
            return ConfluencePublishResult(
                action="FAILED",
                success=False,
                page_title=repo_name,
                page_id=target_page_id or None,
                parent_page_id=parent_page_id,
                error=err_msg,
            )

        # 4. Read runbook content
        path = Path(runbook_path)
        if not path.exists() or not path.is_file():
            err_msg = f"Runbook file not found at {path}"
            LOGGER.error("repoName=%s confluencePublishStatus=FAILED reason=%s", repo_name, err_msg)
            return ConfluencePublishResult(
                action="FAILED",
                success=False,
                page_title=repo_name,
                page_id=target_page_id or None,
                parent_page_id=parent_page_id,
                error=err_msg,
            )

        try:
            runbook_content = path.read_text(encoding="utf-8")
        except Exception as exc:
            err_msg = f"Failed to read runbook content: {exc}"
            LOGGER.error("repoName=%s confluencePublishStatus=FAILED reason=%s", repo_name, err_msg)
            return ConfluencePublishResult(
                action="FAILED",
                success=False,
                page_title=repo_name,
                page_id=target_page_id or None,
                parent_page_id=parent_page_id,
                error=err_msg,
            )

        # --- A. EXACT PAGE ID FLOW (NO TITLE DISCOVERY, NO PAGE CREATION) ---
        if target_page_id:
            try:
                full_page = self.client.get_page(target_page_id)
            except Exception as exc:
                err_msg = f"Failed to retrieve configured Confluence page {target_page_id}: {exc}"
                LOGGER.error("repoName=%s confluencePublishStatus=FAILED reason=%s", repo_name, err_msg)
                return ConfluencePublishResult(
                    action="FAILED",
                    success=False,
                    page_id=target_page_id,
                    page_title=repo_name,
                    error=err_msg,
                )

            preserved_notes = ""
            if self.config.preserve_manual_notes:
                try:
                    preserved_notes = extract_manual_notes(full_page.body_storage)
                except ConfluenceManualNotesError as exc:
                    err_msg = f"Manual notes parsing error on existing page {target_page_id}: {exc}"
                    LOGGER.error("repoName=%s confluencePublishStatus=FAILED reason=%s", repo_name, err_msg)
                    return ConfluencePublishResult(
                        action="FAILED",
                        success=False,
                        page_id=target_page_id,
                        page_title=full_page.title or repo_name,
                        error=err_msg,
                    )

            updated_markdown = inject_manual_notes(runbook_content, preserved_notes) if preserved_notes else runbook_content

            if dry_run:
                LOGGER.info("repoName=%s confluenceAction=DRY_RUN action=UPDATE pageId=%s", repo_name, target_page_id)
                return ConfluencePublishResult(
                    action="DRY_RUN",
                    planned_action="UPDATE",
                    success=True,
                    page_id=target_page_id,
                    page_title=full_page.title or repo_name,
                    version=full_page.version + 1,
                    manual_notes_preserved=bool(preserved_notes),
                )

            try:
                LOGGER.info("repoName=%s confluenceAction=UPDATE pageId=%s", repo_name, target_page_id)
                body_storage = self.client.markdown_to_storage(updated_markdown)
                next_version = full_page.version + 1
                page_title = full_page.title or repo_name
                updated = self.client.update_page(
                    page_id=target_page_id,
                    title=page_title,
                    version=next_version,
                    body_storage=body_storage,
                )
                LOGGER.info("repoName=%s confluencePublishStatus=SUCCESS pageId=%s", repo_name, updated.id)
                return ConfluencePublishResult(
                    action="UPDATED",
                    success=True,
                    page_id=updated.id,
                    page_title=updated.title,
                    version=updated.version,
                    manual_notes_preserved=bool(preserved_notes),
                    page_url=f"{self.config.base_url}/pages/{updated.id}",
                )
            except Exception as exc:
                err_msg = f"Failed to update Confluence page {target_page_id}: {exc}"
                LOGGER.error("repoName=%s confluencePublishStatus=FAILED reason=%s", repo_name, err_msg)
                return ConfluencePublishResult(
                    action="FAILED",
                    success=False,
                    page_id=target_page_id,
                    page_title=full_page.title or repo_name,
                    error=err_msg,
                )

        # --- B. LEGACY PARENT PAGE SEARCH FLOW ---
        # 5. Search for child pages under configured parentPageId
        try:
            children = self.client.get_child_pages(parent_page_id)
        except Exception as exc:
            err_msg = f"Failed to query child pages under parent {parent_page_id}: {exc}"
            LOGGER.error("repoName=%s confluencePublishStatus=FAILED reason=%s", repo_name, err_msg)
            return ConfluencePublishResult(
                action="FAILED",
                success=False,
                page_title=repo_name,
                parent_page_id=parent_page_id,
                error=err_msg,
            )

        # 6. Exact title matching against repository name
        exact_matches = [p for p in children if p.title == repo_name]

        # Resolution: Multiple matches -> FAIL SAFE
        if len(exact_matches) > 1:
            err_msg = (
                f"Multiple ({len(exact_matches)}) exact child pages found with title '{repo_name}' "
                f"under parent {parent_page_id}. Aborting update to prevent accidental corruption."
            )
            LOGGER.error("repoName=%s confluencePublishStatus=FAILED reason=MULTIPLE_MATCHES", repo_name)
            return ConfluencePublishResult(
                action="FAILED",
                success=False,
                page_title=repo_name,
                parent_page_id=parent_page_id,
                error=err_msg,
            )

        # Resolution: 0 matches -> CREATE
        if len(exact_matches) == 0:
            if dry_run:
                LOGGER.info("repoName=%s confluenceAction=DRY_RUN action=CREATE parentPageId=%s", repo_name, parent_page_id)
                return ConfluencePublishResult(
                    action="DRY_RUN",
                    planned_action="CREATE",
                    success=True,
                    page_title=repo_name,
                    parent_page_id=parent_page_id,
                )

            # Live CREATE
            try:
                LOGGER.info("repoName=%s confluenceAction=CREATE parentPageId=%s", repo_name, parent_page_id)
                body_storage = self.client.markdown_to_storage(runbook_content)
                created = self.client.create_page(
                    title=repo_name,
                    parent_page_id=parent_page_id,
                    body_storage=body_storage,
                )
                LOGGER.info("repoName=%s confluencePublishStatus=SUCCESS pageId=%s", repo_name, created.id)
                return ConfluencePublishResult(
                    action="CREATED",
                    success=True,
                    page_id=created.id,
                    page_title=repo_name,
                    parent_page_id=parent_page_id,
                    version=created.version,
                    page_url=f"{self.config.base_url}/pages/{created.id}",
                )
            except Exception as exc:
                err_msg = f"Failed to create Confluence page: {exc}"
                LOGGER.error("repoName=%s confluencePublishStatus=FAILED reason=%s", repo_name, err_msg)
                return ConfluencePublishResult(
                    action="FAILED",
                    success=False,
                    page_title=repo_name,
                    parent_page_id=parent_page_id,
                    error=err_msg,
                )

        # Resolution: 1 match -> UPDATE
        existing_page = exact_matches[0]
        page_id = existing_page.id

        # Fetch full page to get storage body and current version
        try:
            full_page = self.client.get_page(page_id)
        except Exception as exc:
            err_msg = f"Failed to retrieve existing page {page_id} for update: {exc}"
            LOGGER.error("repoName=%s confluencePublishStatus=FAILED reason=%s", repo_name, err_msg)
            return ConfluencePublishResult(
                action="FAILED",
                success=False,
                page_id=page_id,
                page_title=repo_name,
                parent_page_id=parent_page_id,
                error=err_msg,
            )

        # Handle manual notes preservation
        preserved_notes = ""
        if self.config.preserve_manual_notes:
            try:
                preserved_notes = extract_manual_notes(full_page.body_storage)
            except ConfluenceManualNotesError as exc:
                err_msg = f"Manual notes parsing error on existing page {page_id}: {exc}"
                LOGGER.error("repoName=%s confluencePublishStatus=FAILED reason=%s", repo_name, err_msg)
                return ConfluencePublishResult(
                    action="FAILED",
                    success=False,
                    page_id=page_id,
                    page_title=repo_name,
                    parent_page_id=parent_page_id,
                    error=err_msg,
                )

        updated_markdown = inject_manual_notes(runbook_content, preserved_notes) if preserved_notes else runbook_content

        if dry_run:
            LOGGER.info("repoName=%s confluenceAction=DRY_RUN action=UPDATE pageId=%s", repo_name, page_id)
            return ConfluencePublishResult(
                action="DRY_RUN",
                planned_action="UPDATE",
                success=True,
                page_id=page_id,
                page_title=repo_name,
                parent_page_id=parent_page_id,
                version=full_page.version,
                manual_notes_preserved=bool(preserved_notes),
            )

        # Live UPDATE
        try:
            LOGGER.info("repoName=%s confluenceAction=UPDATE pageId=%s", repo_name, page_id)
            body_storage = self.client.markdown_to_storage(updated_markdown)
            next_version = full_page.version + 1
            updated = self.client.update_page(
                page_id=page_id,
                title=repo_name,
                version=next_version,
                body_storage=body_storage,
            )
            LOGGER.info("repoName=%s confluencePublishStatus=SUCCESS pageId=%s", repo_name, updated.id)
            return ConfluencePublishResult(
                action="UPDATED",
                success=True,
                page_id=updated.id,
                page_title=repo_name,
                parent_page_id=parent_page_id,
                version=updated.version,
                manual_notes_preserved=bool(preserved_notes),
                page_url=f"{self.config.base_url}/pages/{updated.id}",
            )
        except Exception as exc:
            err_msg = f"Failed to update Confluence page {page_id}: {exc}"
            LOGGER.error("repoName=%s confluencePublishStatus=FAILED reason=%s", repo_name, err_msg)
            return ConfluencePublishResult(
                action="FAILED",
                success=False,
                page_id=page_id,
                page_title=repo_name,
                parent_page_id=parent_page_id,
                error=err_msg,
            )
