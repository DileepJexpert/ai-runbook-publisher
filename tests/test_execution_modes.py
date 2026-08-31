"""Comprehensive tests for LOCAL vs PIPELINE execution mode architecture."""

from __future__ import annotations

from pathlib import Path
import subprocess
import pytest

from agent.llm_client import MockLlmClient
from agent.models import LlmResponse
from publisher import (
    CommitMismatchError,
    DirtyWorkingTreeError,
    ExecutionMode,
    LocalConfluencePageResolver,
    LocalCredentialProvider,
    LocalIdfcCoderEngine,
    LocalRepositoryProvider,
    ModeEnforcementError,
    PipelineCredentialProvider,
    PipelineExecutionError,
    PipelineLlmApiEngine,
    PipelineOrchestrator,
    PipelineRepositoryProvider,
    ProductionConfluencePageResolver,
    inspect_repository,
)
from publisher.confluence import ConfluenceConfig


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
}

GOOD_FINDINGS = """# Repository Findings
## Service Purpose
Handles payments.
"""

GOOD_RUNBOOK = """# Production Support Runbook - payment-service
> **Service:** payment-service
> **Version:** 1.0.0
> **Environment:** production

## Service Overview
Handles payments.

## Support Boundaries
Support must not replay Kafka events without approval.
"""


# ---------------------------------------------------------------------------
# 1. ExecutionMode & AiGenerationEngine Tests
# ---------------------------------------------------------------------------

def test_01_execution_mode_enum_values():
    assert ExecutionMode.LOCAL == "LOCAL"
    assert ExecutionMode.PIPELINE == "PIPELINE"


def test_02_local_idfc_engine_rejected_in_pipeline_mode():
    with pytest.raises(ModeEnforcementError) as exc_info:
        LocalIdfcCoderEngine(execution_mode=ExecutionMode.PIPELINE)
    assert "strictly excluded from PIPELINE" in str(exc_info.value)


def test_03_pipeline_api_engine_never_falls_back_to_idfc_coder(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))

    # Mock client that raises an error on run_turn
    class ErrorLlmClient(MockLlmClient):
        def run_turn(self, messages, tools):
            raise RuntimeError("Internal LLM API Gateway Timeout 504")

    engine = PipelineLlmApiEngine(client=ErrorLlmClient())
    assert engine.allow_fallback_to_idfc_coder is False

    from publisher.engines import GenerationContext
    context = GenerationContext(
        repo_path=str(repo),
        service_name="payment-service",
        commit_sha=info.commit_sha,
        branch="main",
        environment="production",
        version="1.0.0",
        discovery_prompt="prompt",
        runbook_prompt="prompt",
        service_facts_path=str(tmp_path / "facts.json"),
        output_dir=str(tmp_path / "output"),
    )

    result = engine.generate(context)
    assert result.status == "FAILED"
    assert "No fallback to idfc-coder permitted" in result.error or "failed" in result.error
    assert result.engine == "pipeline-api"


# ---------------------------------------------------------------------------
# 2. RepositoryProvider Tests
# ---------------------------------------------------------------------------

def test_04_local_repository_provider_allows_dirty_working_tree(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    # Make working tree dirty
    (repo / "src/main/resources/application.yml").write_text("modified: true", encoding="utf-8")

    provider = LocalRepositoryProvider(repo_path=repo)
    info = provider.get_repository()
    assert info.working_tree_clean is False
    # Local validation must pass even when dirty
    provider.validate_for_execution()


def test_05_pipeline_repository_provider_rejects_dirty_working_tree(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))

    # Make working tree dirty
    (repo / "src/main/resources/application.yml").write_text("modified: true", encoding="utf-8")

    provider = PipelineRepositoryProvider(repo_path=repo, expected_commit_sha=info.commit_sha)
    with pytest.raises(DirtyWorkingTreeError) as exc_info:
        provider.validate_for_execution()
    assert "contains uncommitted modifications" in str(exc_info.value)


