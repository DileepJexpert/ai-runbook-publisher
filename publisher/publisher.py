"""Pipeline orchestration for local AI runbook generation and Confluence publishing."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .confluence_client import ConfluenceClient
from .idfc_coder import build_runbook_task, execute_idfc_coder
from .manual_notes import extract_manual_notes, inject_manual_notes
from .repository import resolve_repository
from .validator import validate_runbook

LOGGER = logging.getLogger(__name__)


@dataclass
class PublishResult:
    success: bool
    action: str = ""
    run_dir: Path | None = None
    runbook_path: Path | None = None
    page_url: str = ""
    page_id: str = ""
    error: str | None = None
    runbook: str = ""
    validation_passed: bool = False
    validation_reasons: list[str] = field(default_factory=list)


def _setup_run_logger(run_dir: Path) -> logging.Logger:
    """Create a dedicated file logger for the run."""
    run_log_file = run_dir / "run.log"
    logger = logging.getLogger(f"runbook.{run_dir.name}")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(run_log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    return logger


def publish(
    repo_path: str,
    service: str | None = None,
    environment: str = "production",
    version: str = "latest",
    commit_sha: str | None = None,
    branch: str | None = None,
    config: dict | None = None,
    dry_run: bool = True,
    coder_cmd: str | None = None,
    mode: str | None = None,
) -> PublishResult:
    """
    Execute the end-to-end runbook generation and publishing pipeline.
    """
    config = config or {}
    ai_cfg = config.get("ai", {})

    # Determine coder command and execution mode with fallbacks
    resolved_coder = (
        coder_cmd
        or os.environ.get("IDFC_CODER_CMD")
        or ai_cfg.get("coder_cmd")
        or "idfc-coder"
    )
    resolved_mode = (
        mode
        or os.environ.get("IDFC_CODER_MODE")
        or ai_cfg.get("mode")
        or "interactive"
    )

    # 1. Resolve repository metadata
    repo_info = resolve_repository(
        repo_path,
        service_override=service,
        branch_override=branch,
        commit_override=commit_sha,
    )

    # 2. Create isolated run directory
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    runs_root = Path(__file__).parent.parent / "runs"
    run_dir = runs_root / repo_info.service_name / timestamp_str
    if run_dir.exists():
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        run_dir = runs_root / repo_info.service_name / timestamp_str
    run_dir.mkdir(parents=True, exist_ok=True)

    run_logger = _setup_run_logger(run_dir)
    run_logger.info("Starting runbook pipeline for %s", repo_info.service_name)
    run_logger.info("Repository: %s", repo_info.path)
    run_logger.info("Branch: %s, Commit: %s", repo_info.branch, repo_info.commit_sha)
    run_logger.info("Mode: %s, Dry-run: %s, AI Command: %s", resolved_mode, dry_run, resolved_coder)

    # 3. Write metadata.json
    repo_path_obj = Path(repo_info.path).resolve()
    metadata = {
        "service_name": repo_info.service_name,
        "repo_path": str(repo_path_obj),
        "commit_sha": repo_info.commit_sha,
        "branch": repo_info.branch,
        "origin_url": repo_info.origin_url,
        "environment": environment,
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "mode": resolved_mode,
        "coder_cmd": resolved_coder,
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    # 4. Build and write RUNBOOK_TASK.md
    prompt_path = Path(__file__).parent.parent / "prompts" / "runbook-prompt.txt"
    prompt_template = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    
    runbook_path = run_dir / "RUNBOOK.md"
    task_content = build_runbook_task(
        repo_info=repo_info,
        output_runbook_path=runbook_path,
        prompt_template=prompt_template,
        pipeline_metadata=metadata,
    )
    task_path = run_dir / "RUNBOOK_TASK.md"
    task_path.write_text(task_content, encoding="utf-8")
    run_logger.info("Created RUNBOOK_TASK.md at %s", task_path)

    # 5. Launch idfc-coder from inside the target repository
    agent_log_path = run_dir / "agent.log"
    run_logger.info("Launching AI coder...")
    exec_res = execute_idfc_coder(
        coder_cmd=resolved_coder,
        mode=resolved_mode,
        task_content=task_content,
        task_path=task_path,
        repo_path=repo_path_obj,
        agent_log_path=agent_log_path,
        run_logger=run_logger,
    )
    run_logger.info("AI coder completed with return code %d", exec_res.returncode)

    # 6. Verify RUNBOOK.md exists and is non-empty
    if not runbook_path.exists() or runbook_path.stat().st_size == 0:
        err_msg = f"RUNBOOK_GENERATION_FAILED: RUNBOOK.md was not generated at {runbook_path}."
        run_logger.error(err_msg)
        return PublishResult(
            success=False,
            error=err_msg,
            run_dir=run_dir,
            runbook_path=runbook_path,
        )

    # 7. Validate generated runbook
    run_logger.info("Validating generated RUNBOOK.md...")
    val_res = validate_runbook(runbook_path, run_dir, repo_info)
    runbook_text = runbook_path.read_text(encoding="utf-8", errors="ignore")

    if not val_res.passed:
        err_msg = f"RUNBOOK_VALIDATION_FAILED: {'; '.join(val_res.reasons)}"
        run_logger.error(err_msg)
        return PublishResult(
            success=False,
            error=err_msg,
            run_dir=run_dir,
            runbook_path=runbook_path,
            validation_passed=False,
            validation_reasons=val_res.reasons,
            runbook=runbook_text,
        )

    run_logger.info("Runbook validation PASSED.")

    # 8. Dry-run handling
    if dry_run:
        run_logger.info("Dry-run complete. Runbook generated and validated locally.")
        return PublishResult(
            success=True,
            action="dry-run",
            run_dir=run_dir,
            runbook_path=runbook_path,
            validation_passed=True,
            runbook=runbook_text,
        )

    # 9. Confluence publishing
    cfg = config.get("confluence", {})
    base_url = cfg.get("base_url", "")
    space_key = cfg.get("space_key", "")
    username = cfg.get("username", "")
    api_token = cfg.get("api_token", "")
    parent_page_id = cfg.get("parent_page_id", "")

    if not (base_url and space_key and username and api_token):
        err_msg = "RUNBOOK_PUBLISH_FAILED: Missing Confluence credentials or configuration in config.yml."
        run_logger.error(err_msg)
        return PublishResult(
            success=False,
            error=err_msg,
            run_dir=run_dir,
            runbook_path=runbook_path,
            validation_passed=True,
            runbook=runbook_text,
        )

    client = ConfluenceClient(base_url, space_key, username, api_token, parent_page_id)
    title = f"Production Support Runbook - {repo_info.service_name}"
    
    try:
        run_logger.info("Searching for existing Confluence page '%s' in space '%s'", title, space_key)
        existing = client.find_page(title)
        notes = extract_manual_notes(client.get_page_content(str(existing["id"]))) if existing else ""
        storage = client.markdown_to_confluence(inject_manual_notes(runbook_text, notes))
        
        if existing:
            version_num = existing.get("version", {}).get("number")
            if version_num is None:
                current = client._request("GET", f"/pages/{existing['id']}")
                version_num = current["version"]["number"]
            page = client.update_page(str(existing["id"]), int(version_num), title, storage)
            action = "updated"
        else:
            page = client.create_page(title, storage)
            action = "created"

        page_id = str(page["id"])
        page_url = client.page_url(page_id)
        run_logger.info("Successfully %s Confluence page: %s", action, page_url)
        return PublishResult(
            success=True,
            action=action,
            page_url=page_url,
            page_id=page_id,
            run_dir=run_dir,
            runbook_path=runbook_path,
            validation_passed=True,
            runbook=runbook_text,
        )
    except Exception as exc:
        err_msg = f"RUNBOOK_PUBLISH_FAILED: {exc}"
        run_logger.error(err_msg)
        return PublishResult(
            success=False,
            error=err_msg,
            run_dir=run_dir,
            runbook_path=runbook_path,
            validation_passed=True,
            runbook=runbook_text,
        )
