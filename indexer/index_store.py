"""In-memory code index store with JSON persistence and commit-SHA cache validation.

No LLM. No embeddings. Local deterministic storage only.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .models import CodeChunk, IndexManifest, SymbolReference

LOGGER = logging.getLogger(__name__)

_INDEX_DIR = ".runbook-index"
_SCHEMA_VERSION = "1.0"


class CodeIndexStore:
    """In-memory code index: chunks, symbol index, annotation index, config-key index."""

    def __init__(
        self,
        manifest: IndexManifest,
        chunks: list[CodeChunk],
        symbol_index: dict[str, list[str]],
        annotation_index: dict[str, list[str]],
        config_key_index: dict[str, list[str]],
        references: list[SymbolReference] | None = None,
    ) -> None:
        self.manifest = manifest
        self.chunks = chunks
        self._chunk_by_id: dict[str, CodeChunk] = {c.chunk_id: c for c in chunks}
        self.symbol_index = symbol_index
        self.annotation_index = annotation_index
        self.config_key_index = config_key_index
        self.references = references or []

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get_chunk(self, chunk_id: str) -> CodeChunk | None:
        return self._chunk_by_id.get(chunk_id)

    def get_by_annotation(self, annotation: str) -> list[CodeChunk]:
        """Return all chunks tagged with the given annotation (e.g. '@KafkaListener')."""
        norm = annotation if annotation.startswith("@") else f"@{annotation}"
        ids = self.annotation_index.get(norm, [])
        return [c for cid in ids if (c := self._chunk_by_id.get(cid))]

    def get_by_symbol(self, symbol: str) -> list[CodeChunk]:
        """Return all chunks whose symbol_name contains the given name."""
        ids = self.symbol_index.get(symbol, [])
        chunks = [c for cid in ids if (c := self._chunk_by_id.get(cid))]
        # Also partial match
        if not chunks:
            lower = symbol.lower()
            for sym_key, cids in self.symbol_index.items():
                if lower in sym_key.lower():
                    for cid in cids:
                        c = self._chunk_by_id.get(cid)
                        if c and c not in chunks:
                            chunks.append(c)
        return chunks

    def get_by_config_key(self, key: str) -> list[CodeChunk]:
        """Return chunks whose symbol_name or content contains the given config key."""
        # Exact index lookup first
        ids = self.config_key_index.get(key, [])
        chunks = [c for cid in ids if (c := self._chunk_by_id.get(cid))]
        # Partial lookup
        if not chunks:
            lower = key.lower()
            for idx_key, cids in self.config_key_index.items():
                if lower in idx_key.lower():
                    for cid in cids:
                        c = self._chunk_by_id.get(cid)
                        if c and c not in chunks:
                            chunks.append(c)
        return chunks

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def persist(self, base_dir: str | Path | None = None) -> Path:
        """Save index files to .runbook-index/<service>/<commit>/."""
        root = Path(base_dir) if base_dir else Path(_INDEX_DIR)
        index_dir = root / self.manifest.service_name / self.manifest.commit_sha
        index_dir.mkdir(parents=True, exist_ok=True)

        # manifest.json
        _write_json(index_dir / "manifest.json", self.manifest.to_dict())

        # chunks.json
        _write_json(index_dir / "chunks.json", [c.to_dict() for c in self.chunks])

        # symbols.json
        _write_json(index_dir / "symbols.json", self.symbol_index)

        # annotations.json
        _write_json(index_dir / "annotations.json", self.annotation_index)

        # config-keys.json
        _write_json(index_dir / "config-keys.json", self.config_key_index)

        # references.json (optional)
        if self.references:
            _write_json(index_dir / "references.json", [r.to_dict() for r in self.references])

        LOGGER.info(
            "Persisted code index for %s@%s: %d chunks → %s",
            self.manifest.service_name,
            self.manifest.commit_sha[:12],
            self.manifest.chunk_count,
            index_dir,
        )
        return index_dir

    @staticmethod
    def load(service_name: str, commit_sha: str, base_dir: str | Path | None = None) -> "CodeIndexStore | None":
        """Load a persisted index and validate it matches the given commit SHA."""
        root = Path(base_dir) if base_dir else Path(_INDEX_DIR)
        index_dir = root / service_name / commit_sha

        manifest_file = index_dir / "manifest.json"
        if not manifest_file.exists():
            return None

        try:
            manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            manifest = IndexManifest.from_dict(manifest_data)

            # Commit SHA validation — never silently use a stale index
            if manifest.commit_sha != commit_sha:
                LOGGER.warning(
                    "Index commit SHA mismatch: expected %s, found %s. Rebuilding.",
                    commit_sha, manifest.commit_sha,
                )
                return None

            chunks_data = json.loads((index_dir / "chunks.json").read_text(encoding="utf-8"))
            chunks = [CodeChunk.from_dict(d) for d in chunks_data]

            symbols = json.loads((index_dir / "symbols.json").read_text(encoding="utf-8"))
            annotations = json.loads((index_dir / "annotations.json").read_text(encoding="utf-8"))
            config_keys = json.loads((index_dir / "config-keys.json").read_text(encoding="utf-8"))

            refs: list[SymbolReference] = []
            refs_file = index_dir / "references.json"
            if refs_file.exists():
                refs_data = json.loads(refs_file.read_text(encoding="utf-8"))
                refs = [SymbolReference.from_dict(r) for r in refs_data]

            return CodeIndexStore(
                manifest=manifest,
                chunks=chunks,
                symbol_index=symbols,
                annotation_index=annotations,
                config_key_index=config_keys,
                references=refs,
            )

        except Exception as exc:
            LOGGER.warning("Failed to load index from %s: %s", index_dir, exc)
            return None


def load_code_index(
    service_name: str,
    commit_sha: str,
    base_dir: str | Path | None = None,
) -> "CodeIndexStore | None":
    """Load a persisted code index if it exists and matches the commit SHA."""
    return CodeIndexStore.load(service_name=service_name, commit_sha=commit_sha, base_dir=base_dir)


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
