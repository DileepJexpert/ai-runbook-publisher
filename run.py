"""CLI entry point for ai-runbook-publisher."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import click
import yaml

from collector import collect_service_facts, save_service_facts
from publisher.publisher import publish
from publisher.repository import inspect_repository
from publisher.repository_tools import RepositoryTools
from indexer.index_builder import CodeIndexBuilder
from indexer.index_store import CodeIndexStore, load_code_index
from indexer.search import CodeSearchEngine
from agent import AgentConfig, OpenAiLlmClient, RepositoryAgent


def load_config(path: str) -> dict:
    """Load YAML configuration with environment variable interpolation."""
    config_file = Path(path)
    if not config_file.is_file():
        return {}
    raw = config_file.read_text(encoding="utf-8")
    raw = re.sub(r"\$\{([^}]+)\}", lambda match: os.environ.get(match.group(1), ""), raw)
    return yaml.safe_load(raw) or {}


@click.command()
@click.option(
    "--repo",
    "repo_path",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Path to the local Java Spring Boot repository.",
)
@click.option("--service", default=None, help="Service name override (defaults to spring.application.name or folder name).")
@click.option("--environment", default="production", show_default=True, help="Target deployment environment.")
@click.option("--version", "app_version", default="latest", show_default=True, help="Application version.")
@click.option("--commit", "commit_sha", default=None, help="Git commit SHA override (defaults to HEAD).")
@click.option("--branch", default=None, help="Git branch override (defaults to current branch).")
@click.option(
    "--config",
    "config_path",
    default="config/config.yml",
    show_default=True,
    type=click.Path(dir_okay=False),
    help="Path to configuration file.",
)
@click.option("--coder", "coder_cmd", default=None, help="AI coder executable (default: idfc-coder or IDFC_CODER_CMD).")
@click.option(
    "--mode",
    type=click.Choice(["interactive", "stdin", "arg"], case_sensitive=False),
    default=None,
    help="IDFC coder execution mode (default: interactive or IDFC_CODER_MODE).",
)
@click.option("--dry-run", is_flag=True, default=False, help="Generate and validate runbook locally without publishing to Confluence.")
@click.option("--inspect-repo", is_flag=True, default=False, help="Perform safe read-only repository inspection without running AI or Confluence.")
@click.option("--collect-facts", is_flag=True, default=False, help="Run deterministic Layer 1 service fact collection without AI or Confluence.")
@click.option("--build-index", is_flag=True, default=False, help="Build deterministic Layer 2 searchable code index without AI or Confluence.")
@click.option("--search-index", "search_query", default=None, help="Search the code index with the given query string (builds index if needed).")
@click.option("--ask-repo", "ask_question", default=None, help="Ask a question about the repository using the tool-calling LLM agent.")
@click.option("--agent-debug", is_flag=True, default=False, help="Show agent tool calls during repository investigation.")
def main(
    repo_path: Path,
    service: str | None,
    environment: str,
    app_version: str,
    commit_sha: str | None,
    branch: str | None,
    config_path: str,
    coder_cmd: str | None,
    mode: str | None,
    dry_run: bool,
    inspect_repo: bool,
    collect_facts: bool,
    build_index: bool,
    search_query: str | None,
    ask_question: str | None,
    agent_debug: bool,
) -> None:
    """Generate a Production Support Runbook for a Java Spring Boot microservice using IDFC Coder or deterministic fact collection."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if ask_question:
        try:
            # Load configuration
            loaded_cfg = load_config(config_path)
            llm_cfg = loaded_cfg.get("llm", {})

            base_url = os.environ.get("LLM_BASE_URL") or llm_cfg.get("base_url")
            api_key = os.environ.get("LLM_API_KEY") or llm_cfg.get("api_key")
            model = os.environ.get("LLM_MODEL") or llm_cfg.get("model", "gpt-4o")

            if not base_url:
                raise click.ClickException(
                    "LLM_BASE_URL is not configured.\n"
                    "Please set the LLM_BASE_URL environment variable or configure it in config/config.yml\n"
                    "Note: Ensure the configured endpoint is approved by your organization for repository source code."
                )

            # Optional deterministic service facts baseline
            facts = None
            try:
                facts = collect_service_facts(
                    repo_path=str(repo_path),
                    service_name=service,
                    branch=branch,
                    commit_sha=commit_sha,
                )
            except Exception as e:
                logging.debug("Service facts collection optional fallback: %s", e)

            client = OpenAiLlmClient(base_url=base_url, api_key=api_key, model=model)
            agent_config = AgentConfig(
                base_url=base_url,
                api_key=api_key,
                model=model,
                debug=agent_debug,
            )
            agent = RepositoryAgent(
                repo_path=str(repo_path),
                client=client,
                config=agent_config,
                service_facts=facts,
            )

            click.echo(f"Question:\n{ask_question}\n")
            answer = agent.ask(ask_question)

            click.echo(f"Answer:\n{answer.answer}\n")
            if answer.evidence:
                click.echo("Evidence:")
                for ev in answer.evidence:
                    click.echo(f"- {ev.format()}")
                click.echo("")
            click.echo(f"Tool calls: {answer.tool_calls}")
            click.echo(f"Status: {answer.status}")
            return
        except Exception as exc:
            logging.error("Repository agent execution failed: %s", exc)
            raise click.ClickException(str(exc)) from exc

    if collect_facts:
        try:
            facts = collect_service_facts(
                repo_path=str(repo_path),
                service_name=service,
                branch=branch,
                commit_sha=commit_sha,
            )
            saved_path = save_service_facts(facts)

            click.echo("Service Fact Collection")
            click.echo("-----------------------")
            click.echo(f"Service: {facts.service.name}")
            click.echo(f"Commit: {facts.service.commit_sha}")
            click.echo(f"Scan: {facts.scan.status}")
            click.echo("")
            click.echo(f"APIs: {len(facts.apis)}")
            click.echo(f"Validation rules: {len(facts.validation_rules)}")
            click.echo(f"Kafka consumers: {len(facts.kafka.consumers)}")
            click.echo(f"Kafka producers: {len(facts.kafka.producers)}")
            click.echo(f"Config entries: {len(facts.configuration)}")
            click.echo(f"Database tables: {len(facts.datastores.database_tables)}")
            click.echo(f"Downstream clients: {len(facts.downstream_dependencies)}")
            click.echo(f"Custom metrics: {len(facts.health_and_metrics.custom_metrics)}")
            click.echo("")
            click.echo("Output:")
            click.echo(str(saved_path))
            return
        except Exception as exc:
            logging.error("Deterministic fact collection failed: %s", exc)
            raise click.ClickException(str(exc)) from exc

    if build_index or search_query:
        try:
            repo_info = inspect_repository(str(repo_path))
            svc_name = service or repo_info.service_name
            sha = commit_sha or repo_info.commit_sha

            def _get_or_build_index() -> "CodeIndexStore":
                existing = load_code_index(svc_name, sha)
                if existing is not None:
                    click.echo(f"Loaded existing index for {svc_name}@{sha[:12]}")
                    return existing
                builder = CodeIndexBuilder()
                store = builder.build(repo_path=str(repo_path), service_name=svc_name, commit_sha=sha)
                store.persist()
                return store

            if build_index:
                store = _get_or_build_index()
                m = store.manifest

                click.echo("Code Index Build")
                click.echo("----------------")
                click.echo(f"Service: {m.service_name}")
                click.echo(f"Commit: {m.commit_sha}")
                click.echo(f"Files indexed: {m.file_count}")
                click.echo(f"Chunks: {m.chunk_count}")
                click.echo(f"Production chunks: {m.production_chunk_count}")
                click.echo(f"Test chunks: {m.test_chunk_count}")
                click.echo("")
                click.echo(f"Java methods: {m.chunk_types.get('JAVA_METHOD', 0)}")
                click.echo(f"Enums: {m.chunk_types.get('JAVA_ENUM', 0)}")
                click.echo(f"Config sections: {m.chunk_types.get('CONFIG_SECTION', 0) + m.chunk_types.get('PROPERTIES_SECTION', 0)}")
                click.echo(f"SQL chunks: {m.chunk_types.get('SQL_STATEMENT', 0)}")
                click.echo("")
                click.echo("Index:")
                click.echo(f".runbook-index/{m.service_name}/{m.commit_sha}/")
                return

            if search_query:
                store = _get_or_build_index()
                engine = CodeSearchEngine(store)
                hits = engine.search(search_query, top_k=10)

                click.echo(f"Search: {search_query}")
                click.echo("")
                if not hits:
                    click.echo("No results found.")
                    return
                for rank, hit in enumerate(hits, start=1):
                    c = hit.chunk
                    sym = c.method_name or c.class_name or c.symbol_name or ""
                    click.echo(f"{rank}. {c.file_path}:{c.start_line}-{c.end_line}")
                    if sym:
                        click.echo(f"   Symbol: {sym}")
                    click.echo(f"   Type: {c.chunk_type}")
                    click.echo(f"   Score: {hit.score:.0f}")
                    click.echo("")
                return

        except Exception as exc:
            logging.error("Index operation failed: %s", exc)
            raise click.ClickException(str(exc)) from exc

    if inspect_repo:
        try:
            info = inspect_repository(str(repo_path))
            tools = RepositoryTools(str(repo_path))
            files = tools.list_files(max_results=500)
            rest_matches = tools.search_code("@RestController")

            click.echo("Repository Inspection")
            click.echo("---------------------")
            click.echo(f"Service: {info.service_name}")
            click.echo(f"Repository: {info.path}")
            click.echo(f"Branch: {info.branch or 'detached'}")
            click.echo(f"Commit: {info.commit_sha}")
            click.echo(f"Origin: {info.origin_url or 'none'}")
            click.echo(f"Working Tree Clean: {str(info.working_tree_clean).lower()}")
            click.echo("")
            click.echo("Repository Files")
            click.echo("----------------")
            click.echo(f"Eligible text files: {len(files)}")
            click.echo("")
            click.echo("Example files:")
            for f in files[:8]:
                click.echo(f)
            if len(files) > 8:
                click.echo("...")
            click.echo("")
            click.echo("Search '@RestController':")
            click.echo(f"{len(rest_matches)} matches")
            return
        except Exception as exc:
            logging.error("Repository inspection failed: %s", exc)
            raise click.ClickException(str(exc)) from exc

    config = load_config(config_path)

    try:
        result = publish(
            repo_path=str(repo_path),
            service=service,
            environment=environment,
            version=app_version,
            commit_sha=commit_sha,
            branch=branch,
            config=config,
            dry_run=dry_run,
            coder_cmd=coder_cmd,
            mode=mode,
        )

        if result.success:
            if dry_run:
                click.echo("\n=======================================================")
                click.echo(" [SUCCESS] Runbook generated and validated successfully")
                click.echo("=======================================================")
                click.echo(f"Run folder:   {result.run_dir}")
                click.echo(f"Runbook path: {result.runbook_path}")
                click.echo("Validation:   PASS")
            else:
                click.echo("\n=======================================================")
                click.echo(f" [SUCCESS] Runbook published to Confluence ({result.action})")
                click.echo("=======================================================")
                click.echo(f"Confluence URL: {result.page_url}")
                click.echo(f"Page ID:        {result.page_id}")
                click.echo(f"Run folder:     {result.run_dir}")
        else:
            click.echo("\n=======================================================", err=True)
            click.echo(f" [FAILED] {result.error}", err=True)
            click.echo("=======================================================", err=True)
            if result.run_dir:
                click.echo(f"Run folder: {result.run_dir}", err=True)
                agent_log = result.run_dir / "agent.log"
                run_log = result.run_dir / "run.log"
                val_rep = result.run_dir / "validation-report.txt"
                if agent_log.exists():
                    click.echo(f"Agent log:  {agent_log}", err=True)
                if run_log.exists():
                    click.echo(f"Run log:    {run_log}", err=True)
                if val_rep.exists():
                    click.echo(f"Validation: {val_rep}", err=True)
            raise click.ClickException(result.error or "Runbook generation failed.")

    except click.ClickException:
        raise
    except Exception as exc:
        logging.error("Pipeline unexpected error: %s", exc)
        raise click.ClickException(str(exc)) from exc


if __name__ == "__main__":
    main()
