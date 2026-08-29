"""Provider-neutral LLM client abstraction and implementations (Phase 3)."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Protocol

from .models import LlmMessage, LlmResponse, ToolCall

LOGGER = logging.getLogger(__name__)


class LlmClient(Protocol):
    """Protocol for LLM providers supporting function/tool calling."""

    def run_turn(
        self,
        messages: list[LlmMessage],
        tools: list[dict[str, Any]],
    ) -> LlmResponse:
        """Send messages and available tools to the LLM and return the assistant response."""
        ...


class OpenAiLlmClient:
    """
    OpenAI-compatible tool-calling API client.
    Works with enterprise LLM gateways, local models (Ollama/vLLM), and OpenAI-compatible endpoints.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str = "gpt-4o",
        timeout_seconds: int = 60,
    ) -> None:
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("LLM_API_KEY") or ""
        self.model = model or os.environ.get("LLM_MODEL") or "gpt-4o"
        self.timeout_seconds = timeout_seconds

    def run_turn(
        self,
        messages: list[LlmMessage],
        tools: list[dict[str, Any]],
    ) -> LlmResponse:
        """Call the OpenAI-compatible /chat/completions endpoint."""
        if not self.base_url:
            raise ValueError(
                "LLM_BASE_URL is not configured. Please set the LLM_BASE_URL environment variable "
                "or configure it in config/config.yml."
            )

        endpoint = f"{self.base_url}/chat/completions"

        # Format messages for OpenAI API
        formatted_messages = []
        for m in messages:
            msg_dict: dict[str, Any] = {"role": m.role}
            if m.content is not None:
                msg_dict["content"] = m.content
            if m.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in m.tool_calls
                ]
            if m.tool_call_id:
                msg_dict["tool_call_id"] = m.tool_call_id
            if m.name:
                msg_dict["name"] = m.name
            formatted_messages.append(msg_dict)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ai-runbook-publisher/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
                res_json = json.loads(body)
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            LOGGER.error("LLM API HTTP %s error: %s", err.code, err_body)
            raise RuntimeError(f"LLM API error (HTTP {err.code}): {err_body}") from err
        except urllib.error.URLError as err:
            LOGGER.error("LLM connection error: %s", err.reason)
            raise RuntimeError(f"LLM connection error: {err.reason}") from err

        choices = res_json.get("choices", [])
        if not choices:
            raise RuntimeError(f"LLM returned no choices in response: {res_json}")

        first_choice = choices[0]
        choice_msg = first_choice.get("message", {})
        content = choice_msg.get("content")
        finish_reason = first_choice.get("finish_reason", "stop")

        tool_calls: list[ToolCall] = []
        raw_tool_calls = choice_msg.get("tool_calls", [])
        for raw_tc in raw_tool_calls:
            tc_id = raw_tc.get("id", "")
            fn_dict = raw_tc.get("function", {})
            fn_name = fn_dict.get("name", "")
            raw_args = fn_dict.get("arguments", "{}")
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except Exception:
                    args = {}
            else:
                args = raw_args
            tool_calls.append(ToolCall(id=tc_id, name=fn_name, arguments=args))

        return LlmResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )


class MockLlmClient:
    """
    Mock LLM client for deterministic unit testing.
    Can be configured with a queue of responses or a dynamic response handler.
    """

    def __init__(
        self,
        responses: list[LlmResponse] | None = None,
        handler: Callable[[list[LlmMessage], list[dict[str, Any]]], LlmResponse] | None = None,
    ) -> None:
        self.responses: list[LlmResponse] = list(responses or [])
        self.handler = handler
        self.history: list[list[LlmMessage]] = []

    def run_turn(
        self,
        messages: list[LlmMessage],
        tools: list[dict[str, Any]],
    ) -> LlmResponse:
        self.history.append(list(messages))

        if self.handler is not None:
            return self.handler(messages, tools)

        if self.responses:
            return self.responses.pop(0)

        # Default fallback response
        return LlmResponse(content="Default mock response", finish_reason="stop")
