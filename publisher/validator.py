"""Lightweight validation for generated Production Support Runbooks."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .repository import RepositoryInfo

LOGGER = logging.getLogger(__name__)

# Patterns that indicate unsafe operations if recommended to Support
UNSAFE_ACTION_PATTERNS = [
    (r"\b(?:replay|re-play|republish|re-send|resend)\s+(?:the\s+)?(?:kafka|topic|events?|messages?)\b", "Replaying Kafka events/topics"),
    (r"\breplay\s+kafka\b", "Replaying Kafka events/topics"),
    (r"\b(?:change|reset|modify|advance|seek|set)\s+(?:the\s+)?(?:kafka\s+)?(?:consumer\s+)?offsets?\b", "Modifying/resetting Kafka offsets"),
    (r"\bUPDATE\s+[A-Za-z0-9_]+\s+SET\b", "Direct SQL UPDATE statement"),
    (r"\bDELETE\s+FROM\s+[A-Za-z0-9_]+\b", "Direct SQL DELETE statement"),
    (r"\b(?:modify|update|delete|mutate|insert)\s+(?:the\s+)?(?:production\s+)?(?:aerospike|database\s+records?|database\s+state|database|db\s+records?)\b", "Directly mutating database or Aerospike records"),
    (r"\b(?:force|manually\s+change|manually\s+update|manually\s+reprocess)\s+(?:the\s+)?(?:transaction\s+)?state\b", "Forcing transaction state without authorization"),
    (r"\bmanually\s+reprocess\s+(?:the\s+)?(?:financial\s+)?transactions?\b", "Manually reprocessing transactions without authorization"),
    (r"\b(?:restart|restarting)\s+(?:the\s+)?pods?\b", "Restarting pods as transaction recovery"),
    (r"\b(?:change|modify|edit|update)\s+(?:the\s+)?production\s+config(?:uration)?\b", "Changing production configuration directly"),
]

SECRET_PATTERNS = [
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "Private key block"),
    (r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b", "GitHub personal access token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS Access Key ID"),
    (r"\b(?:api_key|apikey|secret_key|private_key)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{20,}[\"']", "Exposed API secret key"),
]

PROHIBITION_PHRASES = (
    "must not",
    "must never",
    "do not",
    "don't",
    "never",
    "cannot",
    "can't",
    "should not",
    "shouldn't",
    "shall not",
    "prohibited",
    "forbidden",
    "not permitted",
    "not allowed",
    "strictly prohibited",
    "without l3",
    "without approval",
    "approval required",
    "l3 approval",
    "l3/development approval",
    "explicit approval",
    "not be used",
    "not authorized",
    "avoid",
    "refrain from",
)


@dataclass
class ValidationResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)


def validate_runbook(
    runbook_path: Path,
    run_dir: Path,
    repo_info: RepositoryInfo,
) -> ValidationResult:
    """
    Validate RUNBOOK.md against operational safety and quality rules.
    Writes validation-report.txt to run_dir.
    """
    reasons: list[str] = []

    # 1. Existence check
    if not runbook_path.exists():
        reasons.append(f"Runbook file does not exist: {runbook_path}")
        _write_report(run_dir, False, reasons, repo_info.service_name, 0)
        return ValidationResult(passed=False, reasons=reasons)

    if not runbook_path.is_file():
        reasons.append(f"Runbook path is not a file: {runbook_path}")
        _write_report(run_dir, False, reasons, repo_info.service_name, 0)
        return ValidationResult(passed=False, reasons=reasons)

    try:
        content = runbook_path.read_text(encoding="utf-8")
    except Exception as exc:
        reasons.append(f"Failed to read runbook file: {exc}")
        _write_report(run_dir, False, reasons, repo_info.service_name, 0)
        return ValidationResult(passed=False, reasons=reasons)

    char_count = len(content.strip())

    # 2. Non-empty check
    if char_count == 0:
        reasons.append("Runbook content is empty.")

    # 3. Minimum sensible length
    elif char_count < 200:
        reasons.append(f"Runbook content is unusually short ({char_count} characters, minimum expected: 200).")

    # 4. Service identity check
    service_clean = repo_info.service_name.lower().replace("-", "").replace("_", "")
    content_clean = content.lower().replace("-", "").replace("_", "")
    if service_clean not in content_clean and "**service:**" not in content.lower():
        reasons.append(f"Runbook does not mention the service identity '{repo_info.service_name}'.")

    # 5. Raw Java code blocks
    if re.search(r"```java\b", content, re.IGNORECASE):
        reasons.append("Runbook contains raw Java code blocks (```java), which is prohibited for L1/L2 operational runbooks.")

    # 6. 'Not found in repository' placeholder
    if re.search(r"not found in (?:the )?repository", content, re.IGNORECASE):
        reasons.append("Runbook contains 'Not found in repository' placeholders (sections without repository support must be omitted).")

    # 7. Obvious source code modifications / patch headers
    if re.search(r"^diff --git ", content, re.MULTILINE) or re.search(r"^--- a/.*?\n\+\+\+ b/", content, re.MULTILINE):
        reasons.append("Runbook contains application source diff/patch markers.")

    # 8. Unsafe support actions (Block- and List-Aware Context)
    in_prohibition_list = False
    for line in content.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue

        if line_clean.startswith("#"):
            # Headings are organizational structure and must never activate prohibition context by themselves
            in_prohibition_list = False
            continue

        line_lower = line_clean.lower()
        is_bullet = line_clean.startswith(("-", "*", "+")) or bool(re.match(r"^\d+\.", line_clean))
        has_prohibition_phrase = any(neg in line_lower for neg in PROHIBITION_PHRASES)

        if not is_bullet:
            if has_prohibition_phrase:
                in_prohibition_list = True
                continue
            else:
                in_prohibition_list = False
                for pattern, description in UNSAFE_ACTION_PATTERNS:
                    match = re.search(pattern, line_clean, re.IGNORECASE)
                    if match:
                        reasons.append(f"Runbook contains unsafe support recommendation: {description} ('{match.group(0)}')")
                        break
        else:
            if has_prohibition_phrase or in_prohibition_list:
                continue

            for pattern, description in UNSAFE_ACTION_PATTERNS:
                match = re.search(pattern, line_clean, re.IGNORECASE)
                if match:
                    reasons.append(f"Runbook contains unsafe support recommendation: {description} ('{match.group(0)}')")
                    break

    # 9. Secret exposure check
    for pattern, description in SECRET_PATTERNS:
        if re.search(pattern, content):
            reasons.append(f"Runbook appears to contain exposed credentials/secrets: {description}.")
            break

    # 10. Obvious internal implementation leakage
    leakage_matches = re.findall(r"\b(?:ThreadPoolTaskExecutor|RunbookJobController|RunbookJobService|CreateJobRequest|PublishRequest)\b", content)
    if leakage_matches:
        unique_matches = sorted(set(leakage_matches))
        reasons.append(f"Runbook exposes internal Java implementation class names ({', '.join(unique_matches)}), which should be omitted from L1/L2 operational documentation.")

    passed = len(reasons) == 0
    _write_report(run_dir, passed, reasons, repo_info.service_name, char_count)
    return ValidationResult(passed=passed, reasons=reasons)


def _write_report(run_dir: Path, passed: bool, reasons: list[str], service_name: str, char_count: int) -> None:
    report_file = run_dir / "validation-report.txt"
    lines = []
    if passed:
        lines.append("VALIDATION: PASS")
        lines.append(f"Service: {service_name}")
        lines.append(f"Runbook Size: {char_count} characters")
        lines.append("Status: All operational quality and safety checks passed successfully.")
    else:
        lines.append("VALIDATION: FAILED")
        lines.append(f"Service: {service_name}")
        lines.append(f"Runbook Size: {char_count} characters")
        lines.append("Reasons:")
        for r in reasons:
            lines.append(f"  - {r}")

    report_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOGGER.info("Wrote validation report to %s (passed=%s)", report_file, passed)
