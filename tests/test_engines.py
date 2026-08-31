"""Tests for flag-based generation engines (ApiAgentEngine, IdfcCoderEngine, ExternalAgentEngine) with Two-Pass Architecture."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import pytest

from agent.llm_client import MockLlmClient
from agent.models import LlmResponse, ToolCall
from publisher.engines import (
    ApiAgentEngine,
    EngineConfigurationError,
    ExternalAgentEngine,
    IdfcCoderEngine,
    UnsupportedGenerationEngineError,
    create_generation_engine,
)
from publisher.repository import inspect_repository
from publisher.runbook_generator import RunbookGenerator


# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
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
    <groupId>com.acme</groupId>
    <artifactId>order-service</artifactId>
    <version>1.0.0</version>
    <properties>
        <java.version>17</java.version>
    </properties>
</project>""",
    "src/main/resources/application.yml": """spring:
  application:
    name: order-service
order:
  kafka:
    topic: order-events-v1
""",
    "src/main/java/com/acme/OrderConsumer.java": """package com.acme;

import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class OrderConsumer {
    @KafkaListener(topics = "${order.kafka.topic}")
    public void onOrder(String message) {
        // process order
    }
}
""",
}

GOOD_FINDINGS_MARKDOWN = """# Repository Findings

## Service Purpose
Handles order event processing and tracking.

## Kafka
- Inbound Topic: `order-events-v1`

## Operational Logs
- `Order transaction started: {orderId}`
"""

GOOD_RUNBOOK_MARKDOWN = """# Production Support Runbook - order-service

> **Service:** order-service
> **Version:** 1.0.0
> **Environment:** production
> **Commit:** {COMMIT_SHA}
> **Generated:** 2026-08-29 12:00:00 UTC
> **Branch:** main

## Service Overview
Handles inbound order event processing and tracking.

## How to Trace a Transaction
Look up the transaction ID in Kibana using the log signature:
`Order transaction started: {orderId}`

## Kafka Topics
- Inbound Topic: `order-events-v1` (configured via `order.kafka.topic`)

## Support Boundaries
Support engineers must not replay Kafka events, reset offsets, or modify database records without L3/Development approval.

## Escalation Guide
Collect the service name, version, environment, order identifier, exact log signature, and first occurrence timestamp before escalating to L3.
"""


# ---------------------------------------------------------------------------
# Engine Selection & Factory Tests
# ---------------------------------------------------------------------------

def test_01_create_engine_api():
    mock_client = MockLlmClient(responses=[LlmResponse(content="ok", finish_reason="stop")])
    engine = create_generation_engine("api", client=mock_client)
    assert isinstance(engine, ApiAgentEngine)


def test_02_create_engine_idfc_coder():
    engine = create_generation_engine("idfc-coder", coder_cmd="my-coder", coder_mode="stdin")
    assert isinstance(engine, IdfcCoderEngine)
    assert engine.coder_cmd == "my-coder"
    assert engine.mode == "stdin"


def test_03_create_engine_external_agent():
    engine = create_generation_engine("external-agent")
    assert isinstance(engine, ExternalAgentEngine)


def test_04_create_engine_unsupported_raises_error():
    with pytest.raises(UnsupportedGenerationEngineError) as exc_info:
        create_generation_engine("non-existent-engine")
    assert "Unsupported generation engine" in str(exc_info.value)


# ---------------------------------------------------------------------------
# API Engine Tests
# ---------------------------------------------------------------------------

