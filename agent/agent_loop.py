"""Iterative repository exploration agent loop with hard guardrails and evidence validation (Phase 3)."""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from collector.models import ServiceFacts
from publisher.repository import RepositoryInfo, inspect_repository
from publisher.repository_tools import RepositoryTools

from .llm_client import LlmClient
from .models import AgentAnswer, AgentConfig, Evidence, LlmMessage, LlmResponse, ToolCall
from .prompts import build_system_prompt
from .tools import ToolExecutor

LOGGER = logging.getLogger(__name__)

# Pattern to extract citations from answer text, e.g. src/main/java/Foo.java:10-25 or application.yml
_CITATION_PATTERN = re.compile(
    r"\b((?:src|docs|config|\w+[\w\-./]*)\/[a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)(?::(\d+)(?:-(\d+))?)?\b"
)


class RepositoryAgent:
    """
    LLM-powered agent that investigates a local repository interactively using bounded read-only tools.
    Never receives or requests the whole repository at once.
    """

    def __init__(
        self,
        repo_path: str,
        client: LlmClient,
        config: AgentConfig | None = None,
        service_facts: ServiceFacts | None = None,
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.repo_info = inspect_repository(str(self.repo_path))
        self.repo_tools = RepositoryTools(str(self.repo_path))
        self.service_facts = service_facts
        self.client = client
        self.config = config or AgentConfig()
        self.executor = ToolExecutor(self.repo_tools, self.service_facts)

    def ask(self, question: str) -> AgentAnswer:
        """
        Ask a repository-specific question. The agent iteratively calls tools until
        it has enough evidence to produce a grounded answer.
        """
        start_time = time.time()
        LOGGER.info("Starting repository agent for %s. Question: %s", self.repo_info.service_name, question)

        system_prompt = build_system_prompt(self.repo_info, self.service_facts)
        messages: list[LlmMessage] = [
            LlmMessage(role="system", content=system_prompt),
            LlmMessage(role="user", content=question),
        ]

        tool_schemas = self.executor.get_tool_schemas()
        total_tool_calls = 0
        total_tool_chars = 0
        inspected_evidence: list[Evidence] = []

        for turn in range(1, self.config.max_agent_turns + 1):
            LOGGER.debug("Agent turn %d/%d", turn, self.config.max_agent_turns)

            try:
                response = self.client.run_turn(messages, tool_schemas)
            except Exception as exc:
                LOGGER.error("LLM turn execution failed: %s", exc)
                return AgentAnswer(
                    answer=f"Error communicating with LLM: {exc}",
                    evidence=[],
                    tool_calls=total_tool_calls,
                    status="ERROR",
                    duration_seconds=time.time() - start_time,
                )

            # If the LLM requests tool calls
            if response.tool_calls:
                # Add assistant message with tool calls
                messages.append(
                    LlmMessage(
                        role="assistant",
                        content=response.content,
                        tool_calls=response.tool_calls,
                    )
                )

                for tc in response.tool_calls:
                    # Enforce hard limits
                    if total_tool_calls >= self.config.max_tool_calls:
                        LOGGER.warning("Maximum tool call limit (%d) reached.", self.config.max_tool_calls)
                        return AgentAnswer(
                            answer="Maximum tool call limit reached during repository investigation.",
                            evidence=self._validate_evidence(inspected_evidence),
                            tool_calls=total_tool_calls,
                            status="LIMIT_REACHED",
                            duration_seconds=time.time() - start_time,
                        )

                    if total_tool_chars >= self.config.max_total_tool_chars:
                        LOGGER.warning("Maximum tool character budget (%d) reached.", self.config.max_total_tool_chars)
                        return AgentAnswer(
                            answer="Maximum tool character budget reached during repository investigation.",
                            evidence=self._validate_evidence(inspected_evidence),
                            tool_calls=total_tool_calls,
                            status="LIMIT_REACHED",
                            duration_seconds=time.time() - start_time,
                        )

                    if self.config.debug:
                        args_str = ", ".join(f"{k}={v!r}" for k, v in tc.arguments.items())
                        print(f"Agent tool call: {tc.name}({args_str})")

                    # Track inspected files for evidence candidate pool
                    if tc.name in ("read_file", "read_lines"):
                        rel_file = tc.arguments.get("relative_path")
                        if rel_file and isinstance(rel_file, str):
                            start_l = tc.arguments.get("start_line")
                            end_l = tc.arguments.get("end_line")
                            inspected_evidence.append(
                                Evidence(
                                    file=rel_file,
                                    start_line=int(start_l) if start_l is not None else None,
                                    end_line=int(end_l) if end_l is not None else None,
                                )
                            )

                    # Execute tool call
                    result = self.executor.execute(tc)
                    total_tool_calls += 1
                    total_tool_chars += len(result.content)

                    # Append tool result message
                    messages.append(
                        LlmMessage(
                            role="tool",
                            tool_call_id=result.tool_call_id,
                            name=result.name,
                            content=result.content,
                        )
                    )

            # If the LLM provides final answer without tool calls
            elif response.content:
                answer_text = response.content.strip()
                extracted_citations = self._extract_citations_from_text(answer_text)
                all_candidates = extracted_citations + inspected_evidence
                validated = self._validate_evidence(all_candidates)

                status = "COMPLETE"
                lower_ans = answer_text.lower()
                if "insufficient evidence" in lower_ans or "could not find evidence" in lower_ans:
                    status = "INSUFFICIENT_EVIDENCE"

                LOGGER.info("Agent answered in %d turns (%d tool calls). Status: %s", turn, total_tool_calls, status)
                return AgentAnswer(
                    answer=answer_text,
                    evidence=validated,
                    tool_calls=total_tool_calls,
                    status=status,
                    duration_seconds=time.time() - start_time,
                )

        # Loop exhausted turns
        LOGGER.warning("Agent exhausted max turns (%d).", self.config.max_agent_turns)
        return AgentAnswer(
            answer="Maximum turns reached without a final answer from the LLM.",
            evidence=self._validate_evidence(inspected_evidence),
            tool_calls=total_tool_calls,
            status="LIMIT_REACHED",
            duration_seconds=time.time() - start_time,
        )

    def _extract_citations_from_text(self, text: str) -> list[Evidence]:
        """Extract path:start-end or path citations from the LLM response text."""
        citations: list[Evidence] = []
        for match in _CITATION_PATTERN.finditer(text):
            file_path = match.group(1)
            start_str = match.group(2)
            end_str = match.group(3)

            start_l = int(start_str) if start_str else None
            end_l = int(end_str) if end_str else None
            citations.append(Evidence(file=file_path, start_line=start_l, end_line=end_l))
        return citations

    def _validate_evidence(self, candidates: list[Evidence]) -> list[Evidence]:
        """
        Validate evidence citations against the local repository.
        Drops non-existent files, out-of-range lines, and path traversals.
        Returns a deduplicated list of valid repository-relative Evidence objects.
        """
        validated: list[Evidence] = []
        seen: set[str] = set()

        for ev in candidates:
            # Clean and normalize path
            rel_file = ev.file.strip().replace("\\", "/").lstrip("./")
            key = f"{rel_file}:{ev.start_line}:{ev.end_line}"
            if key in seen:
                continue

            try:
                full_path = self.repo_tools._resolve_secure_path(rel_file, must_exist=True)
                if not full_path.is_file():
                    continue

                # Validate line ranges if provided
                start_l = ev.start_line
                end_l = ev.end_line
                if start_l is not None:
                    line_count = len(full_path.read_text(encoding="utf-8", errors="replace").splitlines())
                    if start_l < 1 or start_l > line_count:
                        start_l = None
                        end_l = None
                    elif end_l is not None and (end_l < start_l or end_l > line_count):
                        end_l = None

                validated_ev = Evidence(file=rel_file, start_line=start_l, end_line=end_l)
                seen.add(key)
                validated.append(validated_ev)

            except Exception:
                # Invalid file, path traversal, or unreadable -> drop citation
                continue

        return validated
