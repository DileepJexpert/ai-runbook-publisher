"""Local IDFC Coder task construction and process execution."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .repository import RepositoryInfo

LOGGER = logging.getLogger(__name__)

INTERACTIVE_BANNER = """
=============================================
ACTION REQUIRED - IDFC CODER IS ABOUT TO OPEN

1. Click IDFC Coder.
2. Press Cmd + V.
3. Press Enter.
4. If PLAN MODE appears, approve it.
5. If EXECUTE MODE asks to continue, type Proceed.
6. Wait for RUNBOOK COMPLETE.
7. Exit IDFC Coder when generation finishes.
=============================================
""".strip()


@dataclass
class ExecutionResult:
    success: bool
    returncode: int
    error: str | None = None


def build_runbook_task(
    repo_info: RepositoryInfo,
    output_runbook_path: Path,
    prompt_template: str,
    pipeline_metadata: dict,
) -> str:
    """
    Construct the authoritative RUNBOOK_TASK.md content.
    Crucial: DO NOT include repository source files in the task content.
    """
    values = {
        "SERVICE_NAME": repo_info.service_name,
        "APP_VERSION": pipeline_metadata.get("app_version") or pipeline_metadata.get("version") or "latest",
        "ENVIRONMENT": pipeline_metadata.get("environment") or "production",
        "COMMIT_SHA": repo_info.commit_sha,
        "TIMESTAMP": pipeline_metadata.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "BRANCH": repo_info.branch,
    }
    
    prompt = prompt_template
    for key, value in values.items():
        prompt = prompt.replace("{" + key + "}", str(value))

    repo_path_obj = Path(repo_info.path).resolve()
    repo_posix = repo_path_obj.as_posix()
    out_posix = output_runbook_path.resolve().as_posix()

    task_content = f"""# Production Support Runbook Generation Task

Repository:
{repo_posix}

Service:
{repo_info.service_name}

Commit:
{repo_info.commit_sha}

Branch:
{repo_info.branch}

Origin:
{repo_info.origin_url}

Output:
{out_posix}

You are analyzing the complete repository at:
{repo_posix}

Use repository search, Git commands and file inspection.

Do NOT modify:
- Java source
- configuration
- tests
- Git history
- repository files

Read-only analysis only.

You may create ONLY:
{out_posix}

Do not create files inside the target repository.
Do not ask the user what task to perform.
Start repository analysis immediately.

{prompt}
""".strip()

    return task_content


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard using pbcopy when available."""
    if shutil.which("pbcopy"):
        try:
            proc = subprocess.run(
                ["pbcopy"],
                input=text,
                text=True,
                check=False,
                capture_output=True,
            )
            if proc.returncode == 0:
                LOGGER.info("Copied task instructions to clipboard via pbcopy.")
                return True
        except Exception as exc:
            LOGGER.debug("pbcopy execution failed: %s", exc)
    return False


