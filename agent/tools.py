"""Safe, bounded tool definitions and executor for LLM repository exploration (Phase 3)."""

from __future__ import annotations

import json
import logging
from typing import Any

from collector.models import ServiceFacts
from publisher.repository_tools import RepositoryAccessError, RepositoryTools
from .models import ToolCall, ToolResult

LOGGER = logging.getLogger(__name__)

# Standard tool definitions in OpenAI function-calling format
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in the repository under a given relative directory path, optionally filtered by a glob pattern. Ignores build artifacts and binaries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path (e.g. '' for root, 'src/main/java')",
                        "default": "",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Optional glob pattern to filter filenames (e.g. '*.java', '*Consumer*')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of files to return (default 100, max 100)",
                        "default": 100,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search text or regex pattern across repository source files. Returns matching file paths and line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search string (e.g. '@KafkaListener', 'PaymentService', 'ConcurrentMessageListenerContainer')",
                    },
                    "file_glob": {
                        "type": "string",
                        "description": "Optional glob to restrict search files (e.g. '*.java', '*.yml')",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum matches to return (default 30, max 30)",
                        "default": 30,
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Whether to perform case-sensitive search (default false)",
                        "default": False,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the text contents of a repository file. Bounded to a maximum character limit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": {
                        "type": "string",
                        "description": "Repository-relative file path (e.g. 'src/main/resources/application.yml')",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum characters to read (default 20000, max 20000)",
                        "default": 20000,
                    },
                },
                "required": ["relative_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_lines",
            "description": "Read a specific 1-based line range from a repository file. Bounded to maximum 500 lines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "relative_path": {
                        "type": "string",
                        "description": "Repository-relative file path (e.g. 'src/main/java/com/acme/OrderService.java')",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Starting line number (1-based, inclusive)",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Ending line number (1-based, inclusive)",
                    },
                },
                "required": ["relative_path", "start_line", "end_line"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_metadata",
            "description": "Get Git repository metadata (branch, commit SHA, remote origin, clean status).",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_service_facts",
            "description": "Get high-confidence deterministic service facts extracted by Layer 1 (APIs, Kafka, database, config, health, deployment).",
            "parameters": {
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "description": "Optional section to retrieve: 'service', 'build', 'configuration', 'apis', 'kafka', 'datastores', 'downstream_dependencies', 'health_and_metrics', 'deployment'. If omitted, returns an overview.",
                    },
                },
            },
        },
    },
]


