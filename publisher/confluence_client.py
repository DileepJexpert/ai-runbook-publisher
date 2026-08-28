"""Small Confluence REST API v2 client."""

from __future__ import annotations

import html
import logging
import re
from urllib.parse import quote

import markdown
import requests

LOGGER = logging.getLogger(__name__)


class ConfluenceClient:
    def __init__(self, base_url: str, space_key: str, username: str, api_token: str, parent_page_id: str = ""):
        self.base_url = base_url.rstrip("/")
        self.space_key = space_key
        self.parent_page_id = parent_page_id
        self.session = requests.Session()
        self.session.auth = (username, api_token)
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self._space_id: str | None = None

    def find_page(self, title: str) -> dict | None:
        data = self._request("GET", "/pages", params={"space-id": self._get_space_id(), "title": title, "body-format": "storage"})
        for page in data.get("results", []):
            if page.get("title") == title:
                LOGGER.info("Confluence page found: %s", page.get("id"))
                return page
        LOGGER.info("Confluence page not found: %s", title)
        return None

    def get_page_content(self, page_id: str) -> str:
        data = self._request("GET", f"/pages/{page_id}", params={"body-format": "storage"})
        return data.get("body", {}).get("storage", {}).get("value", "")

    def create_page(self, title: str, content: str) -> dict:
        payload = {"spaceId": self._get_space_id(), "status": "current", "title": title, "body": {"representation": "storage", "value": content}}
        if self.parent_page_id:
            payload["parentId"] = self.parent_page_id
        page = self._request("POST", "/pages", json=payload)
        LOGGER.info("Confluence page created: %s", page.get("id"))
        return page

    def update_page(self, page_id: str, version: int, title: str, content: str) -> dict:
        payload = {"id": str(page_id), "status": "current", "title": title, "version": {"number": int(version) + 1}, "body": {"representation": "storage", "value": content}}
        page = self._request("PUT", f"/pages/{page_id}", json=payload)
        LOGGER.info("Confluence page updated: %s", page_id)
        return page

    def markdown_to_confluence(self, markdown_text: str) -> str:
        """Convert the needed Markdown subset to Confluence storage XHTML."""
        rendered = markdown.markdown(markdown_text, extensions=["tables", "fenced_code", "sane_lists"])
        # Confluence's info macro gives blockquotes a useful visual distinction.
        rendered = re.sub(
            r"<blockquote>\s*<p>(.*?)</p>\s*</blockquote>",
            lambda m: '<ac:structured-macro ac:name="info"><ac:rich-text-body><p>' + m.group(1) + "</p></ac:rich-text-body></ac:structured-macro>",
            rendered,
            flags=re.DOTALL,
        )
        return rendered

    def page_url(self, page_id: str) -> str:
        return f"{self.base_url}/wiki/spaces/{quote(self.space_key)}/pages/{page_id}"

    def _get_space_id(self) -> str:
        if self._space_id:
            return self._space_id
        data = self._request("GET", "/spaces", params={"keys": self.space_key})
        spaces = data.get("results", [])
        if not spaces:
            raise RuntimeError(f"Confluence space not found: {self.space_key}")
        self._space_id = str(spaces[0]["id"])
        return self._space_id

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self.session.request(method, f"{self.base_url}/wiki/api/v2{path}", timeout=30, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            detail = exc.response.text[:500] if exc.response is not None else str(exc)
            LOGGER.error("Confluence API failure during %s %s: %s", method, path, detail)
            raise RuntimeError(f"Confluence API failure: {detail}") from exc
