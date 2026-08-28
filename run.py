"""CLI entry point for ai-runbook-publisher."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml

from publisher.publisher import publish


def load_config(path: str) -> dict:
    raw = Path(path).read_text(encoding="utf-8")
    raw = re.sub(r"\$\{([^}]+)\}", lambda match: os.environ.get(match.group(1), ""), raw)
    return yaml.safe_load(raw) or {}


@click.command()
@click.option("--repo", "repo_path", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path), help="Path to the Java Spring Boot repository.")
@click.option("--service", required=True, help="Service name used in the Confluence page title.")
@click.option("--environment", required=True, help="Target environment.")
@click.option("--version", required=True, help="Application version.")
@click.option("--commit", "commit_sha", required=True, help="Git commit SHA.")
@click.option("--branch", required=True, help="Git branch.")
@click.option("--config", "config_path", default="config/config.yml", show_default=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True, help="Generate and print the runbook without publishing it.")
def main(repo_path: Path, service: str, environment: str, version: str, commit_sha: str, branch: str, config_path: str, dry_run: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        result = publish(str(repo_path), service, {"service_name": service, "environment": environment, "app_version": version, "commit_sha": commit_sha, "branch": branch, "timestamp": datetime.now(timezone.utc).isoformat()}, load_config(config_path), dry_run=dry_run)
        if dry_run:
            click.echo(result.runbook)
        elif result.success:
            click.echo(result.page_url)
        else:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            fallback = Path.cwd() / f"runbook-{service}-{timestamp}.md"
            fallback.write_text(result.runbook, encoding="utf-8")
            logging.error("File save fallback triggered: %s", fallback)
            raise click.ClickException(f"Confluence publish failed; saved runbook to {fallback}: {result.error}")
    except click.ClickException:
        raise
    except Exception as exc:
        logging.error("Runbook pipeline failed: %s", exc)
        raise click.ClickException(str(exc)) from exc


if __name__ == "__main__":
    main()
