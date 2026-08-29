"""Java structural code splitter for the deterministic code index.

Reuses collector.java_parser.JavaParser — no duplicate parser invention.
No LLM. No embeddings. Local deterministic parsing only.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Sequence

from collector.java_parser import (
    JavaClass,
    JavaField,
    JavaMethod,
    JavaParsedFile,
    JavaParser,
)

from .models import (
    SOURCE_SCOPE_PRODUCTION,
    SOURCE_SCOPE_TEST,
    CHUNK_TYPE_JAVA_CLASS_HEADER,
    CHUNK_TYPE_JAVA_ENUM,
    CHUNK_TYPE_JAVA_FIELD_BLOCK,
    CHUNK_TYPE_JAVA_INTERFACE,
    CHUNK_TYPE_JAVA_METHOD,
    CHUNK_TYPE_JAVA_RECORD,
    CodeChunk,
    SymbolReference,
    _compute_content_hash,
    make_chunk_id,
)

LOGGER = logging.getLogger(__name__)

# Stop words to exclude from keyword extraction
_STOP_WORDS = frozenset(
    "the a an is are was were be been being have has had do does did will would could should may "
    "might shall can cannot not this that these those with from for into out but and or if else "
    "return new throw try catch finally void null true false class public private protected static "
    "final abstract override extends implements import package super this".split()
)

# Java method-call pattern: something.methodName( or methodName(
_METHOD_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([a-z][A-Za-z0-9_]*)\s*\(")
_TYPE_REF_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]{2,})\b")


def _is_test_file(file_path: str) -> bool:
    """Return True if the file path indicates test source."""
    posix = file_path.replace("\\", "/")
    return "/test/" in posix or "/test" in posix.split("/")[-3:]


def _extract_keywords(text: str) -> tuple[str, ...]:
    """Extract meaningful identifier tokens from code text."""
    tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", text)
    seen: dict[str, None] = {}
    for t in tokens:
        tl = t.lower()
        if len(t) >= 3 and tl not in _STOP_WORDS:
            seen[tl] = None
    return tuple(seen.keys())


def _extract_method_references(chunk_id: str, body: str) -> list[SymbolReference]:
    """Extract lightweight symbol references from a method body."""
    refs: list[SymbolReference] = []
    seen: set[str] = set()

    for m in _METHOD_CALL_RE.finditer(body):
        symbol = m.group(2)
        key = f"METHOD_CALL::{symbol}"
        if key not in seen:
            seen.add(key)
            refs.append(SymbolReference(
                source_chunk_id=chunk_id,
                referenced_symbol=symbol,
                reference_type="METHOD_CALL",
            ))

    for m in _TYPE_REF_RE.finditer(body):
        symbol = m.group(1)
        # Only collect class-like names (PascalCase, length >= 3)
        if len(symbol) >= 3:
            key = f"TYPE_REFERENCE::{symbol}"
            if key not in seen:
                seen.add(key)
                refs.append(SymbolReference(
                    source_chunk_id=chunk_id,
                    referenced_symbol=symbol,
                    reference_type="TYPE_REFERENCE",
                ))

    return refs


def _split_large_method_content(
    content: str,
    max_chunk_chars: int,
) -> list[str]:
    """Split content that exceeds max_chunk_chars into parts at blank line / statement boundaries."""
    if len(content) <= max_chunk_chars:
        return [content]

    parts: list[str] = []
    lines = content.splitlines(keepends=True)
    current_lines: list[str] = []
    current_len = 0

    for line in lines:
        if current_len + len(line) > max_chunk_chars and current_lines:
            parts.append("".join(current_lines))
            current_lines = []
            current_len = 0
        current_lines.append(line)
        current_len += len(line)

    if current_lines:
        parts.append("".join(current_lines))

    return parts or [content]


class JavaCodeSplitter:
    """Splits Java source files into structural CodeChunk objects."""

    def __init__(self, java_parser: JavaParser | None = None, max_chunk_chars: int = 20_000) -> None:
        self._parser = java_parser or JavaParser()
        self.max_chunk_chars = max_chunk_chars

    def split_file(
        self,
        file_path: str,
        content: str,
    ) -> tuple[list[CodeChunk], list[SymbolReference]]:
        """Parse a Java file and return (chunks, symbol_references)."""
        source_scope = SOURCE_SCOPE_TEST if _is_test_file(file_path) else SOURCE_SCOPE_PRODUCTION
        parsed: JavaParsedFile = self._parser.parse(file_path, content)

        source_lines = content.splitlines()
        file_imports = tuple(parsed.imports)

        chunks: list[CodeChunk] = []
        refs: list[SymbolReference] = []

        for java_class in parsed.classes:
            class_chunks, class_refs = self._split_class(
                file_path=file_path,
                java_class=java_class,
                source_lines=source_lines,
                file_imports=file_imports,
                package=parsed.package,
                source_scope=source_scope,
            )
            chunks.extend(class_chunks)
            refs.extend(class_refs)

        return chunks, refs

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _split_class(
        self,
        file_path: str,
        java_class: JavaClass,
        source_lines: list[str],
        file_imports: tuple[str, ...],
        package: str,
        source_scope: str,
    ) -> tuple[list[CodeChunk], list[SymbolReference]]:
        chunks: list[CodeChunk] = []
        refs: list[SymbolReference] = []

        class_type = java_class.class_type  # class, interface, enum, record

        # Determine the correct chunk type for the class-level declaration
        if class_type == "enum":
            header_chunk_type = CHUNK_TYPE_JAVA_ENUM
        elif class_type == "interface":
            header_chunk_type = CHUNK_TYPE_JAVA_INTERFACE
        elif class_type == "record":
            header_chunk_type = CHUNK_TYPE_JAVA_RECORD
        else:
            header_chunk_type = CHUNK_TYPE_JAVA_CLASS_HEADER

        # --- Class Header Chunk ---
        header_lines = source_lines[java_class.line_start - 1 : java_class.line_end]
        # For header chunk: keep package + imports + annotations + declaration only
        # We use the raw source lines for the class declaration range
        # but cap after first opening brace for header
        header_content = _build_class_header_content(
            package=package,
            imports=list(file_imports),
            java_class=java_class,
            source_lines=source_lines,
        )

        class_annotations = tuple(f"@{a.name}" for a in java_class.annotations)
        header_chunk_id = make_chunk_id(file_path, header_chunk_type, java_class.name)

        header_chunk = CodeChunk(
            chunk_id=header_chunk_id,
            file_path=file_path,
            language="java",
            chunk_type=header_chunk_type,
            class_name=java_class.name,
            method_name=None,
            symbol_name=java_class.name,
            start_line=java_class.line_start,
            end_line=java_class.line_end,
            content=header_content,
            annotations=class_annotations,
            imports=file_imports,
            keywords=_extract_keywords(header_content),
            parent_chunk_id=None,
            content_hash=_compute_content_hash(header_content),
            source_scope=source_scope,
        )
        chunks.append(header_chunk)

        # For enums/interfaces/records: extract method chunks too
        # --- Method Chunks ---
        for method in java_class.methods:
            method_chunks, method_refs = self._split_method(
                file_path=file_path,
                java_class=java_class,
                method=method,
                source_lines=source_lines,
                file_imports=file_imports,
                parent_chunk_id=header_chunk_id,
                source_scope=source_scope,
            )
            chunks.extend(method_chunks)
            refs.extend(method_refs)

        # --- Field Block Chunk ---
        if java_class.fields:
            field_chunk = self._build_field_chunk(
                file_path=file_path,
                java_class=java_class,
                source_lines=source_lines,
                file_imports=file_imports,
                parent_chunk_id=header_chunk_id,
                source_scope=source_scope,
            )
            if field_chunk:
                chunks.append(field_chunk)

        return chunks, refs

    def _split_method(
        self,
        file_path: str,
        java_class: JavaClass,
        method: JavaMethod,
        source_lines: list[str],
        file_imports: tuple[str, ...],
        parent_chunk_id: str,
        source_scope: str,
    ) -> tuple[list[CodeChunk], list[SymbolReference]]:
        chunks: list[CodeChunk] = []
        refs: list[SymbolReference] = []

        method_lines = source_lines[method.line_start - 1 : method.line_end]
        method_content = "\n".join(method_lines)
        method_annotations = tuple(f"@{a.name}" for a in method.annotations)

        # Build method signature label for chunk ID
        param_types = ",".join(p.param_type for p in method.parameters)
        sig_label = f"{method.name}({param_types})" if param_types else method.name

        base_chunk_id = make_chunk_id(file_path, CHUNK_TYPE_JAVA_METHOD, f"{java_class.name}.{sig_label}")

        if len(method_content) <= self.max_chunk_chars:
            chunk = CodeChunk(
                chunk_id=base_chunk_id,
                file_path=file_path,
                language="java",
                chunk_type=CHUNK_TYPE_JAVA_METHOD,
                class_name=java_class.name,
                method_name=method.name,
                symbol_name=f"{java_class.name}.{method.name}",
                start_line=method.line_start,
                end_line=method.line_end,
                content=method_content,
                annotations=method_annotations,
                imports=file_imports,
                keywords=_extract_keywords(method_content),
                parent_chunk_id=parent_chunk_id,
                content_hash=_compute_content_hash(method_content),
                source_scope=source_scope,
            )
            chunks.append(chunk)
            refs.extend(_extract_method_references(base_chunk_id, method.body))
        else:
            # Split large method into parts
            parts = _split_large_method_content(method_content, self.max_chunk_chars)
            current_line = method.line_start
            for idx, part_content in enumerate(parts, start=1):
                part_lines = part_content.count("\n") + 1
                part_end = current_line + part_lines - 1
                part_chunk_id = make_chunk_id(
                    file_path, CHUNK_TYPE_JAVA_METHOD, f"{java_class.name}.{sig_label}__PART_{idx}"
                )
                chunk = CodeChunk(
                    chunk_id=part_chunk_id,
                    file_path=file_path,
                    language="java",
                    chunk_type=CHUNK_TYPE_JAVA_METHOD,
                    class_name=java_class.name,
                    method_name=method.name,
                    symbol_name=f"{java_class.name}.{method.name}",
                    start_line=current_line,
                    end_line=part_end,
                    content=part_content,
                    annotations=method_annotations if idx == 1 else (),
                    imports=file_imports if idx == 1 else (),
                    keywords=_extract_keywords(part_content),
                    parent_chunk_id=base_chunk_id,
                    content_hash=_compute_content_hash(part_content),
                    source_scope=source_scope,
                )
                chunks.append(chunk)
                refs.extend(_extract_method_references(part_chunk_id, part_content))
                current_line = part_end + 1

        return chunks, refs

    def _build_field_chunk(
        self,
        file_path: str,
        java_class: JavaClass,
        source_lines: list[str],
        file_imports: tuple[str, ...],
        parent_chunk_id: str,
        source_scope: str,
    ) -> CodeChunk | None:
        if not java_class.fields:
            return None

        field_lines: list[str] = []
        min_line = java_class.line_end
        max_line = java_class.line_start

        for f in java_class.fields:
            min_line = min(min_line, f.line_start)
            max_line = max(max_line, f.line_end)
            for src_line in source_lines[f.line_start - 1 : f.line_end]:
                field_lines.append(src_line)
            field_lines.append("")  # separator

        content = "\n".join(field_lines).strip()
        if not content:
            return None

        field_annotations = tuple(
            f"@{a.name}"
            for fld in java_class.fields
            for a in fld.annotations
        )

        chunk_id = make_chunk_id(file_path, CHUNK_TYPE_JAVA_FIELD_BLOCK, java_class.name)
        return CodeChunk(
            chunk_id=chunk_id,
            file_path=file_path,
            language="java",
            chunk_type=CHUNK_TYPE_JAVA_FIELD_BLOCK,
            class_name=java_class.name,
            method_name=None,
            symbol_name=f"{java_class.name}.__fields__",
            start_line=min_line,
            end_line=max_line,
            content=content,
            annotations=field_annotations,
            imports=file_imports,
            keywords=_extract_keywords(content),
            parent_chunk_id=parent_chunk_id,
            content_hash=_compute_content_hash(content),
            source_scope=source_scope,
        )


def _build_class_header_content(
    package: str,
    imports: list[str],
    java_class: JavaClass,
    source_lines: list[str],
) -> str:
    """Build a concise class header string: package + imports + class declaration."""
    lines: list[str] = []

    if package:
        lines.append(f"package {package};")
        lines.append("")

    if imports:
        for imp in imports[:30]:  # cap imports to avoid huge headers
            lines.append(f"import {imp};")
        if len(imports) > 30:
            lines.append(f"// ... {len(imports) - 30} more imports")
        lines.append("")

    # Annotations
    for anno in java_class.annotations:
        lines.append(anno.raw_text)

    # Class declaration line
    decl_line = source_lines[java_class.line_start - 1] if source_lines else ""
    lines.append(decl_line)

    # extends / implements
    if java_class.extends_class:
        pass  # already in decl_line
    if java_class.implements_interfaces:
        pass  # already in decl_line

    # Add a short excerpt of class body (constants, interface method signatures)
    # Only for interface/enum — include raw_content excerpt
    if java_class.class_type in ("enum", "interface"):
        body_excerpt = java_class.raw_content[:2000].strip()
        if body_excerpt:
            lines.append("// --- body ---")
            lines.append(body_excerpt)

    return "\n".join(lines)
