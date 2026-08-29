"""Immutable data models for the deterministic code index (Phase 3).

No LLM. No embeddings. Local models only.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Chunk type constants
# ---------------------------------------------------------------------------

CHUNK_TYPE_JAVA_CLASS_HEADER = "JAVA_CLASS_HEADER"
CHUNK_TYPE_JAVA_METHOD = "JAVA_METHOD"
CHUNK_TYPE_JAVA_FIELD_BLOCK = "JAVA_FIELD_BLOCK"
CHUNK_TYPE_JAVA_ENUM = "JAVA_ENUM"
CHUNK_TYPE_JAVA_INTERFACE = "JAVA_INTERFACE"
CHUNK_TYPE_JAVA_RECORD = "JAVA_RECORD"
CHUNK_TYPE_JAVA_ANNOTATION_BLOCK = "JAVA_ANNOTATION_BLOCK"
CHUNK_TYPE_CONFIG_SECTION = "CONFIG_SECTION"
CHUNK_TYPE_PROPERTIES_SECTION = "PROPERTIES_SECTION"
CHUNK_TYPE_SQL_STATEMENT = "SQL_STATEMENT"
CHUNK_TYPE_XML_SECTION = "XML_SECTION"
CHUNK_TYPE_README_SECTION = "README_SECTION"
CHUNK_TYPE_GENERIC_TEXT = "GENERIC_TEXT"

ALL_CHUNK_TYPES = {
    CHUNK_TYPE_JAVA_CLASS_HEADER,
    CHUNK_TYPE_JAVA_METHOD,
    CHUNK_TYPE_JAVA_FIELD_BLOCK,
    CHUNK_TYPE_JAVA_ENUM,
    CHUNK_TYPE_JAVA_INTERFACE,
    CHUNK_TYPE_JAVA_RECORD,
    CHUNK_TYPE_JAVA_ANNOTATION_BLOCK,
    CHUNK_TYPE_CONFIG_SECTION,
    CHUNK_TYPE_PROPERTIES_SECTION,
    CHUNK_TYPE_SQL_STATEMENT,
    CHUNK_TYPE_XML_SECTION,
    CHUNK_TYPE_README_SECTION,
    CHUNK_TYPE_GENERIC_TEXT,
}

# Source scope
SOURCE_SCOPE_PRODUCTION = "PRODUCTION"
SOURCE_SCOPE_TEST = "TEST"

# Reference types
REF_TYPE_METHOD_CALL = "METHOD_CALL"
REF_TYPE_TYPE_REFERENCE = "TYPE_REFERENCE"
REF_TYPE_FIELD_REFERENCE = "FIELD_REFERENCE"


def _compute_content_hash(content: str) -> str:
    """Return a stable 16-char SHA-256 hex digest of chunk content.

    Uses hashlib (not Python built-in hash) so it is stable across processes.
    """
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]


def make_chunk_id(file_path: str, chunk_type: str, symbol: str) -> str:
    """Build a deterministic chunk ID.

    Format: ``{file_path}::{CHUNK_TYPE}::{symbol}``
    Example: ``src/main/java/.../PaymentService.java::JAVA_METHOD::executePayment``
    """
    return f"{file_path}::{chunk_type}::{symbol}"


@dataclass(frozen=True)
class CodeChunk:
    """Immutable representation of one indexable code unit."""

    chunk_id: str
    file_path: str
    language: str  # java, yaml, properties, sql, xml, markdown, text
    chunk_type: str

    class_name: str | None
    method_name: str | None
    symbol_name: str | None

    start_line: int
    end_line: int

    content: str

    annotations: tuple[str, ...]
    imports: tuple[str, ...]
    keywords: tuple[str, ...]

    parent_chunk_id: str | None
    content_hash: str

    source_scope: str = SOURCE_SCOPE_PRODUCTION  # PRODUCTION or TEST

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunkId": self.chunk_id,
            "filePath": self.file_path,
            "language": self.language,
            "chunkType": self.chunk_type,
            "className": self.class_name,
            "methodName": self.method_name,
            "symbolName": self.symbol_name,
            "startLine": self.start_line,
            "endLine": self.end_line,
            "content": self.content,
            "annotations": list(self.annotations),
            "imports": list(self.imports),
            "keywords": list(self.keywords),
            "parentChunkId": self.parent_chunk_id,
            "contentHash": self.content_hash,
            "sourceScope": self.source_scope,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "CodeChunk":
        return CodeChunk(
            chunk_id=d["chunkId"],
            file_path=d["filePath"],
            language=d["language"],
            chunk_type=d["chunkType"],
            class_name=d.get("className"),
            method_name=d.get("methodName"),
            symbol_name=d.get("symbolName"),
            start_line=d["startLine"],
            end_line=d["endLine"],
            content=d["content"],
            annotations=tuple(d.get("annotations", [])),
            imports=tuple(d.get("imports", [])),
            keywords=tuple(d.get("keywords", [])),
            parent_chunk_id=d.get("parentChunkId"),
            content_hash=d["contentHash"],
            source_scope=d.get("sourceScope", SOURCE_SCOPE_PRODUCTION),
        )


@dataclass(frozen=True)
class SearchHit:
    """A search result with score and matched terms."""

    chunk: CodeChunk
    score: float
    matched_terms: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunkId": self.chunk.chunk_id,
            "filePath": self.chunk.file_path,
            "chunkType": self.chunk.chunk_type,
            "className": self.chunk.class_name,
            "methodName": self.chunk.method_name,
            "symbolName": self.chunk.symbol_name,
            "startLine": self.chunk.start_line,
            "endLine": self.chunk.end_line,
            "score": self.score,
            "matchedTerms": list(self.matched_terms),
            "sourceScope": self.chunk.source_scope,
        }


@dataclass(frozen=True)
class SymbolReference:
    """A lightweight, mechanically extracted symbol relationship."""

    source_chunk_id: str
    referenced_symbol: str
    reference_type: str  # METHOD_CALL, TYPE_REFERENCE, FIELD_REFERENCE

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceChunkId": self.source_chunk_id,
            "referencedSymbol": self.referenced_symbol,
            "referenceType": self.reference_type,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "SymbolReference":
        return SymbolReference(
            source_chunk_id=d["sourceChunkId"],
            referenced_symbol=d["referencedSymbol"],
            reference_type=d["referenceType"],
        )


@dataclass
class IndexManifest:
    """Metadata describing an index snapshot."""

    schema_version: str
    service_name: str
    commit_sha: str
    created_at: str
    chunk_count: int
    production_chunk_count: int
    test_chunk_count: int
    file_count: int
    chunk_types: dict[str, int]  # chunk_type -> count
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "serviceName": self.service_name,
            "commitSha": self.commit_sha,
            "createdAt": self.created_at,
            "chunkCount": self.chunk_count,
            "productionChunkCount": self.production_chunk_count,
            "testChunkCount": self.test_chunk_count,
            "fileCount": self.file_count,
            "chunkTypes": self.chunk_types,
            "warnings": self.warnings,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "IndexManifest":
        return IndexManifest(
            schema_version=d["schemaVersion"],
            service_name=d["serviceName"],
            commit_sha=d["commitSha"],
            created_at=d["createdAt"],
            chunk_count=d["chunkCount"],
            production_chunk_count=d["productionChunkCount"],
            test_chunk_count=d["testChunkCount"],
            file_count=d["fileCount"],
            chunk_types=d.get("chunkTypes", {}),
            warnings=d.get("warnings", []),
        )
