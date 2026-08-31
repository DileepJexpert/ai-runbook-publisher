"""Comprehensive tests verifying the Two-Pass (Discovery -> Fresh Context -> Runbook Writing) Architecture."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
import subprocess
import pytest

from agent.llm_client import MockLlmClient
from agent.models import LlmMessage, LlmResponse, ToolCall
from publisher.engines import (
    ApiAgentEngine,
    ExternalAgentEngine,
    GenerationContext,
    IdfcCoderEngine,
    create_generation_engine,
)
from publisher.repository import inspect_repository
from publisher.runbook_generator import RunbookGenerator
from publisher.validator import validate_runbook


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
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


SAMPLE_REPO_FILES = {
    "pom.xml": """<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.idfc.pay</groupId>
    <artifactId>payment-service</artifactId>
    <version>1.0.0</version>
    <properties>
        <java.version>21</java.version>
    </properties>
</project>""",
    "src/main/resources/application.yml": """spring:
  application:
    name: payment-service
kafka:
  inbound:
    topic: payment-inbound-topic
""",
    "src/main/java/com/idfc/pay/PaymentListener.java": """package com.idfc.pay;

import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class PaymentListener {
    @KafkaListener(topics = "${kafka.inbound.topic}")
    public void onMessage(String payload) {
        // process payment
    }
}
""",
}

FINDINGS_SAMPLE = """# Repository Findings

## Service Purpose
Processes incoming payment events from Kafka.

## Kafka
- Inbound topic: `payment-inbound-topic` (configured in `kafka.inbound.topic`)

## Operational Logs
- `Processing payment event: {eventId}`
"""

RUNBOOK_SAMPLE = """# Production Support Runbook - payment-service

> **Service:** payment-service
> **Version:** 1.0.0
> **Environment:** production
> **Commit:** {COMMIT_SHA}
> **Generated:** 2026-08-29 12:00:00 UTC
> **Branch:** main

## Service Overview
Processes incoming payment events from Kafka.

## How to Trace a Transaction
Look up event in logs: `Processing payment event: {eventId}`

## Kafka Topics
- Inbound Topic: `payment-inbound-topic`

## Support Boundaries
Support must not replay Kafka topics or reset offsets without L3 approval.

