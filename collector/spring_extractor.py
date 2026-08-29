"""Spring API and Bean Validation fact extractor."""

from __future__ import annotations

import logging
import re
from typing import Any

from .java_parser import JavaClass, JavaParsedFile, JavaParser
from .models import ApiEndpoint, SourceEvidence, ValidationRule

LOGGER = logging.getLogger(__name__)

MAPPING_HTTP_METHODS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "PatchMapping": "PATCH",
    "DeleteMapping": "DELETE",
}

VALIDATION_ANNOTATIONS = {
    "NotNull": "must not be null",
    "NotBlank": "must not be blank",
    "NotEmpty": "must not be empty",
    "Positive": "must be greater than zero",
    "PositiveOrZero": "must be greater than or equal to zero",
    "Negative": "must be less than zero",
    "NegativeOrZero": "must be less than or equal to zero",
    "Min": "minimum value",
    "Max": "maximum value",
    "DecimalMin": "minimum decimal value",
    "DecimalMax": "maximum decimal value",
    "Size": "size constraint",
    "Pattern": "must match pattern",
    "Email": "must be a well-formed email address",
    "Past": "must be a date in the past",
    "PastOrPresent": "must be a date in the past or present",
    "Future": "must be a date in the future",
    "FutureOrPresent": "must be a date in the future or present",
    "Digits": "digit count constraint",
}

AUTH_ANNOTATION_NAMES = {"PreAuthorize", "Secured", "RolesAllowed", "PermitAll", "DenyAll"}


def _normalize_path(base: str, sub: str) -> str:
    """Combine base path and sub path cleanly into a valid URI pattern."""
    b = base.strip()
    s = sub.strip()

    if not b and not s:
        return "/"

    # Strip surrounding quotes if present
    if (b.startswith('"') and b.endswith('"')) or (b.startswith("'") and b.endswith("'")):
        b = b[1:-1]
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]

    if b.endswith("/"):
        b = b[:-1]
    if s.startswith("/"):
        s = s[1:]

    combined = f"{b}/{s}" if b else f"/{s}"
    if not combined.startswith("/"):
        combined = "/" + combined
    if len(combined) > 1 and combined.endswith("/"):
        combined = combined[:-1]
    return combined


def _extract_paths_from_annotation(anno_attrs: dict[str, Any]) -> list[str]:
    """Extract list of path strings from path or value attribute."""
    paths: list[str] = []
    raw = anno_attrs.get("path") or anno_attrs.get("value")
    if raw is None:
        return [""]
    if isinstance(raw, list):
        for item in raw:
            paths.append(str(item).strip('"\''))
    else:
        paths.append(str(raw).strip('"\''))
    return paths if paths else [""]


def _extract_methods_from_request_mapping(anno_attrs: dict[str, Any]) -> list[str]:
    """Extract HTTP methods from @RequestMapping(method = ...)."""
    raw_method = anno_attrs.get("method")
    if not raw_method:
        return ["GET"]  # Default in Spring if unspecified
    methods = []
    if isinstance(raw_method, list):
        for m in raw_method:
            clean = str(m).replace("RequestMethod.", "").upper()
            methods.append(clean)
    else:
        clean = str(raw_method).replace("RequestMethod.", "").upper()
        methods.append(clean)
    return methods


def _build_mechanical_description(annotation_name: str, params: dict[str, Any]) -> str:
    """Build a non-interpretive mechanical description of validation parameters."""
    if annotation_name == "Size":
        min_v = params.get("min")
        max_v = params.get("max")
        if min_v is not None and max_v is not None:
            return f"size between {min_v} and {max_v}"
        if min_v is not None:
            return f"minimum size {min_v}"
        if max_v is not None:
            return f"maximum size {max_v}"
        return "size constraint"
    if annotation_name in {"Min", "DecimalMin"}:
        val = params.get("value")
        return f"minimum value {val}" if val is not None else "minimum value constraint"
    if annotation_name in {"Max", "DecimalMax"}:
        val = params.get("value")
        return f"maximum value {val}" if val is not None else "maximum value constraint"
    if annotation_name == "Pattern":
        regexp = params.get("regexp") or params.get("value")
        return f"must match pattern '{regexp}'" if regexp is not None else "pattern constraint"
    if annotation_name in VALIDATION_ANNOTATIONS:
        return VALIDATION_ANNOTATIONS[annotation_name]
    return f"validation constraint @{annotation_name}"


