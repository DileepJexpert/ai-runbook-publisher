from __future__ import annotations
import json, subprocess
from abc import ABC, abstractmethod
from .models import Finding, ReviewResult, ReviewMode
class ReviewEngine(ABC):
    @abstractmethod
    def review(self, prompt: str, mode: ReviewMode, worktree: str) -> ReviewResult: ...
class IdfcCoderEngine(ReviewEngine):
    def __init__(self, executable: str = "idfc-coder", input_mode: str = "stdin"): self.executable, self.input_mode = executable, input_mode
    def review(self, prompt, mode, worktree):
        args = [self.executable] + ([prompt] if self.input_mode == "arg" else [])
        result = subprocess.run(args, input=prompt if self.input_mode == "stdin" else None, text=True, capture_output=True, cwd=worktree, check=True)
        try: data = json.loads(result.stdout)
        except json.JSONDecodeError: return ReviewResult(mode=mode, summary=result.stdout.strip(), raw_output=result.stdout)
        findings = [Finding(**item) for item in data.get("findings", [])]
        return ReviewResult(mode=mode, findings=findings, summary=data.get("summary", ""), raw_output=result.stdout)
class FakeReviewEngine(ReviewEngine):
    def __init__(self, results=None): self.results = results or {}; self.calls = []
    def review(self, prompt, mode, worktree): self.calls.append((mode, worktree)); return self.results.get(mode, ReviewResult(mode=mode, summary=f"{mode.value} complete"))
