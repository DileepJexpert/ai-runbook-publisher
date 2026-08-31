"""Confluence REST API client for deterministic page operations."""

from __future__ import annotations

import logging
import re
from typing import Any
import markdown
import requests

from .models import ConfluenceConfig, ConfluenceError, ConfluencePage

LOGGER = logging.getLogger(__name__)


class ConfluenceClient:
    """HTTP client communicating with Confluence REST APIs."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout_seconds: int = 30,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        if self.token:
            # Standard Bearer token authentication
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    @classmethod
    def from_config(cls, config: ConfluenceConfig, session: requests.Session | None = None) -> ConfluenceClient:
        return cls(
            base_url=config.base_url,
            token=config.token,
            timeout_seconds=config.timeout_seconds,
            session=session,
        )

    def get_child_pages(self, parent_page_id: str) -> list[ConfluencePage]:
        """
        Fetch all child pages under the given parent page ID.
        Queries Confluence API with pagination if available.
        """
        if not parent_page_id:
            raise ConfluenceError("Parent page ID cannot be empty.")

        # Query v2 /pages/{id}/children or fallback /pages?parent-id={id}
        pages: list[ConfluencePage] = []
        path = f"/wiki/api/v2/pages/{parent_page_id}/children"

        try:
            data = self._request("GET", path)
            results = data.get("results", [])
            for item in results:
                page_id = str(item.get("id", ""))
                title = str(item.get("title", ""))
                ver_obj = item.get("version", {})
                ver_num = int(ver_obj.get("number", 1)) if isinstance(ver_obj, dict) else 1
                pages.append(ConfluencePage(
                    id=page_id,
                    title=title,
                    version=ver_num,
                    parent_id=parent_page_id,
                    space_id=str(item.get("spaceId", "")) or None,
                ))
        except ConfluenceError as exc:
            # If v2 child endpoint returns 404, try v1 fallback /rest/api/content/{id}/child/page
            LOGGER.debug("Confluence v2 child lookup fallback: %s", exc)
            fallback_path = f"/rest/api/content/{parent_page_id}/child/page"
            data = self._request("GET", fallback_path)
            results = data.get("results", [])
            for item in results:
                page_id = str(item.get("id", ""))
                title = str(item.get("title", ""))
                ver_obj = item.get("version", {})
                ver_num = int(ver_obj.get("number", 1)) if isinstance(ver_obj, dict) else 1
                pages.append(ConfluencePage(
                    id=page_id,
                    title=title,
                    version=ver_num,
                    parent_id=parent_page_id,
                ))

        return pages

    def get_page(self, page_id: str) -> ConfluencePage:
        """Fetch details and storage content for a specific page."""
        if not page_id:
            raise ConfluenceError("Page ID cannot be empty.")

        path = f"/wiki/api/v2/pages/{page_id}"
        try:
            data = self._request("GET", path, params={"body-format": "storage"})
            title = str(data.get("title", ""))
            ver_obj = data.get("version", {})
            ver_num = int(ver_obj.get("number", 1)) if isinstance(ver_obj, dict) else 1
            body_storage = data.get("body", {}).get("storage", {}).get("value", "")
            space_id = str(data.get("spaceId", "")) or None
            parent_id = str(data.get("parentId", "")) or None

            return ConfluencePage(
                id=str(page_id),
                title=title,
                version=ver_num,
                parent_id=parent_id,
                body_storage=body_storage,
                space_id=space_id,
            )
        except ConfluenceError as exc:
            # Fallback to v1 API /rest/api/content/{id}?expand=body.storage,version
            LOGGER.debug("Confluence v2 get_page fallback: %s", exc)
            fallback_path = f"/rest/api/content/{page_id}"
            data = self._request("GET", fallback_path, params={"expand": "body.storage,version,ancestors"})
            title = str(data.get("title", ""))
            ver_obj = data.get("version", {})
            ver_num = int(ver_obj.get("number", 1)) if isinstance(ver_obj, dict) else 1
            body_storage = data.get("body", {}).get("storage", {}).get("value", "")
            ancestors = data.get("ancestors", [])
            parent_id = str(ancestors[-1].get("id", "")) if ancestors else None

            return ConfluencePage(
                id=str(page_id),
                title=title,
                version=ver_num,
                parent_id=parent_id,
                body_storage=body_storage,
            )

    def create_page(
        self,
        title: str,
        parent_page_id: str,
        body_storage: str,
        space_id: str | None = None,
    ) -> ConfluencePage:
        """Create a new child page beneath the specified parent."""
        if not title:
            raise ConfluenceError("Page title cannot be empty.")
        if not parent_page_id:
            raise ConfluenceError("Parent page ID cannot be empty.")

        # Try to resolve spaceId if not passed by inspecting parent
        resolved_space_id = space_id
        if not resolved_space_id:
            try:
                parent_page = self.get_page(parent_page_id)
                resolved_space_id = parent_page.space_id
            except Exception as exc:
                LOGGER.debug("Could not inspect parent spaceId: %s", exc)

        payload: dict[str, Any] = {
            "title": title,
            "status": "current",
            "parentId": str(parent_page_id),
            "body": {
                "representation": "storage",
                "value": body_storage,
            },
        }
        if resolved_space_id:
            payload["spaceId"] = resolved_space_id

        try:
            data = self._request("POST", "/wiki/api/v2/pages", json=payload)
            page_id = str(data.get("id", ""))
            ver_obj = data.get("version", {})
            ver_num = int(ver_obj.get("number", 1)) if isinstance(ver_obj, dict) else 1
            return ConfluencePage(
                id=page_id,
                title=title,
                version=ver_num,
                parent_id=parent_page_id,
                body_storage=body_storage,
                space_id=resolved_space_id,
            )
        except ConfluenceError as exc:
            # Fallback to v1 /rest/api/content
            LOGGER.debug("Confluence v2 create fallback: %s", exc)
            v1_payload: dict[str, Any] = {
                "type": "page",
                "title": title,
                "ancestors": [{"id": str(parent_page_id)}],
                "body": {
                    "storage": {
                        "value": body_storage,
                        "representation": "storage",
                    }
                },
            }
            data = self._request("POST", "/rest/api/content", json=v1_payload)
            page_id = str(data.get("id", ""))
            ver_obj = data.get("version", {})
            ver_num = int(ver_obj.get("number", 1)) if isinstance(ver_obj, dict) else 1
            return ConfluencePage(
                id=page_id,
                title=title,
                version=ver_num,
                parent_id=parent_page_id,
                body_storage=body_storage,
            )

    def update_page(
        self,
        page_id: str,
        title: str,
        version: int,
        body_storage: str,
    ) -> ConfluencePage:
        """Update an existing page with new content and incremented version."""
        if not page_id:
            raise ConfluenceError("Page ID cannot be empty.")

        payload: dict[str, Any] = {
            "id": str(page_id),
            "status": "current",
            "title": title,
            "version": {
                "number": int(version),
                "message": "Automated update via ai-runbook-publisher",
            },
            "body": {
                "representation": "storage",
                "value": body_storage,
            },
        }

        try:
            data = self._request("PUT", f"/wiki/api/v2/pages/{page_id}", json=payload)
            ver_obj = data.get("version", {})
            ver_num = int(ver_obj.get("number", version)) if isinstance(ver_obj, dict) else version
            return ConfluencePage(
                id=str(page_id),
                title=title,
                version=ver_num,
                body_storage=body_storage,
            )
        except ConfluenceError as exc:
            # Fallback to v1 /rest/api/content/{id}
            LOGGER.debug("Confluence v2 update fallback: %s", exc)
            v1_payload: dict[str, Any] = {
                "id": str(page_id),
                "type": "page",
                "title": title,
                "version": {
                    "number": int(version),
                },
                "body": {
                    "storage": {
                        "value": body_storage,
                        "representation": "storage",
                    }
                },
            }
            data = self._request("PUT", f"/rest/api/content/{page_id}", json=v1_payload)
            ver_obj = data.get("version", {})
            ver_num = int(ver_obj.get("number", version)) if isinstance(ver_obj, dict) else version
            return ConfluencePage(
                id=str(page_id),
                title=title,
                version=ver_num,
                body_storage=body_storage,
            )

    def markdown_to_storage(self, markdown_text: str) -> str:
        """
        Deterministically convert Markdown runbook text to Confluence XHTML storage format.
        """
        html_content = markdown.markdown(
            markdown_text,
            extensions=["tables", "fenced_code", "sane_lists"],
        )
        # Wrap blockquotes in Confluence info macros for operational readability
        html_content = re.sub(
            r"<blockquote>\s*<p>(.*?)</p>\s*</blockquote>",
            lambda m: f'<ac:structured-macro ac:name="info"><ac:rich-text-body><p>{m.group(1)}</p></ac:rich-text-body></ac:structured-macro>',
            html_content,
            flags=re.DOTALL,
        )
        return html_content

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        """Execute an HTTP request with error handling and sensitive header protection."""
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        try:
            response = self.session.request(
                method=method,
                url=url,
                timeout=self.timeout_seconds,
                **kwargs,
            )
            response.raise_for_status()
            if response.content:
                return response.json()
            return {}
        except requests.exceptions.Timeout as exc:
            LOGGER.error("Confluence API timeout during %s %s", method, path)
            raise ConfluenceError(f"Confluence request timed out after {self.timeout_seconds}s") from exc
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            err_body = exc.response.text[:300] if exc.response is not None else str(exc)
            if status_code in (401, 403):
                LOGGER.error("Confluence authentication/authorization failed (status %d)", status_code)
                raise ConfluenceError(f"Confluence authentication failed (HTTP {status_code})") from exc
            LOGGER.error("Confluence API error during %s %s (status %d): %s", method, path, status_code, err_body)
            raise ConfluenceError(f"Confluence API returned HTTP {status_code}: {err_body}") from exc
        except requests.exceptions.RequestException as exc:
            LOGGER.error("Confluence network failure during %s %s: %s", method, path, exc)
            raise ConfluenceError(f"Confluence connection failed: {exc}") from exc
        except Exception as exc:
            LOGGER.error("Unexpected error during Confluence %s %s: %s", method, path, exc)
            raise ConfluenceError(f"Confluence request error: {exc}") from exc
