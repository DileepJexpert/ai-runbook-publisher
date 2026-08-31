"""Confluence publisher package."""

from .client import ConfluenceClient
from .models import (
    ConfluenceConfig,
    ConfluenceDuplicatePageError,
    ConfluenceError,
    ConfluenceManualNotesError,
    ConfluencePage,
    ConfluencePublishResult,
)
from .publisher import ConfluencePublisher, extract_manual_notes, inject_manual_notes

__all__ = [
    "ConfluenceClient",
    "ConfluenceConfig",
    "ConfluenceDuplicatePageError",
    "ConfluenceError",
    "ConfluenceManualNotesError",
    "ConfluencePage",
    "ConfluencePublishResult",
    "ConfluencePublisher",
    "extract_manual_notes",
    "inject_manual_notes",
]
