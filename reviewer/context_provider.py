"""Fast deterministic first-pass context; no runbook dependencies."""
from __future__ import annotations
import re
from pathlib import Path
from .git_snapshot import is_excluded

class ContextProvider:
    def build(self, worktree: str, changed_files: list[str], depth: str) -> str:
        root=Path(worktree); limit={"fast":8,"standard":20,"deep":60}[depth]; selected=[]
        stems={Path(item.split('\t')[-1]).stem.replace('Service','').replace('Controller','').replace('Repository','') for item in changed_files}
        for path in root.rglob('*'):
            if len(selected)>=limit or not path.is_file(): continue
            rel=path.relative_to(root).as_posix()
            if is_excluded(rel) or path.suffix not in {'.java','.kt','.yml','.yaml','.properties','.xml','.sql'}: continue
            if rel in {x.split('\t')[-1] for x in changed_files} or any(stem and stem.lower() in path.name.lower() for stem in stems):
                selected.append(rel)
        return "Initial deterministic impact context (inspect these first):\n" + "\n".join(f"- {p}" for p in selected)
