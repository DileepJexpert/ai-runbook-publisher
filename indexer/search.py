"""Deterministic keyword + symbol + annotation search engine for the code index.

No LLM. No embeddings. No ML ranking.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Sequence

from .index_store import CodeIndexStore
from .models import (
    SOURCE_SCOPE_PRODUCTION,
    CodeChunk,
    SearchHit,
)

# ---------------------------------------------------------------------------
# Stop words — excluded from query tokenization
# ---------------------------------------------------------------------------

_STOP_WORDS = frozenset(
    "the a an is are was were be been being have has had do does did will would could should "
    "may might shall can cannot not what how does where when why which who this that these "
    "those from into out but and or if else get set use run call find get".split()
)

# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

_SCORE_EXACT_SYMBOL = 10.0
_SCORE_METHOD_CLASS_NAME = 8.0
_SCORE_ANNOTATION_MATCH = 7.0
_SCORE_CONFIG_KEY_EXACT = 7.0
_SCORE_KEYWORD_IN_HEADER = 5.0
_SCORE_KEYWORD_IN_CONTENT = 2.0
_SCORE_MULTI_TERM_BONUS = 1.5  # per additional term matched
_SCORE_PRODUCTION_BOOST = 1.0

_MAX_TOP_K = 50


def _tokenize(query: str) -> list[str]:
    """Lowercase, split, and filter stop words from a query string."""
    raw = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", query)
    return [t.lower() for t in raw if t.lower() not in _STOP_WORDS]


class CodeSearchEngine:
    """Deterministic multi-mode search engine over a CodeIndexStore."""

    def __init__(self, store: CodeIndexStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 10,
        file_glob: str | None = None,
        chunk_types: set[str] | None = None,
        source_scope: str | None = None,
    ) -> list[SearchHit]:
        """Search by keyword query with optional filters."""
        top_k = min(max(1, top_k), _MAX_TOP_K)
        terms = _tokenize(query)
        if not terms:
            return []

        hits: list[SearchHit] = []
        for chunk in self._store.chunks:
            if not self._passes_filters(chunk, file_glob, chunk_types, source_scope):
                continue
            score, matched = self._score_chunk(chunk, terms, query)
            if score > 0:
                hits.append(SearchHit(chunk=chunk, score=score, matched_terms=tuple(matched)))

        hits.sort(key=lambda h: (-h.score, h.chunk.file_path, h.chunk.start_line))
        return hits[:top_k]

    def search_symbol(self, symbol: str, top_k: int = 20) -> list[SearchHit]:
        """Search by exact or partial symbol name."""
        top_k = min(max(1, top_k), _MAX_TOP_K)
        lower_sym = symbol.lower()
        hits: list[SearchHit] = []

        seen_ids: set[str] = set()

        # Exact index lookup
        for chunk in self._store.get_by_symbol(symbol):
            if chunk.chunk_id not in seen_ids:
                seen_ids.add(chunk.chunk_id)
                score = self._symbol_score(chunk, symbol, lower_sym)
                hits.append(SearchHit(chunk=chunk, score=score, matched_terms=(symbol,)))

        # Fallback: scan all chunks for partial match in symbol_name / class_name / method_name
        if not hits:
            for chunk in self._store.chunks:
                if chunk.chunk_id in seen_ids:
                    continue
                score = self._symbol_score(chunk, symbol, lower_sym)
                if score > 0:
                    seen_ids.add(chunk.chunk_id)
                    hits.append(SearchHit(chunk=chunk, score=score, matched_terms=(symbol,)))

        hits.sort(key=lambda h: (-h.score, h.chunk.file_path, h.chunk.start_line))
        return hits[:top_k]

    def get_by_annotation(self, annotation: str) -> list[CodeChunk]:
        """Return all chunks tagged with the given annotation."""
        return self._store.get_by_annotation(annotation)

    def search_config_key(self, key: str) -> list[CodeChunk]:
        """Return chunks matching a config key."""
        chunks = self._store.get_by_config_key(key)
        if not chunks:
            # Fallback: scan content
            lower_key = key.lower().replace("-", ".").replace("_", ".")
            for c in self._store.chunks:
                if lower_key in c.content.lower() and c not in chunks:
                    chunks.append(c)
        return chunks[:20]

    def retrieve_context(
        self,
        query: str,
        top_k: int = 10,
        max_chars: int = 60_000,
    ) -> list[CodeChunk]:
        """Return top matching chunks within a character budget."""
        hits = self.search(query, top_k=min(top_k, _MAX_TOP_K))
        selected: list[CodeChunk] = []
        total_chars = 0
        for hit in hits:
            chunk_len = len(hit.chunk.content)
            if total_chars + chunk_len > max_chars:
                break
            selected.append(hit.chunk)
            total_chars += chunk_len
        return selected

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _passes_filters(
        self,
        chunk: CodeChunk,
        file_glob: str | None,
        chunk_types: set[str] | None,
        source_scope: str | None,
    ) -> bool:
        if file_glob and not (
            fnmatch.fnmatch(chunk.file_path, file_glob)
            or fnmatch.fnmatch(chunk.file_path.split("/")[-1], file_glob)
        ):
            return False
        if chunk_types and chunk.chunk_type not in chunk_types:
            return False
        if source_scope and chunk.source_scope != source_scope:
            return False
        return True

    def _score_chunk(self, chunk: CodeChunk, terms: list[str], raw_query: str) -> tuple[float, list[str]]:
        score = 0.0
        matched: list[str] = []

        content_lower = chunk.content.lower()
        symbol_lower = (chunk.symbol_name or "").lower()
        class_lower = (chunk.class_name or "").lower()
        method_lower = (chunk.method_name or "").lower()
        anno_lowers = {a.lower() for a in chunk.annotations}
        kw_lowers = {k.lower() for k in chunk.keywords}

        for term in terms:
            term_matched = False

            # Exact symbol match
            if term == symbol_lower or term in symbol_lower.split("."):
                score += _SCORE_EXACT_SYMBOL
                term_matched = True

            # Method / class name match
            if term in method_lower or term in class_lower:
                score += _SCORE_METHOD_CLASS_NAME
                term_matched = True

            # Annotation match
            anno_hit = any(term in a for a in anno_lowers)
            if anno_hit:
                score += _SCORE_ANNOTATION_MATCH
                term_matched = True

            # Config key
            config_key_lower = (chunk.symbol_name or "").lower().replace("-", ".").replace("_", ".")
            if term in config_key_lower:
                score += _SCORE_CONFIG_KEY_EXACT
                term_matched = True

            # Keyword in header / content
            if term in kw_lowers:
                score += _SCORE_KEYWORD_IN_HEADER
                term_matched = True
            elif term in content_lower:
                score += _SCORE_KEYWORD_IN_CONTENT
                term_matched = True

            if term_matched:
                matched.append(term)

        if len(matched) > 1:
            score += _SCORE_MULTI_TERM_BONUS * (len(matched) - 1)

        if chunk.source_scope == SOURCE_SCOPE_PRODUCTION:
            score += _SCORE_PRODUCTION_BOOST

        return score, matched

    def _symbol_score(self, chunk: CodeChunk, symbol: str, lower_sym: str) -> float:
        score = 0.0
        sn_lower = (chunk.symbol_name or "").lower()
        cn_lower = (chunk.class_name or "").lower()
        mn_lower = (chunk.method_name or "").lower()

        if lower_sym == sn_lower or lower_sym == cn_lower or lower_sym == mn_lower:
            score += _SCORE_EXACT_SYMBOL
        elif lower_sym in sn_lower or lower_sym in cn_lower or lower_sym in mn_lower:
            score += _SCORE_METHOD_CLASS_NAME
        elif lower_sym in chunk.content.lower():
            score += _SCORE_KEYWORD_IN_CONTENT

        if chunk.source_scope == SOURCE_SCOPE_PRODUCTION:
            score += _SCORE_PRODUCTION_BOOST

        return score
