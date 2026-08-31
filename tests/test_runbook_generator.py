"""Tests for Direct AI Production Support Runbook Generator with Two-Pass Architecture (Phase 4)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
import subprocess
import pytest

from agent.llm_client import MockLlmClient
from agent.models import LlmResponse, ToolCall
from publisher.repository import inspect_repository
from publisher.runbook_generator import RunbookGenerator, RunbookGenerationResult
from publisher.validator import validate_runbook


# ---------------------------------------------------------------------------
# Test Fixtures
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
    <artifactId>payment-service</artifactId>
    <version>1.0.0</version>
    <properties>
        <java.version>17</java.version>
    </properties>
</project>""",
    "src/main/resources/application.yml": """spring:
  application:
    name: payment-service
payment:
  kafka:
    topic: payment-inbound-v1
""",
    "src/main/java/com/acme/PaymentConsumer.java": """package com.acme;

import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
public class PaymentConsumer {
    @KafkaListener(topics = "${payment.kafka.topic}")
    public void onPayment(String message) {
        // process
    }
}
""",
}

GOOD_FINDINGS_MARKDOWN = """# Repository Findings

## Service Purpose
Handles payment transaction ingestion via Kafka.

## Kafka
- Inbound topic configured via `payment.kafka.topic`: `payment-inbound-v1`
- Consumer located in `src/main/java/com/acme/PaymentConsumer.java:5-15`

## Operational Logs
- `Payment transaction started: {transactionId}`
"""

GOOD_RUNBOOK_MARKDOWN = """# Production Support Runbook - payment-service

> **Service:** payment-service
> **Version:** 1.0.0
> **Environment:** production
> **Commit:** {COMMIT_SHA}
> **Generated:** 2026-08-29 12:00:00 UTC
> **Branch:** main

## Service Overview
Handles inbound payment transaction event processing.

## How to Trace a Transaction
Look up the transaction ID in Kibana using the log signature:
`Payment transaction started: {transactionId}`

## Kafka Topics
- Inbound Topic: `payment-inbound-v1` (configured via `payment.kafka.topic`)

## Support Boundaries
Support engineers must not replay Kafka events, reset offsets, or modify database records without L3/Development approval.

## Escalation Guide
Collect the service name, version, environment, transaction identifier, exact log signature, and first occurrence timestamp before escalating to L3.
"""


# ---------------------------------------------------------------------------
# Unit and Integration Tests
# ---------------------------------------------------------------------------

def test_01_runbook_prompt_loaded_and_metadata_included(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    monkeypatch.chdir(tmp_path)

    captured_prompts = []

    def capturing_handler(messages, tools):
        captured_prompts.append(messages[1].content)  # User prompt / task
        if len(captured_prompts) == 1:
            # Discovery pass return findings
            return LlmResponse(content=GOOD_FINDINGS_MARKDOWN, finish_reason="stop")
        # Runbook pass return runbook
        return LlmResponse(
            content=GOOD_RUNBOOK_MARKDOWN.replace("{COMMIT_SHA}", "dummy_sha"),
            finish_reason="stop",
        )

    client = MockLlmClient(handler=capturing_handler)
    generator = RunbookGenerator(client=client)
    result = generator.generate(str(repo), environment="production", version="1.0.0")

    assert len(captured_prompts) == 2

    # Pass 1: Discovery Prompt
    discovery_text = captured_prompts[0]
    assert "senior Java/Spring Boot engineer investigating a service repository" in discovery_text
    assert "payment-service" in discovery_text

    # Pass 2: Runbook Prompt
    runbook_text = captured_prompts[1]
    assert "Expert Site Reliability Engineer" in runbook_text
    assert "payment-service" in runbook_text
    assert "production" in runbook_text
    assert "1.0.0" in runbook_text
    # Verify findings are passed to runbook writer
    assert "Repository Findings" in runbook_text
    # Verify whole-repo source concatenation was NOT included
    assert "package com.acme;" not in runbook_text


def test_02_generator_executes_tool_calls_and_saves_runbook(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))

    monkeypatch.chdir(tmp_path)

    mock_client = MockLlmClient(responses=[
        # Pass 1 Turn 1: Agent searches for Kafka consumer
        LlmResponse(
            tool_calls=[ToolCall(id="c1", name="search_code", arguments={"query": "@KafkaListener"})],
            finish_reason="tool_calls",
        ),
        # Pass 1 Turn 2: Agent reads consumer lines
        LlmResponse(
            tool_calls=[ToolCall(id="c2", name="read_lines", arguments={
                "relative_path": "src/main/java/com/acme/PaymentConsumer.java",
                "start_line": 5,
                "end_line": 15,
            })],
            finish_reason="tool_calls",
        ),
        # Pass 1 Turn 3: Discovery Agent returns Findings
        LlmResponse(
            content=GOOD_FINDINGS_MARKDOWN,
            finish_reason="stop",
        ),
        # Pass 2: Runbook Writer returns Markdown
        LlmResponse(
            content=GOOD_RUNBOOK_MARKDOWN.replace("{COMMIT_SHA}", info.commit_sha),
            finish_reason="stop",
        ),
    ])

    generator = RunbookGenerator(client=mock_client)
    result = generator.generate(str(repo), environment="production", version="1.0.0")

    assert result.service_name == "payment-service"
    assert result.commit_sha == info.commit_sha
    assert result.tool_calls == 2
    assert result.validation_status == "PASSED"
    assert len(result.validation_errors) == 0

    # Verify REPOSITORY_FINDINGS.md file
    assert result.findings_path is not None
    findings_file = Path(result.findings_path)
    assert findings_file.is_file()
    assert "Repository Findings" in findings_file.read_text(encoding="utf-8")

    # Verify RUNBOOK.md file
    runbook_file = Path(result.runbook_path)
    assert runbook_file.is_file()
    content = runbook_file.read_text(encoding="utf-8")
    assert "payment-service" in content
    assert "Kafka Topics" in content

    # Verify evidence.json file
    evidence_file = Path(result.evidence_path)
    assert evidence_file.is_file()
    ev_data = json.loads(evidence_file.read_text(encoding="utf-8"))
    assert len(ev_data) >= 1
    assert any(e["file"] == "src/main/java/com/acme/PaymentConsumer.java" for e in ev_data)


