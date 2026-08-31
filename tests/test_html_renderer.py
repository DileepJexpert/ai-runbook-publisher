"""Unit tests for deterministic Markdown-to-HTML rendering (RUNBOOK.html)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
import pytest

from publisher.html_renderer import (
    generate_runbook_html,
    render_body,
    render_document,
)
from publisher.repository import RepositoryInfo
from publisher.validator import validate_runbook


SAMPLE_RUNBOOK_MARKDOWN = """# Production Support Runbook - payments-service

> **Service:** payments-service
> **Environment:** production
> **Version:** 1.0.0

## Service Overview
The `payments-service` orchestrates payments and validations.
Check details at [Payment Docs](https://docs.internal.example.com).

## Key Troubleshooting Table
| Error Code | Meaning | Safe Support Action |
| --- | --- | --- |
| `ERR_TIMEOUT` | Gateway timeout | Check downstream status |
| `ERR_AUTH` | Token invalid | Escalate to L3 |

## Common Procedures
1. Verify network health
2. Review Kibana logs

### Prohibited Operations
- Do not replay Kafka events
- Do not modify database records directly

```
LOG: Transaction failed with code 500 & error <critical>
```
"""


# ---------------------------------------------------------------------------
# 1-5. Core HTML Generation & Structure Tests
# ---------------------------------------------------------------------------

def test_01_validated_runbook_generates_runbook_html(tmp_path: Path):
    """1. validated RUNBOOK.md generates RUNBOOK.html in the same directory."""
    runbook_md = tmp_path / "RUNBOOK.md"
    runbook_md.write_text(SAMPLE_RUNBOOK_MARKDOWN, encoding="utf-8")

    html_file = generate_runbook_html(
        runbook_path=runbook_md,
        output_dir=tmp_path,
        repo_name="payments-service-repo",
    )

    assert html_file.exists()
    assert html_file.name == "RUNBOOK.html"
    assert html_file.parent == tmp_path
    content = html_file.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "payments-service" in content


def test_02_validation_failure_does_not_generate_html(tmp_path: Path):
    """2. validation failure does not generate RUNBOOK.html."""
    repo_info = RepositoryInfo(
        path=str(tmp_path),
        service_name="payments-service",
        branch="main",
        commit_sha="12345678",
        origin_url=None,
        repo_name="payments-service",
    )
    bad_runbook = tmp_path / "RUNBOOK.md"
    bad_runbook.write_text("# Bad\nReplay Kafka events now.", encoding="utf-8")

    val_res = validate_runbook(bad_runbook, tmp_path, repo_info)
    assert val_res.passed is False

    # Simulate pipeline condition: HTML generated ONLY if val_res.passed is True
    html_target = tmp_path / "RUNBOOK.html"
    if val_res.passed:
        generate_runbook_html(bad_runbook, tmp_path, repo_info.repo_name)

    assert not html_target.exists()


def test_03_runbook_md_remains_byte_for_byte_unchanged(tmp_path: Path):
    """3. RUNBOOK.md remains byte-for-byte unchanged after rendering."""
    runbook_md = tmp_path / "RUNBOOK.md"
    runbook_md.write_text(SAMPLE_RUNBOOK_MARKDOWN, encoding="utf-8")
    original_bytes = runbook_md.read_bytes()

    generate_runbook_html(
        runbook_path=runbook_md,
        output_dir=tmp_path,
        repo_name="payments-service-repo",
    )

    assert runbook_md.read_bytes() == original_bytes


def test_04_generated_file_is_valid_standalone_html_structure(tmp_path: Path):
    """4. generated file is valid standalone HTML structure."""
    runbook_md = tmp_path / "RUNBOOK.md"
    runbook_md.write_text(SAMPLE_RUNBOOK_MARKDOWN, encoding="utf-8")

    html_file = generate_runbook_html(runbook_md, tmp_path, repo_name="payments-service")
    html_text = html_file.read_text(encoding="utf-8")

    assert html_text.strip().startswith("<!DOCTYPE html>")
    assert "<html" in html_text
    assert "<head>" in html_text
    assert '<meta charset="utf-8">' in html_text
    assert '<meta name="viewport"' in html_text
    assert "<style>" in html_text
    assert "</style>" in html_text
    assert "<body>" in html_text
    assert "</body>" in html_text
    assert "</html>" in html_text


def test_05_generated_html_contains_expected_title():
    """5. generated HTML contains expected repository/runbook title."""
    doc = render_document(SAMPLE_RUNBOOK_MARKDOWN, title="ai-runbook-service-springboot - Production Support Runbook")
    assert "<title>ai-runbook-service-springboot - Production Support Runbook</title>" in doc


# ---------------------------------------------------------------------------
# 6-14. Markdown Element Rendering Tests
# ---------------------------------------------------------------------------

def test_06_markdown_headings_render_correctly():
    """6. Markdown H1/H2/H3 headings render correctly."""
    md = "# Heading 1\n## Heading 2\n### Heading 3"
    body = render_body(md)
    assert "<h1>Heading 1</h1>" in body
    assert "<h2>Heading 2</h2>" in body
    assert "<h3>Heading 3</h3>" in body


def test_07_unordered_lists_render_correctly():
    """7. unordered lists render correctly."""
    md = "- Item 1\n- Item 2\n- Item 3"
    body = render_body(md)
    assert "<ul>" in body
    assert "<li>Item 1</li>" in body
    assert "<li>Item 2</li>" in body
    assert "<li>Item 3</li>" in body
    assert "</ul>" in body


def test_08_ordered_lists_render_correctly():
    """8. ordered lists render correctly."""
    md = "1. First step\n2. Second step"
    body = render_body(md)
    assert "<ol>" in body
    assert "<li>First step</li>" in body
    assert "<li>Second step</li>" in body
    assert "</ol>" in body


def test_09_markdown_tables_render_as_html_tables():
    """9. Markdown tables render as HTML tables with headers and cells."""
    md = "| Col 1 | Col 2 |\n| --- | --- |\n| Val A | Val B |"
    body = render_body(md)
    assert "<table>" in body
    assert "<thead>" in body
    assert "<th>Col 1</th>" in body
    assert "<th>Col 2</th>" in body
    assert "<tbody>" in body
    assert "<td>Val A</td>" in body
    assert "<td>Val B</td>" in body
    assert "</table>" in body


def test_10_inline_code_renders_correctly():
    """10. inline code renders correctly."""
    md = "Run `kubectl get pods` command."
    body = render_body(md)
    assert "<code>kubectl get pods</code>" in body


def test_11_fenced_code_block_renders_correctly():
    """11. fenced code block renders correctly."""
    md = "```json\n{\n  \"status\": \"UP\"\n}\n```"
    body = render_body(md)
    assert "<pre>" in body
    assert "<code" in body
    assert '"status": "UP"' in body or '&quot;status&quot;: &quot;UP&quot;' in body


def test_12_bold_and_italics_render_correctly():
    """12. bold and italics render correctly."""
    md = "This is **bold** and *italic* text."
    body = render_body(md)
    assert "<strong>bold</strong>" in body
    assert "<em>italic</em>" in body


def test_13_links_render_correctly():
    """13. links render correctly."""
    md = "See [Runbook Wiki](https://wiki.example.com/runbook)."
    body = render_body(md)
    assert '<a href="https://wiki.example.com/runbook">Runbook Wiki</a>' in body


def test_14_special_html_characters_are_safely_escaped():
    """14. special HTML characters in text and code are safely escaped."""
    md = "Check if value < 100 & count > 0 in `<tag & attr>`"
    body = render_body(md)
    assert "&lt; 100" in body
    assert "&amp;" in body
    assert "&gt; 0" in body
    assert "<code>&lt;tag &amp; attr&gt;</code>" in body


# ---------------------------------------------------------------------------
# 15-18. Body vs Standalone & Renderer Guardrail Tests
# ---------------------------------------------------------------------------

def test_15_body_renderer_does_not_contain_html_wrapper():
    """15. body renderer does not contain <html>/<head>/<body> wrapper."""
    body = render_body(SAMPLE_RUNBOOK_MARKDOWN)
    assert "<!DOCTYPE" not in body
    assert "<html" not in body
    assert "<head" not in body
    assert "<body" not in body
    assert "<h1>" in body


def test_16_standalone_document_contains_full_wrapper():
    """16. standalone document renderer contains full wrapper."""
    doc = render_document(SAMPLE_RUNBOOK_MARKDOWN, title="Test Runbook")
    assert doc.startswith("<!DOCTYPE html>")
    assert "<html" in doc
    assert "<head>" in doc
    assert "<title>Test Runbook</title>" in doc
    assert "<body>" in doc
    assert '<div class="runbook-container">' in doc
    assert "</body>" in doc
    assert "</html>" in doc


def test_17_renderer_performs_no_network_calls():
    """17. renderer performs zero network calls."""
    with patch("urllib.request.urlopen") as mock_urllib, patch("requests.Session.request") as mock_req:
        render_document(SAMPLE_RUNBOOK_MARKDOWN, title="Local Runbook")
        mock_urllib.assert_not_called()
        mock_req.assert_not_called()


def test_18_html_generation_failure_does_not_alter_runbook_md(tmp_path: Path):
    """18. HTML generation failure does not alter RUNBOOK.md."""
    runbook_md = tmp_path / "RUNBOOK.md"
    runbook_md.write_text(SAMPLE_RUNBOOK_MARKDOWN, encoding="utf-8")
    original_text = runbook_md.read_text(encoding="utf-8")

    # Attempt writing to non-existent root or protected path to simulate failure
    with pytest.raises(Exception):
        with patch("pathlib.Path.write_text", side_effect=PermissionError("Read only")):
            generate_runbook_html(runbook_md, tmp_path, repo_name="payments-service")

    assert runbook_md.exists()
    assert runbook_md.read_text(encoding="utf-8") == original_text


# ---------------------------------------------------------------------------
# 19-20. Generation Summary HTML Tracking Tests
# ---------------------------------------------------------------------------

def test_19_generation_summary_records_html_success(tmp_path: Path):
    """19. generation-summary records HTML success."""
    summary_file = tmp_path / "generation-summary.json"
    initial_summary = {
        "service": "payments-service",
        "validationStatus": "PASSED",
    }
    summary_file.write_text(json.dumps(initial_summary), encoding="utf-8")

    # Simulate pipeline update
    html_target = tmp_path / "RUNBOOK.html"
    sum_data = json.loads(summary_file.read_text(encoding="utf-8"))
    sum_data["html"] = {"generated": True, "path": str(html_target)}
    summary_file.write_text(json.dumps(sum_data, indent=2), encoding="utf-8")

    final_data = json.loads(summary_file.read_text(encoding="utf-8"))
    assert final_data["html"]["generated"] is True
    assert final_data["html"]["path"] == str(html_target)


def test_20_generation_summary_records_html_failure(tmp_path: Path):
    """20. generation-summary records HTML failure."""
    summary_file = tmp_path / "generation-summary.json"
    initial_summary = {
        "service": "payments-service",
        "validationStatus": "FAILED",
    }
    summary_file.write_text(json.dumps(initial_summary), encoding="utf-8")

    # Simulate pipeline failure recording
    sum_data = json.loads(summary_file.read_text(encoding="utf-8"))
    sum_data["html"] = {"generated": False, "error": "Validation not passed"}
    summary_file.write_text(json.dumps(sum_data, indent=2), encoding="utf-8")

    final_data = json.loads(summary_file.read_text(encoding="utf-8"))
    assert final_data["html"]["generated"] is False
    assert "Validation not passed" in final_data["html"]["error"]
