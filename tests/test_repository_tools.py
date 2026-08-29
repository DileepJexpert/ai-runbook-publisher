"""Unit tests for publisher/repository_tools.py."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from publisher.repository import RepositoryAccessError
from publisher.repository_tools import RepositoryTools, SearchResult


@pytest.fixture
def populated_git_repo(tmp_path: Path) -> Path:
    """Create a temporary initialized git repository with sample Java files, configs, and build artifacts."""
    repo = tmp_path / "mock-spring-service"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True, capture_output=True)

    # 1. Source files
    java_dir = repo / "src" / "main" / "java" / "com" / "example"
    java_dir.mkdir(parents=True)
    
    controller = java_dir / "PaymentController.java"
    controller.write_text(
        """package com.example;

import org.springframework.web.bind.annotation.RestController;

@RestController
public class PaymentController {
    public void processPayment() {
        // Line 8
        System.out.println("Processing payment");
    }
}
""",
        encoding="utf-8",
    )

    service_file = java_dir / "PaymentService.java"
    service_file.write_text(
        """package com.example;

public class PaymentService {
    public boolean execute() {
        return true;
    }
}
""",
        encoding="utf-8",
    )

    # 2. Test file (should be included in list_files since src/test is not permanently excluded in Phase 1)
    test_dir = repo / "src" / "test" / "java"
    test_dir.mkdir(parents=True)
    (test_dir / "PaymentTest.java").write_text("// Test file", encoding="utf-8")

    # 3. Config file
    res_dir = repo / "src" / "main" / "resources"
    res_dir.mkdir(parents=True)
    (res_dir / "application.yml").write_text("spring:\n  application:\n    name: mock-spring-service\n", encoding="utf-8")

    # 4. Ignored directories and files
    target_dir = repo / "target" / "classes"
    target_dir.mkdir(parents=True)
    (target_dir / "PaymentController.class").write_bytes(b"\xca\xfe\xba\xbe\x00\x00")

    build_dir = repo / "build"
    build_dir.mkdir()
    (build_dir / "output.txt").write_text("build output", encoding="utf-8")

    # Binary file in root
    (repo / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00")

    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo), check=True, capture_output=True)

    return repo


def test_list_files_relative_paths(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    files = tools.list_files()

    assert all(not f.startswith("/") for f in files)
    assert "src/main/java/com/example/PaymentController.java" in files
    assert "src/main/java/com/example/PaymentService.java" in files
    assert "src/main/resources/application.yml" in files
    assert "src/test/java/PaymentTest.java" in files


def test_list_files_ignores_target_and_build_and_git(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    files = tools.list_files()

    assert not any(f.startswith("target/") for f in files)
    assert not any(f.startswith("build/") for f in files)
    assert not any(f.startswith(".git/") for f in files)


def test_list_files_ignores_binary_artifacts(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    files = tools.list_files()

    assert not any(f.endswith(".class") for f in files)
    assert not any(f.endswith(".png") for f in files)


def test_list_files_deterministic_ordering(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    files_1 = tools.list_files()
    files_2 = tools.list_files()

    assert files_1 == files_2
    assert files_1 == sorted(files_1)


def test_list_files_with_glob_pattern(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    java_files = tools.list_files(pattern="*.java")

    assert all(f.endswith(".java") for f in java_files)
    assert len(java_files) == 3


def test_search_code_returns_correct_line_and_file(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    results = tools.search_code("@RestController")

    assert len(results) == 1
    res = results[0]
    assert isinstance(res, SearchResult)
    assert res.file == "src/main/java/com/example/PaymentController.java"
    assert res.line == 5
    assert res.text == "@RestController"


def test_search_code_honors_max_results(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    # 'public' appears in multiple java files
    results = tools.search_code("public", max_results=1)

    assert len(results) == 1


def test_search_code_file_glob(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    results = tools.search_code("application", file_glob="*.yml")

    assert len(results) >= 1
    assert all(r.file.endswith(".yml") for r in results)


def test_read_file_success(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    content = tools.read_file("src/main/resources/application.yml")

    assert "mock-spring-service" in content


def test_read_file_truncation(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    content = tools.read_file("src/main/java/com/example/PaymentController.java", max_chars=30)

    assert len(content) <= 30 + len("\n[TRUNCATED]")
    assert "[TRUNCATED]" in content


def test_read_lines_success(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    lines_output = tools.read_lines("src/main/java/com/example/PaymentController.java", start_line=5, end_line=7)

    expected = "5 | @RestController\n6 | public class PaymentController {\n7 |     public void processPayment() {"
    assert lines_output == expected


def test_read_lines_validation_errors(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))

    with pytest.raises(RepositoryAccessError, match="start_line must be >= 1"):
        tools.read_lines("src/main/resources/application.yml", start_line=0, end_line=5)

    with pytest.raises(RepositoryAccessError, match="cannot be less than start_line"):
        tools.read_lines("src/main/resources/application.yml", start_line=10, end_line=5)

    with pytest.raises(RepositoryAccessError, match="exceeds maximum allowed"):
        tools.read_lines("src/main/resources/application.yml", start_line=1, end_line=600)


def test_path_traversal_rejected(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))

    with pytest.raises(RepositoryAccessError, match="Path traversal"):
        tools.read_file("../../etc/passwd")

    with pytest.raises(RepositoryAccessError, match="Path traversal"):
        tools.read_file("src/main/../../../../secret.txt")


def test_absolute_outside_path_rejected(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))

    with pytest.raises(RepositoryAccessError, match="Absolute paths are rejected"):
        tools.read_file("/etc/passwd")


def test_binary_file_read_rejected(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))

    with pytest.raises(RepositoryAccessError, match="Cannot read binary file"):
        tools.read_file("logo.png")


def test_directory_read_rejected(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))

    with pytest.raises(RepositoryAccessError, match="Path is a directory"):
        tools.read_file("src/main/java")


def test_symlink_escape_rejected(populated_git_repo: Path, tmp_path: Path):
    outside_file = tmp_path / "outside_secret.txt"
    outside_file.write_text("top secret", encoding="utf-8")

    link_path = populated_git_repo / "symlink_secret.txt"
    try:
        os.symlink(outside_file, link_path)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not supported in this environment")

    tools = RepositoryTools(str(populated_git_repo))
    with pytest.raises(RepositoryAccessError, match="Symlink escapes repository"):
        tools.read_file("symlink_secret.txt")


def test_git_metadata_returns_expected_fields(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    meta = tools.git_metadata()

    assert meta["serviceName"] == "mock-spring-service"
    assert len(meta["commitSha"]) == 40
    assert meta["workingTreeClean"] is True
    assert meta["repositoryPath"] == str(populated_git_repo.resolve())
    assert meta["repositoryName"] == "mock-spring-service"


def test_git_file_history(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    history = tools.git_file_history("src/main/resources/application.yml")

    assert len(history) >= 1
    assert "commitSha" in history[0]
    assert "subject" in history[0]
    assert history[0]["subject"] == "Initial commit"


def test_repository_tools_do_not_modify_repository_contents(populated_git_repo: Path):
    tools = RepositoryTools(str(populated_git_repo))
    
    # Perform various read operations
    tools.list_files()
    tools.search_code("public")
    tools.read_file("src/main/resources/application.yml")
    tools.read_lines("src/main/java/com/example/PaymentController.java", 1, 5)
    tools.git_metadata()

    # Verify working tree is strictly unmodified
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(populated_git_repo), capture_output=True, text=True)
    assert status.stdout.strip() == ""


def test_regression_no_whole_repo_concatenation_api():
    """Ensure no giant-prompt repository concatenation function exists in RepositoryTools."""
    forbidden_names = [
        "collect_repo",
        "repository_content",
        "full_repo_text",
        "concatenate_sources",
        "build_whole_repo_prompt",
    ]
    for name in forbidden_names:
        assert not hasattr(RepositoryTools, name), f"Forbidden whole-repo method '{name}' found on RepositoryTools"
