"""Pipeline internal LLM API engine for automated CI/CD pipeline execution mode."""

from __future__ import annotations

import logging
from typing import Any

from agent.llm_client import LlmClient
from agent.models import AgentConfig
from publisher.execution_mode import ExecutionMode, ModeEnforcementError
from .api_engine import ApiAgentEngine
from .base import EngineGenerationResult, GenerationContext

LOGGER = logging.getLogger(__name__)


class PipelineLlmApiEngine(ApiAgentEngine):
    """
    Generation engine for PIPELINE execution mode.
    Uses internal organization LLM API in non-interactive mode.
    Strictly excludes IDFC Coder.
    Configurable/mockable adapter until real internal LLM API endpoint/auth contract is provided.
    NEVER falls back to IDFC Coder on failure.
    """

    engine_name: str = "pipeline-api"
    execution_mode: ExecutionMode = ExecutionMode.PIPELINE

    def __init__(
        self,
        client: LlmClient | None = None,
        config: AgentConfig | None = None,
        llm_config: dict[str, Any] | None = None,
        execution_mode: ExecutionMode = ExecutionMode.PIPELINE,
    ) -> None:
        super().__init__(client=client, config=config, llm_config=llm_config)
        self.execution_mode = execution_mode
        self.allow_fallback_to_idfc_coder = False  # Strict rule: No fallback

    def generate(self, context: GenerationContext) -> EngineGenerationResult:
        LOGGER.info("Executing PipelineLlmApiEngine in PIPELINE mode for %s (non-interactive)", context.service_name)
        try:
            result = super().generate(context)
            result.engine = "pipeline-api"
            return result
        except Exception as exc:
            LOGGER.error("PipelineLlmApiEngine failed: %s (No fallback to idfc-coder permitted)", exc)
            # Re-raise or return failure without attempting IDFC Coder fallback
            return EngineGenerationResult(
                status="FAILED",
                engine="pipeline-api",
                error=f"Pipeline LLM API generation failed: {exc}",
                discovery_status="FAILED",
                runbook_status="FAILED",
            )
