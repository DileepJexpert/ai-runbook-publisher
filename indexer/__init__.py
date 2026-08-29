"""Indexer package: deterministic code chunking and searchable repository index.

No LLM. No embeddings. Local deterministic indexing only.
"""

from __future__ import annotations

from .index_builder import CodeIndexBuilder
from .index_store import CodeIndexStore, load_code_index
from .models import CodeChunk, IndexManifest, SearchHit, SymbolReference

__all__ = [
    "CodeChunk",
    "CodeIndexBuilder",
    "CodeIndexStore",
    "IndexManifest",
    "SearchHit",
    "SymbolReference",
    "load_code_index",
]


def build_code_index(
    repo_path: str,
    service_name: str,
    commit_sha: str,
    *,
    max_chunk_chars: int = 20_000,
) -> "CodeIndexStore":
    """Convenience helper: build and persist a code index for a repository commit."""
    builder = CodeIndexBuilder(max_chunk_chars=max_chunk_chars)
    return builder.build(repo_path=repo_path, service_name=service_name, commit_sha=commit_sha)
