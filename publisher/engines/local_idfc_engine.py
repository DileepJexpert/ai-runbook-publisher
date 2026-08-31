"""Local IDFC Coder engine for developer/local execution mode."""

from __future__ import annotations

import logging
from typing import Any

from publisher.execution_mode import ExecutionMode, ModeEnforcementError
from .base import EngineGenerationResult, GenerationContext
from .idfc_coder_engine import IdfcCoderEngine

LOGGER = logging.getLogger(__name__)


class LocalIdfcCoderEngine(IdfcCoderEngine):
    """
    Generation engine for LOCAL execution mode.
    Uses local idfc-coder in target repository. Interactive prompts allowed.
    Strictly forbidden in PIPELINE mode.
    """

    engine_name: str = "idfc-coder"
    execution_mode: ExecutionMode = ExecutionMode.LOCAL

    def __init__(
        self,
        coder_cmd: str | None = None,
        mode: str | None = None,
        execution_mode: ExecutionMode = ExecutionMode.LOCAL,
    ) -> None:
        super().__init__(coder_cmd=coder_cmd, mode=mode)
        self.execution_mode = execution_mode
        if self.execution_mode == ExecutionMode.PIPELINE:
            raise ModeEnforcementError(
                "IDFC Coder is strictly excluded from PIPELINE execution mode. Use PipelineLlmApiEngine instead."
            )

    def generate(self, context: GenerationContext) -> EngineGenerationResult:
        if self.execution_mode == ExecutionMode.PIPELINE:
            raise ModeEnforcementError(
                "IDFC Coder is strictly excluded from PIPELINE execution mode. Use PipelineLlmApiEngine instead."
            )
        LOGGER.info("Executing LocalIdfcCoderEngine in LOCAL mode for %s", context.service_name)
        return super().generate(context)
