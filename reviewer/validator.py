from .models import Finding, ReviewResult
HIGH = {"BLOCKER", "MAJOR"}
def validate(result: ReviewResult) -> ReviewResult:
    valid, existing = [], list(result.pre_existing_observations)
    for finding in result.findings:
        if not finding.introduced_by_pr:
            existing.append(finding); continue
        if not finding.evidence: continue
        if finding.severity.upper() in HIGH and (finding.verification_status not in {"CONFIRMED", "DOWNGRADED"} or not finding.execution_path or not finding.counter_evidence_checked or not finding.counter_evidence_conclusion): continue
        valid.append(finding)
    result.findings, result.pre_existing_observations = valid, existing
    return result
