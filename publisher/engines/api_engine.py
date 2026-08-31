"""API-based generation engine implementing two-pass Discovery -> Runbook Writing."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from agent.llm_client import LlmClient, OpenAiLlmClient
from agent.models import AgentConfig, LlmMessage
from collector.models import ServiceFacts
from .base import EngineConfigurationError, EngineGenerationResult, GenerationContext

LOGGER = logging.getLogger(__name__)


class ApiAgentEngine:
    """Generation engine that executes Pass 1 (Discovery) and Pass 2 (Runbook Writing in a fresh context)."""

    def __init__(
        self,
        client: LlmClient | None = None,
        config: AgentConfig | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> None:
        self.llm_config = llm_config or {}

        if client is not None:
            self.client = client
            self.config = config or AgentConfig()
        else:
            base_url = os.environ.get("LLM_BASE_URL") or self.llm_config.get("base_url")
            api_key = os.environ.get("LLM_API_KEY") or self.llm_config.get("api_key")
            model = os.environ.get("LLM_MODEL") or self.llm_config.get("model", "gpt-4o")

            if not base_url:
                raise EngineConfigurationError(
                    "API_ENGINE_CONFIGURATION_MISSING: LLM_BASE_URL is required.\n"
                    "Please set the LLM_BASE_URL environment variable or configure it in config/config.yml\n"
                    "Note: Ensure the configured endpoint is approved by your organization for repository source code."
                )

            self.client = OpenAiLlmClient(base_url=base_url, api_key=api_key, model=model)
            self.config = config or AgentConfig(
                base_url=base_url,
                api_key=api_key,
                model=model,
            )

    def generate(self, context: GenerationContext) -> EngineGenerationResult:
        """Execute Pass 1 Discovery followed by Pass 2 Runbook Writing in a completely fresh context."""
        LOGGER.info("Starting ApiAgentEngine two-pass generation for %s (%s)", context.service_name, context.commit_sha[:12])

        out_dir = Path(context.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        findings_path = out_dir / context.findings_filename
        runbook_path = out_dir / context.runbook_filename
        evidence_path = out_dir / "evidence.json"

        # -------------------------------------------------------------------
        # PASS 1: DISCOVERY (Interactive Repository Investigation)
        # -------------------------------------------------------------------
        LOGGER.info("Executing Pass 1 (Discovery) for %s", context.service_name)

        facts: ServiceFacts | None = None
        facts_path = Path(context.service_facts_path)
        if facts_path.exists():
            LOGGER.debug("Service facts available at %s", facts_path)

        discovery_task_instruction = (
            f"{context.discovery_prompt}\n\n"
            "## Investigation Target\n"
            f"- **Service Name:** `{context.service_name}`\n"
            f"- **Commit SHA:** `{context.commit_sha}`\n"
            f"- **Branch:** `{context.branch or 'main'}`\n"
            f"- **Environment:** `{context.environment}`\n"
            f"- **Version:** `{context.version or 'latest'}`\n\n"
            "## Discovery Instructions\n"
            "Explore the repository using safe tools and baseline facts.\n"
            "Follow actual implementation rather than names or docs.\n"
            "Write ONLY the engineering investigation findings as REPOSITORY_FINDINGS.md Markdown.\n"
        )

        agent_config = AgentConfig(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
            model=self.config.model,
            max_agent_turns=self.config.max_agent_turns,
            max_tool_calls=self.config.max_tool_calls,
            max_total_tool_chars=self.config.max_total_tool_chars,
            debug=context.agent_debug or self.config.debug,
        )

        from agent.agent_loop import RepositoryAgent

        discovery_agent = RepositoryAgent(
            repo_path=context.repo_path,
            client=self.client,
            config=agent_config,
            service_facts=facts,
        )

        discovery_answer = discovery_agent.ask(discovery_task_instruction)
        findings_content = discovery_answer.answer.strip()
        findings_path.write_text(findings_content, encoding="utf-8")

        evidence_data = [
            {
                "file": ev.file,
                "startLine": ev.start_line,
                "endLine": ev.end_line,
            }
            for ev in discovery_answer.evidence
        ]
        evidence_path.write_text(json.dumps(evidence_data, indent=2), encoding="utf-8")

        # -------------------------------------------------------------------
        # PASS 2: FRESH CONTEXT -> RUNBOOK WRITING
        # -------------------------------------------------------------------
        LOGGER.info("Executing Pass 2 (Runbook Writing in fresh context) for %s", context.service_name)

        runbook_task_instruction = (
            f"{context.runbook_prompt}\n\n"
            "## Technical Investigation Input (REPOSITORY_FINDINGS.md)\n"
            f"{findings_content}\n\n"
            "## Task Instructions\n"
            "THIS IS A FRESH RUNBOOK-WRITING TASK.\n"
            "You do not have direct repository tool access in this pass.\n"
            "Translate the verified technical repository findings above into a Production Support Runbook in Markdown for L1/L2 support engineers.\n"
            "- Use plain operational English.\n"
            "- Omit any sections unsupported by the findings.\n"
            "- Never expose raw Java code blocks, method signatures, or stack traces.\n"
            "- Return ONLY the final Markdown runbook starting with the metadata header.\n"
        )

        fresh_messages = [
            LlmMessage(
                role="system",
                content=(
                    "You are an Expert Site Reliability Engineer and Production Support Specialist. "
                    "Your job is to translate technical repository findings into an operational Support Runbook."
                ),
            ),
            LlmMessage(role="user", content=runbook_task_instruction),
        ]

        writer_response = self.client.run_turn(fresh_messages, tools=[])
        runbook_content = (writer_response.content or "").strip()
        runbook_path.write_text(runbook_content, encoding="utf-8")

        return EngineGenerationResult(
            status="SUCCESS",
            runbook_path=str(runbook_path),
            findings_path=str(findings_path),
            evidence_path=str(evidence_path),
            tool_calls=discovery_answer.tool_calls,
            engine="api",
            runbook_content=runbook_content,
            findings_content=findings_content,
            discovery_status="COMPLETE",
            runbook_status="COMPLETE",
        )
