from __future__ import annotations
import json, subprocess
from abc import ABC, abstractmethod
from .models import Finding, ReviewResult, ReviewMode
class ReviewEngine(ABC):
    @abstractmethod
    def review(self, prompt: str, mode: ReviewMode, worktree: str) -> ReviewResult: ...
class IdfcCoderEngine(ReviewEngine):
    def __init__(self, executable: str = "idfc-coder", input_mode: str = "prompt", timeout: int = 1800): self.executable, self.input_mode, self.timeout = executable, input_mode, timeout
    def review(self, prompt, mode, worktree):
        if self.input_mode not in {"prompt", "stdin", "interactive"}: raise ValueError("coder mode must be prompt, stdin, or interactive")
        args = [self.executable] + (["-p", prompt] if self.input_mode == "prompt" else [])
        result = subprocess.run(args, input=prompt if self.input_mode == "stdin" else None, text=True, capture_output=True, cwd=worktree, check=True, timeout=self.timeout)
        try: data = json.loads(result.stdout)
        except json.JSONDecodeError as exc: raise RuntimeError(f"IDFC Coder returned malformed structured review output: {exc}") from exc
        findings = [Finding(**item) for item in data.get("findings", [])]
        from .models import ReviewOutcome
        if not {"outcome","summary","findings","pre_existing_observations"}.issubset(data): raise RuntimeError("Structured review output is missing required fields")
        return ReviewResult(mode=mode, findings=findings, summary=data["summary"], outcome=ReviewOutcome(data["outcome"]), pre_existing_observations=[Finding(**item) for item in data["pre_existing_observations"]], raw_output=result.stdout)
class FakeReviewEngine(ReviewEngine):
    def __init__(self, results=None): self.results = results or {}; self.calls = []
    def review(self, prompt, mode, worktree): self.calls.append((mode, worktree)); return self.results.get(mode, ReviewResult(mode=mode, summary=f"{mode.value} complete"))
