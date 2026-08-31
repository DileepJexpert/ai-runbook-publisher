"""CLI entry point for ai-runbook-publisher."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import click
import yaml

from collector import collect_service_facts, save_service_facts
from publisher.confluence import ConfluenceConfig, ConfluencePublisher
from publisher.engines import create_generation_engine
from publisher.html_renderer import generate_runbook_html
from publisher.publisher import publish
from publisher.repository import inspect_repository
from publisher.repository_tools import RepositoryTools
from publisher.runbook_generator import RunbookGenerator
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
@click.option(
    "--engine",
    "engine_name",
    type=click.Choice(["api", "idfc-coder", "external-agent"], case_sensitive=False),
    default=None,
    help="Generation engine (default: api or config generation.default_engine).",
)
@click.option("--output-suffix", default=None, help="Optional suffix for runbook filename (e.g. --output-suffix api -> RUNBOOK-api.md).")
@click.option("--dry-run", is_flag=True, default=False, help="Generate and validate runbook locally without publishing to Confluence.")
@click.option("--inspect-repo", is_flag=True, default=False, help="Perform safe read-only repository inspection without running AI or Confluence.")
@click.option("--collect-facts", is_flag=True, default=False, help="Run deterministic Layer 1 service fact collection without AI or Confluence.")
@click.option("--build-index", is_flag=True, default=False, help="Build deterministic Layer 2 searchable code index without AI or Confluence.")
@click.option("--search-index", "search_query", default=None, help="Search the code index with the given query string (builds index if needed).")
@click.option("--ask-repo", "ask_question", default=None, help="Ask a question about the repository using the tool-calling LLM agent.")
@click.option("--generate-runbook", is_flag=True, default=False, help="Generate a Production Support Runbook directly using the selected generation engine.")
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
    engine_name: str | None,
    output_suffix: str | None,
    dry_run: bool,
    inspect_repo: bool,
    collect_facts: bool,
    build_index: bool,
    search_query: str | None,
    ask_question: str | None,
    generate_runbook: bool,
    agent_debug: bool,
) -> None:
    """Generate a Production Support Runbook for a Java Spring Boot microservice using IDFC Coder or deterministic fact collection."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if generate_runbook:
        try:
            loaded_cfg = load_config(config_path)
            llm_cfg = loaded_cfg.get("llm", {})
            gen_cfg = loaded_cfg.get("generation", {})
            idfc_cfg = loaded_cfg.get("idfc_coder", {})

            active_engine_name = engine_name or gen_cfg.get("default_engine", "api")
            active_coder_cmd = coder_cmd or idfc_cfg.get("command")
            active_coder_mode = mode or idfc_cfg.get("mode")

            engine_instance = create_generation_engine(
                name=active_engine_name,
                coder_cmd=active_coder_cmd,
                coder_mode=active_coder_mode,
                llm_config=llm_cfg,
            )

            generator = RunbookGenerator(engine=engine_instance)
            result = generator.generate(
                repo_path=str(repo_path),
                environment=environment,
                version=app_version,
                service_name_override=service,
                commit_sha_override=commit_sha,
                branch_override=branch,
                output_suffix=output_suffix,
                agent_debug=agent_debug,
            )

            if result.validation_status == "DISCOVERY_PREPARED":
                commit_short = result.commit_sha[:16]
                click.echo("Production Support Runbook")
                click.echo("--------------------------")
                click.echo("")
                click.echo(f"Service: {result.service_name}")
                click.echo(f"Engine: {result.engine}")
                click.echo("")
                click.echo("Discovery:")
                click.echo("PREPARED")
                click.echo("")
                click.echo("Task:")
                click.echo(f"output/{result.service_name}/{commit_short}/DISCOVERY_TASK.md")
                click.echo("")
                click.echo("Expected artifact:")
                click.echo(f"output/{result.service_name}/{commit_short}/REPOSITORY_FINDINGS.md")
                click.echo("")
                click.echo("Runbook:")
                click.echo("WAITING_FOR_DISCOVERY")
                click.echo("")
                click.echo("Confluence:")
                click.echo("NOT PUBLISHED (dry-run)")
                return

            if result.validation_status == "RUNBOOK_PREPARED":
                commit_short = result.commit_sha[:16]
                click.echo("Production Support Runbook")
                click.echo("--------------------------")
                click.echo("")
                click.echo(f"Service: {result.service_name}")
                click.echo(f"Engine: {result.engine}")
                click.echo("")
                click.echo("Discovery:")
                click.echo("COMPLETE")
                click.echo("")
                click.echo("Runbook:")
                click.echo("PREPARED")
                click.echo("")
                click.echo("Task:")
                click.echo(f"output/{result.service_name}/{commit_short}/RUNBOOK_TASK.md")
                click.echo("")
                click.echo("Expected artifact:")
                click.echo(f"output/{result.service_name}/{commit_short}/RUNBOOK.md")
                click.echo("")
                click.echo("Confluence:")
                click.echo("NOT PUBLISHED (dry-run)")
                return

            # Phase 5: Deterministic HTML Generation and Confluence Publication after Validation
            html_path = None
            html_error = None
            confluence_config = ConfluenceConfig.from_dict(loaded_cfg.get("confluence", {}))
            confluence_res = None

            if result.validation_status == "PASSED":
                repo_info = inspect_repository(str(repo_path))
                commit_short = result.commit_sha[:16]
                output_dir = Path("output") / result.service_name / commit_short

                # 1. Deterministic HTML generation
                try:
                    html_path = generate_runbook_html(
                        runbook_path=result.runbook_path,
                        output_dir=output_dir,
                        repo_name=repo_info.repo_name,
                        service_name=result.service_name,
                    )
                except Exception as exc:
                    html_error = str(exc)
                    logging.error("Failed to generate HTML runbook: %s", exc)

                # 2. Confluence publishing (if enabled)
                confluence_pub = ConfluencePublisher(config=confluence_config)
                confluence_res = confluence_pub.publish_runbook(
                    runbook_path=result.runbook_path,
                    repo_info=repo_info,
                    validation_status=result.validation_status,
                    dry_run=dry_run,
                )

                # 3. Update generation summary with HTML and Confluence info
                summary_file = output_dir / "generation-summary.json"
                if summary_file.exists():
                    try:
                        sum_data = json.loads(summary_file.read_text(encoding="utf-8"))
                        if html_path:
                            sum_data["html"] = {"generated": True, "path": str(html_path)}
                        elif html_error:
                            sum_data["html"] = {"generated": False, "error": html_error}
                        else:
                            sum_data["html"] = {"generated": False, "reason": "Validation not passed"}

                        sum_data["confluence"] = confluence_res.to_summary_dict(enabled=confluence_config.enabled)
                        summary_file.write_text(json.dumps(sum_data, indent=2), encoding="utf-8")
                    except Exception as exc:
                        logging.debug("Could not update generation summary: %s", exc)

            click.echo("Production Support Runbook Generation")
            click.echo("-------------------------------------")
            click.echo("")
            click.echo(f"Service: {result.service_name}")
            click.echo(f"Commit: {result.commit_sha}")
            click.echo(f"Environment: {result.environment}")
            click.echo("")
            click.echo("Deterministic facts loaded: YES")
            click.echo(f"Generation engine: {result.engine}")
            click.echo(f"Tool calls: {result.tool_calls}")
            click.echo("")
            click.echo("Discovery:")
            click.echo(result.discovery_status)
            if result.findings_path:
                click.echo(f"Findings: {result.findings_path}")
            click.echo("")
            click.echo("Runbook:")
            click.echo(result.runbook_path or "(Not yet generated)")
            click.echo("")
            click.echo(f"Validation: {result.validation_status}")
            if result.validation_errors:
                click.echo("Validation errors:")
                for err in result.validation_errors:
                    click.echo(f"  - {err}")
            click.echo("")
            click.echo("HTML:")
            if result.validation_status == "PASSED":
                if html_path:
                    click.echo("GENERATED")
                    click.echo(str(html_path))
                else:
                    click.echo("FAILED")
                    click.echo(html_error or "Unknown error during HTML rendering")
            else:
                click.echo("NOT GENERATED (validation failed)")
            click.echo("")
            click.echo("Evidence:")
            click.echo(result.evidence_path or "None")
            click.echo("")
            click.echo("Confluence:")
            if confluence_res:
                if confluence_res.action == "DRY_RUN":
                    click.echo("DRY RUN")
                    click.echo(f"Action: {confluence_res.planned_action}")
                    click.echo(f"Parent Page ID: {confluence_res.parent_page_id}")
                    click.echo(f"Page title: {confluence_res.page_title}")
                    if confluence_res.page_id:
                        click.echo(f"Existing Page ID: {confluence_res.page_id}")
                elif confluence_res.action in ("CREATED", "UPDATED"):
                    click.echo(f"PUBLISHED ({confluence_res.action})")
                    click.echo(f"Page ID: {confluence_res.page_id}")
                    click.echo(f"Page title: {confluence_res.page_title}")
                    click.echo(f"Parent Page ID: {confluence_res.parent_page_id}")
                    if confluence_res.version:
                        click.echo(f"Version: {confluence_res.version}")
                    if confluence_res.page_url:
                        click.echo(f"URL: {confluence_res.page_url}")
                elif confluence_res.action == "FAILED":
                    click.echo("FAILED")
                    click.echo(f"Reason: {confluence_res.error}")
                elif confluence_res.action == "SKIPPED":
                    if not confluence_config.enabled:
                        click.echo("NOT PUBLISHED (disabled)")
                    else:
                        click.echo(f"SKIPPED ({confluence_res.error or 'not published'})")
                else:
                    click.echo("NOT PUBLISHED (dry-run)")
            else:
                if not confluence_config.enabled:
                    click.echo("NOT PUBLISHED (disabled)")
                else:
                    click.echo("NOT PUBLISHED (dry-run)")
            return
        except Exception as exc:
            logging.error("Runbook generation failed: %s", exc)
            raise click.ClickException(str(exc)) from exc

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
