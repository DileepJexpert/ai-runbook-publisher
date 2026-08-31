"""Factory for instantiating GenerationEngine instances."""

from __future__ import annotations

from typing import Any

from agent.llm_client import LlmClient
from agent.models import AgentConfig
from .api_engine import ApiAgentEngine
from .base import GenerationEngine, UnsupportedGenerationEngineError
from .external_agent_engine import ExternalAgentEngine
from .idfc_coder_engine import IdfcCoderEngine


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
    if clean_name == "api":
        return ApiAgentEngine(client=client, config=agent_config, llm_config=llm_config)
    elif clean_name == "idfc-coder":
        return IdfcCoderEngine(coder_cmd=coder_cmd, mode=coder_mode)
    elif clean_name in ("external-agent", "external"):
        return ExternalAgentEngine()
    else:
        raise UnsupportedGenerationEngineError(
            f"Unsupported generation engine: '{name}'. Supported engines are 'api', 'idfc-coder', 'external-agent'."
        )
