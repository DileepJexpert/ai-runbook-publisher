"""External agent bridge engine supporting state-machine two-pass testing (Discovery -> Runbook Writing)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import EngineGenerationResult, GenerationContext

LOGGER = logging.getLogger(__name__)


class ExternalAgentEngine:
    """
    Generation engine for manual external coding agents (Codex, Antigravity, etc.).
    Implements state-machine:
    1. If REPOSITORY_FINDINGS.md absent -> creates DISCOVERY_TASK.md (returns DISCOVERY_PREPARED)
    2. If REPOSITORY_FINDINGS.md present & RUNBOOK.md absent -> creates RUNBOOK_TASK.md (returns RUNBOOK_PREPARED)
    3. If RUNBOOK.md present -> returns SUCCESS for common pipeline validation
    """

    def generate(self, context: GenerationContext) -> EngineGenerationResult:
        """Prepare discovery task, prepare runbook writing task, or return existing runbook."""
        LOGGER.info("Starting ExternalAgentEngine for %s (%s)", context.service_name, context.commit_sha[:12])

        out_dir = Path(context.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        findings_path = out_dir / context.findings_filename
        runbook_path = out_dir / context.runbook_filename
        discovery_task_path = out_dir / "DISCOVERY_TASK.md"
        runbook_task_path = out_dir / "RUNBOOK_TASK.md"

        repo_path_posix = Path(context.repo_path).resolve().as_posix()
        findings_posix = findings_path.resolve().as_posix()
        runbook_posix = runbook_path.resolve().as_posix()
        facts_posix = Path(context.service_facts_path).resolve().as_posix() if Path(context.service_facts_path).exists() else context.service_facts_path

        # -------------------------------------------------------------------
        # STATE 1: REPOSITORY_FINDINGS.md absent -> Create DISCOVERY_TASK.md
        # -------------------------------------------------------------------
        if not findings_path.exists() or findings_path.stat().st_size == 0:
            discovery_content = f"""# Repository Discovery Task (External Agent)

## Metadata
- **Target Repository:** `{repo_path_posix}`
- **Service Name:** `{context.service_name}`
- **Commit SHA:** `{context.commit_sha}`
- **Branch:** `{context.branch or 'main'}`
- **Environment:** `{context.environment}`
- **Version:** `{context.version or 'latest'}`
- **Deterministic Facts Path:** `{facts_posix}`
- **Target Findings Path:** `{findings_posix}`

---

## Instructions for External Agent (Discovery Pass)
1. Inspect the target repository at `{repo_path_posix}` directly using your codebase tools (search, read lines, list files).
2. Do NOT modify any application source files or Git history in the target repository.
3. Review baseline deterministic facts at `{facts_posix}` as starting evidence, but verify and follow actual code implementation.
4. Follow implementation over names, document observed vs inferred findings, trace failure paths, and record negative findings.
5. Write ONLY the technical engineering investigation findings in Markdown to the exact path:
   `{findings_posix}`

---

## Authoritative Discovery Specification
{context.discovery_prompt}
""".strip()
            discovery_task_path.write_text(discovery_content, encoding="utf-8")
            LOGGER.info("Wrote discovery task to %s", discovery_task_path)

            return EngineGenerationResult(
                status="DISCOVERY_PREPARED",
                findings_path=None,
                runbook_path=None,
                engine="external-agent",
                discovery_status="PREPARED",
                runbook_status="WAITING_FOR_DISCOVERY",
            )

        findings_content = findings_path.read_text(encoding="utf-8")

        # -------------------------------------------------------------------
        # STATE 2: REPOSITORY_FINDINGS.md present, RUNBOOK.md absent -> Create RUNBOOK_TASK.md
        # -------------------------------------------------------------------
        if not runbook_path.exists() or runbook_path.stat().st_size == 0:
            runbook_task_content = f"""# Production Support Runbook Task (External Agent)

## Metadata
- **Service Name:** `{context.service_name}`
- **Commit SHA:** `{context.commit_sha}`
- **Branch:** `{context.branch or 'main'}`
- **Environment:** `{context.environment}`
- **Version:** `{context.version or 'latest'}`
- **Verified Findings Path:** `{findings_posix}`
- **Target Runbook Path:** `{runbook_posix}`

---

## Instructions for External Agent (Runbook Writing Pass)
1. **THIS IS A FRESH WRITING TASK.**
2. Do NOT inspect the Java repository again.
3. Treat `REPOSITORY_FINDINGS.md` as the authoritative technical investigation input.
4. Do not invent facts beyond the supplied findings.
5. Convert technical findings into an operational Production Support Runbook for L1/L2 engineers.
6. Use plain operational English, preserve exact log signatures and config keys from findings, omit unsupported sections, and produce safe actions.
7. Write ONLY the final Production Support Runbook in Markdown to the exact path:
   `{runbook_posix}`

---

## Technical Investigation Input (REPOSITORY_FINDINGS.md)
{findings_content}

---

## Authoritative Support Runbook Specification
{context.runbook_prompt}
""".strip()
            runbook_task_path.write_text(runbook_task_content, encoding="utf-8")
            LOGGER.info("Wrote runbook writing task to %s", runbook_task_path)

            return EngineGenerationResult(
                status="RUNBOOK_PREPARED",
                findings_path=str(findings_path),
                runbook_path=None,
                engine="external-agent",
                findings_content=findings_content,
                discovery_status="COMPLETE",
                runbook_status="PREPARED",
            )

        # -------------------------------------------------------------------
        # STATE 3: RUNBOOK.md present -> Return SUCCESS for common validation
        # -------------------------------------------------------------------
        runbook_content = runbook_path.read_text(encoding="utf-8")
        return EngineGenerationResult(
            status="SUCCESS",
            findings_path=str(findings_path),
            runbook_path=str(runbook_path),
            engine="external-agent",
            findings_content=findings_content,
            runbook_content=runbook_content,
            discovery_status="COMPLETE",
            runbook_status="COMPLETE",
        )
