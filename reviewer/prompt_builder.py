from __future__ import annotations
from pathlib import Path
from .models import ReviewMode, Snapshot
ROOT = Path(__file__).parent
def build_prompt(snapshot: Snapshot, mode: ReviewMode, evidence_dir: Path, rules_dir: Path) -> str:
    neutral = (ROOT / "prompts" / "neutral-review.md").read_text(encoding="utf-8")
    contract = (ROOT / "prompts" / "output-contract.md").read_text(encoding="utf-8")
    verification = (ROOT / "prompts" / "verification.md").read_text(encoding="utf-8")
    rules = "" if mode is ReviewMode.BASELINE else "\n\n".join(p.read_text(encoding="utf-8") for p in sorted(rules_dir.glob("*.md")))
    return f"{neutral}\n\n{verification}\n\nFrozen source SHA: {snapshot.source_sha}\nTarget SHA: {snapshot.target_sha}\nMerge base: {snapshot.merge_base}\nEvidence directory: {evidence_dir}\nWorktree: {snapshot.worktree}\n\n{rules}\n\n{contract}"
