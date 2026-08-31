"""Comprehensive tests for generation identity, fingerprinting, caching/reuse, retry tracking, and HTML generation."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import pytest

from agent.llm_client import MockLlmClient
from agent.models import LlmMessage, LlmResponse, ToolCall
from publisher.engines import (
    ApiAgentEngine,
    EngineGenerationResult,
    GenerationContext,
    GenerationEngine,
    create_generation_engine,
)
from publisher.html_renderer import (
    generate_runbook_html,
    render_body,
    render_confluence_body,
    render_document,
    sanitize_html,
)
from publisher.identity import (
    DEFAULT_CONTRACT_VERSION,
    GenerationMetadata,
    calculate_context_fingerprint,
    calculate_generation_key,
    calculate_prompt_fingerprint,
    calculate_source_fingerprint,
    create_attempt_id,
    load_generation_metadata,
    record_attempt,
    save_generation_metadata,
)
from publisher.repository import inspect_repository
from publisher.runbook_generator import RunbookGenerator


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
        <java.version>17</java.version>
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

GOOD_FINDINGS = """# Repository Findings

## Service Purpose
Handles payment transactions.

## Kafka
- Topic: `payment-inbound-topic`
"""

GOOD_RUNBOOK = """# Production Support Runbook - payment-service

> **Service:** payment-service
> **Version:** 1.0.0
> **Environment:** production

## Service Overview
Handles payment transactions.

## How to Trace a Transaction
Check Kibana logs for transaction ID.

