"""Splitters for YAML, Properties, SQL, XML, and Markdown files.

No LLM. No embeddings. Local deterministic parsing only.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Sequence

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from .models import (
    SOURCE_SCOPE_PRODUCTION,
    CHUNK_TYPE_CONFIG_SECTION,
    CHUNK_TYPE_GENERIC_TEXT,
    CHUNK_TYPE_PROPERTIES_SECTION,
    CHUNK_TYPE_README_SECTION,
    CHUNK_TYPE_SQL_STATEMENT,
    CHUNK_TYPE_XML_SECTION,
    CodeChunk,
    _compute_content_hash,
    make_chunk_id,
)

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# YAML splitter
# ---------------------------------------------------------------------------

class YamlSplitter:
    """Splits YAML config files by top-level keys into CONFIG_SECTION chunks."""

    def split_file(self, file_path: str, content: str) -> list[CodeChunk]:
        if not _YAML_AVAILABLE:
            return self._fallback_split(file_path, content)

        chunks: list[CodeChunk] = []
        lines = content.splitlines()

        # Collect top-level keys and their line ranges
        top_level_sections: list[tuple[str, int, int]] = []  # (key, start_line_1based, end_line_1based)
        current_key: str | None = None
        current_start: int = 1

        for idx, line in enumerate(lines, start=1):
            stripped = line.rstrip()
            # Top-level key: no leading spaces, not a comment, contains ':'
            if stripped and not stripped.startswith("#") and not stripped.startswith(" ") and not stripped.startswith("\t"):
                colon_pos = stripped.find(":")
                if colon_pos > 0:
                    key_name = stripped[:colon_pos].strip()
                    if key_name and key_name.isidentifier() or re.match(r"^[a-zA-Z0-9_\-]+$", key_name):
                        if current_key is not None:
                            top_level_sections.append((current_key, current_start, idx - 1))
                        current_key = key_name
                        current_start = idx

        if current_key is not None:
            top_level_sections.append((current_key, current_start, len(lines)))

        if not top_level_sections:
            # Fallback: single chunk for whole file
            return self._whole_file_chunk(file_path, content)

        for key_name, start, end in top_level_sections:
            section_lines = lines[start - 1 : end]
            section_content = "\n".join(section_lines).strip()
            if not section_content:
                continue

            chunk_id = make_chunk_id(file_path, CHUNK_TYPE_CONFIG_SECTION, key_name)
            chunks.append(CodeChunk(
                chunk_id=chunk_id,
                file_path=file_path,
                language="yaml",
                chunk_type=CHUNK_TYPE_CONFIG_SECTION,
                class_name=None,
                method_name=None,
                symbol_name=key_name,
                start_line=start,
                end_line=end,
                content=section_content,
                annotations=(),
                imports=(),
                keywords=tuple(self._yaml_keywords(section_content)),
                parent_chunk_id=None,
                content_hash=_compute_content_hash(section_content),
                source_scope=SOURCE_SCOPE_PRODUCTION,
            ))

        return chunks

    def _yaml_keywords(self, content: str) -> list[str]:
        """Extract config keys as keywords."""
        keys: list[str] = []
        seen: set[str] = set()
        for line in content.splitlines():
            stripped = line.strip()
            if ":" in stripped and not stripped.startswith("#"):
                k = stripped.split(":")[0].strip(" \t-")
                if k and k not in seen:
                    seen.add(k)
                    # Also add camelCase fragments
                    for part in re.split(r"[-_\.]", k):
                        if part and part.lower() not in seen:
                            seen.add(part.lower())
                            keys.append(part.lower())
                    keys.append(k)
        return keys

    def _fallback_split(self, file_path: str, content: str) -> list[CodeChunk]:
        return self._whole_file_chunk(file_path, content)

    def _whole_file_chunk(self, file_path: str, content: str) -> list[CodeChunk]:
        chunk_id = make_chunk_id(file_path, CHUNK_TYPE_CONFIG_SECTION, "__root__")
        return [CodeChunk(
            chunk_id=chunk_id,
            file_path=file_path,
            language="yaml",
            chunk_type=CHUNK_TYPE_CONFIG_SECTION,
            class_name=None,
            method_name=None,
            symbol_name="__root__",
            start_line=1,
            end_line=content.count("\n") + 1,
            content=content.strip(),
            annotations=(),
            imports=(),
            keywords=(),
            parent_chunk_id=None,
            content_hash=_compute_content_hash(content),
            source_scope=SOURCE_SCOPE_PRODUCTION,
        )]


# ---------------------------------------------------------------------------
# Properties splitter
# ---------------------------------------------------------------------------

class PropertiesSplitter:
    """Groups .properties file keys by common prefix into PROPERTIES_SECTION chunks."""

    def split_file(self, file_path: str, content: str) -> list[CodeChunk]:
        # Collect key -> (value, line_number)
        key_lines: list[tuple[str, str, int]] = []  # (key, line_content, line_no)
        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("!"):
                continue
            if "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                key_lines.append((k, line, idx))
            elif ":" in stripped:
                k = stripped.split(":", 1)[0].strip()
                key_lines.append((k, line, idx))

        if not key_lines:
            return []

        # Group by prefix (first 2 dot-segments)
        groups: dict[str, list[tuple[str, int]]] = {}
        for k, line_content, line_no in key_lines:
            parts = k.split(".")
            prefix = ".".join(parts[:2]) if len(parts) >= 2 else parts[0]
            if prefix not in groups:
                groups[prefix] = []
            groups[prefix].append((line_content, line_no))

        chunks: list[CodeChunk] = []
        for prefix, members in sorted(groups.items()):
            line_nos = [ln for _, ln in members]
            section_lines = [lc for lc, _ in members]
            section_content = "\n".join(section_lines)
            start_line = min(line_nos)
            end_line = max(line_nos)

            chunk_id = make_chunk_id(file_path, CHUNK_TYPE_PROPERTIES_SECTION, prefix)
            chunks.append(CodeChunk(
                chunk_id=chunk_id,
                file_path=file_path,
                language="properties",
                chunk_type=CHUNK_TYPE_PROPERTIES_SECTION,
                class_name=None,
                method_name=None,
                symbol_name=prefix,
                start_line=start_line,
                end_line=end_line,
                content=section_content,
                annotations=(),
                imports=(),
                keywords=tuple(self._property_keywords(section_content)),
                parent_chunk_id=None,
                content_hash=_compute_content_hash(section_content),
                source_scope=SOURCE_SCOPE_PRODUCTION,
            ))

        return chunks

    def _property_keywords(self, content: str) -> list[str]:
        kws: list[str] = []
        seen: set[str] = set()
        for line in content.splitlines():
            if "=" in line:
                k = line.split("=")[0].strip()
            elif ":" in line:
                k = line.split(":")[0].strip()
            else:
                continue
            for seg in re.split(r"[\.\-_]", k):
                seg = seg.lower().strip()
                if seg and seg not in seen and len(seg) >= 2:
                    seen.add(seg)
                    kws.append(seg)
        return kws


# ---------------------------------------------------------------------------
# SQL splitter
# ---------------------------------------------------------------------------

_SQL_STATEMENT_STARTS = re.compile(
    r"^\s*(CREATE\s+(?:TABLE|INDEX|VIEW|SEQUENCE|FUNCTION|PROCEDURE|TRIGGER)|"
    r"ALTER\s+TABLE|DROP\s+(?:TABLE|INDEX|VIEW)|INSERT\s+INTO|UPDATE\s+\w|"
    r"DELETE\s+FROM)",
    re.IGNORECASE | re.MULTILINE,
)

_SQL_TABLE_NAME_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\"\[]?[\w.]+[`\"\]]?)",
    re.IGNORECASE,
)
_SQL_ALTER_RE = re.compile(r"ALTER\s+TABLE\s+([`\"\[]?[\w.]+[`\"\]]?)", re.IGNORECASE)
_SQL_INDEX_RE = re.compile(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\"\[]?[\w.]+[`\"\]]?)", re.IGNORECASE)


class SqlSplitter:
    """Splits SQL migration files into one SQL_STATEMENT chunk per statement."""

    def split_file(self, file_path: str, content: str) -> list[CodeChunk]:
        # Split on semicolon boundaries
        raw_statements = content.split(";")
        chunks: list[CodeChunk] = []

        current_line = 1
        stmt_count = 0

        for raw in raw_statements:
            stmt = raw.strip()
            if not stmt:
                current_line += raw.count("\n")
                continue

            stmt_lines = stmt.count("\n") + 1
            end_line = current_line + stmt_lines - 1

            symbol = self._extract_symbol(stmt, stmt_count)
            chunk_id = make_chunk_id(file_path, CHUNK_TYPE_SQL_STATEMENT, symbol)

            # Deduplicate chunk IDs if same symbol appears multiple times
            if any(c.chunk_id == chunk_id for c in chunks):
                chunk_id = f"{chunk_id}_{stmt_count}"

            chunks.append(CodeChunk(
                chunk_id=chunk_id,
                file_path=file_path,
                language="sql",
                chunk_type=CHUNK_TYPE_SQL_STATEMENT,
                class_name=None,
                method_name=None,
                symbol_name=symbol,
                start_line=current_line,
                end_line=end_line,
                content=stmt + ";",
                annotations=(),
                imports=(),
                keywords=tuple(self._sql_keywords(stmt)),
                parent_chunk_id=None,
                content_hash=_compute_content_hash(stmt),
                source_scope=SOURCE_SCOPE_PRODUCTION,
            ))

            current_line = end_line + 1
            stmt_count += 1

        return chunks

    def _extract_symbol(self, stmt: str, idx: int) -> str:
        m = _SQL_TABLE_NAME_RE.search(stmt)
        if m:
            return f"CREATE_TABLE_{m.group(1).strip('`\"[]')}"
        m = _SQL_ALTER_RE.search(stmt)
        if m:
            return f"ALTER_TABLE_{m.group(1).strip('`\"[]')}"
        m = _SQL_INDEX_RE.search(stmt)
        if m:
            return f"CREATE_INDEX_{m.group(1).strip('`\"[]')}"
        # Fallback to first significant word
        words = stmt.split()
        label = "_".join(w.upper() for w in words[:3] if w.isalpha())
        return label or f"STMT_{idx}"

    def _sql_keywords(self, stmt: str) -> list[str]:
        tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", stmt)
        seen: dict[str, None] = {}
        sql_stop = {"CREATE", "TABLE", "ALTER", "INDEX", "INSERT", "INTO", "SELECT", "FROM",
                    "WHERE", "AND", "NOT", "NULL", "DEFAULT", "PRIMARY", "KEY", "FOREIGN",
                    "REFERENCES", "CONSTRAINT", "EXISTS", "UNIQUE", "VARCHAR", "INTEGER",
                    "BIGINT", "BOOLEAN", "TIMESTAMP", "TEXT", "ADD", "COLUMN", "DROP"}
        for t in tokens:
            tl = t.lower()
            if t.upper() not in sql_stop and tl not in seen:
                seen[tl] = None
        return list(seen.keys())


# ---------------------------------------------------------------------------
# XML splitter
# ---------------------------------------------------------------------------

class XmlSplitter:
    """Splits pom.xml / Liquibase XML into logical XML_SECTION chunks."""

    def split_file(self, file_path: str, content: str) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        lines = content.splitlines()

        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            # Fallback: single generic chunk
            chunk_id = make_chunk_id(file_path, CHUNK_TYPE_XML_SECTION, "__root__")
            return [CodeChunk(
                chunk_id=chunk_id,
                file_path=file_path,
                language="xml",
                chunk_type=CHUNK_TYPE_XML_SECTION,
                class_name=None,
                method_name=None,
                symbol_name="__root__",
                start_line=1,
                end_line=len(lines),
                content=content[:5000],
                annotations=(),
                imports=(),
                keywords=(),
                parent_chunk_id=None,
                content_hash=_compute_content_hash(content),
                source_scope=SOURCE_SCOPE_PRODUCTION,
            )]

        # For pom.xml: chunk major sections: dependencies, build, plugins
        tag_name = root.tag.split("}")[-1] if "}" in root.tag else root.tag

        if tag_name == "project":
            chunks.extend(self._split_pom(file_path, root, content, lines))
        else:
            # Liquibase or other XML: chunk by top-level children
            chunks.extend(self._split_generic_xml(file_path, root, content, lines))

        return chunks or self._fallback(file_path, content, lines)

    def _split_pom(self, file_path: str, root: ET.Element, content: str, lines: list[str]) -> list[CodeChunk]:
        chunks: list[CodeChunk] = []
        ns_re = re.compile(r"\{[^}]*\}")

        # Extract major pom sections by searching for their text blocks
        section_names = ["dependencies", "build", "plugins", "dependencyManagement",
                         "properties", "profiles", "repositories", "parent"]

        for section in section_names:
            # Simple line-range search
            open_tag = f"<{section}"
            close_tag = f"</{section}>"
            start_line = None
            end_line = None

            for idx, line in enumerate(lines, start=1):
                if open_tag in line and start_line is None:
                    start_line = idx
                if close_tag in line and start_line is not None:
                    end_line = idx
                    break

            if start_line and end_line:
                sec_lines = lines[start_line - 1 : end_line]
                sec_content = "\n".join(sec_lines)
                chunk_id = make_chunk_id(file_path, CHUNK_TYPE_XML_SECTION, section)
                chunks.append(CodeChunk(
                    chunk_id=chunk_id,
                    file_path=file_path,
                    language="xml",
                    chunk_type=CHUNK_TYPE_XML_SECTION,
                    class_name=None,
                    method_name=None,
                    symbol_name=section,
                    start_line=start_line,
                    end_line=end_line,
                    content=sec_content,
                    annotations=(),
                    imports=(),
                    keywords=tuple(self._xml_keywords(sec_content)),
                    parent_chunk_id=None,
                    content_hash=_compute_content_hash(sec_content),
                    source_scope=SOURCE_SCOPE_PRODUCTION,
                ))

        return chunks

    def _split_generic_xml(self, file_path: str, root: ET.Element, content: str, lines: list[str]) -> list[CodeChunk]:
        # Chunk each top-level child element
        chunks: list[CodeChunk] = []
        child_count: dict[str, int] = {}

        for child in root:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            child_count[tag] = child_count.get(tag, 0) + 1
            symbol = f"{tag}_{child_count[tag]}"

            child_content = ET.tostring(child, encoding="unicode")[:3000]
            chunk_id = make_chunk_id(file_path, CHUNK_TYPE_XML_SECTION, symbol)
            chunks.append(CodeChunk(
                chunk_id=chunk_id,
                file_path=file_path,
                language="xml",
                chunk_type=CHUNK_TYPE_XML_SECTION,
                class_name=None,
                method_name=None,
                symbol_name=symbol,
                start_line=1,
                end_line=len(lines),
                content=child_content,
                annotations=(),
                imports=(),
                keywords=tuple(self._xml_keywords(child_content)),
                parent_chunk_id=None,
                content_hash=_compute_content_hash(child_content),
                source_scope=SOURCE_SCOPE_PRODUCTION,
            ))

        return chunks

    def _fallback(self, file_path: str, content: str, lines: list[str]) -> list[CodeChunk]:
        chunk_id = make_chunk_id(file_path, CHUNK_TYPE_XML_SECTION, "__root__")
        return [CodeChunk(
            chunk_id=chunk_id,
            file_path=file_path,
            language="xml",
            chunk_type=CHUNK_TYPE_XML_SECTION,
            class_name=None,
            method_name=None,
            symbol_name="__root__",
            start_line=1,
            end_line=len(lines),
            content=content[:5000],
            annotations=(),
            imports=(),
            keywords=(),
            parent_chunk_id=None,
            content_hash=_compute_content_hash(content),
            source_scope=SOURCE_SCOPE_PRODUCTION,
        )]

    def _xml_keywords(self, content: str) -> list[str]:
        tokens = re.findall(r"\b[A-Za-z][A-Za-z0-9\-\.]{2,}\b", content)
        seen: dict[str, None] = {}
        for t in tokens:
            tl = t.lower()
            if tl not in seen:
                seen[tl] = None
        return list(seen.keys())[:40]


# ---------------------------------------------------------------------------
# Markdown splitter
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


class MarkdownSplitter:
    """Splits Markdown files into README_SECTION chunks by heading."""

    def split_file(self, file_path: str, content: str) -> list[CodeChunk]:
        lines = content.splitlines()
        headings: list[tuple[int, str]] = []  # (line_no_1based, heading_text)

        for idx, line in enumerate(lines, start=1):
            m = _HEADING_RE.match(line)
            if m:
                headings.append((idx, m.group(2).strip()))

        if not headings:
            # Single chunk for the whole file
            chunk_id = make_chunk_id(file_path, CHUNK_TYPE_README_SECTION, "root")
            return [CodeChunk(
                chunk_id=chunk_id,
                file_path=file_path,
                language="markdown",
                chunk_type=CHUNK_TYPE_README_SECTION,
                class_name=None,
                method_name=None,
                symbol_name="root",
                start_line=1,
                end_line=len(lines),
                content=content[:5000],
                annotations=(),
                imports=(),
                keywords=self._md_keywords(content),
                parent_chunk_id=None,
                content_hash=_compute_content_hash(content),
                source_scope=SOURCE_SCOPE_PRODUCTION,
            )]

        chunks: list[CodeChunk] = []
        for i, (start_line, heading_text) in enumerate(headings):
            end_line = headings[i + 1][0] - 1 if i + 1 < len(headings) else len(lines)
            section_lines = lines[start_line - 1 : end_line]
            section_content = "\n".join(section_lines).strip()

            # Sanitize heading to make safe symbol
            symbol = re.sub(r"[^A-Za-z0-9_\-]", "_", heading_text)[:60]
            chunk_id = make_chunk_id(file_path, CHUNK_TYPE_README_SECTION, symbol)

            # Deduplicate
            if any(c.chunk_id == chunk_id for c in chunks):
                chunk_id = f"{chunk_id}_{i}"

            chunks.append(CodeChunk(
                chunk_id=chunk_id,
                file_path=file_path,
                language="markdown",
                chunk_type=CHUNK_TYPE_README_SECTION,
                class_name=None,
                method_name=None,
                symbol_name=symbol,
                start_line=start_line,
                end_line=end_line,
                content=section_content,
                annotations=(),
                imports=(),
                keywords=self._md_keywords(section_content),
                parent_chunk_id=None,
                content_hash=_compute_content_hash(section_content),
                source_scope=SOURCE_SCOPE_PRODUCTION,
            ))

        return chunks

    def _md_keywords(self, content: str) -> tuple[str, ...]:
        tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", content)
        seen: dict[str, None] = {}
        stop = {"the", "and", "for", "with", "from", "that", "this", "are", "not", "you",
                "can", "use", "will", "its", "how", "run", "your", "add", "see"}
        for t in tokens:
            tl = t.lower()
            if tl not in stop and tl not in seen:
                seen[tl] = None
        return tuple(seen.keys())
