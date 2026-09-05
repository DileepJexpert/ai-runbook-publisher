from __future__ import annotations
import html, json
from pathlib import Path
from .models import ReviewResult, Snapshot
def render(result: ReviewResult, snapshot: Snapshot, output: Path, changed_files: list[str] | None = None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    def finding(f):
        evidence = "<br>".join(html.escape(f"{e.get('file','')}:{e.get('line','')}") for e in f.evidence)
        return f"<section><h3>{html.escape(f.severity)} — {html.escape(f.title)}</h3><p>Category: {html.escape(f.category)} · Introduced by PR: {f.introduced_by_pr}</p><p><b>Evidence:</b> {evidence}</p><p><b>Failure:</b> {html.escape(f.failure_scenario)}</p><p><b>Impact:</b> {html.escape(f.impact)}</p><p><b>Execution:</b> {html.escape(f.execution_path)}</p><p><b>Counter-evidence:</b> {html.escape('; '.join(f.counter_evidence_checked))}<br>{html.escape(f.counter_evidence_conclusion)}</p><p><b>Recommendation:</b> {html.escape(f.recommendation)}</p><p>Confidence: {html.escape(f.confidence)} · Verification: {html.escape(f.verification_status)}</p></section>"
    deterministic=[f for f in result.findings if f.source=='deterministic']; ai=[f for f in result.findings if f.source!='deterministic']
    markdown = ["# PR Review", f"**Outcome:** {result.outcome.value}", "## Deterministic Checks"] + [f"### {f.severity}: {f.title}\nSource: deterministic\nEvidence: {f.evidence}\n\n{f.recommendation}" for f in deterministic] + ["## AI Findings"] + [f"### {f.severity}: {f.title}\nSource: ai\nEvidence: {f.evidence}\n\n{f.recommendation}" for f in ai]
    if result.pre_existing_observations: markdown += ["## Pre-existing Architectural Observations"] + [f"### {f.title}\nIntroduced by PR: NO" for f in result.pre_existing_observations]
    (output / "review.md").write_text("\n\n".join(markdown) + "\n", encoding="utf-8")
    rows = "".join(finding(f) for f in ai); deterministic_rows = "".join(finding(f) for f in deterministic); existing = "".join(finding(f) for f in result.pre_existing_observations)
    changed='<br>'.join(html.escape(x) for x in (changed_files or []))
    page = f"<!doctype html><html><head><meta charset='utf-8'><style>body{{font:16px Arial;margin:40px;max-width:1000px}}section{{border:1px solid #ddd;padding:14px;margin:12px 0}}h1,h2{{color:#12355b}}</style></head><body><h1>PR Review</h1><p>Repository: {html.escape(snapshot.repository)}<br>Source: {html.escape(snapshot.source)} ({snapshot.source_sha})<br>Target: {html.escape(snapshot.target)} ({snapshot.target_sha})<br>Merge base: {snapshot.merge_base}<br>Mode: {result.mode.value}<br>Outcome: {result.outcome.value}<br>Summary: {html.escape(result.summary)}</p><h2>Changed Files</h2><p>{changed}</p><h2>Deterministic Checks</h2>{deterministic_rows}<h2>AI Findings</h2>{rows}<h2>Pre-existing Architectural Observations</h2>{existing}</body></html>"
    (output / "review.html").write_text(page, encoding="utf-8")
    (output / "review-summary.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
