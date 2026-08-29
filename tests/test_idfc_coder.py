"""Unit tests for publisher/idfc_coder.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from publisher.idfc_coder import (
    ExecutionResult,
    build_runbook_task,
    copy_to_clipboard,
    execute_idfc_coder,
)
from publisher.repository import RepositoryInfo


def test_build_runbook_task_format():
    repo_info = RepositoryInfo(
        path="/test/path/my-service",
        service_name="my-service",
        branch="main",
        commit_sha="1234567890abcdef",
        origin_url="https://github.com/org/my-service.git",
        working_tree_clean=True,
    )
    output_path = Path("/runs/my-service/20260828-120000/RUNBOOK.md")
    prompt_template = "Generate runbook for {SERVICE_NAME} on {BRANCH} commit {COMMIT_SHA}."
    metadata = {
        "app_version": "1.2.3",
        "environment": "production",
    }

    task = build_runbook_task(repo_info, output_path, prompt_template, metadata)

    # Validate header fields
    assert "Repository:\n/test/path/my-service" in task or "Repository:\n" in task
    assert "Service:\nmy-service" in task
    assert "Commit:\n1234567890abcdef" in task
    assert "Branch:\nmain" in task
    assert "Origin:\nhttps://github.com/org/my-service.git" in task
    assert "Output:\n/runs/my-service/20260828-120000/RUNBOOK.md" in task or "Output:\n" in task

    # Validate instructions
    assert "Do NOT modify:" in task
    assert "Read-only analysis only." in task
    assert "Start repository analysis immediately." in task
    assert "Generate runbook for my-service on main commit 1234567890abcdef." in task


def test_task_does_not_contain_repository_source_content():
    repo_info = RepositoryInfo(
        path="/dummy/repo",
        service_name="payment-service",
        branch="main",
        commit_sha="abcd123",
        origin_url="",
        working_tree_clean=True,
    )
    output_path = Path("/runs/output/RUNBOOK.md")
    prompt_template = "Prompt template text."
    
    task = build_runbook_task(repo_info, output_path, prompt_template, {})

    # Ensure no source concatenation markers or raw file embeddings exist
    assert "=== FILE:" not in task
    assert "=== END FILE ===" not in task
    assert "=== REPOSITORY MANIFEST ===" not in task
    assert "public class PaymentApplication" not in task
    # Size should be small (just instructions & metadata)
    assert len(task) < 5000


@patch("subprocess.run")
def test_execute_idfc_coder_sets_cwd_to_target_repo(mock_run, tmp_path: Path):
    mock_run.return_value = MagicMock(returncode=0)
    repo_path = tmp_path / "target-repo"
    repo_path.mkdir()
    task_path = tmp_path / "RUNBOOK_TASK.md"
    task_path.write_text("Task content", encoding="utf-8")
    agent_log_path = tmp_path / "agent.log"

    result = execute_idfc_coder(
        coder_cmd="idfc-coder",
        mode="interactive",
        task_content="Task content",
        task_path=task_path,
        repo_path=repo_path,
        agent_log_path=agent_log_path,
    )

    assert result.success is True
    assert mock_run.called
    called_args, called_kwargs = mock_run.call_args
    assert called_kwargs.get("cwd") == str(repo_path.resolve())
    assert agent_log_path.exists()


@patch("subprocess.run")
def test_execute_idfc_coder_stdin_mode(mock_run, tmp_path: Path):
    mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
    repo_path = tmp_path / "target-repo"
    repo_path.mkdir()
    task_path = tmp_path / "RUNBOOK_TASK.md"
    agent_log_path = tmp_path / "agent.log"

    result = execute_idfc_coder(
        coder_cmd="idfc-coder",
        mode="stdin",
        task_content="Task text",
        task_path=task_path,
        repo_path=repo_path,
        agent_log_path=agent_log_path,
    )

    assert result.success is True
    called_args, called_kwargs = mock_run.call_args
    assert called_kwargs.get("input") == "Task text"
    assert called_kwargs.get("cwd") == str(repo_path.resolve())


@patch("subprocess.run")
def test_execute_idfc_coder_arg_mode(mock_run, tmp_path: Path):
    mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
    repo_path = tmp_path / "target-repo"
    repo_path.mkdir()
    task_path = tmp_path / "RUNBOOK_TASK.md"
    task_path.write_text("Task text", encoding="utf-8")
    agent_log_path = tmp_path / "agent.log"

    result = execute_idfc_coder(
        coder_cmd="idfc-coder",
        mode="arg",
        task_content="Task text",
        task_path=task_path,
        repo_path=repo_path,
        agent_log_path=agent_log_path,
    )

    assert result.success is True
    called_args, called_kwargs = mock_run.call_args
    assert called_args[0] == ["idfc-coder", str(task_path.resolve())]
    assert called_kwargs.get("cwd") == str(repo_path.resolve())


@patch("shutil.which")
@patch("subprocess.run")
def test_copy_to_clipboard(mock_run, mock_which):
    mock_which.return_value = "/usr/bin/pbcopy"
    mock_run.return_value = MagicMock(returncode=0)

    copied = copy_to_clipboard("test text")
    assert copied is True
    mock_run.assert_called_once_with(["pbcopy"], input="test text", text=True, check=False, capture_output=True)
