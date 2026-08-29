"""Unit tests for publisher/publisher.py."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from publisher.publisher import publish


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary initialized git repository."""
    repo = tmp_path / "mock-order-service"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True, capture_output=True)

    dummy_file = repo / "README.md"
    dummy_file.write_text("# Mock Order Service", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo), check=True, capture_output=True)

    return repo


@patch("publisher.publisher.execute_idfc_coder")
def test_publisher_output_directory_isolation(mock_execute, temp_git_repo: Path):
    """Verify run folder is created under runs/ and NOT inside target repository."""
    def side_effect(coder_cmd, mode, task_content, task_path, repo_path, agent_log_path, run_logger):
        # Simulate AI generating valid RUNBOOK.md
        runbook = task_path.parent / "RUNBOOK.md"
        runbook.write_text(
            """# Production Support Runbook - mock-order-service
> **Service:** mock-order-service
> **Environment:** production

## Service Overview
Handles order lifecycle.

## Support Boundaries
Support must not replay Kafka events without approval.
""" + ("\nPadding content to fulfill sensible minimum length requirements." * 5),
            encoding="utf-8",
        )
        return MagicMock(success=True, returncode=0)

    mock_execute.side_effect = side_effect

    result = publish(
        repo_path=str(temp_git_repo),
        dry_run=True,
        mode="stdin",
    )

    assert result.success is True
    assert result.run_dir is not None
    # Ensure run_dir is NOT inside temp_git_repo
    assert not str(result.run_dir).startswith(str(temp_git_repo))
    assert result.run_dir.name != ""
    assert (result.run_dir / "metadata.json").exists()
    assert (result.run_dir / "RUNBOOK_TASK.md").exists()
    assert (result.run_dir / "RUNBOOK.md").exists()
    assert (result.run_dir / "validation-report.txt").exists()


@patch("publisher.publisher.execute_idfc_coder")
def test_publisher_missing_runbook_fails_with_generation_failed(mock_execute, temp_git_repo: Path):
    """When idfc-coder exits without generating RUNBOOK.md, return failure."""
    mock_execute.return_value = MagicMock(success=True, returncode=0)

    result = publish(
        repo_path=str(temp_git_repo),
        dry_run=True,
    )

    assert result.success is False
    assert "RUNBOOK_GENERATION_FAILED" in (result.error or "")


@patch("publisher.publisher.execute_idfc_coder")
def test_publisher_validation_failure(mock_execute, temp_git_repo: Path):
    """When generated runbook fails validation, return failure and do not publish."""
    def side_effect(coder_cmd, mode, task_content, task_path, repo_path, agent_log_path, run_logger):
        runbook = task_path.parent / "RUNBOOK.md"
        # Invalid runbook containing java code and SQL update
        runbook.write_text(
            """# Production Support Runbook - mock-order-service
```java
public class UnsafeCode {}
```
Run UPDATE orders SET status = 1;
""",
            encoding="utf-8",
        )
        return MagicMock(success=True, returncode=0)

    mock_execute.side_effect = side_effect

    result = publish(
        repo_path=str(temp_git_repo),
        dry_run=True,
    )

    assert result.success is False
    assert "RUNBOOK_VALIDATION_FAILED" in (result.error or "")
    assert result.validation_passed is False


@patch("publisher.publisher.ConfluenceClient")
@patch("publisher.publisher.execute_idfc_coder")
def test_dry_run_never_calls_confluence(mock_execute, mock_confluence, temp_git_repo: Path):
    """Dry run should never instantiate or call ConfluenceClient."""
    def side_effect(coder_cmd, mode, task_content, task_path, repo_path, agent_log_path, run_logger):
        runbook = task_path.parent / "RUNBOOK.md"
        runbook.write_text(
            """# Production Support Runbook - mock-order-service
> **Service:** mock-order-service

## Service Overview
Overview text.
""" + ("\nPadding content to fulfill sensible minimum length requirements." * 5),
            encoding="utf-8",
        )
        return MagicMock(success=True, returncode=0)

    mock_execute.side_effect = side_effect

    result = publish(
        repo_path=str(temp_git_repo),
        dry_run=True,
    )

    assert result.success is True
    assert result.action == "dry-run"
    assert not mock_confluence.called


@patch("publisher.publisher.ConfluenceClient")
@patch("publisher.publisher.execute_idfc_coder")
def test_publish_mode_calls_confluence(mock_execute, mock_confluence_class, temp_git_repo: Path):
    """Non-dry-run mode should call Confluence and update/create page."""
    def side_effect(coder_cmd, mode, task_content, task_path, repo_path, agent_log_path, run_logger):
        runbook = task_path.parent / "RUNBOOK.md"
        runbook.write_text(
            """# Production Support Runbook - mock-order-service
> **Service:** mock-order-service

## Service Overview
Valid runbook.
""" + ("\nPadding content to fulfill sensible minimum length requirements." * 5),
            encoding="utf-8",
        )
        return MagicMock(success=True, returncode=0)

    mock_execute.side_effect = side_effect

    mock_client = MagicMock()
    mock_confluence_class.return_value = mock_client
    mock_client.find_page.return_value = {"id": "12345", "version": {"number": 1}}
    mock_client.get_page_content.return_value = "<!-- MANUAL SUPPORT NOTES START -->\nKeep this manual note\n<!-- MANUAL SUPPORT NOTES END -->"
    mock_client.markdown_to_confluence.return_value = "<p>confluence-storage</p>"
    mock_client.update_page.return_value = {"id": "12345"}
    mock_client.page_url.return_value = "https://confluence.org/pages/12345"

    config = {
        "confluence": {
            "base_url": "https://confluence.org",
            "space_key": "SUPPORT",
            "username": "user@org.com",
            "api_token": "secret_token",
        }
    }

    result = publish(
        repo_path=str(temp_git_repo),
        config=config,
        dry_run=False,
    )

    assert result.success is True
    assert result.action == "updated"
    assert result.page_id == "12345"
    assert result.page_url == "https://confluence.org/pages/12345"
    assert mock_client.update_page.called
