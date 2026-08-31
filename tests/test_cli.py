"""Unit tests for run.py Click CLI argument parsing and execution."""

from __future__ import annotations

import inspect
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest
from click.testing import CliRunner

from run import main


def _make_git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create a minimal real git repository in tmp_path with given files."""
    repo = tmp_path / "sample-service"
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
</project>""",
    "src/main/resources/application.yml": """spring:
  application:
    name: payment-service
""",
}


def test_01_cli_help_exits_zero():
    """Verify python run.py --help exits 0 with full usage output."""
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "--repo" in result.output
    assert "--dry-run" in result.output
    assert "--agent-debug" in result.output
    assert "--execution-mode" in result.output


def test_02_cli_option_names_map_exactly_to_main_signature():
    """Verify all @click.option parameters map 1-to-1 to main() callback parameters without TypeErrors."""
    # Get parameters defined on the click command
    click_param_names = {param.name for param in main.params}
    
    # Get Python function signature parameters
    sig = inspect.signature(main.callback)
    fn_param_names = set(sig.parameters.keys())

    assert click_param_names == fn_param_names
    assert "generate_runbook" not in fn_param_names
    assert "agent_debug" in fn_param_names


def test_03_removed_generate_runbook_produces_no_such_option_error(tmp_path: Path):
    """Verify passing obsolete --generate-runbook produces Click's standard No such option error."""
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    runner = CliRunner()
    result = runner.invoke(main, ["--repo", str(repo), "--generate-runbook"])
    assert result.exit_code != 0
    assert "No such option" in result.output
    assert "--generate-runbook" in result.output


def test_04_normal_dry_run_command_executes_without_type_error(tmp_path: Path):
    """Verify python run.py --repo <repo> --engine external-agent --dry-run executes cleanly."""
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    runner = CliRunner()
    result = runner.invoke(main, ["--repo", str(repo), "--engine", "external-agent", "--dry-run"])
    assert result.exit_code == 0
    assert "Production Support Runbook" in result.output
    assert "DISCOVERY_TASK.md" in result.output


def test_05_agent_debug_flag_accepted(tmp_path: Path):
    """Verify python run.py --repo <repo> --engine external-agent --agent-debug --dry-run is accepted."""
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    runner = CliRunner()
    result = runner.invoke(main, ["--repo", str(repo), "--engine", "external-agent", "--agent-debug", "--dry-run"])
    assert result.exit_code == 0
    assert "Production Support Runbook" in result.output


def test_06_inspect_repo_flag_works(tmp_path: Path):
    """Verify python run.py --repo <repo> --inspect-repo works cleanly."""
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    runner = CliRunner()
    result = runner.invoke(main, ["--repo", str(repo), "--inspect-repo"])
    assert result.exit_code == 0
    assert "Repository Inspection" in result.output
    assert "payment-service" in result.output


def test_07_collect_facts_flag_works(tmp_path: Path):
    """Verify python run.py --repo <repo> --collect-facts works cleanly."""
    repo = _make_git_repo(tmp_path, SAMPLE_REPO_FILES)
    runner = CliRunner()
    result = runner.invoke(main, ["--repo", str(repo), "--collect-facts"])
    assert result.exit_code == 0
    assert "Service Fact Collection" in result.output
    assert "payment-service" in result.output