def test_05_api_engine_missing_config_raises_clear_error(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    with pytest.raises(EngineConfigurationError) as exc_info:
        ApiAgentEngine(client=None, llm_config={})
    assert "API_ENGINE_CONFIGURATION_MISSING" in str(exc_info.value)


def test_06_api_engine_executes_tool_calling_and_generates_runbook(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    mock_client = MockLlmClient(responses=[
        # Pass 1: Tool call + findings
        LlmResponse(
            tool_calls=[ToolCall(id="1", name="search_code", arguments={"query": "@KafkaListener"})],
            finish_reason="tool_calls",
        ),
        LlmResponse(
            content=GOOD_FINDINGS_MARKDOWN,
            finish_reason="stop",
        ),
        # Pass 2: Fresh runbook writing
        LlmResponse(
            content=GOOD_RUNBOOK_MARKDOWN.replace("{COMMIT_SHA}", info.commit_sha),
            finish_reason="stop",
        ),
    ])

    engine = ApiAgentEngine(client=mock_client)
    generator = RunbookGenerator(engine=engine)
    result = generator.generate(str(repo), environment="production", version="1.0.0")

    assert result.service_name == "order-service"
    assert result.commit_sha == info.commit_sha
    assert result.engine == "api"
    assert result.tool_calls == 1
    assert result.validation_status == "PASSED"
    assert Path(result.findings_path).is_file()
    assert Path(result.runbook_path).is_file()


def test_07_api_engine_output_suffix(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    mock_client = MockLlmClient(responses=[
        # Pass 1: Findings
        LlmResponse(content=GOOD_FINDINGS_MARKDOWN, finish_reason="stop"),
        # Pass 2: Runbook
        LlmResponse(
            content=GOOD_RUNBOOK_MARKDOWN.replace("{COMMIT_SHA}", info.commit_sha),
            finish_reason="stop",
        ),
    ])

    engine = ApiAgentEngine(client=mock_client)
    generator = RunbookGenerator(engine=engine)
    result = generator.generate(str(repo), output_suffix="api")

    assert result.findings_path.endswith("REPOSITORY_FINDINGS-api.md")
    assert result.runbook_path.endswith("RUNBOOK-api.md")
    assert Path(result.findings_path).is_file()
    assert Path(result.runbook_path).is_file()


# ---------------------------------------------------------------------------
# IDFC-Coder Engine Tests
# ---------------------------------------------------------------------------

def test_08_idfc_coder_engine_missing_executable_fails_clearly(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    monkeypatch.chdir(tmp_path)

    engine = IdfcCoderEngine(coder_cmd="non-existent-coder-12345", mode="interactive")
    generator = RunbookGenerator(engine=engine)
    result = generator.generate(str(repo))

    assert result.engine == "idfc-coder"
    assert result.validation_status == "FAILED"
    assert any("Executable not found" in err or "failed" in err for err in result.validation_errors)


def test_09_idfc_coder_engine_creates_task_with_prompt_and_metadata(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    engine = IdfcCoderEngine(coder_cmd="python -c \"pass\"", mode="stdin")
    generator = RunbookGenerator(engine=engine)
    result = generator.generate(str(repo))

    out_dir = tmp_path / "output" / "order-service" / result.generation_key

    # Verify discovery task file created with correct metadata
    task_file = out_dir / "idfc-coder-discovery-task.md"
    assert task_file.is_file()
    task_text = task_file.read_text(encoding="utf-8")
    assert "order-service" in task_text
    assert info.commit_sha in task_text
    assert "Repository Discovery Task" in task_text
    assert "package com.acme;" not in task_text


# ---------------------------------------------------------------------------
# External Agent Engine Tests
# ---------------------------------------------------------------------------

def test_10_external_agent_engine_prepares_discovery_task_when_findings_absent(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    engine = ExternalAgentEngine()
    generator = RunbookGenerator(engine=engine)
    result = generator.generate(str(repo), environment="production", version="1.0.0")

    assert result.engine == "external-agent"
    assert result.validation_status == "DISCOVERY_PREPARED"

    out_dir = tmp_path / "output" / "order-service" / result.generation_key
    task_file = out_dir / "DISCOVERY_TASK.md"
    assert task_file.is_file()
    content = task_file.read_text(encoding="utf-8")
    assert "order-service" in content
    assert info.commit_sha in content
    assert "Target Repository" in content
    assert "Deterministic Facts Path" in content
    assert "package com.acme;" not in content
    assert not (out_dir / "RUNBOOK_TASK.md").exists()


def test_11_external_agent_engine_prepares_runbook_task_when_findings_present(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    engine = ExternalAgentEngine()
    generator = RunbookGenerator(engine=engine)
    res_prep = generator.generate(str(repo), environment="production", version="1.0.0")
    out_dir = tmp_path / "output" / "order-service" / res_prep.generation_key

    # Write REPOSITORY_FINDINGS.md
    (out_dir / "REPOSITORY_FINDINGS.md").write_text(GOOD_FINDINGS_MARKDOWN, encoding="utf-8")

    result = generator.generate(str(repo), environment="production", version="1.0.0")

    assert result.engine == "external-agent"
    assert result.validation_status == "RUNBOOK_PREPARED"

    task_file = out_dir / "RUNBOOK_TASK.md"
    assert task_file.is_file()
    content = task_file.read_text(encoding="utf-8")
    assert "THIS IS A FRESH WRITING TASK" in content
    assert "not inspect the java repository again" in content.lower()
    assert "Technical Investigation Input (REPOSITORY_FINDINGS.md)" in content


def test_12_external_agent_engine_validates_existing_runbook(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    engine = ExternalAgentEngine()
    generator = RunbookGenerator(engine=engine)
    res_prep = generator.generate(str(repo), environment="production", version="1.0.0")
    out_dir = tmp_path / "output" / "order-service" / res_prep.generation_key

    (out_dir / "REPOSITORY_FINDINGS.md").write_text(GOOD_FINDINGS_MARKDOWN, encoding="utf-8")
    runbook_file = out_dir / "RUNBOOK.md"
    runbook_file.write_text(GOOD_RUNBOOK_MARKDOWN.replace("{COMMIT_SHA}", info.commit_sha), encoding="utf-8")

    result = generator.generate(str(repo), environment="production", version="1.0.0")

    assert result.engine == "external-agent"
    assert result.validation_status == "PASSED"
    assert len(result.validation_errors) == 0
    assert Path(result.runbook_path).resolve() == runbook_file.resolve()


# ---------------------------------------------------------------------------
# Common Pipeline & Safety Tests
# ---------------------------------------------------------------------------

def test_13_common_validator_catches_unsafe_instructions_across_engines(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    engine = ExternalAgentEngine()
    generator = RunbookGenerator(engine=engine)
    res_prep = generator.generate(str(repo))
    out_dir = tmp_path / "output" / "order-service" / res_prep.generation_key

    (out_dir / "REPOSITORY_FINDINGS.md").write_text(GOOD_FINDINGS_MARKDOWN, encoding="utf-8")
    bad_runbook = f"""# Production Support Runbook - order-service
> **Service:** order-service
> **Commit:** {info.commit_sha}

## Unsafe Operation
Support should manually force transaction state when stalled.
"""
    (out_dir / "RUNBOOK.md").write_text(bad_runbook, encoding="utf-8")

    result = generator.generate(str(repo))

    assert result.validation_status == "FAILED"
    assert any("unsafe support recommendation" in err for err in result.validation_errors)


def test_14_repository_remains_unmodified_across_all_engine_runs(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    monkeypatch.chdir(tmp_path)

    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True).stdout

    engine = ExternalAgentEngine()
    generator = RunbookGenerator(engine=engine)
    generator.generate(str(repo))

    status_after = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True).stdout
    assert status_before == status_after == ""