def test_06_pipeline_repository_provider_rejects_commit_mismatch(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    provider = PipelineRepositoryProvider(repo_path=repo, expected_commit_sha="bad_commit_sha_12345")
    with pytest.raises(CommitMismatchError) as exc_info:
        provider.validate_for_execution()
    assert "does not match actual repository commit SHA" in str(exc_info.value)


def test_07_pipeline_repository_provider_rejects_deployed_commit_mismatch(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))

    provider = PipelineRepositoryProvider(
        repo_path=repo,
        expected_commit_sha=info.commit_sha,
        deployed_commit_sha="different_deployed_commit_sha_999",
    )
    with pytest.raises(CommitMismatchError) as exc_info:
        provider.validate_for_execution()
    assert "deployed commit SHA 'different_deployed_commit_sha_999' does not match analyzed commit SHA" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. CredentialProvider Tests
# ---------------------------------------------------------------------------

def test_08_local_credential_provider(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_TOKEN", "user_dev_token_123")
    monkeypatch.setenv("LLM_API_KEY", "user_llm_key_456")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.local.dev")

    provider = LocalCredentialProvider()
    assert provider.get_confluence_token() == "user_dev_token_123"
    assert provider.get_llm_api_key() == "user_llm_key_456"
    assert provider.get_llm_base_url() == "https://llm.local.dev"


def test_09_pipeline_credential_provider(monkeypatch):
    monkeypatch.setenv("PIPELINE_CONFLUENCE_TOKEN", "machine_service_account_token_789")
    monkeypatch.setenv("PIPELINE_LLM_API_KEY", "machine_llm_key_999")
    monkeypatch.setenv("PIPELINE_LLM_BASE_URL", "https://llm-gateway.internal")

    provider = PipelineCredentialProvider()
    assert provider.get_confluence_token() == "machine_service_account_token_789"
    assert provider.get_llm_api_key() == "machine_llm_key_999"
    assert provider.get_llm_base_url() == "https://llm-gateway.internal"


# ---------------------------------------------------------------------------
# 4. ConfluencePageResolver & Exact PageId Tests
# ---------------------------------------------------------------------------

def test_10_local_service_id_resolves_exact_test_page_id(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))

    resolver = LocalConfluencePageResolver(pages={"payment-service": "123456"})
    assert resolver.is_production() is False
    assert resolver.resolve_page_id(info) == "123456"


def test_11_pipeline_service_id_resolves_exact_production_page_id(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))

    resolver = ProductionConfluencePageResolver(pages={"payment-service": "987654"})
    assert resolver.is_production() is True
    assert resolver.resolve_page_id(info) == "987654"


def test_12_local_cannot_access_production_mappings(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))

    resolver = LocalConfluencePageResolver(
        pages={"payment-service": "987654"},
        prohibited_production_pages={"987654"},
    )
    with pytest.raises(ModeEnforcementError) as exc_info:
        resolver.resolve_page_id(info)
    assert "LOCAL execution cannot target production Confluence pageId '987654'" in str(exc_info.value)


def test_13_pipeline_does_not_use_local_mappings(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))

    config = {
        "local": {"confluence": {"pages": {"payment-service": "123456"}}},
        "pipeline": {"confluence": {"pages": {"payment-service": "987654"}}},
    }
    resolver = ProductionConfluencePageResolver(config=config)
    assert resolver.resolve_page_id(info) == "987654"


def test_14_missing_mapping_blocks_publish(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))

    # Missing local mapping
    local_resolver = LocalConfluencePageResolver(pages={})
    with pytest.raises(ModeEnforcementError) as exc_local:
        local_resolver.resolve_page_id(info)
    assert "LOCAL_CONFLUENCE_PAGE_NOT_CONFIGURED" in str(exc_local.value)

    # Missing pipeline mapping
    pipe_resolver = ProductionConfluencePageResolver(pages={})
    with pytest.raises(PipelineExecutionError) as exc_pipe:
        pipe_resolver.resolve_page_id(info)
    assert "PRODUCTION_CONFLUENCE_PAGE_NOT_CONFIGURED" in str(exc_pipe.value)


