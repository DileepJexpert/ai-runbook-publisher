from __future__ import annotations
from pathlib import Path
from .models import ReviewMode, Snapshot
ROOT = Path(__file__).parent
def build_prompt(snapshot: Snapshot, mode: ReviewMode, evidence_dir: Path, rules_dir: Path, impact_context: str = "", depth: str = "standard") -> str:
    neutral = (ROOT / "prompts" / "neutral-review.md").read_text(encoding="utf-8")
    contract = (ROOT / "prompts" / "output-contract.md").read_text(encoding="utf-8")
    verification = (ROOT / "prompts" / "verification.md").read_text(encoding="utf-8")
    rules = "" if mode is ReviewMode.BASELINE else "\n\n".join(p.read_text(encoding="utf-8") for p in sorted(rules_dir.glob("*.md")))
    budget={"fast":"Inspect changed files and immediate dependencies only; stop unless clear high-risk evidence appears.","standard":"Start with impact context. Limit initial investigation to about 15 files; expand only to verify a credible BLOCKER/MAJOR candidate.","deep":"Use broad repository investigation only where evidence requires it."}[depth]
    return f"{neutral}\n\n{verification}\n\nReview depth: {depth}. {budget}\n{impact_context}\n\nFrozen source SHA: {snapshot.source_sha}\nTarget SHA: {snapshot.target_sha}\nMerge base: {snapshot.merge_base}\nEvidence directory: {evidence_dir}\nWorktree: {snapshot.worktree}\n\n{rules}\n\n{contract}"
