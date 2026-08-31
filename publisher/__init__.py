"""Generate and publish production support runbooks."""

from .confluence import (
    ConfluenceConfig,
    ConfluencePage,
    ConfluencePublishResult,
    ConfluencePublisher,
)
from .credential_provider import (
    CredentialProvider,
    LocalCredentialProvider,
    PipelineCredentialProvider,
)
from .engines import (
    AiGenerationEngine,
    ApiAgentEngine,
    EngineConfigurationError,
    EngineGenerationResult,
    ExternalAgentEngine,
    GenerationContext,
    GenerationEngine,
    IdfcCoderEngine,
    LocalIdfcCoderEngine,
    PipelineLlmApiEngine,
    UnsupportedGenerationEngineError,
    create_generation_engine,
)
from .execution_mode import (
    CommitMismatchError,
    DirtyWorkingTreeError,
    ExecutionMode,
    ModeEnforcementError,
    PipelineExecutionError,
)
from .html_renderer import (
    generate_runbook_html,
    render_body,
    render_confluence_body,
    render_document,
    sanitize_html,
)
from .identity import (
    GenerationMetadata,
    calculate_context_fingerprint,
    calculate_generation_key,
    calculate_prompt_fingerprint,
    calculate_source_fingerprint,
    create_attempt_id,
    load_generation_metadata,
    record_attempt,
    save_generation_metadata,
)
from .page_resolver import (
    ConfluencePageResolver,
    LocalConfluencePageResolver,
    ProductionConfluencePageResolver,
)
from .pipeline_orchestrator import PipelineOrchestrator
from .publisher import PublishResult, publish
from .repository import (
    RepositoryAccessError,
    RepositoryInfo,
    inspect_repository,
    resolve_repository,
)
from .repository_provider import (
    LocalRepositoryProvider,
    PipelineRepositoryProvider,
    RepositoryProvider,
)
from .repository_tools import RepositoryTools, SearchResult
from .validator import ValidationResult, validate_runbook

__all__ = [
    "publish",
    "PublishResult",
    "inspect_repository",
    "resolve_repository",
    "RepositoryInfo",
    "RepositoryAccessError",
    "RepositoryTools",
    "SearchResult",
    "validate_runbook",
    "ValidationResult",
    "ConfluenceConfig",
    "ConfluencePage",
    "ConfluencePublishResult",
    "ConfluencePublisher",
    "generate_runbook_html",
    "render_body",
    "render_confluence_body",
    "render_document",
    "sanitize_html",
    "GenerationMetadata",
    "calculate_source_fingerprint",
    "calculate_prompt_fingerprint",
    "calculate_context_fingerprint",
    "calculate_generation_key",
    "create_attempt_id",
    "load_generation_metadata",
    "save_generation_metadata",
    "record_attempt",
    "ExecutionMode",
    "ModeEnforcementError",
    "PipelineExecutionError",
    "DirtyWorkingTreeError",
    "CommitMismatchError",
    "RepositoryProvider",
    "LocalRepositoryProvider",
    "PipelineRepositoryProvider",
    "CredentialProvider",
    "LocalCredentialProvider",
    "PipelineCredentialProvider",
    "ConfluencePageResolver",
    "LocalConfluencePageResolver",
    "ProductionConfluencePageResolver",
    "PipelineOrchestrator",
    "AiGenerationEngine",
    "GenerationEngine",
    "LocalIdfcCoderEngine",
    "PipelineLlmApiEngine",
    "ApiAgentEngine",
    "IdfcCoderEngine",
    "ExternalAgentEngine",
    "create_generation_engine",
    "EngineGenerationResult",
    "GenerationContext",
    "UnsupportedGenerationEngineError",
    "EngineConfigurationError",
]
