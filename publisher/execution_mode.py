"""Execution modes and mode enforcement exceptions for ai-runbook-publisher."""

from __future__ import annotations

from enum import Enum


class ExecutionMode(str, Enum):
    """
    Execution mode governing engine selection, repository validation, credentials, and Confluence page resolution.
    """
    LOCAL = "LOCAL"
    PIPELINE = "PIPELINE"


class ModeEnforcementError(Exception):
    """Raised when an operation violates the constraints of the active ExecutionMode."""
    pass


class PipelineExecutionError(ModeEnforcementError):
    """Base exception for pipeline execution failures."""
    pass


class DirtyWorkingTreeError(PipelineExecutionError):
    """Raised when pipeline execution encounters uncommitted changes in the repository."""
    pass


class CommitMismatchError(PipelineExecutionError):
    """Raised when analyzed commit SHA does not match expected or deployed commit SHA."""
    pass