def test_03_validation_failure_sets_failed_status(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    # Bad runbook with raw Java code block and unsafe operation
    bad_markdown = f"""# Production Support Runbook - payment-service
> **Service:** payment-service
> **Commit:** {info.commit_sha}

## Unsafe Operation
Support should replay Kafka topic when messages fail.

```java
public void badCodeBlock() {{}}
```
"""

    mock_client = MockLlmClient(responses=[
        # Pass 1: Discovery
        LlmResponse(content=GOOD_FINDINGS_MARKDOWN, finish_reason="stop"),
        # Pass 2: Bad Runbook
        LlmResponse(content=bad_markdown, finish_reason="stop"),
    ])

    generator = RunbookGenerator(client=mock_client)
    result = generator.generate(str(repo))

    assert result.validation_status == "FAILED"
    assert len(result.validation_errors) >= 1
    err_str = " ".join(result.validation_errors)
    assert "Java code block" in err_str or "unsafe support recommendation" in err_str


def test_04_validator_does_not_auto_generate_replacement_text():
    """Verify validator is purely evaluative and contains no generative repair methods."""
    import publisher.validator as val_mod
    src = inspect.getsource(val_mod)
    assert "def generate" not in src
    assert "def repair" not in src
    assert "def fix" not in src


def test_05_no_index_or_embeddings_in_runbook_generator():
    """Verify RunbookGenerator does not import or use indexer or embeddings."""
    import publisher.runbook_generator as gen_mod
    src = inspect.getsource(gen_mod).lower()
    assert "faiss" not in src
    assert "chroma" not in src
    assert "embedding" not in src
    assert "codeindexbuilder" not in src
    assert "indexer" not in src


def test_06_repository_remains_unmodified_during_generation(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    status_before = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True).stdout

    mock_client = MockLlmClient(responses=[
        LlmResponse(
            tool_calls=[ToolCall(id="1", name="search_code", arguments={"query": "Payment"})],
            finish_reason="tool_calls",
        ),
        LlmResponse(content=GOOD_FINDINGS_MARKDOWN, finish_reason="stop"),
        LlmResponse(
            content=GOOD_RUNBOOK_MARKDOWN.replace("{COMMIT_SHA}", info.commit_sha),
            finish_reason="stop",
        ),
    ])

    generator = RunbookGenerator(client=mock_client)
    generator.generate(str(repo))

    status_after = subprocess.run(["git", "status", "--porcelain"], cwd=str(repo), capture_output=True, text=True).stdout
    assert status_before == status_after


def test_07_not_found_placeholder_fails_validation(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    monkeypatch.chdir(tmp_path)

    bad_markdown = f"""# Production Support Runbook - payment-service
> **Service:** payment-service
> **Commit:** {info.commit_sha}

## Database
Not found in the repository.
"""

    mock_client = MockLlmClient(responses=[
        LlmResponse(content=GOOD_FINDINGS_MARKDOWN, finish_reason="stop"),
        LlmResponse(content=bad_markdown, finish_reason="stop"),
    ])

    generator = RunbookGenerator(client=mock_client)
    result = generator.generate(str(repo))

    assert result.validation_status == "FAILED"
    assert any("Not found in repository" in err for err in result.validation_errors)


def test_08_service_identity_missing_fails_validation(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    monkeypatch.chdir(tmp_path)

    bad_markdown = """# Generic Runbook
Some generic text without any service name header or identity.
"""

    mock_client = MockLlmClient(responses=[
        LlmResponse(content=GOOD_FINDINGS_MARKDOWN, finish_reason="stop"),
        LlmResponse(content=bad_markdown, finish_reason="stop"),
    ])

    generator = RunbookGenerator(client=mock_client)
    result = generator.generate(str(repo))

    assert result.validation_status == "FAILED"
    assert any("does not mention the service identity" in err for err in result.validation_errors)


def test_09_no_confluence_called_in_generator():
    """Verify RunbookGenerator never imports or calls Confluence publisher."""
    import publisher.runbook_generator as gen_mod
    src = inspect.getsource(gen_mod).lower()
    assert "confluencepublisher" not in src
    assert "publish_to_confluence" not in src


def test_10_no_whole_repo_concatenation_in_generator():
    """Verify RunbookGenerator never reads or concatenates all files into one prompt."""
    import publisher.runbook_generator as gen_mod
    src = inspect.getsource(gen_mod)
    assert "read_text" not in src or "pom.xml" not in src
    assert "for root, dirs, files in os.walk" not in src
