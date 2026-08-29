"""Unit tests for publisher/repository.py."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from publisher.repository import (
    RepositoryAccessError,
    RepositoryInfo,
    inspect_repository,
    resolve_branch,
    resolve_commit_sha,
    resolve_origin_url,
    resolve_repository,
    resolve_service_name,
    resolve_working_tree_clean,
    validate_git_repo,
)


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary initialized git repository."""
    repo = tmp_path / "sample-payments-service"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True, capture_output=True)

    # Add an initial commit
    dummy_file = repo / "README.md"
    dummy_file.write_text("# Sample Payments Service", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo), check=True, capture_output=True)

    return repo


def test_validate_git_repo_success(temp_git_repo: Path):
    validate_git_repo(temp_git_repo)


def test_validate_git_repo_non_existent(tmp_path: Path):
    non_existent = tmp_path / "does-not-exist"
    with pytest.raises(RepositoryAccessError, match="does not exist"):
        validate_git_repo(non_existent)


def test_validate_git_repo_not_a_git_repo(tmp_path: Path):
    non_git = tmp_path / "regular-folder"
    non_git.mkdir()
    with pytest.raises(RepositoryAccessError, match="not a valid Git repository"):
        validate_git_repo(non_git)


def test_inspect_repository_resolves_absolute_path(temp_git_repo: Path):
    info = inspect_repository(str(temp_git_repo))
    assert Path(info.path).is_absolute()
    assert str(temp_git_repo.resolve()) == info.path


def test_resolve_commit_and_branch(temp_git_repo: Path):
    commit = resolve_commit_sha(temp_git_repo)
    assert len(commit) == 40
    assert commit != "unknown"

    branch = resolve_branch(temp_git_repo)
    assert branch in ("main", "master")


def test_resolve_branch_detached_head(temp_git_repo: Path):
    # Checkout specific commit directly to create detached HEAD
    commit = resolve_commit_sha(temp_git_repo)
    subprocess.run(["git", "checkout", commit], cwd=str(temp_git_repo), check=True, capture_output=True)
    branch = resolve_branch(temp_git_repo)
    assert branch is None


def test_resolve_origin_missing_and_present(temp_git_repo: Path):
    # Missing origin
    origin = resolve_origin_url(temp_git_repo)
    assert origin is None

    # Add origin
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/org/sample-service.git"],
        cwd=str(temp_git_repo),
        check=True,
        capture_output=True,
    )
    origin_after = resolve_origin_url(temp_git_repo)
    assert origin_after == "https://github.com/org/sample-service.git"


def test_resolve_working_tree_clean(temp_git_repo: Path):
    assert resolve_working_tree_clean(temp_git_repo) is True

    # Modify file
    (temp_git_repo / "README.md").write_text("# Changed Content", encoding="utf-8")
    assert resolve_working_tree_clean(temp_git_repo) is False


def test_resolve_service_name_from_application_yaml(temp_git_repo: Path):
    res_dir = temp_git_repo / "src" / "main" / "resources"
    res_dir.mkdir(parents=True)
    app_yaml = res_dir / "application.yml"
    app_yaml.write_text(
        """
server:
  port: 8080
spring:
  application:
    name: payments-engine
""",
        encoding="utf-8",
    )

    name = resolve_service_name(temp_git_repo)
    assert name == "payments-engine"


def test_resolve_service_name_from_application_yaml_alt(temp_git_repo: Path):
    res_dir = temp_git_repo / "src" / "main" / "resources"
    res_dir.mkdir(parents=True)
    app_yaml = res_dir / "application.yaml"
    app_yaml.write_text(
        """
spring:
  application:
    name: payments-yaml-service
""",
        encoding="utf-8",
    )

    name = resolve_service_name(temp_git_repo)
    assert name == "payments-yaml-service"


def test_resolve_service_name_from_application_properties(temp_git_repo: Path):
    res_dir = temp_git_repo / "src" / "main" / "resources"
    res_dir.mkdir(parents=True)
    app_props = res_dir / "application.properties"
    app_props.write_text(
        """
# Configuration properties
server.port=8080
spring.application.name = billing-service
""",
        encoding="utf-8",
    )

    name = resolve_service_name(temp_git_repo)
    assert name == "billing-service"


def test_resolve_service_name_fallback_to_folder(temp_git_repo: Path):
    name = resolve_service_name(temp_git_repo)
    assert name == "sample-payments-service"


def test_inspect_repository_end_to_end(temp_git_repo: Path):
    info = inspect_repository(str(temp_git_repo))
    assert isinstance(info, RepositoryInfo)
    assert info.service_name == "sample-payments-service"
    assert len(info.commit_sha) == 40
    assert info.path == str(temp_git_repo.resolve())
    assert info.working_tree_clean is True


def test_resolve_repository_with_overrides(temp_git_repo: Path):
    info = resolve_repository(
        temp_git_repo,
        service_override="custom-service",
        branch_override="release-1.0",
        commit_override="abc1234",
    )
    assert info.service_name == "custom-service"
    assert info.branch == "release-1.0"
    assert info.commit_sha == "abc1234"
