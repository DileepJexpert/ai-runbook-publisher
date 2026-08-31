"""Lightweight validation for generated Production Support Runbooks."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .repository import RepositoryInfo

LOGGER = logging.getLogger(__name__)

# Patterns that indicate unsafe operations if recommended or instructed to Support
UNSAFE_ACTION_PATTERNS = [
    (r"\b(?:replay|re-play|republish|re-send|resend)\s+(?:the\s+)?(?:kafka|topic|events?|messages?)\b", "Replaying Kafka events/topics"),
    (r"\breplay\s+kafka\b", "Replaying Kafka events/topics"),
    (r"\b(?:kafka|event|message)\s+replay\b", "Replaying Kafka events/topics"),
    (r"\breprocess(?:ing)?\s+(?:the\s+)?(?:kafka|events?|messages?)\b", "Reprocessing Kafka events/messages"),
    (r"\b(?:change|reset|modify|advance|seek|set|adjust)\s+(?:the\s+)?(?:kafka\s+)?(?:consumer\s+)?offsets?\b", "Modifying/resetting Kafka offsets"),
    (r"\b(?:offset|consumer\s+offset)\s+(?:change|reset|modification|mutation)\b", "Modifying/resetting Kafka offsets"),
    (r"\bUPDATE\s+[A-Za-z0-9_]+\s+SET\b", "Direct SQL UPDATE statement"),
    (r"\bDELETE\s+FROM\s+[A-Za-z0-9_]+\b", "Direct SQL DELETE statement"),
    (r"\bINSERT\s+INTO\s+[A-Za-z0-9_]+\b", "Direct SQL INSERT statement"),
    (r"\b(?:modify|update|delete|mutate|insert)\s+(?:the\s+)?(?:production\s+)?(?:aerospike|database\s+records?|database\s+state|database|db\s+records?|db\s+rows?|table\s+records?)\b", "Directly mutating database or Aerospike records"),
    (r"\b(?:edit|change)\s+(?:the\s+)?(?:production\s+)?(?:aerospike|database|db)\s+records?\b", "Directly mutating database or Aerospike records"),
    (r"\b(?:force|manually\s+change|manually\s+update|manually\s+reprocess|forcefully\s+set)\s+(?:the\s+)?(?:transaction\s+)?state\b", "Forcing transaction state without authorization"),
    (r"\bmanually\s+reprocess\s+(?:the\s+)?(?:financial\s+|payment\s+)?transactions?\b", "Manually reprocessing transactions without authorization"),
    (r"\b(?:manual\s+reprocessing|manual\s+reprocess)\b", "Manual reprocessing without authorization"),
    (r"\b(?:restart|restarting)\s+(?:the\s+)?pods?\b", "Restarting pods as transaction recovery"),
    (r"\b(?:restart|restarting)\s+(?:the\s+)?(?:service|application)\s+to\s+recover\b", "Restarting service as transaction recovery"),
    (r"\b(?:change|modify|edit|update)\s+(?:the\s+)?production\s+config(?:uration)?\b", "Changing production configuration directly"),
    (r"\b(?:force|manually\s+trigger)\s+(?:the\s+)?scheduler\b", "Forcing scheduler execution"),
]

SECRET_PATTERNS = [
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "Private key block"),
    (r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b", "GitHub personal access token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS Access Key ID"),
    (r"\b(?:api_key|apikey|secret_key|private_key)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{20,}[\"']", "Exposed API secret key"),
]

# Patterns that indicate explicit prohibition, warning, negation, or authorization requirement
PROHIBITION_REGEX_PATTERNS = [
    r"\bmust\s+not\b",
    r"\bmust\s+never\b",
    r"\bdo\s+not\b",
    r"\bdon't\b",
    r"\bdoes\s+not\b",
    r"\bdoesn't\b",
    r"\bdid\s+not\b",
    r"\bdidn't\b",
    r"\bnever\b",
    r"\bcannot\b",
    r"\bcan't\b",
    r"\bcan\s+not\b",
    r"\bcould\s+not\b",
    r"\bcouldn't\b",
    r"\bshould\s+not\b",
    r"\bshouldn't\b",
    r"\bshall\s+not\b",
    r"\bwould\s+not\b",
    r"\bwouldn't\b",
    r"\bprohibited\b",
    r"\bforbidden\b",
    r"\bdisallowed\b",
    r"\bnot\s+permitted\b",
    r"\bnot\s+allowed\b",
    r"\bnot\s+authorized\b",
    r"\bnot\s+acceptable\b",
    r"\bstrictly\s+prohibited\b",
    r"\bstrictly\s+forbidden\b",
    r"\bwithout\s+(?:explicit\s+)?(?:l3|development|developer|lead|prior|management)?\s*(?:approval|authorization)\b",
    r"\bapproval\s+required\b",
    r"\brequires?\s+(?:explicit\s+)?(?:l3|development|developer|lead|prior)?\s*(?:approval|authorization)\b",
    r"\bl3\s+approval\b",
    r"\bl3/development\s+approval\b",
    r"\bexplicit\s+approval\b",
    r"\bnot\s+be\s+used\b",
    r"\bnot\s+to\s+(?:be\s+)?(?:used|performed|replayed|modified|reset|restarted)\b",
    r"\bavoid\b",
    r"\bavoiding\b",
    r"\brefrain\s+from\b",
    r"\bout\s+of\s+scope\b",
    r"\bno\s+(?:kafka\s+)?(?:replay|re-play|reprocessing)\b",
    r"\bno\s+(?:manual\s+)?(?:reprocessing|modification|mutation|update)\b",
    r"\bno\s+(?:offset|db|database|aerospike|pod)\s+(?:changes?|mutations?|resets?|restarts?)\b",
    r"^[-*+\d.)\s]*no\s+(?:kafka|manual|database|db|aerospike|offset|pod|event|message|state|production|direct|reprocessing|replay|mutation|modification|update|change|restart)\b",
]

COMPILED_PROHIBITION_PATTERNS = [re.compile(p, re.IGNORECASE) for p in PROHIBITION_REGEX_PATTERNS]


def is_prohibited_context(text: str) -> bool:
    """Check whether a text line, clause, or item expresses explicit prohibition or negation."""
    if not text:
        return False
    text_clean = text.strip()
    for pattern in COMPILED_PROHIBITION_PATTERNS:
        if pattern.search(text_clean):
            return True
    return False


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

    # 8. Unsafe support actions (Negation-, Item-, and List-Aware Context)
    in_prohibition_list = False
    for line in content.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue

        if line_clean.startswith("#"):
            # Headings are organizational structure and must never activate prohibition context by themselves
            in_prohibition_list = False
            continue

        is_bullet = line_clean.startswith(("-", "*", "+")) or bool(re.match(r"^\d+[.)]\s*", line_clean))
        line_is_prohibited = is_prohibited_context(line_clean)

        if not is_bullet:
            if line_is_prohibited:
                in_prohibition_list = True
                continue
            else:
                in_prohibition_list = False
                # Check if this non-bullet line contains an unsafe recommendation
                for pattern, description in UNSAFE_ACTION_PATTERNS:
                    match = re.search(pattern, line_clean, re.IGNORECASE)
                    if match:
                        reasons.append(f"Runbook contains unsafe support recommendation: {description} ('{match.group(0)}')")
                        break
        else:
            if line_is_prohibited or in_prohibition_list:
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
