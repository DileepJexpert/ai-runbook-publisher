"""Unit tests for Phase 5: Deterministic Confluence Create-or-Update Publisher."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests

from publisher.confluence import (
    ConfluenceClient,
    ConfluenceConfig,
    ConfluenceDuplicatePageError,
    ConfluenceError,
    ConfluenceManualNotesError,
    ConfluencePage,
    ConfluencePublishResult,
    ConfluencePublisher,
    extract_manual_notes,
    inject_manual_notes,
)
from publisher.repository import RepositoryInfo, resolve_repo_name
from publisher.runbook_generator import RunbookGenerator


# ---------------------------------------------------------------------------
# Test Fixtures & Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def base_config() -> ConfluenceConfig:
    return ConfluenceConfig(
        enabled=True,
        base_url="https://wiki.internal.example.com",
        parent_page_id="111222",
        token="secret-token-12345",
        timeout_seconds=10,
        preserve_manual_notes=True,
    )


@pytest.fixture
def repo_info_sample() -> RepositoryInfo:
    return RepositoryInfo(
        path="/path/to/ai-runbook-service-springboot",
        service_name="ai-runbook-service",
        branch="main",
        commit_sha="d06c4eb855ee222b1dba9d9429f1fd613c3a62f9",
        origin_url="https://github.com/DileepJexpert/ai-runbook-service-springboot.git",
        working_tree_clean=True,
        repo_name="ai-runbook-service-springboot",
    )


# ---------------------------------------------------------------------------
# 1-4. Repository Name Identity Tests
# ---------------------------------------------------------------------------

def test_01_repo_name_derived_from_https_git_origin():
    """1. repo name derived from HTTPS git origin."""
    url = "https://github.com/DileepJexpert/ai-runbook-service-springboot.git"
    assert resolve_repo_name(Path("/tmp/ai-runbook-service-springboot"), url) == "ai-runbook-service-springboot"

    url_no_git = "https://github.com/DileepJexpert/payment-orchestration-service"
    assert resolve_repo_name(Path("/tmp/payment-orchestration-service"), url_no_git) == "payment-orchestration-service"


def test_02_repo_name_derived_from_ssh_git_origin():
    """2. repo name derived from SSH git origin."""
    ssh_scp = "git@github.com:DileepJexpert/ai-runbook-service-springboot.git"
    assert resolve_repo_name(Path("/tmp/any-dir"), ssh_scp) == "ai-runbook-service-springboot"

    ssh_url = "ssh://git@bitbucket.internal:7999/proj/customer-profile-service.git"
    assert resolve_repo_name(Path("/tmp/any-dir"), ssh_url) == "customer-profile-service"


def test_03_repo_name_falls_back_to_repository_folder_name(tmp_path: Path):
    """3. repo name falls back to repository folder name when origin is unavailable."""
    folder = tmp_path / "my-custom-service-repo"
    folder.mkdir()
    assert resolve_repo_name(folder, origin_url=None) == "my-custom-service-repo"
    assert resolve_repo_name(folder, origin_url="") == "my-custom-service-repo"


def test_04_child_page_title_equals_repo_name_exactly(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """4. child page title equals repo name exactly (not service name, no prefixes)."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nOperational content.", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    mock_client.get_child_pages.return_value = []
    mock_client.create_page.return_value = ConfluencePage(id="999", title="ai-runbook-service-springboot", version=1)

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(
        runbook_path=runbook_file,
        repo_info=repo_info_sample,
        validation_status="PASSED",
        dry_run=False,
    )

    assert res.success is True
    assert res.page_title == "ai-runbook-service-springboot"
    assert res.page_title != repo_info_sample.service_name
    mock_client.create_page.assert_called_once()
    assert mock_client.create_page.call_args[1]["title"] == "ai-runbook-service-springboot"


# ---------------------------------------------------------------------------
# 5-11. Page Resolution, CREATE, and UPDATE Lifecycle Tests
# ---------------------------------------------------------------------------