## Support Boundaries
Support must not replay Kafka events or modify database records without explicit approval.
"""


def test_01_same_source_same_prompt_same_generation_key(tmp_path: Path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    src_fp1 = calculate_source_fingerprint(repo)
    src_fp2 = calculate_source_fingerprint(repo)
    assert src_fp1 == src_fp2

    p_fp1 = calculate_prompt_fingerprint(discovery_content="disc1", runbook_content="rb1")
    p_fp2 = calculate_prompt_fingerprint(discovery_content="disc1", runbook_content="rb1")
    assert p_fp1 == p_fp2

    k1_short, k1_full = calculate_generation_key("payment-service", src_fp1, p_fp1)
    k2_short, k2_full = calculate_generation_key("payment-service", src_fp2, p_fp2)
    assert k1_short == k2_short
    assert k1_full == k2_full
    assert len(k1_short) == 16
    assert len(k1_full) == 64


def test_02_source_change_produces_new_generation_key(tmp_path: Path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    src_fp1 = calculate_source_fingerprint(repo)
    p_fp = calculate_prompt_fingerprint(discovery_content="disc1", runbook_content="rb1")
    k1, _ = calculate_generation_key("payment-service", src_fp1, p_fp)

    # Edit Java source
    java_file = repo / "src/main/java/com/idfc/pay/PaymentListener.java"
    java_file.write_text(java_file.read_text() + "\n// extra comment\n", encoding="utf-8")

    src_fp2 = calculate_source_fingerprint(repo)
    k2, _ = calculate_generation_key("payment-service", src_fp2, p_fp)

    assert src_fp1 != src_fp2
    assert k1 != k2


def test_03_uncommitted_local_source_change_produces_new_generation_key(tmp_path: Path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    src_fp1 = calculate_source_fingerprint(repo)

    # Add uncommitted new properties file
    new_prop = repo / "src/main/resources/extra.properties"
    new_prop.write_text("custom.feature.flag=true\n", encoding="utf-8")

    src_fp2 = calculate_source_fingerprint(repo)
    assert src_fp1 != src_fp2


def test_04_ignored_noise_file_does_not_change_generation_key(tmp_path: Path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    src_fp1 = calculate_source_fingerprint(repo)

    # Add noise files in build/ and target/ and .idea/
    (repo / "target").mkdir(parents=True, exist_ok=True)
    (repo / "target" / "classes.jar").write_bytes(b"dummy jar content")
    (repo / "build").mkdir(parents=True, exist_ok=True)
    (repo / "build" / "build.log").write_text("log line", encoding="utf-8")
    (repo / ".idea").mkdir(parents=True, exist_ok=True)
    (repo / ".idea" / "workspace.xml").write_text("<xml/>", encoding="utf-8")

    src_fp2 = calculate_source_fingerprint(repo)
    assert src_fp1 == src_fp2


def test_05_prompt_change_produces_new_generation_key(tmp_path: Path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    src_fp = calculate_source_fingerprint(repo)

    p1 = calculate_prompt_fingerprint(discovery_content="discovery v1", runbook_content="runbook v1")
    p2 = calculate_prompt_fingerprint(discovery_content="discovery v2", runbook_content="runbook v1")
    p3 = calculate_prompt_fingerprint(discovery_content="discovery v1", runbook_content="runbook v2")

    k1, _ = calculate_generation_key("payment-service", src_fp, p1)
    k2, _ = calculate_generation_key("payment-service", src_fp, p2)
    k3, _ = calculate_generation_key("payment-service", src_fp, p3)

    assert p1 != p2
    assert p1 != p3
    assert k1 != k2
    assert k1 != k3


def test_06_contract_version_change_produces_new_generation_key(tmp_path: Path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    src_fp = calculate_source_fingerprint(repo)
    p_fp = calculate_prompt_fingerprint(discovery_content="disc", runbook_content="rb")

    c1 = calculate_context_fingerprint(contract_version="2.1")
    c2 = calculate_context_fingerprint(contract_version="2.2")

    k1, _ = calculate_generation_key("payment-service", src_fp, p_fp, contract_version="2.1", platform_context_fingerprint=c1)
    k2, _ = calculate_generation_key("payment-service", src_fp, p_fp, contract_version="2.2", platform_context_fingerprint=c2)

    assert c1 != c2
    assert k1 != k2


def test_07_platform_context_change_produces_new_generation_key(tmp_path: Path):
    c1 = calculate_context_fingerprint(contract_version="2.1", platform_context="platform-v1")
    c2 = calculate_context_fingerprint(contract_version="2.1", platform_context="platform-v2")
    assert c1 != c2


def test_08_cache_hit_reuses_complete_generation_without_invoking_engine(tmp_path: Path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    out_base = tmp_path / "output"

    mock_client = MockLlmClient(responses=[
        LlmResponse(content=GOOD_FINDINGS, tool_calls=[]),
        LlmResponse(content=GOOD_RUNBOOK, tool_calls=[]),
    ])

    generator = RunbookGenerator(client=mock_client)
    res1 = generator.generate(repo_path=str(repo), output_base_dir=out_base)

    assert res1.validation_status == "PASSED"
    assert res1.cache_hit is False
    assert Path(res1.runbook_path).exists()
    assert Path(res1.confluence_body_path).exists()
    assert Path(res1.runbook_html_path).exists()

    # Second invocation with same inputs: should hit cache and NOT invoke engine
    mock_client_unused = MockLlmClient(responses=[])
    generator2 = RunbookGenerator(client=mock_client_unused)
    res2 = generator2.generate(repo_path=str(repo), output_base_dir=out_base)

    assert res2.validation_status == "PASSED"
    assert res2.cache_hit is True
    assert res2.generation_key == res1.generation_key
    assert res2.runbook_path == res1.runbook_path
    assert res2.confluence_body_path == res1.confluence_body_path


def test_09_force_flag_triggers_new_attempt_under_same_generation_key(tmp_path: Path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    out_base = tmp_path / "output"

    mock_client = MockLlmClient(responses=[
        LlmResponse(content=GOOD_FINDINGS, tool_calls=[]),
        LlmResponse(content=GOOD_RUNBOOK, tool_calls=[]),
        LlmResponse(content=GOOD_FINDINGS, tool_calls=[]),
        LlmResponse(content=GOOD_RUNBOOK, tool_calls=[]),
    ])

    generator = RunbookGenerator(client=mock_client)
    res1 = generator.generate(repo_path=str(repo), output_base_dir=out_base)
    assert res1.cache_hit is False

    # Run with force=True
    res2 = generator.generate(repo_path=str(repo), force=True, output_base_dir=out_base)
    assert res2.cache_hit is False
    assert res2.generation_key == res1.generation_key
    assert res2.attempt_id != res1.attempt_id


def test_10_html_rendering_preserves_headings_and_tables(tmp_path: Path):
    sample_md = """# Title Heading
## Section Heading
### Sub Section

| Header A | Header B |
| --- | --- |
| Val 1 | Val 2 |
"""
    body_html = render_confluence_body(sample_md)
    assert "<h1>Title Heading</h1>" in body_html
    assert "<h2>Section Heading</h2>" in body_html
    assert "<h3>Sub Section</h3>" in body_html
    assert "<table>" in body_html
    assert "<th>Header A</th>" in body_html
    assert "<td>Val 1</td>" in body_html


def test_11_html_sanitizes_script_injection(tmp_path: Path):
    unsafe_md = """# Safe Title
<script>alert('xss');</script>
[Click Here](javascript:evil())
<img src="x" onerror="alert(1)">
"""
    body_html = render_confluence_body(unsafe_md)
    assert "<script>" not in body_html
    assert "alert('xss')" not in body_html
    assert "javascript:evil()" not in body_html
    assert 'onerror=' not in body_html
