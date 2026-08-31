"""Production Support Runbook generation orchestrator with two-pass discovery & writing (Phase 4)."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.llm_client import LlmClient
from agent.models import AgentConfig
from collector import collect_service_facts, save_service_facts
from collector.models import ServiceFacts
from publisher.engines import (
    ApiAgentEngine,
    EngineGenerationResult,
    GenerationContext,
    GenerationEngine,
    create_generation_engine,
)
from publisher.repository import RepositoryInfo, inspect_repository, resolve_repository
from publisher.validator import ValidationResult, validate_runbook

LOGGER = logging.getLogger(__name__)

DEFAULT_RUNBOOK_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "runbook-prompt.txt"
DEFAULT_DISCOVERY_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "discovery-prompt.txt"


@dataclass
class RunbookGenerationResult:
    """The result of direct Production Support Runbook generation across both passes."""

    service_name: str
    commit_sha: str
    environment: str
    runbook_path: str
    evidence_path: str | None
    validation_status: str  # "PASSED", "FAILED", "DISCOVERY_PREPARED", "RUNBOOK_PREPARED", "PREPARED"
    validation_errors: list[str] = field(default_factory=list)
    tool_calls: int = 0
    duration_seconds: float = 0.0
    runbook_content: str = ""
    engine: str = "api"
    findings_path: str | None = None
    discovery_status: str = "UNKNOWN"
    runbook_status: str = "UNKNOWN"
    repo_name: str = ""


class RunbookGenerator:
    """
    Orchestrates Production Support Runbook generation across pluggable generation engines.
    Maintains a single shared pipeline: repository metadata -> service facts -> discovery -> fresh context runbook writing -> validation.
    """

    def __init__(
        self,
        engine: GenerationEngine | None = None,
        client: LlmClient | None = None,
        config: AgentConfig | None = None,
        prompt_path: Path | str | None = None,
        discovery_prompt_path: Path | str | None = None,
    ) -> None:
        if engine is not None:
            self.engine = engine
        elif client is not None:
            self.engine = ApiAgentEngine(client=client, config=config)
        else:
            self.engine = None
        self.prompt_path = Path(prompt_path) if prompt_path else DEFAULT_RUNBOOK_PROMPT_PATH
        self.discovery_prompt_path = Path(discovery_prompt_path) if discovery_prompt_path else DEFAULT_DISCOVERY_PROMPT_PATH

    def generate(
        self,
        repo_path: str,
        environment: str = "production",
        version: str | None = None,
        service_name_override: str | None = None,
        commit_sha_override: str | None = None,
        branch_override: str | None = None,
        engine: GenerationEngine | str | None = None,
        output_suffix: str | None = None,
        agent_debug: bool = False,
    ) -> RunbookGenerationResult:
        """Generate, validate, and persist a Production Support Runbook using the selected engine."""
        start_time = datetime.now(timezone.utc)

        # 1. Inspect repository
        repo_info = resolve_repository(
            repo_path=repo_path,
            service_override=service_name_override,
            commit_override=commit_sha_override,
            branch_override=branch_override,
        )
        LOGGER.info(
            "Inspected repository for runbook generation: %s (%s), repo=%s",
            repo_info.service_name,
            repo_info.commit_sha[:12],
            repo_info.repo_name,
        )

        # 2. Setup output directory: output/<service>/<commit_short>/
        commit_short = repo_info.commit_sha[:16]
        output_dir = Path("output") / repo_info.service_name / commit_short
        output_dir.mkdir(parents=True, exist_ok=True)

        facts_path = output_dir / "service-facts.json"

        # 3. Collect or load deterministic service facts
        facts: ServiceFacts | None = None
        try:
            facts = collect_service_facts(
                repo_path=repo_path,
                service_name=repo_info.service_name,
                branch=repo_info.branch,
                commit_sha=repo_info.commit_sha,
            )
            save_service_facts(facts)
        except Exception as exc:
            LOGGER.warning("Service fact collection fallback during generation: %s", exc)

        # 4. Load authoritative prompts
        if not self.prompt_path.exists():
            raise FileNotFoundError(f"Runbook prompt template not found at {self.prompt_path}")
        if not self.discovery_prompt_path.exists():
            raise FileNotFoundError(f"Discovery prompt template not found at {self.discovery_prompt_path}")

        prompt_template = self.prompt_path.read_text(encoding="utf-8")
        discovery_template = self.discovery_prompt_path.read_text(encoding="utf-8")
        timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Fill header placeholders
        rendered_prompt = (
            prompt_template
            .replace("{SERVICE_NAME}", repo_info.service_name)
            .replace("{APP_VERSION}", version or "latest")
            .replace("{ENVIRONMENT}", environment)
            .replace("{COMMIT_SHA}", repo_info.commit_sha)
            .replace("{TIMESTAMP}", timestamp_str)
            .replace("{BRANCH}", repo_info.branch or "main")
        )

        rendered_discovery_prompt = (
            discovery_template
            .replace("{SERVICE_NAME}", repo_info.service_name)
            .replace("{APP_VERSION}", version or "latest")
            .replace("{ENVIRONMENT}", environment)
            .replace("{COMMIT_SHA}", repo_info.commit_sha)
            .replace("{TIMESTAMP}", timestamp_str)
            .replace("{BRANCH}", repo_info.branch or "main")
        )

        # 5. Resolve active engine
        active_engine: GenerationEngine
        if engine is not None:
            if isinstance(engine, str):
                active_engine = create_generation_engine(name=engine)
            else:
                active_engine = engine
        elif self.engine is not None:
            active_engine = self.engine
        else:
            active_engine = create_generation_engine(name="api")

        findings_filename = f"REPOSITORY_FINDINGS-{output_suffix}.md" if output_suffix else "REPOSITORY_FINDINGS.md"
        runbook_filename = f"RUNBOOK-{output_suffix}.md" if output_suffix else "RUNBOOK.md"

        context = GenerationContext(
            repo_path=repo_path,
            service_name=repo_info.service_name,
            commit_sha=repo_info.commit_sha,
            branch=repo_info.branch,
            environment=environment,
            version=version,
            discovery_prompt=rendered_discovery_prompt,
            runbook_prompt=rendered_prompt,
            service_facts_path=str(facts_path),
            output_dir=str(output_dir),
            findings_filename=findings_filename,
            runbook_filename=runbook_filename,
            agent_debug=agent_debug,
            output_suffix=output_suffix,
        )

        # 6. Execute generation engine (Pass 1 Discovery + Pass 2 Runbook Writing)
        engine_res: EngineGenerationResult = active_engine.generate(context)

        elapsed_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()
        summary_path = output_dir / "generation-summary.json"

        # 7. Handle Engine PREPARED states (DISCOVERY_PREPARED, RUNBOOK_PREPARED)
        if engine_res.status in ("DISCOVERY_PREPARED", "RUNBOOK_PREPARED", "PREPARED"):
            summary_data = {
                "repository": repo_info.repo_name,
                "service": repo_info.service_name,
                "commit": repo_info.commit_sha,
                "environment": environment,
                "version": version or "latest",
                "branch": repo_info.branch,
                "engine": engine_res.engine,
                "discoveryStatus": engine_res.discovery_status,
                "findingsPath": engine_res.findings_path,
                "runbookStatus": engine_res.runbook_status,
                "runbookPath": engine_res.runbook_path,
                "validationStatus": engine_res.status,
                "durationSeconds": elapsed_seconds,
                "generatedAt": timestamp_str,
            }
            summary_path.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")

            return RunbookGenerationResult(
                service_name=repo_info.service_name,
                commit_sha=repo_info.commit_sha,
                environment=environment,
                runbook_path="",
                evidence_path=None,
                validation_status=engine_res.status,
                validation_errors=[],
                tool_calls=0,
                duration_seconds=elapsed_seconds,
                runbook_content="",
                engine=engine_res.engine,
                findings_path=engine_res.findings_path,
                discovery_status=engine_res.discovery_status,
                runbook_status=engine_res.runbook_status,
                repo_name=repo_info.repo_name,
            )

        # 8. Handle Engine FAILED state
        if engine_res.status != "SUCCESS" or not engine_res.runbook_path:
            err_msg = engine_res.error or "Generation engine failed to produce RUNBOOK.md"
            summary_data = {
                "repository": repo_info.repo_name,
                "service": repo_info.service_name,
                "commit": repo_info.commit_sha,
                "environment": environment,
                "version": version or "latest",
                "branch": repo_info.branch,
                "engine": engine_res.engine,
                "discoveryStatus": engine_res.discovery_status,
                "findingsPath": engine_res.findings_path,
                "runbookStatus": "FAILED",
                "runbookPath": None,
                "validationStatus": "FAILED",
                "error": err_msg,
                "durationSeconds": elapsed_seconds,
                "generatedAt": timestamp_str,
            }
            summary_path.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")

            return RunbookGenerationResult(
                service_name=repo_info.service_name,
                commit_sha=repo_info.commit_sha,
                environment=environment,
                runbook_path="",
                evidence_path=None,
                validation_status="FAILED",
                validation_errors=[err_msg],
                tool_calls=engine_res.tool_calls or 0,
                duration_seconds=elapsed_seconds,
                runbook_content="",
                engine=engine_res.engine,
                findings_path=engine_res.findings_path,
                discovery_status=engine_res.discovery_status,
                runbook_status="FAILED",
                repo_name=repo_info.repo_name,
            )

        # 9. Validate generated RUNBOOK.md
        runbook_path = Path(engine_res.runbook_path)
        val_res: ValidationResult = validate_runbook(
            runbook_path=runbook_path,
            run_dir=output_dir,
            repo_info=repo_info,
        )

        # 10. Write generation summary
        summary_data = {
            "repository": repo_info.repo_name,
            "service": repo_info.service_name,
            "commit": repo_info.commit_sha,
            "environment": environment,
            "version": version or "latest",
            "branch": repo_info.branch,
            "engine": engine_res.engine,
            "discoveryStatus": "COMPLETE",
            "findingsPath": engine_res.findings_path,
            "runbookStatus": "COMPLETE",
            "runbookPath": str(runbook_path),
            "toolCalls": engine_res.tool_calls,
            "validationPassed": val_res.passed,
            "validationErrors": val_res.reasons,
            "validationStatus": "PASSED" if val_res.passed else "FAILED",
            "durationSeconds": elapsed_seconds,
            "generatedAt": timestamp_str,
        }
        summary_path.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")

        return RunbookGenerationResult(
            service_name=repo_info.service_name,
            commit_sha=repo_info.commit_sha,
            environment=environment,
            runbook_path=str(runbook_path),
            evidence_path=engine_res.evidence_path,
            validation_status="PASSED" if val_res.passed else "FAILED",
            validation_errors=val_res.reasons,
            tool_calls=engine_res.tool_calls or 0,
            duration_seconds=elapsed_seconds,
            runbook_content=engine_res.runbook_content,
            engine=engine_res.engine,
            findings_path=engine_res.findings_path,
            discovery_status="COMPLETE",
            runbook_status="COMPLETE",
            repo_name=repo_info.repo_name,
        )