def execute_idfc_coder(
    coder_cmd: str,
    mode: str,
    task_content: str,
    task_path: Path,
    repo_path: Path,
    agent_log_path: Path,
    run_logger: logging.Logger | None = None,
) -> ExecutionResult:
    """
    Launch IDFC Coder with working directory set to target repository.
    Supports interactive, stdin, and arg execution modes.
    """
    logger = run_logger or LOGGER
    repo_dir = str(repo_path.resolve())
    mode = (mode or "interactive").lower().strip()

    logger.info("Executing AI coder command '%s' with mode='%s' in cwd='%s'", coder_cmd, mode, repo_dir)

    if mode == "interactive":
        # 1. Attempt clipboard copy
        copied = copy_to_clipboard(task_content)
        if not copied:
            logger.info("Clipboard copy (pbcopy) not available or skipped; task file available at %s", task_path)

        # 2. Display interactive guidance
        print("\n" + INTERACTIVE_BANNER + "\n")

        # 3. Launch interactive process
        try:
            # On macOS/Unix, we could use script if desired, or direct interactive subprocess
            # To ensure standard terminal interactive I/O works seamlessly with TTYs:
            result = subprocess.run([coder_cmd], cwd=repo_dir, check=False)
            
            with agent_log_path.open("a", encoding="utf-8") as f:
                f.write(f"=== IDFC CODER RUN (interactive) ===\n")
                f.write(f"Time: {datetime.now(timezone.utc).isoformat()}\n")
                f.write(f"Command: {coder_cmd}\n")
                f.write(f"Cwd: {repo_dir}\n")
                f.write(f"Return code: {result.returncode}\n")
                f.write("=== END IDFC CODER RUN ===\n")

            return ExecutionResult(success=(result.returncode == 0), returncode=result.returncode)
        except FileNotFoundError:
            err = f"Executable not found: '{coder_cmd}'. Ensure IDFC Coder is installed or specify --coder."
            logger.error(err)
            with agent_log_path.open("a", encoding="utf-8") as f:
                f.write(f"ERROR: {err}\n")
            return ExecutionResult(success=False, returncode=127, error=err)
        except Exception as exc:
            logger.error("Execution failed: %s", exc)
            with agent_log_path.open("a", encoding="utf-8") as f:
                f.write(f"ERROR: {exc}\n")
            return ExecutionResult(success=False, returncode=1, error=str(exc))

    elif mode == "stdin":
        try:
            result = subprocess.run(
                [coder_cmd],
                input=task_content,
                text=True,
                capture_output=True,
                cwd=repo_dir,
                check=False,
            )
            with agent_log_path.open("a", encoding="utf-8") as f:
                f.write(f"=== IDFC CODER RUN (stdin) ===\n")
                f.write(f"Time: {datetime.now(timezone.utc).isoformat()}\n")
                f.write(f"Command: {coder_cmd}\n")
                f.write(f"Cwd: {repo_dir}\n")
                f.write(f"Return code: {result.returncode}\n")
                f.write(f"STDOUT:\n{result.stdout}\n")
                f.write(f"STDERR:\n{result.stderr}\n")
                f.write("=== END IDFC CODER RUN ===\n")

            return ExecutionResult(
                success=(result.returncode == 0),
                returncode=result.returncode,
                error=result.stderr.strip() if result.returncode != 0 else None,
            )
        except FileNotFoundError:
            err = f"Executable not found: '{coder_cmd}'"
            logger.error(err)
            return ExecutionResult(success=False, returncode=127, error=err)
        except Exception as exc:
            logger.error("Execution failed: %s", exc)
            return ExecutionResult(success=False, returncode=1, error=str(exc))

    elif mode == "arg":
        try:
            result = subprocess.run(
                [coder_cmd, str(task_path.resolve())],
                text=True,
                capture_output=True,
                cwd=repo_dir,
                check=False,
            )
            with agent_log_path.open("a", encoding="utf-8") as f:
                f.write(f"=== IDFC CODER RUN (arg) ===\n")
                f.write(f"Time: {datetime.now(timezone.utc).isoformat()}\n")
                f.write(f"Command: {coder_cmd} {task_path}\n")
                f.write(f"Cwd: {repo_dir}\n")
                f.write(f"Return code: {result.returncode}\n")
                f.write(f"STDOUT:\n{result.stdout}\n")
                f.write(f"STDERR:\n{result.stderr}\n")
                f.write("=== END IDFC CODER RUN ===\n")

            return ExecutionResult(
                success=(result.returncode == 0),
                returncode=result.returncode,
                error=result.stderr.strip() if result.returncode != 0 else None,
            )
        except FileNotFoundError:
            err = f"Executable not found: '{coder_cmd}'"
            logger.error(err)
            return ExecutionResult(success=False, returncode=127, error=err)
        except Exception as exc:
            logger.error("Execution failed: %s", exc)
            return ExecutionResult(success=False, returncode=1, error=str(exc))

    else:
        err = f"Unsupported execution mode: '{mode}'. Supported modes: interactive, stdin, arg."
        logger.error(err)
        return ExecutionResult(success=False, returncode=1, error=err)
