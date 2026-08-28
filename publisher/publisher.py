"""Pipeline orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .ai_client import generate_runbook
from .confluence_client import ConfluenceClient
from .manual_notes import extract_manual_notes, inject_manual_notes
from .repo_collector import collect_repo, get_last_collection_stats

LOGGER = logging.getLogger(__name__)


@dataclass
class PublishResult:
    success: bool
    page_url: str = ""
    page_id: str = ""
    action: str = ""
    scan_coverage: str = "COMPLETE"
    error: str | None = None
    runbook: str = ""


def publish(repo_path: str, service_name: str, pipeline_metadata: dict, config: dict, dry_run: bool = False) -> PublishResult:
    repo_content = collect_repo(repo_path, int(config.get("ai", {}).get("repo_max_tokens", 80000)))
    stats = get_last_collection_stats()
    prompt_path = Path(__file__).parent.parent / "prompts" / "runbook-prompt.txt"
    prompt_template = prompt_path.read_text(encoding="utf-8")
    generated = generate_runbook(repo_content, prompt_template, pipeline_metadata, config)
    title = f"Production Support Runbook - {service_name}"
    if dry_run:
        return PublishResult(True, action="dry-run", scan_coverage=stats.coverage, runbook=inject_manual_notes(generated, ""))

    cfg = config.get("confluence", {})
    client = ConfluenceClient(cfg["base_url"], cfg["space_key"], cfg["username"], cfg["api_token"], cfg.get("parent_page_id", ""))
    try:
        existing = client.find_page(title)
        notes = extract_manual_notes(client.get_page_content(str(existing["id"]))) if existing else ""
        storage = client.markdown_to_confluence(inject_manual_notes(generated, notes))
        if existing:
            version = existing.get("version", {}).get("number")
            if version is None:
                current = client._request("GET", f"/pages/{existing['id']}")
                version = current["version"]["number"]
            page = client.update_page(str(existing["id"]), int(version), title, storage)
            action = "updated"
        else:
            page = client.create_page(title, storage)
            action = "created"
        page_id = str(page["id"])
        return PublishResult(True, client.page_url(page_id), page_id, action, stats.coverage, runbook=generated)
    except Exception as exc:
        LOGGER.error("Confluence publish failed: %s", exc)
        return PublishResult(False, scan_coverage=stats.coverage, error=str(exc), runbook=generated)
