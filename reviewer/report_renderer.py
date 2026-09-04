from __future__ import annotations
import html, json
from pathlib import Path
from .models import ReviewResult, Snapshot
def render(result: ReviewResult, snapshot: Snapshot, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    def finding(f):
        evidence = "<br>".join(html.escape(f"{e.get('file','')}:{e.get('line','')}") for e in f.evidence)
        return f"<section><h3>{html.escape(f.severity)} — {html.escape(f.title)}</h3><p><b>Evidence:</b> {evidence}</p><p>{html.escape(f.impact)}</p><p><b>Recommendation:</b> {html.escape(f.recommendation)}</p><p>Confidence: {html.escape(f.confidence)} · Verification: {html.escape(f.verification_status)}</p></section>"
    markdown = ["# PR Review", f"**Outcome:** {result.summary}", "## Findings"] + [f"### {f.severity}: {f.title}\nEvidence: {f.evidence}\n\n{f.recommendation}" for f in result.findings]
    if result.pre_existing_observations: markdown += ["## Pre-existing Architectural Observations"] + [f"### {f.title}\nIntroduced by PR: NO" for f in result.pre_existing_observations]
    (output / "review.md").write_text("\n\n".join(markdown) + "\n", encoding="utf-8")
    rows = "".join(finding(f) for f in result.findings); existing = "".join(finding(f) for f in result.pre_existing_observations)
    page = f"<!doctype html><html><head><meta charset='utf-8'><style>body{{font:16px Arial;margin:40px;max-width:1000px}}section{{border:1px solid #ddd;padding:14px;margin:12px 0}}h1,h2{{color:#12355b}}</style></head><body><h1>PR Review</h1><p>Repository: {html.escape(snapshot.repository)}<br>Source: {html.escape(snapshot.source)} ({snapshot.source_sha})<br>Target: {html.escape(snapshot.target)} ({snapshot.target_sha})<br>Merge base: {snapshot.merge_base}<br>Mode: {result.mode.value}<br>Outcome: {html.escape(result.summary)}</p><h2>Findings</h2>{rows}<h2>Pre-existing Architectural Observations</h2>{existing}</body></html>"
    (output / "review.html").write_text(page, encoding="utf-8")
    (output / "review-summary.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
