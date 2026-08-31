"""Unit tests for publisher/validator.py."""

from __future__ import annotations

from pathlib import Path
import pytest

from publisher.repository import RepositoryInfo
from publisher.validator import validate_runbook


@pytest.fixture
def repo_info() -> RepositoryInfo:
    return RepositoryInfo(
        path="/path/to/payments-service",
        service_name="payments-service",
        branch="main",
        commit_sha="1234567890abcdef",
        origin_url="https://github.com/org/payments-service.git",
        working_tree_clean=True,
    )


def test_validator_pass_on_good_runbook(tmp_path: Path, repo_info: RepositoryInfo):
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service

> **Service:** payments-service
> **Version:** 1.0.0
> **Environment:** production

## Service Overview
The payments-service handles credit card and UPI transactions.

## How to Trace a Transaction
Search Kibana using the transactionId or customerId index.

## Failure Scenarios & Troubleshooting
| Scenario | Kibana Signature | Safe Support Action |
| --- | --- | --- |
| Gateway Timeout | `PAYMENT_GATEWAY_TIMEOUT` | Check downstream payment gateway status page. |

## Support Boundaries
Support must not replay Kafka events, change offsets, or modify database records without L3 approval.

## Escalation Guide
Collect transaction ID, timestamp, and Kibana logs before escalating to the core billing team.
"""
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is True
    assert len(result.reasons) == 0

    report_path = tmp_path / "validation-report.txt"
    assert report_path.exists()
    assert "VALIDATION: PASS" in report_path.read_text(encoding="utf-8")


def test_validator_fail_on_missing_runbook(tmp_path: Path, repo_info: RepositoryInfo):
    missing_path = tmp_path / "DOES_NOT_EXIST.md"
    result = validate_runbook(missing_path, tmp_path, repo_info)
    assert result.passed is False
    assert any("does not exist" in r.lower() for r in result.reasons)


def test_validator_fail_on_empty_runbook(tmp_path: Path, repo_info: RepositoryInfo):
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_path.write_text("", encoding="utf-8")
    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is False
    assert any("empty" in r.lower() for r in result.reasons)


def test_validator_fail_on_short_runbook(tmp_path: Path, repo_info: RepositoryInfo):
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_path.write_text("# payments-service\nToo short.", encoding="utf-8")
    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is False
    assert any("short" in r.lower() for r in result.reasons)


def test_validator_fail_on_java_code_blocks(tmp_path: Path, repo_info: RepositoryInfo):
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

Here is some internal Java implementation detail:

```java
public class PaymentController {
    public ResponseEntity<String> pay() { return ResponseEntity.ok("ok"); }
}
```
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is False
    assert any("java code" in r.lower() for r in result.reasons)


def test_validator_fail_on_not_found_placeholder(tmp_path: Path, repo_info: RepositoryInfo):
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

## Kafka Topics
Not found in repository.
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is False
    assert any("not found in repository" in r.lower() for r in result.reasons)


def test_validator_fail_on_unsafe_mutation_actions(tmp_path: Path, repo_info: RepositoryInfo):
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

## Troubleshooting
When an order is stuck:
Run this query: UPDATE orders SET status = 'FAILED' WHERE id = 123;
Also, replay kafka events from partition 0.
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is False
    assert any("unsafe" in r.lower() or "sql" in r.lower() or "kafka" in r.lower() for r in result.reasons)


def test_validator_allows_negative_safety_boundaries(tmp_path: Path, repo_info: RepositoryInfo):
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

## Support Boundaries
- Support must not replay Kafka events.
- Never modify database records or Aerospike tables directly.
- Do not change offsets without developer approval.
- Support cannot force transaction state manually.
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is True
    assert len(result.reasons) == 0


def test_validator_catches_exposed_private_keys(tmp_path: Path, repo_info: RepositoryInfo):
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

Secret info:
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Y...
-----END RSA PRIVATE KEY-----
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is False
    assert any("credential" in r.lower() or "secret" in r.lower() for r in result.reasons)


# ---------------------------------------------------------------------------
# Specific False-Positive vs True-Positive Safety Tests
# ---------------------------------------------------------------------------

def test_validator_pass_on_list_context_prohibitions(tmp_path: Path, repo_info: RepositoryInfo):
    """Verify list context prohibitions pass without false positives."""
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

## Support Boundaries
Support must not perform the following actions without explicit L3/Development approval:
- Replay Kafka events
- Change offsets
- Modify database or Aerospike records
- Restart pods

These operations require explicit L3/Development approval and must not be performed independently by L1/L2 Support.
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is True
    assert len(result.reasons) == 0


def test_validator_pass_on_inline_prohibitions(tmp_path: Path, repo_info: RepositoryInfo):
    """Verify individual prohibition statements pass safely."""
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

## Safety Rules
Do not modify production database records.
Support must never restart pods as transaction recovery.
Support must never manually reprocess financial transactions.
Do not change Kafka offsets.
Restarting pods must not be used as transaction recovery.
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is True
    assert len(result.reasons) == 0


def test_validator_fail_on_replay_kafka_instruction(tmp_path: Path, repo_info: RepositoryInfo):
    """FAIL: Replay Kafka events and retry processing."""
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

## Recovery Step
Replay Kafka events and retry processing.
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is False
    assert any("Replaying Kafka" in r for r in result.reasons)


def test_validator_fail_on_change_offsets_instruction(tmp_path: Path, repo_info: RepositoryInfo):
    """FAIL: Change Kafka offsets to recover the consumer."""
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

## Recovery Step
Change Kafka offsets to recover the consumer.
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is False
    assert any("Kafka offsets" in r for r in result.reasons)


def test_validator_fail_on_restart_pod_instruction(tmp_path: Path, repo_info: RepositoryInfo):
    """FAIL: Restart the pod and retry the transaction."""
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

## Recovery Step
Restart the pod and retry the transaction.
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is False
    assert any("Restarting pods" in r for r in result.reasons)


def test_validator_fail_on_update_database_instruction(tmp_path: Path, repo_info: RepositoryInfo):
    """FAIL: Update the database state manually."""
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

## Recovery Step
Update the database state manually.
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is False
    assert any("mutating database" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# Tightened Heading vs Semantic Prohibition Tests
# ---------------------------------------------------------------------------

def test_validator_pass_on_heading_plus_prohibited_wording_plus_dangerous_bullets(tmp_path: Path, repo_info: RepositoryInfo):
    """PASS: heading + prohibited wording + dangerous bullets = PASS."""
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

## Support Boundaries

Support must not perform the following actions without explicit L3/Development approval:
- Replay Kafka events
- Change Kafka offsets
- Modify production database records
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is True
    assert len(result.reasons) == 0


def test_validator_fail_on_heading_alone_plus_dangerous_bullets(tmp_path: Path, repo_info: RepositoryInfo):
    """FAIL: heading alone + dangerous affirmative bullets = FAIL."""
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

## Support Boundaries

- Replay Kafka events to retry processing
- Change Kafka offsets to recover the consumer
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is False
    assert any("Replaying Kafka" in r or "Kafka offsets" in r for r in result.reasons)


def test_validator_fail_on_heading_plus_support_can_plus_dangerous_bullets(tmp_path: Path, repo_info: RepositoryInfo):
    """FAIL: heading + 'Support can:' + dangerous bullets = FAIL."""
    runbook_path = tmp_path / "RUNBOOK.md"
    runbook_content = """# Production Support Runbook - payments-service
> **Service:** payments-service

## Support Boundaries

Support can:
- Replay Kafka events
- Change offsets
""" + ("\nAdditional operational padding text to exceed minimum length requirements." * 5)
    runbook_path.write_text(runbook_content, encoding="utf-8")

    result = validate_runbook(runbook_path, tmp_path, repo_info)
    assert result.passed is False
    assert any("Replaying Kafka" in r or "Kafka offsets" in r for r in result.reasons)

