from __future__ import annotations
import json, shutil, subprocess, tempfile
from pathlib import Path
from .models import Snapshot

EXCLUDED_PARTS = {".git", ".gradle", "build", "target", ".idea", ".vscode", "reviews", "output", "logs", "node_modules", "coverage"}
def is_excluded(path: str) -> bool:
    parts = Path(path).parts
    return any(part in EXCLUDED_PARTS for part in parts) or path.endswith(".log") or Path(path).name == ".DS_Store"

class GitSnapshot:
    def __init__(self, repo: str | Path):
        self.repo = Path(repo).resolve(); self.worktree: Path | None = None
    def _git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, text=True, capture_output=True).stdout
    def resolve(self, ref: str) -> str:
        for candidate in (f"origin/{ref}", ref):
            try: return self._git("rev-parse", "--verify", candidate).strip()
            except subprocess.CalledProcessError: pass
        raise ValueError(f"Cannot resolve Git ref: {ref}")
    def freeze(self, source: str, target: str) -> Snapshot:
        source_sha, target_sha = self.resolve(source), self.resolve(target)
        merge_base = self._git("merge-base", target_sha, source_sha).strip()
        # Keep temporary worktrees beside the repository: this is portable and avoids
        # host-specific temp-directory permissions in restricted CI runners.
        self.worktree = Path(tempfile.mkdtemp(prefix=".ai-pr-review-worktree-", dir=str(self.repo.parent))); shutil.rmtree(self.worktree)
        self._git("worktree", "add", "--detach", str(self.worktree), source_sha)
        return Snapshot(str(self.repo), source, target, source_sha, target_sha, merge_base, str(self.worktree))
    def write_evidence(self, snapshot: Snapshot, output: Path) -> None:
        output.mkdir(parents=True, exist_ok=True); rng = f"{snapshot.merge_base}...{snapshot.source_sha}"
        (output / "changed-files.txt").write_text("\n".join(x for x in self._git("diff", "--name-status", rng).splitlines() if not is_excluded(x.split("\t")[-1])) + "\n", encoding="utf-8")
        for filename, args in {"diff-stat.txt": ("diff", "--stat", rng), "pr.diff": ("diff", "--find-renames", "--find-copies", rng), "commits.txt": ("log", "--oneline", f"{snapshot.merge_base}..{snapshot.source_sha}")}.items():
            (output / filename).write_text(self._git(*args), encoding="utf-8")
        (output / "metadata.json").write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
    def cleanup(self) -> None:
        if self.worktree and self.worktree.exists():
            subprocess.run(["git", "-C", str(self.repo), "worktree", "remove", "--force", str(self.worktree)], check=False, capture_output=True, text=True)
            self.worktree = None
