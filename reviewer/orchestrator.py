from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from .engine import ReviewEngine
from .git_snapshot import GitSnapshot
from .models import ReviewMode, ReviewResult
from .prompt_builder import build_prompt
from .report_renderer import render
from .validator import validate
class ReviewOrchestrator:
    def __init__(self, engine: ReviewEngine, rules_dir: Path | None = None): self.engine=engine; self.rules_dir=rules_dir or Path(__file__).parent.parent / "review_rules"
    def run(self, repo: str, base: str, head: str, mode: ReviewMode, output_root: str | Path = "output/reviews", fetch: bool = True) -> dict[ReviewMode, ReviewResult]:
        snapper=GitSnapshot(repo); snapshot=snapper.freeze(head, base, fetch=fetch)
        service=Path(repo).resolve().name; review_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        root=Path(output_root)/service/review_id
        try:
            snapper.write_evidence(snapshot, root)
            modes=[ReviewMode.BASELINE, ReviewMode.GUIDED] if mode is ReviewMode.BOTH else [mode]
            results={}
            for current in modes:
                target=root/current.value if mode is ReviewMode.BOTH else root; target.mkdir(parents=True, exist_ok=True)
                before=snapper._git("-C", snapshot.worktree, "status", "--porcelain")
                prompt=build_prompt(snapshot,current,root,self.rules_dir); changed={line.split('\t')[-1] for line in (root/'changed-files.txt').read_text(encoding='utf-8').splitlines()}; result=validate(self.engine.review(prompt,current,snapshot.worktree), snapshot.worktree, changed); after=snapper._git("-C", snapshot.worktree, "status", "--porcelain")
                if after != before: raise RuntimeError("Reviewer engine modified the frozen worktree; refusing the review result")
                render(result,snapshot,target,(root/'changed-files.txt').read_text(encoding='utf-8').splitlines()); results[current]=result
            return results
        finally: snapper.cleanup()
