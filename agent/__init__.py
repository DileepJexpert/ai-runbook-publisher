"""Agent package: minimal repository tool-calling layer for LLM-driven exploration (Phase 3)."""

from __future__ import annotations

from .agent_loop import RepositoryAgent
from .llm_client import LlmClient, MockLlmClient, OpenAiLlmClient
from .models import AgentAnswer, AgentConfig, Evidence, LlmMessage, LlmResponse, ToolCall, ToolResult
from .tools import TOOL_SCHEMAS, ToolExecutor

__all__ = [
    "AgentAnswer",
    "AgentConfig",
    "Evidence",
    "LlmClient",
    "LlmMessage",
    "LlmResponse",
    "MockLlmClient",
    "OpenAiLlmClient",
    "RepositoryAgent",
    "TOOL_SCHEMAS",
    "ToolCall",
    "ToolExecutor",
    "ToolResult",
]
