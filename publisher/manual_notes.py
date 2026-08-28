"""Keep Support-owned content during generated page updates."""

import logging
import re

LOGGER = logging.getLogger(__name__)
START = "<!-- MANUAL SUPPORT NOTES START -->"
END = "<!-- MANUAL SUPPORT NOTES END -->"
_NOTES = re.compile(re.escape(START) + r"(.*?)" + re.escape(END), re.DOTALL)


def extract_manual_notes(page_content: str) -> str:
    match = _NOTES.search(page_content)
    if not match:
        LOGGER.info("No manual support notes markers found")
        return ""
    notes = match.group(1).strip()
    if notes:
        LOGGER.info("Manual support notes found")
    else:
        LOGGER.warning("Manual support notes markers found but empty")
    return notes


def inject_manual_notes(runbook_content: str, manual_notes: str) -> str:
    if not manual_notes:
        return f"{runbook_content.rstrip()}\n\n{START}\n{END}\n"
    return (
        f"{runbook_content.rstrip()}\n\n## 📝 Manual Support Notes\n"
        "> These notes are maintained by the Support team and preserved across automated updates.\n\n"
        f"{START}\n{manual_notes}\n{END}\n"
    )