def test_05_zero_matching_pages_triggers_create(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """5. zero matching child pages -> CREATE."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nContent.", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    mock_client.get_child_pages.return_value = [
        ConfluencePage(id="101", title="other-service", version=1),
    ]
    mock_client.create_page.return_value = ConfluencePage(id="202", title="ai-runbook-service-springboot", version=1)

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.success is True
    assert res.action == "CREATED"
    assert res.page_id == "202"
    mock_client.create_page.assert_called_once()
    mock_client.update_page.assert_not_called()


def test_06_exactly_one_matching_child_triggers_update(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """6. exactly one exact matching child -> UPDATE."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nNew Content.", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    existing = ConfluencePage(id="303", title="ai-runbook-service-springboot", version=3, body_storage="<p>Old</p>")
    mock_client.get_child_pages.return_value = [existing]
    mock_client.get_page.return_value = existing
    mock_client.update_page.return_value = ConfluencePage(id="303", title="ai-runbook-service-springboot", version=4)

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.success is True
    assert res.action == "UPDATED"
    assert res.page_id == "303"
    assert res.version == 4
    mock_client.update_page.assert_called_once()
    mock_client.create_page.assert_not_called()


def test_07_multiple_exact_matches_fails_safe(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """7. multiple exact matches -> FAIL SAFE."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nContent.", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    mock_client.get_child_pages.return_value = [
        ConfluencePage(id="301", title="ai-runbook-service-springboot", version=1),
        ConfluencePage(id="302", title="ai-runbook-service-springboot", version=2),
    ]

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.success is False
    assert res.action == "FAILED"
    assert "Multiple" in (res.error or "")
    mock_client.create_page.assert_not_called()
    mock_client.update_page.assert_not_called()


def test_08_partial_fuzzy_title_does_not_count_as_match(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """8. partial/fuzzy title does NOT count as match (e.g. ai-runbook-service or ai-runbook-service-springboot-old)."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nContent.", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    mock_client.get_child_pages.return_value = [
        ConfluencePage(id="401", title="ai-runbook-service", version=1),
        ConfluencePage(id="402", title="ai-runbook-service-springboot-old", version=1),
        ConfluencePage(id="403", title="Production Runbook - ai-runbook-service-springboot", version=1),
    ]
    mock_client.create_page.return_value = ConfluencePage(id="501", title="ai-runbook-service-springboot", version=1)

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.success is True
    assert res.action == "CREATED"
    assert res.page_id == "501"
    mock_client.create_page.assert_called_once()
    mock_client.update_page.assert_not_called()


def test_09_same_title_outside_configured_parent_does_not_count(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """9. same title outside configured parent does NOT count (only parent's children are queried)."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nContent.", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    mock_client.get_child_pages.return_value = []
    mock_client.create_page.return_value = ConfluencePage(id="601", title="ai-runbook-service-springboot", version=1)

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    mock_client.get_child_pages.assert_called_once_with("111222")
    assert res.action == "CREATED"


def test_10_update_uses_same_existing_page_id(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """10. update uses same existing page ID."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nContent.", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    existing = ConfluencePage(id="777888", title="ai-runbook-service-springboot", version=5, body_storage="<p>Old</p>")
    mock_client.get_child_pages.return_value = [existing]
    mock_client.get_page.return_value = existing
    mock_client.update_page.return_value = ConfluencePage(id="777888", title="ai-runbook-service-springboot", version=6)

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.page_id == "777888"
    assert mock_client.update_page.call_args[1]["page_id"] == "777888"


def test_11_update_increments_version_correctly(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """11. update increments version correctly where required."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nContent.", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    existing = ConfluencePage(id="888999", title="ai-runbook-service-springboot", version=12, body_storage="<p>Old</p>")
    mock_client.get_child_pages.return_value = [existing]
    mock_client.get_page.return_value = existing
    mock_client.update_page.return_value = ConfluencePage(id="888999", title="ai-runbook-service-springboot", version=13)

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.version == 13
    assert mock_client.update_page.call_args[1]["version"] == 13


# ---------------------------------------------------------------------------
# 12-19. Guardrails, Dry-Run, and Error Handling Tests
# ---------------------------------------------------------------------------

def test_12_validation_failed_skips_confluence_publication(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """12. validation FAILED -> no publish call."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Bad Runbook", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="FAILED", dry_run=False)

    assert res.success is False
    assert res.action == "SKIPPED"
    mock_client.get_child_pages.assert_not_called()
    mock_client.create_page.assert_not_called()
    mock_client.update_page.assert_not_called()


def test_13_dry_run_performs_zero_write_http_calls(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """13. dry-run -> zero write HTTP calls (only read/inspection allowed)."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nContent.", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    mock_client.get_child_pages.return_value = []

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=True)

    assert res.success is True
    assert res.action == "DRY_RUN"
    assert res.planned_action == "CREATE"
    mock_client.create_page.assert_not_called()
    mock_client.update_page.assert_not_called()


def test_14_confluence_disabled_makes_no_http_calls(tmp_path: Path, repo_info_sample: RepositoryInfo):
    """14. Confluence disabled -> no HTTP calls."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nContent.", encoding="utf-8")

    disabled_cfg = ConfluenceConfig(enabled=False)
    mock_client = MagicMock(spec=ConfluenceClient)

    pub = ConfluencePublisher(config=disabled_cfg, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.success is True
    assert res.action == "SKIPPED"
    mock_client.get_child_pages.assert_not_called()
    mock_client.get_page.assert_not_called()
    mock_client.create_page.assert_not_called()
    mock_client.update_page.assert_not_called()


def test_15_missing_required_config_causes_safe_failure(tmp_path: Path, repo_info_sample: RepositoryInfo):
    """15. missing required config -> safe failure."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nContent.", encoding="utf-8")

    cfg_missing = ConfluenceConfig(enabled=True, base_url="", parent_page_id="", token="")
    mock_client = MagicMock(spec=ConfluenceClient)

    pub = ConfluencePublisher(config=cfg_missing, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.success is False
    assert res.action == "FAILED"
    assert "missing required configuration" in (res.error or "")
    mock_client.get_child_pages.assert_not_called()


def test_16_create_http_failure_causes_safe_failure(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """16. create HTTP failure -> safe failure."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nContent.", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    mock_client.get_child_pages.return_value = []
    mock_client.create_page.side_effect = ConfluenceError("HTTP 500: Server Error")

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.success is False
    assert res.action == "FAILED"
    assert "HTTP 500" in (res.error or "")


def test_17_update_http_failure_causes_safe_failure(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """17. update HTTP failure -> safe failure."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nContent.", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    existing = ConfluencePage(id="123", title="ai-runbook-service-springboot", version=1, body_storage="<p>Old</p>")
    mock_client.get_child_pages.return_value = [existing]
    mock_client.get_page.return_value = existing
    mock_client.update_page.side_effect = ConfluenceError("HTTP 409: Version Conflict")

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.success is False
    assert res.action == "FAILED"
    assert "Version Conflict" in (res.error or "")


def test_18_authentication_failure_causes_safe_failure(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """18. authentication failure -> safe failure."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nContent.", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    mock_client.get_child_pages.side_effect = ConfluenceError("Confluence authentication failed (HTTP 401)")

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.success is False
    assert res.action == "FAILED"
    assert "HTTP 401" in (res.error or "")


def test_19_timeout_causes_safe_failure(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """19. timeout -> safe failure."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nContent.", encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    mock_client.get_child_pages.side_effect = ConfluenceError("Confluence request timed out after 10s")

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.success is False
    assert res.action == "FAILED"
    assert "timed out" in (res.error or "")


# ---------------------------------------------------------------------------
# 20-22. Manual Support Notes Preservation Tests
# ---------------------------------------------------------------------------

def test_20_manual_support_notes_preserved_on_update(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """20. manual support notes preserved on update."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nFresh generated content.", encoding="utf-8")

    existing_body = """
    <h1>Runbook</h1>
    <p>Old generated content</p>
    <h2>Manual Support Notes</h2>
    <!-- MANUAL SUPPORT NOTES START -->
    <p>Important: Call on-call DBA at extension 9999 before restarting.</p>
    <!-- MANUAL SUPPORT NOTES END -->
    """
    mock_client = MagicMock(spec=ConfluenceClient)
    existing = ConfluencePage(id="555", title="ai-runbook-service-springboot", version=2, body_storage=existing_body)
    mock_client.get_child_pages.return_value = [existing]
    mock_client.get_page.return_value = existing
    mock_client.update_page.return_value = ConfluencePage(id="555", title="ai-runbook-service-springboot", version=3)

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.success is True
    assert res.manual_notes_preserved is True
    # Verify injected notes passed to markdown_to_storage / update_page
    mock_client.update_page.assert_called_once()
    assert mock_client.markdown_to_storage.called
    called_markdown = mock_client.markdown_to_storage.call_args[0][0]
    assert "Call on-call DBA at extension 9999" in called_markdown
    assert "Fresh generated content." in called_markdown


def test_21_page_without_manual_notes_updates_normally(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """21. page without manual notes updates normally."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nFresh generated content.", encoding="utf-8")

    existing_body = "<p>Old generated content without manual notes</p>"
    mock_client = MagicMock(spec=ConfluenceClient)
    existing = ConfluencePage(id="555", title="ai-runbook-service-springboot", version=2, body_storage=existing_body)
    mock_client.get_child_pages.return_value = [existing]
    mock_client.get_page.return_value = existing
    mock_client.update_page.return_value = ConfluencePage(id="555", title="ai-runbook-service-springboot", version=3)

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.success is True
    assert res.manual_notes_preserved is False
    called_markdown = mock_client.markdown_to_storage.call_args[0][0]
    assert called_markdown == "# Runbook\n\nFresh generated content."


def test_22_ambiguous_manual_notes_structure_fails_safely(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """22. ambiguous manual-notes structure -> safe handling (does not corrupt)."""
    runbook_file = tmp_path / "RUNBOOK.md"
    runbook_file.write_text("# Runbook\n\nFresh content.", encoding="utf-8")

    # Mismatched/unclosed marker
    corrupted_body = "<p>Old</p><!-- MANUAL SUPPORT NOTES START -->No end tag here"
    mock_client = MagicMock(spec=ConfluenceClient)
    existing = ConfluencePage(id="555", title="ai-runbook-service-springboot", version=2, body_storage=corrupted_body)
    mock_client.get_child_pages.return_value = [existing]
    mock_client.get_page.return_value = existing

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    res = pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert res.success is False
    assert res.action == "FAILED"
    assert "manual support notes" in (res.error or "").lower()
    mock_client.update_page.assert_not_called()


# ---------------------------------------------------------------------------
# 23-27. Artifact Integrity & Generation Summary Tests
# ---------------------------------------------------------------------------

def test_23_runbook_md_remains_unchanged_after_publish_failure(tmp_path: Path, base_config: ConfluenceConfig, repo_info_sample: RepositoryInfo):
    """23. RUNBOOK.md remains unchanged after publish failure."""
    runbook_file = tmp_path / "RUNBOOK.md"
    original_text = "# Original Valid Runbook\n\nMust not be deleted or changed."
    runbook_file.write_text(original_text, encoding="utf-8")

    mock_client = MagicMock(spec=ConfluenceClient)
    mock_client.get_child_pages.side_effect = ConfluenceError("Network error")

    pub = ConfluencePublisher(config=base_config, client=mock_client)
    pub.publish_runbook(runbook_file, repo_info_sample, validation_status="PASSED", dry_run=False)

    assert runbook_file.exists()
    assert runbook_file.read_text(encoding="utf-8") == original_text


def test_24_no_secret_or_token_written_to_generation_summary():
    """24. no secret/token written to generation summary."""
    res = ConfluencePublishResult(
        action="UPDATED",
        success=True,
        page_id="123456",
        page_title="ai-runbook-service-springboot",
        parent_page_id="999999",
        version=5,
    )
    summary_dict = res.to_summary_dict(enabled=True)
    serialized = json.dumps(summary_dict)

    assert "secret" not in serialized.lower()
    assert "token" not in serialized.lower()
    assert "authorization" not in serialized.lower()
    assert "password" not in serialized.lower()


def test_25_generation_summary_records_create_correctly():
    """25. generation-summary records CREATE correctly."""
    res = ConfluencePublishResult(
        action="CREATED",
        success=True,
        page_id="987654",
        page_title="ai-runbook-service-springboot",
        parent_page_id="111222",
        version=1,
    )
    summary = res.to_summary_dict(enabled=True)
    assert summary["enabled"] is True
    assert summary["action"] == "CREATED"
    assert summary["pageId"] == "987654"
    assert summary["pageTitle"] == "ai-runbook-service-springboot"
    assert summary["parentPageId"] == "111222"
    assert summary["published"] is True


def test_26_generation_summary_records_update_correctly():
    """26. generation-summary records UPDATE correctly."""
    res = ConfluencePublishResult(
        action="UPDATED",
        success=True,
        page_id="987654",
        page_title="ai-runbook-service-springboot",
        parent_page_id="111222",
        version=7,
        manual_notes_preserved=True,
    )
    summary = res.to_summary_dict(enabled=True)
    assert summary["enabled"] is True
    assert summary["action"] == "UPDATED"
    assert summary["pageId"] == "987654"
    assert summary["version"] == 7
    assert summary["manualNotesPreserved"] is True
    assert summary["published"] is True


def test_27_generation_summary_records_failure_correctly():
    """27. generation-summary records failure correctly."""
    res = ConfluencePublishResult(
        action="FAILED",
        success=False,
        page_title="ai-runbook-service-springboot",
        parent_page_id="111222",
        error="Confluence API returned HTTP 500: Server Error",
    )
    summary = res.to_summary_dict(enabled=True)
    assert summary["enabled"] is True
    assert summary["action"] == "FAILED"
    assert summary["published"] is False
    assert "HTTP 500" in summary["error"]
