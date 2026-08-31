"""Factory for instantiating GenerationEngine instances."""

from __future__ import annotations

from typing import Any

from agent.llm_client import LlmClient
from agent.models import AgentConfig
from .api_engine import ApiAgentEngine
from .base import GenerationEngine, UnsupportedGenerationEngineError
from .external_agent_engine import ExternalAgentEngine
from .idfc_coder_engine import IdfcCoderEngine
from .local_idfc_engine import LocalIdfcCoderEngine
from .pipeline_api_engine import PipelineLlmApiEngine


def create_generation_engine(
    name: str = "api",
    client: LlmClient | None = None,
    agent_config: AgentConfig | None = None,
    coder_cmd: str | None = None,
    coder_mode: str | None = None,
    llm_config: dict[str, Any] | None = None,
) -> GenerationEngine:
    """Create a GenerationEngine instance for the requested engine name."""
    clean_name = (name or "api").lower().strip()
    if clean_name in ("api", "pipeline-api", "pipeline_api"):
        if clean_name in ("pipeline-api", "pipeline_api"):
            return PipelineLlmApiEngine(client=client, config=agent_config, llm_config=llm_config)
        return ApiAgentEngine(client=client, config=agent_config, llm_config=llm_config)
    elif clean_name in ("idfc-coder", "idfc_coder", "local-idfc", "local_idfc"):
        if clean_name in ("local-idfc", "local_idfc"):
            return LocalIdfcCoderEngine(coder_cmd=coder_cmd, mode=coder_mode)
        return IdfcCoderEngine(coder_cmd=coder_cmd, mode=coder_mode)
    elif clean_name in ("external-agent", "external"):
        return ExternalAgentEngine()
    else:
        raise UnsupportedGenerationEngineError(
            f"Unsupported generation engine: '{name}'. Supported engines are 'api', 'idfc-coder', 'pipeline-api', 'local-idfc', 'external-agent'."
        )