class SpringExtractor:
    """Extracts Spring MVC/REST endpoints and Bean Validation rules from parsed Java files."""

    def __init__(self, parser: JavaParser) -> None:
        self.parser = parser

    def extract_apis(self, parsed_files: list[JavaParsedFile]) -> list[ApiEndpoint]:
        endpoints: list[ApiEndpoint] = []

        for pfile in parsed_files:
            for cls in pfile.classes:
                # Check for Controller or RestController annotation
                is_controller = any(a.name in {"RestController", "Controller"} for a in cls.annotations)
                if not is_controller:
                    continue

                # Class-level path(s)
                class_paths = [""]
                class_auth = [a.name for a in cls.annotations if a.name in AUTH_ANNOTATION_NAMES]

                for a in cls.annotations:
                    if a.name == "RequestMapping":
                        class_paths = _extract_paths_from_annotation(a.attributes)

                for method in cls.methods:
                    method_auth = [a.name for a in method.annotations if a.name in AUTH_ANNOTATION_NAMES]
                    all_auth = sorted(list(set(class_auth + method_auth)))

                    for a in method.annotations:
                        http_methods: list[str] = []
                        method_paths: list[str] = [""]

                        if a.name in MAPPING_HTTP_METHODS:
                            http_methods = [MAPPING_HTTP_METHODS[a.name]]
                            method_paths = _extract_paths_from_annotation(a.attributes)
                        elif a.name == "RequestMapping":
                            http_methods = _extract_methods_from_request_mapping(a.attributes)
                            method_paths = _extract_paths_from_annotation(a.attributes)

                        if not http_methods:
                            continue

                        # Extract params, path variables, request body
                        request_body_type = None
                        path_vars: list[str] = []
                        req_params: list[str] = []

                        for param in method.parameters:
                            for p_anno in param.annotations:
                                if p_anno.name == "RequestBody":
                                    request_body_type = param.param_type
                                elif p_anno.name == "PathVariable":
                                    pv_name = p_anno.get_attr("value") or p_anno.get_attr("name") or param.name
                                    path_vars.append(str(pv_name).strip('"\''))
                                elif p_anno.name == "RequestParam":
                                    rp_name = p_anno.get_attr("value") or p_anno.get_attr("name") or param.name
                                    req_params.append(str(rp_name).strip('"\''))

                        evidence = SourceEvidence(
                            file=pfile.file_path,
                            line_start=a.line_start or method.line_start,
                            line_end=method.line_end,
                        )

                        for cp in class_paths:
                            for mp in method_paths:
                                full_path = _normalize_path(cp, mp)
                                for hm in http_methods:
                                    endpoints.append(
                                        ApiEndpoint(
                                            http_method=hm,
                                            path=full_path,
                                            controller_class=cls.name,
                                            handler_method=method.name,
                                            request_body_type=request_body_type,
                                            response_type=method.return_type if method.return_type != "void" else None,
                                            path_variables=path_vars,
                                            request_params=req_params,
                                            auth_annotations=all_auth,
                                            evidence=evidence,
                                        )
                                    )

        return endpoints

    def extract_validation_rules(self, parsed_files: list[JavaParsedFile]) -> list[ValidationRule]:
        rules: list[ValidationRule] = []

        for pfile in parsed_files:
            for cls in pfile.classes:
                # Scan fields for validation annotations
                for field in cls.fields:
                    for anno in field.annotations:
                        if anno.name in VALIDATION_ANNOTATIONS:
                            params = dict(anno.attributes)
                            msg = params.pop("message", None)
                            if msg is not None:
                                msg = str(msg).strip('"\'')

                            desc = _build_mechanical_description(anno.name, params)
                            evidence = SourceEvidence(
                                file=pfile.file_path,
                                line_start=anno.line_start or field.line_start,
                                line_end=field.line_end,
                            )
                            rules.append(
                                ValidationRule(
                                    dto_class=cls.name,
                                    field_name=field.name,
                                    annotation=f"@{anno.name}",
                                    parameters=params,
                                    message=msg,
                                    mechanical_description=desc,
                                    evidence=evidence,
                                )
                            )

        return rules
