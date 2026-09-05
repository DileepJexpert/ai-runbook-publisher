from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from .engine import ReviewEngine
from .git_snapshot import GitSnapshot
from .models import ReviewMode, ReviewResult
from .prompt_builder import build_prompt
from .report_renderer import render
from .validator import validate
from .performance import Performance
from .context_provider import ContextProvider
from .deterministic_checks import run_checks
class ReviewOrchestrator:
    def __init__(self, engine: ReviewEngine, rules_dir: Path | None = None): self.engine=engine; self.rules_dir=rules_dir or Path(__file__).parent.parent / "review_rules"
    def run(self, repo: str, base: str, head: str, mode: ReviewMode, output_root: str | Path = "output/reviews", fetch: bool = True, depth: str = "standard") -> dict[ReviewMode, ReviewResult]:
        if depth not in {"fast","standard","deep"}: raise ValueError("depth must be fast, standard, or deep")
        perf=Performance(); snapper=GitSnapshot(repo); stop=perf.measure("snapshot_seconds"); snapshot=snapper.freeze(head, base, fetch=fetch); stop()
        service=Path(repo).resolve().name; review_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        root=Path(output_root)/service/review_id
        try:
            stop=perf.measure("evidence_seconds"); snapper.write_evidence(snapshot, root); stop()
            stop=perf.measure("deterministic_checks_seconds"); deterministic, java_count=run_checks(snapshot.worktree, root); stop()
            changed_list=(root/'changed-files.txt').read_text(encoding='utf-8').splitlines(); stop=perf.measure("context_build_seconds"); context=ContextProvider().build(snapshot.worktree, changed_list, depth); stop()
            modes=[ReviewMode.BASELINE, ReviewMode.GUIDED] if mode is ReviewMode.BOTH else [mode]
            results={}
            for current in modes:
                target=root/current.value if mode is ReviewMode.BOTH else root; target.mkdir(parents=True, exist_ok=True)
                before=snapper._git("-C", snapshot.worktree, "status", "--porcelain")
                prompt=build_prompt(snapshot,current,root,self.rules_dir,context,depth); changed={line.split('\t')[-1] for line in changed_list}; stop=perf.measure(f"ai_review_{current.value}_seconds"); result=validate(self.engine.review(prompt,current,snapshot.worktree), snapshot.worktree, changed); stop(); after=snapper._git("-C", snapshot.worktree, "status", "--porcelain")
                if after != before: raise RuntimeError("Reviewer engine modified the frozen worktree; refusing the review result")
                result.findings = deterministic + result.findings
                render(result,snapshot,target,(root/'changed-files.txt').read_text(encoding='utf-8').splitlines()); results[current]=result
            perf.write(root, files_changed=len(changed_list), files_in_initial_context=context.count('\n'), deterministic_findings=len(deterministic), java_files_checked=java_count); return results
        finally: snapper.cleanup()
