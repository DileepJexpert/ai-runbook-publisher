from __future__ import annotations
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

class ReviewMode(str, Enum):
    BASELINE = "baseline"
    GUIDED = "guided"
    BOTH = "both"

@dataclass(frozen=True)
class Snapshot:
    repository: str; source: str; target: str; source_sha: str; target_sha: str; merge_base: str; worktree: str
    def to_dict(self): return asdict(self)

@dataclass
class Finding:
    id: str; title: str; severity: str; evidence: list[dict[str, Any]] = field(default_factory=list)
    introduced_by_pr: bool = True; verification_status: str = "UNVERIFIED"; execution_path: str = ""
    counter_evidence_checked: list[str] = field(default_factory=list); counter_evidence_conclusion: str = ""
    impact: str = ""; recommendation: str = ""; confidence: str = "MEDIUM"; failure_scenario: str = ""
    def to_dict(self): return asdict(self)

@dataclass
class ReviewResult:
    mode: ReviewMode; findings: list[Finding] = field(default_factory=list); summary: str = ""
    pre_existing_observations: list[Finding] = field(default_factory=list); raw_output: str = ""
    def to_dict(self): return {"mode": self.mode.value, "summary": self.summary, "findings": [x.to_dict() for x in self.findings], "pre_existing_observations": [x.to_dict() for x in self.pre_existing_observations]}
