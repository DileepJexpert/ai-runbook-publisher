"""Tests for the LLM repository tool-calling agent layer (Phase 3)."""

from __future__ import annotations

import inspect
from pathlib import Path
import subprocess
import pytest

from agent.agent_loop import RepositoryAgent
from agent.llm_client import MockLlmClient, OpenAiLlmClient
from agent.models import AgentConfig, Evidence, LlmMessage, LlmResponse, ToolCall
from agent.prompts import build_system_prompt
from agent.tools import TOOL_SCHEMAS, ToolExecutor
from collector.models import ServiceFacts
from publisher.repository import inspect_repository
from publisher.repository_tools import RepositoryTools


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a minimal real git repository in tmp_path with given files."""
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files.items():
        p = repo / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(repo), check=True, capture_output=True)
    return repo


SAMPLE_SERVICE_FILES = {
    "src/main/java/com/acme/PaymentService.java": """package com.acme;

import org.springframework.stereotype.Service;

@Service
public class PaymentService {
    public void processPayment(String id) {
        System.out.println("Processing " + id);
    }
}
""",
    "src/main/java/com/acme/PaymentConsumer.java": """package com.acme;

import com.acme.annotation.PaymentKafkaListener;
import org.springframework.stereotype.Component;

@Component
public class PaymentConsumer {
    @PaymentKafkaListener(topic = "${payment.topic:payment-events}")
    public void consume(String event) {
        // custom consumer
    }
}
""",
    "src/main/java/com/acme/annotation/PaymentKafkaListener.java": """package com.acme.annotation;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface PaymentKafkaListener {
    String topic() default "";
}
""",
    "src/main/java/com/acme/config/KafkaContainerConfig.java": """package com.acme.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.listener.ConcurrentMessageListenerContainer;
import org.springframework.kafka.listener.ContainerProperties;

@Configuration
public class KafkaContainerConfig {
    @Bean
    public ConcurrentMessageListenerContainer<String, String> paymentContainer() {
        ContainerProperties props = new ContainerProperties("payment-raw-topic");
        return new ConcurrentMessageListenerContainer<>(null, props);
    }
}
""",
    "src/main/java/com/acme/client/CbsClientService.java": """package com.acme.client;

import org.springframework.stereotype.Service;

@Service
public class CbsClientService {
    public void callCbs() {
        CbsClientFactory.createClient("http://cbs-internal:8080");
    }
}
""",
    "src/main/resources/application.yml": """spring:
  application:
    name: sample-payment-service
payment:
  topic: payment-stream-v1
