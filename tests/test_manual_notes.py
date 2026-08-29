"""Unit tests for publisher/manual_notes.py."""

from publisher.manual_notes import extract_manual_notes, inject_manual_notes


def test_extract_manual_notes_success():
    page_content = """
    <h1>Some Confluence Header</h1>
    <!-- MANUAL SUPPORT NOTES START -->
    * On-call escalation: call 555-1234
    * Known issue: retry payment once
    <!-- MANUAL SUPPORT NOTES END -->
    <p>Trailing text</p>
    """
    notes = extract_manual_notes(page_content)
    assert "* On-call escalation: call 555-1234" in notes
    assert "* Known issue: retry payment once" in notes


def test_extract_manual_notes_empty():
    page_content = """
    <h1>Header</h1>
    <!-- MANUAL SUPPORT NOTES START -->
    <!-- MANUAL SUPPORT NOTES END -->
    """
    notes = extract_manual_notes(page_content)
    assert notes == ""


def test_extract_manual_notes_missing():
    page_content = "<h1>Header</h1><p>No markers</p>"
    notes = extract_manual_notes(page_content)
    assert notes == ""


def test_inject_manual_notes_with_content():
    runbook = "# Runbook Content"
    notes = "* Step 1: Call on-call team."
    injected = inject_manual_notes(runbook, notes)

    assert "# Runbook Content" in injected
    assert "## 📝 Manual Support Notes" in injected
    assert "<!-- MANUAL SUPPORT NOTES START -->" in injected
    assert "* Step 1: Call on-call team." in injected
    assert "<!-- MANUAL SUPPORT NOTES END -->" in injected


def test_inject_manual_notes_empty():
    runbook = "# Runbook Content"
    injected = inject_manual_notes(runbook, "")

    assert "# Runbook Content" in injected
    assert "<!-- MANUAL SUPPORT NOTES START -->" in injected
    assert "<!-- MANUAL SUPPORT NOTES END -->" in injected
    # Should not add the user-facing header if empty
    assert "## 📝 Manual Support Notes" not in injected
