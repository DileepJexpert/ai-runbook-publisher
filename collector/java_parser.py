"""Robust Java syntax and annotation parser for deterministic fact extraction."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger(__name__)


@dataclass
class JavaAnnotation:
    name: str  # e.g. "RequestMapping", "KafkaListener", "NotNull"
    raw_text: str
    attributes: dict[str, Any] = field(default_factory=dict)
    line_start: int = 1
    line_end: int = 1

    def get_attr(self, key: str, default: Any = None) -> Any:
        return self.attributes.get(key, default)


@dataclass
class JavaParameter:
    name: str
    param_type: str
    annotations: list[JavaAnnotation] = field(default_factory=list)
    line_number: int = 1


@dataclass
class JavaField:
    name: str
    field_type: str
    annotations: list[JavaAnnotation] = field(default_factory=list)
    initializer: str | None = None
    line_start: int = 1
    line_end: int = 1


@dataclass
class JavaMethod:
    name: str
    return_type: str
    parameters: list[JavaParameter] = field(default_factory=list)
    annotations: list[JavaAnnotation] = field(default_factory=list)
    body: str = ""
    line_start: int = 1
    line_end: int = 1


@dataclass
class JavaClass:
    name: str
    package: str = ""
    class_type: str = "class"  # class, interface, enum, record
    annotations: list[JavaAnnotation] = field(default_factory=list)
    extends_class: str | None = None
    implements_interfaces: list[str] = field(default_factory=list)
    fields: list[JavaField] = field(default_factory=list)
    methods: list[JavaMethod] = field(default_factory=list)
    raw_content: str = ""
    line_start: int = 1
    line_end: int = 1


@dataclass
class JavaParsedFile:
    file_path: str
    package: str = ""
    imports: list[str] = field(default_factory=list)
    classes: list[JavaClass] = field(default_factory=list)
    source_lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _parse_annotation_attributes(attr_text: str) -> dict[str, Any]:
    """Parse annotation attribute key-values e.g. value = "/api", method = RequestMethod.GET."""
    text = attr_text.strip()
    if not text:
        return {}

    attributes: dict[str, Any] = {}

    parts = []
    current: list[str] = []
    paren_depth = 0
    bracket_depth = 0
    brace_depth = 0
    in_quote = False
    escape = False

    for ch in text:
        if escape:
            current.append(ch)
            escape = False
            continue
        if ch == "\\":
            current.append(ch)
            escape = True
            continue
        if ch == '"':
            in_quote = not in_quote
            current.append(ch)
            continue
        if not in_quote:
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                paren_depth -= 1
            elif ch == "[":
                bracket_depth += 1
            elif ch == "]":
                bracket_depth -= 1
            elif ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
            elif ch == "," and paren_depth == 0 and bracket_depth == 0 and brace_depth == 0:
                parts.append("".join(current).strip())
                current = []
                continue
        current.append(ch)

    if current:
        parts.append("".join(current).strip())

    for part in parts:
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            key = k.strip()
            val = _parse_attr_value(v.strip())
            attributes[key] = val
        else:
            attributes["value"] = _parse_attr_value(part.strip())

    return attributes


def _parse_attr_value(val_str: str) -> Any:
    """Parse string, number, boolean, array, or enum constant."""
    val = val_str.strip()
    if val.startswith("{") and val.endswith("}"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        items = []
        for item in inner.split(","):
            items.append(_parse_attr_value(item.strip()))
        return items

    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    if val.lower() == "true":
        return True
    if val.lower() == "false":
        return False
    if val.isdigit():
        return int(val)
    if re.match(r"^\d+[LlFfDd]?$", val):
        return int(re.sub(r"[LlFfDd]", "", val))
    return val


def parse_annotations(text: str, line_offset: int = 1) -> list[JavaAnnotation]:
    """Parse all top-level annotations in a snippet of text with line ranges."""
    annotations: list[JavaAnnotation] = []
    i = 0
    n = len(text)

    while i < n:
        if text[i] == "@":
            start_pos = i
            line_start = line_offset + text[:start_pos].count("\n")
            i += 1
            name_chars = []
            while i < n and (text[i].isalnum() or text[i] in "._"):
                name_chars.append(text[i])
                i += 1
            name = "".join(name_chars).strip()
            if not name:
                continue

            short_name = name.split(".")[-1]

            # Check if has parentheses
            j = i
            while j < n and text[j].isspace():
                j += 1

            attributes: dict[str, Any] = {}
            if j < n and text[j] == "(":
                paren_depth = 0
                k = j
                in_str = False
                esc = False
                while k < n:
                    ch = text[k]
                    if esc:
                        esc = False
                        k += 1
                        continue
                    if ch == "\\":
                        esc = True
                        k += 1
                        continue
                    if ch == '"':
                        in_str = not in_str
                    elif not in_str:
                        if ch == "(":
                            paren_depth += 1
                        elif ch == ")":
                            paren_depth -= 1
                            if paren_depth == 0:
                                k += 1
                                break
                    k += 1
                raw_attr = text[j + 1 : k - 1]
                attributes = _parse_annotation_attributes(raw_attr)
                end_pos = k
                i = k
            else:
                end_pos = i
                i = end_pos

            raw_anno = text[start_pos:end_pos]
            line_end = line_offset + text[:end_pos].count("\n")
            annotations.append(
                JavaAnnotation(
                    name=short_name,
                    raw_text=raw_anno,
                    attributes=attributes,
                    line_start=line_start,
                    line_end=line_end,
                )
            )
        else:
            i += 1

    return annotations


def _find_matching_brace(text: str, open_brace_idx: int) -> int:
    depth = 0
    in_str = False
    esc = False
    i = open_brace_idx
    n = len(text)
    while i < n:
        ch = text[i]
        if esc:
            esc = False
            i += 1
            continue
        if ch == "\\":
            esc = True
            i += 1
            continue
        if ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return -1


class JavaParser:
    """Parser for Java source code extracting classes, interfaces, records, methods, fields, annotations."""

    def parse(self, file_path: str, content: str) -> JavaParsedFile:
        parsed = JavaParsedFile(file_path=file_path)
        parsed.source_lines = content.splitlines()

        # Extract package
        pkg_match = re.search(r"^\s*package\s+([\w.]+)\s*;", content, re.MULTILINE)
        if pkg_match:
            parsed.package = pkg_match.group(1).strip()

        # Extract imports
        for imp_match in re.finditer(r"^\s*import\s+(?:static\s+)?([\w.*]+)\s*;", content, re.MULTILINE):
            parsed.imports.append(imp_match.group(1).strip())

        try:
            parsed.classes = self._parse_classes(content)
        except Exception as exc:
            LOGGER.warning("Class parsing warning for %s: %s", file_path, exc)
            parsed.warnings.append(f"Class parsing warning: {exc}")

        return parsed

    def _parse_classes(self, content: str) -> list[JavaClass]:
        classes: list[JavaClass] = []
        last_scope_end = 0

        class_decl_pattern = re.compile(
            r"\b(class|interface|enum|record)\s+([A-Za-z0-9_]+)(?:<[^>{}]*>)?(?:\([^)]*\))?(?:\s+extends\s+([^{]+?))?(?:\s+implements\s+([^{]+?))?\s*\{",
            re.MULTILINE,
        )

        for match in class_decl_pattern.finditer(content):
            kind = match.group(1)
            name = match.group(2)
            extends_raw = match.group(3)
            implements_raw = match.group(4)

            extends_class = extends_raw.strip() if extends_raw else None
            implements_list = []
            if implements_raw:
                implements_list = [i.strip() for i in implements_raw.split(",") if i.strip()]

            match_start = match.start()
            line_start = content[:match_start].count("\n") + 1

            # Extract all annotations between last scope end and class declaration
            prefix_chunk = content[last_scope_end:match_start]
            prefix_offset = content[:last_scope_end].count("\n") + 1
            class_annotations = parse_annotations(prefix_chunk, line_offset=prefix_offset)

            # Find matching closing brace for this class
            brace_start = match.end() - 1
            body_end = _find_matching_brace(content, brace_start)
            if body_end == -1:
                body_end = len(content)
            line_end = content[:body_end].count("\n") + 1

            class_body = content[brace_start + 1 : body_end - 1]

            java_class = JavaClass(
                name=name,
                class_type=kind,
                annotations=class_annotations,
                extends_class=extends_class,
                implements_interfaces=implements_list,
                raw_content=class_body,
                line_start=line_start,
                line_end=line_end,
            )

            methods, fields = self._parse_class_members(class_body, line_offset=line_start)
            java_class.methods = methods
            java_class.fields = fields

            classes.append(java_class)
            last_scope_end = body_end

        return classes

    def _parse_class_members(self, class_body: str, line_offset: int) -> tuple[list[JavaMethod], list[JavaField]]:
        methods: list[JavaMethod] = []
        fields: list[JavaField] = []

        n = len(class_body)
        i = 0
        last_member_end = 0

        in_str = False
        in_char = False
        esc = False

        while i < n:
            ch = class_body[i]
            if esc:
                esc = False
                i += 1
                continue
            if ch == "\\":
                esc = True
                i += 1
                continue
            if ch == '"' and not in_char:
                in_str = not in_str
                i += 1
                continue
            if ch == "'" and not in_str:
                in_char = not in_char
                i += 1
                continue

            if not in_str and not in_char:
                if ch == "{":
                    # Method / constructor / initializer / inner class body
                    brace_start = i
                    matching_close = _find_matching_brace(class_body, brace_start)
                    if matching_close == -1:
                        matching_close = n

                    header_chunk = class_body[last_member_end:brace_start].strip()
                    method_line_start = line_offset + class_body[:last_member_end].count("\n") + 1
                    method_line_end = line_offset + class_body[:matching_close].count("\n") + 1

                    m_obj = self._parse_method_header(
                        header_chunk=header_chunk,
                        body=class_body[brace_start + 1 : matching_close - 1],
                        line_start=method_line_start,
                        line_end=method_line_end,
                    )
                    if m_obj:
                        methods.append(m_obj)

                    last_member_end = matching_close
                    i = matching_close
                    continue

                elif ch == ";":
                    # Field or abstract/interface method declaration
                    semi_pos = i
                    stmt_raw = class_body[last_member_end:semi_pos].strip()
                    stmt_line_start = line_offset + class_body[:last_member_end].count("\n") + 1
                    stmt_line_end = line_offset + class_body[: semi_pos + 1].count("\n") + 1

                    if stmt_raw:
                        # Check if method header
                        m_obj = self._parse_method_header(
                            header_chunk=stmt_raw,
                            body="",
                            line_start=stmt_line_start,
                            line_end=stmt_line_end,
                        )
                        if m_obj:
                            methods.append(m_obj)
                        else:
                            f_obj = self._parse_field_statement(
                                stmt_raw=stmt_raw,
                                line_start=stmt_line_start,
                                line_end=stmt_line_end,
                            )
                            if f_obj:
                                fields.append(f_obj)

                    last_member_end = semi_pos + 1
                    i = semi_pos + 1
                    continue

            i += 1

        return methods, fields

    def _parse_method_header(self, header_chunk: str, body: str, line_start: int, line_end: int) -> JavaMethod | None:
        # Find '(' of method parameter list (scanning past annotations)
        # Scan for '(' at depth 0
        n = len(header_chunk)
        idx = 0
        in_s = False
        esc = False
        param_paren_start = -1
        param_paren_end = -1

        # We want the method name and opening '('
        # Let's find all annotations first
        annos = parse_annotations(header_chunk, line_offset=line_start)
        clean = header_chunk
        for a in annos:
            clean = clean.replace(a.raw_text, " ")

        paren_start = clean.find("(")
        if paren_start == -1:
            return None

        # Find balanced closing ')' for parameters
        paren_depth = 0
        for i in range(paren_start, len(clean)):
            c = clean[i]
            if c == "(":
                paren_depth += 1
            elif c == ")":
                paren_depth -= 1
                if paren_depth == 0:
                    param_paren_end = i
                    break

        if param_paren_end == -1:
            return None

        before_paren = clean[:paren_start].strip()
        tokens = before_paren.split()
        if not tokens:
            return None

        method_name = tokens[-1]
        if method_name in {"if", "while", "for", "catch", "switch", "synchronized", "return", "new", "throw", "super", "this", "static", "else"}:
            return None

        ret_type = tokens[-2] if len(tokens) >= 2 else "void"

        # Now locate parameter chunk in the original header_chunk to preserve parameter annotations!
        # Method annotations are annotations before method_name in header_chunk
        name_pos = header_chunk.find(method_name)
        if name_pos != -1:
            before_name = header_chunk[:name_pos]
            method_annos = parse_annotations(before_name, line_offset=line_start)
            orig_paren_start = header_chunk.find("(", name_pos)
            if orig_paren_start != -1:
                # Find matching closing ')' in header_chunk
                p_depth = 0
                in_str_h = False
                orig_paren_end = -1
                for j in range(orig_paren_start, len(header_chunk)):
                    ch = header_chunk[j]
                    if ch == '"':
                        in_str_h = not in_str_h
                    elif not in_str_h:
                        if ch == "(":
                            p_depth += 1
                        elif ch == ")":
                            p_depth -= 1
                            if p_depth == 0:
                                orig_paren_end = j
                                break
                if orig_paren_end != -1:
                    raw_params = header_chunk[orig_paren_start + 1 : orig_paren_end].strip()
                    parameters = self._parse_parameters(raw_params, line_start)
                else:
                    parameters = []
            else:
                parameters = []
        else:
            method_annos = annos
            parameters = []

        return JavaMethod(
            name=method_name,
            return_type=ret_type,
            parameters=parameters,
            annotations=method_annos,
            body=body,
            line_start=line_start,
            line_end=line_end,
        )

    def _parse_field_statement(self, stmt_raw: str, line_start: int, line_end: int) -> JavaField | None:
        annos = parse_annotations(stmt_raw, line_offset=line_start)
        clean = stmt_raw
        for a in annos:
            clean = clean.replace(a.raw_text, " ")

        clean = clean.strip()
        if not clean or clean.startswith(("return", "import", "package", "throw", "break", "continue")):
            return None

        init_val = None
        if "=" in clean:
            decl_part, init_val = clean.split("=", 1)
            init_val = init_val.strip()
        else:
            decl_part = clean

        tokens = decl_part.split()
        non_mod_tokens = [t for t in tokens if t not in {"public", "protected", "private", "static", "final", "transient", "volatile"}]
        if len(non_mod_tokens) >= 2:
            f_name = non_mod_tokens[-1].strip()
            f_type = " ".join(non_mod_tokens[:-1]).strip()
            if "(" not in f_type and "(" not in f_name:
                return JavaField(
                    name=f_name,
                    field_type=f_type,
                    annotations=annos,
                    initializer=init_val,
                    line_start=line_start,
                    line_end=line_end,
                )
        return None

    def _parse_parameters(self, params_raw: str, method_line: int) -> list[JavaParameter]:
        params: list[JavaParameter] = []
        if not params_raw:
            return params

        param_chunks = []
        depth = 0
        cur = []
        in_str = False
        esc = False
        for ch in params_raw:
            if esc:
                esc = False
                cur.append(ch)
                continue
            if ch == "\\":
                esc = True
                cur.append(ch)
                continue
            if ch == '"':
                in_str = not in_str
                cur.append(ch)
                continue
            if not in_str:
                if ch in "<(":
                    depth += 1
                elif ch in ">)":
                    depth -= 1
                elif ch == "," and depth == 0:
                    param_chunks.append("".join(cur).strip())
                    cur = []
                    continue
            cur.append(ch)
        if cur:
            param_chunks.append("".join(cur).strip())

        for chunk in param_chunks:
            if not chunk:
                continue
            annos = parse_annotations(chunk, line_offset=method_line)
            clean = chunk
            for a in annos:
                clean = clean.replace(a.raw_text, " ")
            parts = clean.split()
            if len(parts) >= 2:
                p_name = parts[-1].strip()
                p_type = " ".join(parts[:-1]).strip()
                params.append(
                    JavaParameter(
                        name=p_name,
                        param_type=p_type,
                        annotations=annos,
                        line_number=method_line,
                    )
                )
            elif len(parts) == 1:
                params.append(
                    JavaParameter(
                        name=parts[0],
                        param_type="Object",
                        annotations=annos,
                        line_number=method_line,
                    )
                )

        return params
