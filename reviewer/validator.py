from pathlib import Path
from .models import Finding, ReviewResult
from .git_snapshot import is_excluded
HIGH = {"BLOCKER", "MAJOR"}
def validate(result: ReviewResult, worktree: str | None = None, changed_files: set[str] | None = None) -> ReviewResult:
    valid, existing = [], list(result.pre_existing_observations)
    for finding in result.findings:
        if finding.verification_status == "REJECTED": continue
        if not finding.introduced_by_pr:
            existing.append(finding); continue
        if not finding.evidence: continue
        bad_evidence = False
        for evidence in finding.evidence:
            path = str(evidence.get("file", "")); full = (Path(worktree) / path).resolve() if worktree else None
            if is_excluded(path) or (worktree and (not full.is_file() or Path(worktree).resolve() not in full.parents)):
                bad_evidence = True; break
            if full and evidence.get("line") and not 1 <= int(evidence["line"]) <= len(full.read_text(encoding="utf-8", errors="replace").splitlines()): bad_evidence = True; break
        if bad_evidence: continue
        if finding.introduced_by_pr and changed_files and not any(str(e.get("file")) in changed_files for e in finding.evidence) and not finding.execution_path: continue
        if finding.severity.upper() in HIGH and (finding.verification_status != "CONFIRMED" or not finding.execution_path or not finding.counter_evidence_checked or not finding.counter_evidence_conclusion): continue
        valid.append(finding)
    result.findings, result.pre_existing_observations = valid, existing
    return result