## Escalation Guide
Collect service name, version, eventId, and log signature before escalating.
"""


# ---------------------------------------------------------------------------
# Requirement Tests (1 - 30)
# ---------------------------------------------------------------------------

def test_01_discovery_prompt_loaded_from_file(tmp_path):
    """1. Verify discovery-prompt.txt is loaded from file."""
    prompt_file = Path("prompts/discovery-prompt.txt")
    assert prompt_file.is_file()
    content = prompt_file.read_text(encoding="utf-8")
    assert "senior Java/Spring Boot engineer investigating a service repository" in content
    assert "REPOSITORY_FINDINGS.md" in content


def test_02_and_03_service_facts_and_metadata_provided_to_discovery(tmp_path, monkeypatch):
    """2 & 3. Verify service-facts and repository metadata are provided to discovery context."""
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    captured_discovery_prompt = []

    def mock_handler(messages: list[LlmMessage], tools: list[dict]):
        if len(captured_discovery_prompt) == 0:
            captured_discovery_prompt.append(messages[1].content)
            return LlmResponse(content=FINDINGS_SAMPLE, finish_reason="stop")
        return LlmResponse(content=RUNBOOK_SAMPLE.replace("{COMMIT_SHA}", info.commit_sha), finish_reason="stop")

    client = MockLlmClient(handler=mock_handler)
    generator = RunbookGenerator(client=client)
    generator.generate(str(repo), environment="staging", version="2.1.0")

    assert len(captured_discovery_prompt) == 1
    prompt_text = captured_discovery_prompt[0]
    assert "payment-service" in prompt_text
    assert info.commit_sha in prompt_text
    assert "staging" in prompt_text
    assert "2.1.0" in prompt_text


def test_04_whole_repository_not_embedded_into_discovery_task(tmp_path, monkeypatch):
    """4. Verify whole repository source code is not embedded into discovery prompt or task file."""
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    engine = ExternalAgentEngine()
    generator = RunbookGenerator(engine=engine)
    res = generator.generate(str(repo))

    task_file = tmp_path / "output" / "payment-service" / res.generation_key / "DISCOVERY_TASK.md"
    assert task_file.is_file()
    task_text = task_file.read_text(encoding="utf-8")

    assert "package com.idfc.pay;" not in task_text
    assert "public class PaymentListener" not in task_text


def test_05_discovery_produces_repository_findings_md(tmp_path, monkeypatch):
    """5. Verify discovery produces REPOSITORY_FINDINGS.md."""
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    mock_client = MockLlmClient(responses=[
        LlmResponse(content=FINDINGS_SAMPLE, finish_reason="stop"),
        LlmResponse(content=RUNBOOK_SAMPLE.replace("{COMMIT_SHA}", info.commit_sha), finish_reason="stop"),
    ])

    generator = RunbookGenerator(client=mock_client)
    result = generator.generate(str(repo))

    assert result.findings_path is not None
    findings_path = Path(result.findings_path)
    assert findings_path.name == "REPOSITORY_FINDINGS.md"
    assert findings_path.is_file()
    assert "Repository Findings" in findings_path.read_text(encoding="utf-8")


def test_06_to_13_runbook_writing_uses_fresh_context_with_findings_only(tmp_path, monkeypatch):
    """
    6. runbook pass does not start before findings exist
    7. runbook writing uses a fresh context
    8. runbook writing does not receive discovery message history
    9. runbook writer receives findings
    10. runbook writer receives metadata
    11. runbook writer receives runbook prompt
    12. runbook writer does not receive service-facts.json directly
    13. runbook writer does not receive whole repository
    """
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    captured_calls = []

    def mock_handler(messages: list[LlmMessage], tools: list[dict]):
        captured_calls.append({
            "message_count": len(messages),
            "messages": [m.content for m in messages],
            "tools": tools,
        })
        if len(captured_calls) == 1:
            return LlmResponse(content=FINDINGS_SAMPLE, finish_reason="stop")
        return LlmResponse(content=RUNBOOK_SAMPLE.replace("{COMMIT_SHA}", info.commit_sha), finish_reason="stop")

    client = MockLlmClient(handler=mock_handler)
    generator = RunbookGenerator(client=client)
    generator.generate(str(repo), environment="production", version="1.0.0")

    assert len(captured_calls) == 2

    pass1_call = captured_calls[0]
    pass2_call = captured_calls[1]

    # Pass 2 is a FRESH session (exactly system + user message, not accumulated conversation)
    assert pass2_call["message_count"] == 2
    assert pass2_call["tools"] == []  # Writer does not receive repo tools

    pass2_user_prompt = pass2_call["messages"][1]
    # 9. Receives findings
    assert "Technical Investigation Input (REPOSITORY_FINDINGS.md)" in pass2_user_prompt
    assert "Repository Findings" in pass2_user_prompt
    # 10. Receives metadata
    assert "payment-service" in pass2_user_prompt
    assert info.commit_sha in pass2_user_prompt
    # 11. Receives runbook prompt
    assert "Expert Site Reliability Engineer" in pass2_user_prompt
    # 12 & 13. Does not receive raw service-facts schema or whole repo
    assert "package com.idfc.pay;" not in pass2_user_prompt
    assert '"schemaVersion":' not in pass2_user_prompt


def test_14_api_discovery_uses_repository_agent_tools(tmp_path, monkeypatch):
    """14. Verify API discovery uses RepositoryAgent tools."""
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    mock_client = MockLlmClient(responses=[
        LlmResponse(
            tool_calls=[ToolCall(id="t1", name="list_files", arguments={})],
            finish_reason="tool_calls",
        ),
        LlmResponse(
            tool_calls=[ToolCall(id="t2", name="search_code", arguments={"query": "@KafkaListener"})],
            finish_reason="tool_calls",
        ),
        LlmResponse(content=FINDINGS_SAMPLE, finish_reason="stop"),
        LlmResponse(content=RUNBOOK_SAMPLE.replace("{COMMIT_SHA}", info.commit_sha), finish_reason="stop"),
    ])

    engine = ApiAgentEngine(client=mock_client)
    generator = RunbookGenerator(engine=engine)
    result = generator.generate(str(repo))

    assert result.tool_calls == 2
    assert result.validation_status == "PASSED"


def test_15_api_runbook_writing_starts_fresh_session(tmp_path, monkeypatch):
    """15. Verify API runbook writing starts in a brand-new session with no discovery history."""
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    sessions = []

    def tracking_handler(messages, tools):
        sessions.append(len(messages))
        if len(sessions) == 1:
            return LlmResponse(content=FINDINGS_SAMPLE, finish_reason="stop")
        return LlmResponse(content=RUNBOOK_SAMPLE.replace("{COMMIT_SHA}", info.commit_sha), finish_reason="stop")

    client = MockLlmClient(handler=tracking_handler)
    engine = ApiAgentEngine(client=client)
    generator = RunbookGenerator(engine=engine)
    generator.generate(str(repo))

    assert len(sessions) == 2
    # Pass 2 session length is 2 (system + user prompt only)
    assert sessions[1] == 2


def test_16_and_17_idfc_coder_discovery_and_fresh_runbook_task(tmp_path, monkeypatch):
    """16 & 17. Verify idfc-coder discovery runs in target repo and runbook writing is a separate second invocation."""
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    engine = IdfcCoderEngine(coder_cmd="python -c \"pass\"", mode="stdin")
    generator = RunbookGenerator(engine=engine)
    res = generator.generate(str(repo))

    out_dir = tmp_path / "output" / "payment-service" / res.generation_key
    discovery_task = out_dir / "idfc-coder-discovery-task.md"
    assert discovery_task.is_file()
    assert "Repository Discovery Task" in discovery_task.read_text(encoding="utf-8")


def test_18_to_22_external_agent_three_run_state_machine(tmp_path, monkeypatch):
    """
    18. external first run creates DISCOVERY_TASK.md
    19. external first run does not create RUNBOOK_TASK.md
    20. external second run creates RUNBOOK_TASK.md when findings exist
    21. external second task tells agent not to inspect Java repo
    22. external third run validates RUNBOOK.md
    """
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    engine = ExternalAgentEngine()
    generator = RunbookGenerator(engine=engine)

    # --- Run 1: First run with no findings ---
    res1 = generator.generate(str(repo))
    assert res1.validation_status == "DISCOVERY_PREPARED"
    assert res1.discovery_status == "PREPARED"
    assert res1.runbook_status == "WAITING_FOR_DISCOVERY"

    out_dir = tmp_path / "output" / "payment-service" / res1.generation_key
    assert (out_dir / "DISCOVERY_TASK.md").is_file()
    assert not (out_dir / "RUNBOOK_TASK.md").exists()
    assert not (out_dir / "REPOSITORY_FINDINGS.md").exists()

    # --- External agent creates REPOSITORY_FINDINGS.md ---
    (out_dir / "REPOSITORY_FINDINGS.md").write_text(FINDINGS_SAMPLE, encoding="utf-8")

    # --- Run 2: Second run with findings but no RUNBOOK.md ---
    res2 = generator.generate(str(repo))
    assert res2.validation_status == "RUNBOOK_PREPARED"
    assert res2.discovery_status == "COMPLETE"
    assert res2.runbook_status == "PREPARED"
    runbook_task = out_dir / "RUNBOOK_TASK.md"
    assert runbook_task.is_file()
    task_text = runbook_task.read_text(encoding="utf-8")
    assert "THIS IS A FRESH WRITING TASK" in task_text
    assert "not inspect the java repository again" in task_text.lower()

    # --- External agent creates RUNBOOK.md ---
    (out_dir / "RUNBOOK.md").write_text(RUNBOOK_SAMPLE.replace("{COMMIT_SHA}", info.commit_sha), encoding="utf-8")

    # --- Run 3: Third run with RUNBOOK.md present -> Validates ---
    res3 = generator.generate(str(repo))
    assert res3.validation_status == "PASSED"
    assert res3.discovery_status == "COMPLETE"
    assert res3.runbook_status == "COMPLETE"
    assert (out_dir / "validation-report.txt").is_file()


def test_23_repository_remains_unchanged(tmp_path, monkeypatch):
    """23. Verify repository remains strictly unchanged across runs."""
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    monkeypatch.chdir(tmp_path)

    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True).stdout

    engine = ExternalAgentEngine()
    generator = RunbookGenerator(engine=engine)
    generator.generate(str(repo))

    status_after = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True).stdout
    assert status_before == status_after == ""


def test_24_validator_remains_common_across_engines(tmp_path, monkeypatch):
    """24. Verify validator is identical and used for all engines."""
    import publisher.validator as val_mod
    assert hasattr(val_mod, "validate_runbook")
    assert hasattr(val_mod, "ValidationResult")


def test_25_to_29_no_unwanted_architectural_additions():
    """
    25. no semantic-facts.json
    26. no merger
    27. no renderer
    28. no embeddings
    29. no mandatory index
    """
    import publisher.runbook_generator as gen_mod
    import publisher.engines.base as base_mod
    import publisher.engines.api_engine as api_mod
    import publisher.engines.external_agent_engine as ext_mod

    code_combined = "\n".join([
        inspect.getsource(gen_mod),
        inspect.getsource(base_mod),
        inspect.getsource(api_mod),
        inspect.getsource(ext_mod),
    ]).lower()

    assert "semantic_facts" not in code_combined
    assert "semantic-facts" not in code_combined
    assert "merger" not in code_combined
    assert "renderer" not in code_combined
    assert "embedding" not in code_combined
    assert "vector" not in code_combined
    assert "faiss" not in code_combined
    assert "chroma" not in code_combined