def test_15_publisher_gets_exact_page_id_and_puts_same_page_id(tmp_path):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))

    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text(GOOD_RUNBOOK, encoding="utf-8")

    from unittest.mock import MagicMock
    from publisher.confluence import ConfluenceClient, ConfluenceConfig, ConfluencePage, ConfluencePublisher

    mock_client = MagicMock(spec=ConfluenceClient)
    mock_client.get_page.return_value = ConfluencePage(
        id="987654",
        title="Payment Service Runbook",
        version=3,
        body_storage="<p>Old content</p>",
    )
    mock_client.markdown_to_storage.return_value = "<p>New storage body</p>"
    mock_client.update_page.return_value = ConfluencePage(
        id="987654",
        title="Payment Service Runbook",
        version=4,
        body_storage="<p>New storage body</p>",
    )

    conf = ConfluenceConfig(
        enabled=True,
        base_url="https://confluence.internal",
        page_id="987654",
        token="test_token",
    )
    pub = ConfluencePublisher(config=conf, client=mock_client)

    result = pub.publish_runbook(
        runbook_path=runbook_file,
        repo_info=info,
        page_id="987654",
        validation_status="PASSED",
        dry_run=False,
    )

    assert result.success is True
    assert result.action == "UPDATED"
    assert result.page_id == "987654"
    assert result.version == 4

    # Verification of exact flow
    mock_client.get_page.assert_called_once_with("987654")
    mock_client.update_page.assert_called_once()
    call_args = mock_client.update_page.call_args[1] if mock_client.update_page.call_args[1] else mock_client.update_page.call_args[0]
    # Verify pageId passed to update_page equals 987654
    assert mock_client.update_page.call_args.kwargs.get("page_id") == "987654" or mock_client.update_page.call_args.args[0] == "987654"

    # Verify NO title search or child page creation occurred
    mock_client.get_child_pages.assert_not_called()
    mock_client.create_page.assert_not_called()


def test_16_orchestrator_pipeline_mode_with_exact_page_mapping(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    info = inspect_repository(str(repo))
    out_base = tmp_path / "output"

    mock_client = MockLlmClient(responses=[
        LlmResponse(content=GOOD_FINDINGS, finish_reason="stop"),
        LlmResponse(content=GOOD_RUNBOOK, finish_reason="stop"),
    ])

    monkeypatch.setenv("PIPELINE_CONFLUENCE_TOKEN", "mock_pipeline_token_123")
    repo_provider = PipelineRepositoryProvider(repo_path=repo, expected_commit_sha=info.commit_sha)
    page_resolver = ProductionConfluencePageResolver(pages={"payment-service": "987654"})

    orchestrator = PipelineOrchestrator(
        mode=ExecutionMode.PIPELINE,
        repo_provider=repo_provider,
        engine=PipelineLlmApiEngine(client=mock_client),
        page_resolver=page_resolver,
        config={"confluence": {"base_url": "https://confluence.internal"}},
    )

    gen_result = orchestrator.generate_runbook(output_base_dir=out_base)
    assert gen_result.validation_status == "PASSED"

    from unittest.mock import MagicMock
    from publisher.confluence import ConfluencePublishResult

    mock_publisher = MagicMock()
    mock_publisher.publish_runbook.return_value = ConfluencePublishResult(
        action="DRY_RUN",
        success=True,
        page_id="987654",
        page_title="payment-service",
    )

    pub_result = orchestrator.publish_runbook(
        runbook_path=gen_result.runbook_path,
        deployed_commit_sha=info.commit_sha,
        dry_run=True,
        publisher=mock_publisher,
    )
    assert pub_result.action == "DRY_RUN"
    assert pub_result.page_id == "987654"