class ToolExecutor:
    """Safely executes tool calls requested by the LLM by delegating strictly to RepositoryTools."""

    def __init__(
        self,
        repo_tools: RepositoryTools,
        service_facts: ServiceFacts | None = None,
    ) -> None:
        self.repo_tools = repo_tools
        self.service_facts = service_facts

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Return the OpenAI-compatible tool definitions."""
        return TOOL_SCHEMAS

    def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call safely, catching all errors and returning bounded results."""
        name = tool_call.name
        args = tool_call.arguments

        try:
            if name == "list_files":
                return self._exec_list_files(tool_call.id, args)
            elif name == "search_code":
                return self._exec_search_code(tool_call.id, args)
            elif name == "read_file":
                return self._exec_read_file(tool_call.id, args)
            elif name == "read_lines":
                return self._exec_read_lines(tool_call.id, args)
            elif name == "git_metadata":
                return self._exec_git_metadata(tool_call.id, args)
            elif name == "get_service_facts":
                return self._exec_get_service_facts(tool_call.id, args)
            else:
                return ToolResult(
                    tool_call_id=tool_call.id,
                    name=name,
                    content=f"Error: Unknown tool '{name}'. Available tools: list_files, search_code, read_file, read_lines, git_metadata, get_service_facts.",
                    is_error=True,
                )
        except RepositoryAccessError as err:
            return ToolResult(
                tool_call_id=tool_call.id,
                name=name,
                content=f"RepositoryAccessError: {err}",
                is_error=True,
            )
        except Exception as exc:
            LOGGER.warning("Tool execution error for %s: %s", name, exc)
            return ToolResult(
                tool_call_id=tool_call.id,
                name=name,
                content=f"Error executing {name}: {exc}",
                is_error=True,
            )

    def _exec_list_files(self, call_id: str, args: dict[str, Any]) -> ToolResult:
        path = str(args.get("path", "") or "")
        pattern = args.get("pattern")
        if pattern:
            pattern = str(pattern)
        max_results = min(int(args.get("max_results", 100)), 100)

        files = self.repo_tools.list_files(path=path, pattern=pattern, max_results=max_results)
        if not files:
            content = f"No files found matching path='{path}' pattern='{pattern}'"
        else:
            content = f"Found {len(files)} files:\n" + "\n".join(files)
        return ToolResult(tool_call_id=call_id, name="list_files", content=content)

    def _exec_search_code(self, call_id: str, args: dict[str, Any]) -> ToolResult:
        query = args.get("query")
        if not query or not isinstance(query, str):
            return ToolResult(
                tool_call_id=call_id,
                name="search_code",
                content="Error: 'query' argument is required and must be a non-empty string.",
                is_error=True,
            )

        file_glob = args.get("file_glob")
        if file_glob:
            file_glob = str(file_glob)
        max_results = min(int(args.get("max_results", 30)), 30)
        case_sensitive = bool(args.get("case_sensitive", False))

        matches = self.repo_tools.search_code(
            query=query,
            file_glob=file_glob,
            max_results=max_results,
            case_sensitive=case_sensitive,
        )

        if not matches:
            content = f"No matches found for '{query}'"
        else:
            lines = [f"Found {len(matches)} matches for '{query}':"]
            for m in matches:
                lines.append(f"{m.file}:{m.line}: {m.text.strip()}")
            content = "\n".join(lines)

        return ToolResult(tool_call_id=call_id, name="search_code", content=content)

    def _exec_read_file(self, call_id: str, args: dict[str, Any]) -> ToolResult:
        rel_path = args.get("relative_path")
        if not rel_path or not isinstance(rel_path, str):
            return ToolResult(
                tool_call_id=call_id,
                name="read_file",
                content="Error: 'relative_path' argument is required.",
                is_error=True,
            )

        max_chars = min(int(args.get("max_chars", 20000)), 20000)
        content = self.repo_tools.read_file(relative_path=rel_path, max_chars=max_chars)
        return ToolResult(tool_call_id=call_id, name="read_file", content=content)

    def _exec_read_lines(self, call_id: str, args: dict[str, Any]) -> ToolResult:
        rel_path = args.get("relative_path")
        if not rel_path or not isinstance(rel_path, str):
            return ToolResult(
                tool_call_id=call_id,
                name="read_lines",
                content="Error: 'relative_path' argument is required.",
                is_error=True,
            )

        try:
            start_line = int(args.get("start_line", 1))
            end_line = int(args.get("end_line", 1))
        except (ValueError, TypeError):
            return ToolResult(
                tool_call_id=call_id,
                name="read_lines",
                content="Error: 'start_line' and 'end_line' must be valid integers.",
                is_error=True,
            )

        content = self.repo_tools.read_lines(relative_path=rel_path, start_line=start_line, end_line=end_line)
        return ToolResult(tool_call_id=call_id, name="read_lines", content=content)

    def _exec_git_metadata(self, call_id: str, args: dict[str, Any]) -> ToolResult:
        meta = self.repo_tools.git_metadata()
        return ToolResult(
            tool_call_id=call_id,
            name="git_metadata",
            content=json.dumps(meta, indent=2),
        )

    def _exec_get_service_facts(self, call_id: str, args: dict[str, Any]) -> ToolResult:
        if self.service_facts is None:
            return ToolResult(
                tool_call_id=call_id,
                name="get_service_facts",
                content="Deterministic service facts are not available for this session.",
            )

        section = args.get("section")
        facts_dict = self.service_facts.to_dict()

        if section and isinstance(section, str) and section in facts_dict:
            selected = {section: facts_dict[section]}
            content = json.dumps(selected, indent=2)
        elif section:
            available = list(facts_dict.keys())
            content = f"Section '{section}' not found. Available sections: {available}"
        else:
            overview = {
                "service": facts_dict.get("service"),
                "build": facts_dict.get("build"),
                "api_count": len(facts_dict.get("apis", [])),
                "kafka_consumer_count": len(facts_dict.get("kafka", {}).get("consumers", [])),
                "kafka_producer_count": len(facts_dict.get("kafka", {}).get("producers", [])),
                "database_table_count": len(facts_dict.get("datastores", {}).get("database_tables", [])),
                "downstream_dependency_count": len(facts_dict.get("downstream_dependencies", [])),
                "configuration_key_count": len(facts_dict.get("configuration", [])),
                "scan_status": facts_dict.get("scan", {}).get("status"),
            }
            content = json.dumps(overview, indent=2)

        return ToolResult(tool_call_id=call_id, name="get_service_facts", content=content)