""",
}


# ---------------------------------------------------------------------------
# Tool Tests
# ---------------------------------------------------------------------------

def test_01_tool_definitions_expose_only_safe_bounded_tools(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)
    tools = RepositoryTools(str(repo))
    executor = ToolExecutor(tools)
    schemas = executor.get_tool_schemas()

    tool_names = {s["function"]["name"] for s in schemas}
    assert "list_files" in tool_names
    assert "search_code" in tool_names
    assert "read_file" in tool_names
    assert "read_lines" in tool_names
    assert "git_metadata" in tool_names
    assert "get_service_facts" in tool_names

    # Ensure no dangerous tools
    forbidden = {"run_shell", "execute", "bash", "write_file", "delete_file", "git_checkout"}
    assert not (tool_names & forbidden)


def test_02_list_files_result_bounded(tmp_path):
    # Create 150 dummy files
    many_files = {f"src/file_{i}.txt": f"content {i}" for i in range(150)}
    repo = _make_git_repo(tmp_path, many_files)
    tools = RepositoryTools(str(repo))
    executor = ToolExecutor(tools)

    res = executor.execute(ToolCall(id="1", name="list_files", arguments={"max_results": 200}))
    assert not res.is_error
    lines = res.content.splitlines()
    # Header line + max 100 files
    assert len(lines) <= 101


def test_03_search_code_result_bounded(tmp_path):
    many_files = {f"src/file_{i}.txt": "target_match_line" for i in range(50)}
    repo = _make_git_repo(tmp_path, many_files)
    tools = RepositoryTools(str(repo))
    executor = ToolExecutor(tools)

    res = executor.execute(ToolCall(id="2", name="search_code", arguments={"query": "target_match_line", "max_results": 50}))
    assert not res.is_error
    assert "Found 30 matches" in res.content  # Capped at 30


def _make_sample_service_facts(name: str = "sample-service", java_ver: str = "17") -> ServiceFacts:
    from collector.models import BuildFacts, ScanManifest, ServiceMeta
    return ServiceFacts(
        schema_version="1.0.0",
        service=ServiceMeta(
            name=name,
            repository_name=name,
            branch="main",
            commit_sha="1234567890ab",
            origin_url=None,
        ),
        build=BuildFacts(build_system="MAVEN", java_version=java_ver),
        scan=ScanManifest(status="COMPLETE"),
    )


def test_04_read_file_result_bounded(tmp_path):
    large_content = "x" * 50_000
    repo = _make_git_repo(tmp_path, {"large.txt": large_content})
    tools = RepositoryTools(str(repo))
    executor = ToolExecutor(tools)

    res = executor.execute(ToolCall(id="3", name="read_file", arguments={"relative_path": "large.txt", "max_chars": 30000}))
    assert not res.is_error
    # Truncation marker added, content capped within max_chars
    assert "[TRUNCATED]" in res.content
    assert len(res.content) <= 20_050


def test_05_read_lines_result_bounded(tmp_path):
    lines_content = "\n".join(f"line {i}" for i in range(1, 1000))
    repo = _make_git_repo(tmp_path, {"lines.txt": lines_content})
    tools = RepositoryTools(str(repo))
    executor = ToolExecutor(tools)

    # Valid read
    res = executor.execute(ToolCall(id="4", name="read_lines", arguments={"relative_path": "lines.txt", "start_line": 10, "end_line": 20}))
    assert not res.is_error
    assert "line 10" in res.content
    assert "line 20" in res.content

    # Over 500 lines rejected by RepositoryTools
    res_large = executor.execute(ToolCall(id="5", name="read_lines", arguments={"relative_path": "lines.txt", "start_line": 1, "end_line": 600}))
    assert res_large.is_error


def test_06_path_traversal_blocked_in_tools(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)
    tools = RepositoryTools(str(repo))
    executor = ToolExecutor(tools)

    res = executor.execute(ToolCall(id="6", name="read_file", arguments={"relative_path": "../../etc/passwd"}))
    assert res.is_error
    assert "RepositoryAccessError" in res.content or "Error" in res.content


def test_07_invalid_tool_name_rejected_safely(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)
    tools = RepositoryTools(str(repo))
    executor = ToolExecutor(tools)

    res = executor.execute(ToolCall(id="7", name="run_shell", arguments={"cmd": "ls"}))
    assert res.is_error
    assert "Unknown tool 'run_shell'" in res.content


def test_08_malformed_tool_args_rejected_safely(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)
    tools = RepositoryTools(str(repo))
    executor = ToolExecutor(tools)

    # search_code without query
    res = executor.execute(ToolCall(id="8", name="search_code", arguments={}))
    assert res.is_error

    # read_lines with invalid types
    res2 = executor.execute(ToolCall(id="9", name="read_lines", arguments={"relative_path": "app.yml", "start_line": "bad"}))
    assert res2.is_error


def test_09_get_service_facts_tool(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)
    tools = RepositoryTools(str(repo))
    facts = _make_sample_service_facts(name="my-service")
    executor = ToolExecutor(tools, service_facts=facts)

    # Overview
    res = executor.execute(ToolCall(id="10", name="get_service_facts", arguments={}))
    assert not res.is_error
    assert "my-service" in res.content

    # Specific section
    res_sec = executor.execute(ToolCall(id="11", name="get_service_facts", arguments={"section": "service"}))
    assert not res_sec.is_error
    assert "my-service" in res_sec.content


# ---------------------------------------------------------------------------
# Agent Loop Tests
# ---------------------------------------------------------------------------

def test_10_agent_executes_single_turn_and_returns_answer(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)

    mock_client = MockLlmClient(responses=[
        LlmResponse(
            content="The service is PaymentService in src/main/java/com/acme/PaymentService.java:1-10.",
            finish_reason="stop",
        )
    ])

    agent = RepositoryAgent(str(repo), client=mock_client)
    ans = agent.ask("What is the main service class?")

    assert ans.status == "COMPLETE"
    assert "PaymentService" in ans.answer
    assert ans.tool_calls == 0
    assert len(ans.evidence) == 1
    assert ans.evidence[0].file == "src/main/java/com/acme/PaymentService.java"


def test_11_agent_executes_multi_turn_tool_calls(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)

    mock_client = MockLlmClient(responses=[
        # Turn 1: LLM asks to search code
        LlmResponse(
            tool_calls=[ToolCall(id="call_1", name="search_code", arguments={"query": "processPayment"})],
            finish_reason="tool_calls",
        ),
        # Turn 2: LLM reads the file found
        LlmResponse(
            tool_calls=[ToolCall(id="call_2", name="read_lines", arguments={
                "relative_path": "src/main/java/com/acme/PaymentService.java",
                "start_line": 5,
                "end_line": 10,
            })],
            finish_reason="tool_calls",
        ),
        # Turn 3: LLM returns final answer
        LlmResponse(
            content="Payment processing is implemented in src/main/java/com/acme/PaymentService.java:5-10.",
            finish_reason="stop",
        ),
    ])

    agent = RepositoryAgent(str(repo), client=mock_client)
    ans = agent.ask("Where is payment processed?")

    assert ans.status == "COMPLETE"
    assert ans.tool_calls == 2
    assert len(ans.evidence) >= 1
    assert any(e.file == "src/main/java/com/acme/PaymentService.java" for e in ans.evidence)


def test_12_agent_max_turns_enforced(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)

    # Endless loop of search calls
    def loop_handler(messages, tools):
        return LlmResponse(
            tool_calls=[ToolCall(id="loop_call", name="search_code", arguments={"query": "Payment"})],
            finish_reason="tool_calls",
        )

    mock_client = MockLlmClient(handler=loop_handler)
    config = AgentConfig(max_agent_turns=3)
    agent = RepositoryAgent(str(repo), client=mock_client, config=config)

    ans = agent.ask("Infinite loop question")
    assert ans.status == "LIMIT_REACHED"
    assert "Maximum turns reached" in ans.answer


def test_13_agent_max_tool_calls_enforced(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)

    # Request 5 tool calls in one turn when max is 2
    mock_client = MockLlmClient(responses=[
        LlmResponse(
            tool_calls=[
                ToolCall(id="c1", name="search_code", arguments={"query": "A"}),
                ToolCall(id="c2", name="search_code", arguments={"query": "B"}),
                ToolCall(id="c3", name="search_code", arguments={"query": "C"}),
            ],
            finish_reason="tool_calls",
        )
    ])

    config = AgentConfig(max_tool_calls=2)
    agent = RepositoryAgent(str(repo), client=mock_client, config=config)

    ans = agent.ask("Check tool call limit")
    assert ans.status == "LIMIT_REACHED"
    assert "Maximum tool call limit reached" in ans.answer


def test_14_agent_max_total_tool_chars_enforced(tmp_path):
    large_text = "A" * 5000
    repo = _make_git_repo(tmp_path, {"file.txt": large_text})

    mock_client = MockLlmClient(responses=[
        LlmResponse(
            tool_calls=[ToolCall(id="c1", name="read_file", arguments={"relative_path": "file.txt", "max_chars": 5000})],
            finish_reason="tool_calls",
        ),
        LlmResponse(
            tool_calls=[ToolCall(id="c2", name="read_file", arguments={"relative_path": "file.txt", "max_chars": 5000})],
            finish_reason="tool_calls",
        ),
    ])

    config = AgentConfig(max_total_tool_chars=3000)
    agent = RepositoryAgent(str(repo), client=mock_client, config=config)

    ans = agent.ask("Check char budget limit")
    assert ans.status == "LIMIT_REACHED"
    assert "Maximum tool character budget reached" in ans.answer


def test_15_evidence_validation_drops_hallucinated_files(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)

    mock_client = MockLlmClient(responses=[
        LlmResponse(
            content="Real evidence: src/main/java/com/acme/PaymentService.java:1-5\nFake evidence: src/main/FakeNonExistent.java:10-20",
            finish_reason="stop",
        )
    ])

    agent = RepositoryAgent(str(repo), client=mock_client)
    ans = agent.ask("Evidence test")

    files = [e.file for e in ans.evidence]
    assert "src/main/java/com/acme/PaymentService.java" in files
    assert "src/main/FakeNonExistent.java" not in files


def test_16_evidence_validation_drops_out_of_bounds_lines(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)

    # PaymentService.java has ~10 lines
    mock_client = MockLlmClient(responses=[
        LlmResponse(
            content="Evidence: src/main/java/com/acme/PaymentService.java:1000-2000",
            finish_reason="stop",
        )
    ])

    agent = RepositoryAgent(str(repo), client=mock_client)
    ans = agent.ask("Evidence lines test")

    assert len(ans.evidence) == 1
    # Line numbers out of range should be sanitized to None
    assert ans.evidence[0].file == "src/main/java/com/acme/PaymentService.java"
    assert ans.evidence[0].start_line is None


def test_17_evidence_paths_are_strictly_relative(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)

    mock_client = MockLlmClient(responses=[
        LlmResponse(
            content=f"Evidence: ./src/main/java/com/acme/PaymentService.java:1-8",
            finish_reason="stop",
        )
    ])

    agent = RepositoryAgent(str(repo), client=mock_client)
    ans = agent.ask("Relative path test")

    for ev in ans.evidence:
        assert not ev.file.startswith("./")
        assert not ev.file.startswith("/")
        assert not ":" in ev.file[:3]  # No Windows drive C: in file path


def test_18_system_prompt_contains_compact_service_summary(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)
    info = inspect_repository(str(repo))
    facts = _make_sample_service_facts(name="test-service", java_ver="17")

    prompt = build_system_prompt(info, facts)
    assert "Java / Spring Boot Version: 17" in prompt
    assert "Deterministic Baseline Facts" in prompt
    assert "GROUNDED IN EVIDENCE" in prompt


# ---------------------------------------------------------------------------
# Domain Investigation Tests (Custom annotations, programmatic, custom SDK)
# ---------------------------------------------------------------------------

def test_19_custom_annotation_investigation(tmp_path):
    """
    Demonstrates that the LLM agent can discover and investigate a custom annotation (@PaymentKafkaListener)
    without requiring Python deterministic rules to have prior knowledge of that annotation.
    """
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)

    mock_client = MockLlmClient(responses=[
        # 1. Agent searches for custom annotation
        LlmResponse(
            tool_calls=[ToolCall(id="1", name="search_code", arguments={"query": "PaymentKafkaListener"})],
            finish_reason="tool_calls",
        ),
        # 2. Agent inspects definition
        LlmResponse(
            tool_calls=[ToolCall(id="2", name="read_file", arguments={
                "relative_path": "src/main/java/com/acme/annotation/PaymentKafkaListener.java"
            })],
            finish_reason="tool_calls",
        ),
        # 3. Agent inspects consumer usage
        LlmResponse(
            tool_calls=[ToolCall(id="3", name="read_lines", arguments={
                "relative_path": "src/main/java/com/acme/PaymentConsumer.java",
                "start_line": 1,
                "end_line": 15,
            })],
            finish_reason="tool_calls",
        ),
        # 4. Agent provides answer grounded in evidence
        LlmResponse(
            content=(
                "Kafka consumption is configured using the custom `@PaymentKafkaListener` annotation.\n"
                "Evidence:\n"
                "- src/main/java/com/acme/annotation/PaymentKafkaListener.java:8-12\n"
                "- src/main/java/com/acme/PaymentConsumer.java:7-13"
            ),
            finish_reason="stop",
        ),
    ])

    agent = RepositoryAgent(str(repo), client=mock_client)
    ans = agent.ask("How does this service consume Kafka messages?")

    assert ans.status == "COMPLETE"
    assert "@PaymentKafkaListener" in ans.answer
    assert ans.tool_calls == 3
    ev_files = {e.file for e in ans.evidence}
    assert "src/main/java/com/acme/annotation/PaymentKafkaListener.java" in ev_files
    assert "src/main/java/com/acme/PaymentConsumer.java" in ev_files


def test_20_programmatic_kafka_container_investigation(tmp_path):
    """
    Demonstrates discovering programmatic Kafka listener container setup without special parser rules.
    """
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)

    mock_client = MockLlmClient(responses=[
        # 1. Search for container setup
        LlmResponse(
            tool_calls=[ToolCall(id="1", name="search_code", arguments={"query": "ConcurrentMessageListenerContainer"})],
            finish_reason="tool_calls",
        ),
        # 2. Read container configuration class
        LlmResponse(
            tool_calls=[ToolCall(id="2", name="read_file", arguments={
                "relative_path": "src/main/java/com/acme/config/KafkaContainerConfig.java"
            })],
            finish_reason="tool_calls",
        ),
        # 3. Answer
        LlmResponse(
            content=(
                "The service programmatically sets up a `ConcurrentMessageListenerContainer` listening to `payment-raw-topic`.\n"
                "Evidence: src/main/java/com/acme/config/KafkaContainerConfig.java:10-15"
            ),
            finish_reason="stop",
        ),
    ])

    agent = RepositoryAgent(str(repo), client=mock_client)
    ans = agent.ask("How is Kafka programmatically configured?")

    assert ans.status == "COMPLETE"
    assert "ConcurrentMessageListenerContainer" in ans.answer
    assert any(e.file == "src/main/java/com/acme/config/KafkaContainerConfig.java" for e in ans.evidence)


def test_21_custom_http_client_investigation(tmp_path):
    """
    Demonstrates discovering custom factory client creations (e.g. CbsClientFactory.createClient).
    """
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)

    mock_client = MockLlmClient(responses=[
        # 1. Search for client factory
        LlmResponse(
            tool_calls=[ToolCall(id="1", name="search_code", arguments={"query": "CbsClientFactory"})],
            finish_reason="tool_calls",
        ),
        # 2. Read caller service
        LlmResponse(
            tool_calls=[ToolCall(id="2", name="read_file", arguments={
                "relative_path": "src/main/java/com/acme/client/CbsClientService.java"
            })],
            finish_reason="tool_calls",
        ),
        # 3. Answer
        LlmResponse(
            content=(
                "The service creates a downstream client via `CbsClientFactory.createClient` pointing to `http://cbs-internal:8080`.\n"
                "Evidence: src/main/java/com/acme/client/CbsClientService.java:7-9"
            ),
            finish_reason="stop",
        ),
    ])

    agent = RepositoryAgent(str(repo), client=mock_client)
    ans = agent.ask("Which external HTTP services are invoked?")

    assert ans.status == "COMPLETE"
    assert "CbsClientFactory" in ans.answer
    assert any(e.file == "src/main/java/com/acme/client/CbsClientService.java" for e in ans.evidence)


# ---------------------------------------------------------------------------
# Security & Architecture Guardrail Tests
# ---------------------------------------------------------------------------

def test_22_openai_client_missing_base_url_raises_clear_error():
    client = OpenAiLlmClient(base_url="")
    with pytest.raises(ValueError, match="LLM_BASE_URL is not configured"):
        client.run_turn([], [])


def test_23_repository_remains_unmodified_after_agent_interaction(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_SERVICE_FILES)
    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True).stdout

    mock_client = MockLlmClient(responses=[
        LlmResponse(
            tool_calls=[
                ToolCall(id="1", name="list_files", arguments={}),
                ToolCall(id="2", name="search_code", arguments={"query": "Payment"}),
                ToolCall(id="3", name="read_file", arguments={"relative_path": "src/main/resources/application.yml"}),
            ],
            finish_reason="tool_calls",
        ),
        LlmResponse(content="Done.", finish_reason="stop"),
    ])

    agent = RepositoryAgent(str(repo), client=mock_client)
    agent.ask("Test repo immutability")

    status_after = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True).stdout
    assert status_before == status_after == ""


def test_24_no_confluence_call_from_agent():
    import agent.agent_loop as m1
    import agent.llm_client as m2
    import agent.prompts as m3
    import agent.tools as m4

    for mod in [m1, m2, m3, m4]:
        src = inspect.getsource(mod).lower()
        assert "confluence" not in src, f"Confluence reference in {mod.__name__}"


def test_25_no_whole_repository_concatenation_in_agent():
    import agent.agent_loop as m1
    import agent.tools as m2

    forbidden = ["repo_text", "full_source", "concatenate_repo", "whole_repo", "entire_repository"]
    for mod in [m1, m2]:
        src = inspect.getsource(mod).lower()
        for marker in forbidden:
            assert marker not in src, f"Forbidden concatenation marker '{marker}' in {mod.__name__}"
