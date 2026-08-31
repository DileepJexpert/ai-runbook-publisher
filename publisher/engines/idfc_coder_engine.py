"""IDFC Coder execution engine supporting two-pass Discovery -> Runbook Writing."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from publisher.idfc_coder import execute_idfc_coder
from publisher.repository import RepositoryInfo
from .base import EngineConfigurationError, EngineGenerationResult, GenerationContext

LOGGER = logging.getLogger(__name__)


class IdfcCoderEngine:
    """Generation engine that launches idfc-coder in target repo for discovery and runbook writing passes."""

    def __init__(
        self,
        coder_cmd: str | None = None,
        mode: str | None = None,
    ) -> None:
        self.coder_cmd = coder_cmd or os.environ.get("IDFC_CODER_CMD") or "idfc-coder"
        self.mode = mode or os.environ.get("IDFC_CODER_MODE") or "interactive"

    def generate(self, context: GenerationContext) -> EngineGenerationResult:
        """Execute discovery pass followed by runbook writing pass via idfc-coder."""
        LOGGER.info("Starting IdfcCoderEngine two-pass generation for %s (%s)", context.service_name, context.commit_sha[:12])

        out_dir = Path(context.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        findings_path = out_dir / context.findings_filename
        runbook_path = out_dir / context.runbook_filename
        agent_log_path = out_dir / "agent.log"
        repo_posix = Path(context.repo_path).resolve().as_posix()
        findings_posix = findings_path.resolve().as_posix()
        runbook_posix = runbook_path.resolve().as_posix()

        # -------------------------------------------------------------------
        # PASS 1: DISCOVERY
        # -------------------------------------------------------------------
        if not findings_path.exists() or findings_path.stat().st_size == 0:
            LOGGER.info("Executing Pass 1 (Discovery) with idfc-coder for %s", context.service_name)
            discovery_task_path = out_dir / "idfc-coder-discovery-task.md"

            discovery_task_content = f"""# Repository Discovery Task (IDFC Coder)

Repository:
{repo_posix}

Service:
{context.service_name}

Commit:
{context.commit_sha}

Environment:
{context.environment}

Deterministic Facts:
{context.service_facts_path}

Output:
{findings_posix}

You are analyzing the complete repository at:
{repo_posix}

Use repository search, Git commands and file inspection.
Do NOT modify repository files.
Write ONLY the engineering investigation findings to:
{findings_posix}

{context.discovery_prompt}
""".strip()
            discovery_task_path.write_text(discovery_task_content, encoding="utf-8")

            exec_res = execute_idfc_coder(
                coder_cmd=self.coder_cmd,
                mode=self.mode,
                task_content=discovery_task_content,
                task_path=discovery_task_path,
                repo_path=Path(context.repo_path),
                agent_log_path=agent_log_path,
            )

            if not exec_res.success:
                err_msg = exec_res.error or f"idfc-coder discovery failed with returncode {exec_res.returncode}"
                return EngineGenerationResult(
                    status="FAILED",
                    engine="idfc-coder",
                    error=err_msg,
                    discovery_status="FAILED",
                )

            if not findings_path.exists() or findings_path.stat().st_size == 0:
                return EngineGenerationResult(
                    status="FAILED",
                    engine="idfc-coder",
                    error=f"idfc-coder completed discovery but output findings file was not found at {findings_path}",
                    discovery_status="FAILED",
                )

        findings_content = findings_path.read_text(encoding="utf-8")

        # -------------------------------------------------------------------
        # PASS 2: FRESH RUNBOOK WRITING
        # -------------------------------------------------------------------
        if not runbook_path.exists() or runbook_path.stat().st_size == 0:
            LOGGER.info("Executing Pass 2 (Runbook Writing in fresh session) with idfc-coder for %s", context.service_name)
            runbook_task_path = out_dir / "idfc-coder-runbook-task.md"

            runbook_task_content = f"""# Production Support Runbook Generation Task (IDFC Coder)

Service:
{context.service_name}

Commit:
{context.commit_sha}

Environment:
{context.environment}

Output:
{runbook_posix}

THIS IS A FRESH RUNBOOK-WRITING TASK.
Do NOT inspect the Java repository again.
Translate the verified technical repository findings below into the final Production Support Runbook in Markdown.
Write ONLY the final runbook to:
{runbook_posix}

## Technical Investigation Input (REPOSITORY_FINDINGS.md)
{findings_content}

## Authoritative Runbook Instructions
{context.runbook_prompt}
""".strip()
            runbook_task_path.write_text(runbook_task_content, encoding="utf-8")

            exec_res = execute_idfc_coder(
                coder_cmd=self.coder_cmd,
                mode=self.mode,
                task_content=runbook_task_content,
                task_path=runbook_task_path,
                repo_path=Path(context.repo_path),
                agent_log_path=agent_log_path,
            )

            if not exec_res.success:
                err_msg = exec_res.error or f"idfc-coder runbook writing failed with returncode {exec_res.returncode}"
                return EngineGenerationResult(
                    status="FAILED",
                    findings_path=str(findings_path),
                    engine="idfc-coder",
                    error=err_msg,
                    discovery_status="COMPLETE",
                    runbook_status="FAILED",
                )

        if runbook_path.exists() and runbook_path.stat().st_size > 0:
            runbook_content = runbook_path.read_text(encoding="utf-8")
            return EngineGenerationResult(
                status="SUCCESS",
                runbook_path=str(runbook_path),
                findings_path=str(findings_path),
                engine="idfc-coder",
                runbook_content=runbook_content,
                findings_content=findings_content,
                discovery_status="COMPLETE",
                runbook_status="COMPLETE",
            )

        return EngineGenerationResult(
            status="FAILED",
            findings_path=str(findings_path),
            engine="idfc-coder",
            error=f"idfc-coder completed but output runbook was not found at {runbook_path}",
            discovery_status="COMPLETE",
            runbook_status="FAILED",
        )
