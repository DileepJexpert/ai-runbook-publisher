"""Data models for the LLM repository tool-calling agent layer (Phase 3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Evidence:
    """A citation to a specific file and optional line range in the repository."""

    file: str
    start_line: int | None = None
    end_line: int | None = None

    def format(self) -> str:
        """Format citation as file:start-end or file."""
        if self.start_line is not None and self.end_line is not None:
            return f"{self.file}:{self.start_line}-{self.end_line}"
        if self.start_line is not None:
            return f"{self.file}:{self.start_line}"
        return self.file


@dataclass
class AgentAnswer:
    """The structured result returned by RepositoryAgent.ask()."""

    answer: str
    evidence: list[Evidence] = field(default_factory=list)
    tool_calls: int = 0
    status: str = "COMPLETE"  # COMPLETE, INSUFFICIENT_EVIDENCE, LIMIT_REACHED, ERROR
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """The result of executing a tool call."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class LlmMessage:
    """A message in the multi-turn LLM conversation."""

    role: str  # "system", "user", "assistant", "tool"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class LlmResponse:
    """The response returned by LlmClient.run_turn()."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"  # "stop", "tool_calls", "length"


@dataclass
class AgentConfig:
    """Configuration for the repository tool-calling agent."""

    base_url: str | None = None
    api_key: str | None = None
    model: str = "gpt-4o"
    max_agent_turns: int = 15
    max_tool_calls: int = 25
    max_total_tool_chars: int = 100_000
    debug: bool = False
