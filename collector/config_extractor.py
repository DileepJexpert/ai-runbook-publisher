"""Configuration extractor for YAML and Properties Spring Boot files."""

from __future__ import annotations

import logging
import re
from typing import Any

import yaml
from publisher.repository_tools import RepositoryTools

from .models import ConfigEntry, SourceEvidence

LOGGER = logging.getLogger(__name__)

SENSITIVE_KEYWORDS = {
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "client-secret",
    "client_secret",
    "private-key",
    "private_key",
    "access-key",
    "access_key",
    "api-key",
    "api_key",
    "apikey",
}

PRIORITY_CONFIG_PATTERNS = [
    r"url",
    r"host",
    r"port",
    r"timeout",
    r"retry",
    r"delay",
    r"interval",
    r"concurrency",
    r"topic",
    r"group",
    r"dlt",
    r"dlq",
    r"feature",
    r"enabled",
    r"batch",
    r"limit",
    r"cron",
    r"ttl",
    r"pool",
    r"health",
    r"actuator",
    r"datasource",
    r"aerospike",
    r"kafka",
    r"redis",
    r"database",
    r"server\.port",
    r"spring\.application\.name",
    r"management\.",
    r"resilience4j\.",
    r"feign\.",
    r"client\.",
]


def is_sensitive_key(key: str) -> bool:
    """Check if a property key matches any sensitive security concepts."""
    lower = key.lower()
    for kw in SENSITIVE_KEYWORDS:
        if kw in lower:
            return True
    return False


def is_priority_key(key: str, custom_referenced_keys: set[str] | None = None) -> bool:
    """Check if a property key matches operationally useful patterns or is referenced by code."""
    if is_sensitive_key(key):
        return True
    if custom_referenced_keys and key in custom_referenced_keys:
        return True
    for pattern in PRIORITY_CONFIG_PATTERNS:
        if re.search(pattern, key, re.IGNORECASE):
            return True
    return False


def parse_placeholder(raw_val: Any) -> tuple[str | None, Any | None, bool]:
    """
    Parse a string value for Spring placeholder patterns like ${CONFIG_KEY} or ${CONFIG_KEY:default}.
    Returns: (config_key, repository_default, is_placeholder)
    """
    if not isinstance(raw_val, str):
        return None, None, False

    val = raw_val.strip()
    match = re.fullmatch(r"\$\{([^:}]+)(?::(.*))?\}", val)
    if match:
        config_key = match.group(1).strip()
        default_val = match.group(2)
        if default_val is not None:
            default_val = default_val.strip()
            # Clean quotes if any
            if (default_val.startswith('"') and default_val.endswith('"')) or (default_val.startswith("'") and default_val.endswith("'")):
                default_val = default_val[1:-1]
        return config_key, default_val, True

    # Partial match e.g. "http://${HOST}:${PORT}/api"
    # If it contains ${...}, extract the primary key
    partial = re.search(r"\$\{([^:}]+)(?::([^}]*))?\}", val)
    if partial:
        config_key = partial.group(1).strip()
        default_val = partial.group(2)
        return config_key, default_val, True

    return None, None, False


class ConfigExtractor:
    """Extracts, normalizes, and redacts Spring Boot configuration properties."""

    def __init__(self, tools: RepositoryTools) -> None:
        self.tools = tools
        self._cached_entries: list[ConfigEntry] | None = None

    def extract(self, referenced_keys: set[str] | None = None) -> list[ConfigEntry]:
        if self._cached_entries is None:
            self._cached_entries = self._discover_and_parse_all()

        # Filter by priority or referenced keys
        results: list[ConfigEntry] = []
        for entry in self._cached_entries:
            if is_priority_key(entry.property_key, referenced_keys):
                results.append(entry)

        return results

    def get_all_entries(self) -> list[ConfigEntry]:
        """Get all parsed entries without priority filtering."""
        if self._cached_entries is None:
            self._cached_entries = self._discover_and_parse_all()
        return list(self._cached_entries)

    def _discover_and_parse_all(self) -> list[ConfigEntry]:
        all_entries: list[ConfigEntry] = []

        try:
            files = self.tools.list_files(max_results=1000)
        except Exception:
            files = []

        config_files = []
        for f in files:
            path_lower = f.lower()
            name = path_lower.split("/")[-1]
            if name.startswith("application") or name.startswith("bootstrap"):
                if name.endswith((".yml", ".yaml", ".properties")):
                    config_files.append(f)

        for cf in config_files:
            try:
                content = self.tools.read_file(cf)
                profile = self._extract_profile(cf)
                if cf.endswith((".yml", ".yaml")):
                    entries = self._parse_yaml(cf, content, profile)
                else:
                    entries = self._parse_properties(cf, content, profile)
                all_entries.extend(entries)
            except Exception as exc:
                LOGGER.warning("Failed to parse config file %s: %s", cf, exc)

        return all_entries

    def _extract_profile(self, file_path: str) -> str | None:
        filename = file_path.split("/")[-1]
        match = re.match(r"(?:application|bootstrap)-([A-Za-z0-9_-]+)\.(?:ya?ml|properties)", filename)
        if match:
            return match.group(1)
        return "default"

    def _parse_yaml(self, file_path: str, content: str, profile: str | None) -> list[ConfigEntry]:
        entries: list[ConfigEntry] = []
        lines = content.splitlines()

        # Handle multi-document YAML (---)
        docs = list(yaml.safe_load_all(content))
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            flat = self._flatten_dict(doc)
            for key, val in flat.items():
                line_no = self._find_key_line_in_yaml(lines, key)
                entry = self._create_entry(file_path, key, val, profile, line_no)
                entries.append(entry)

        return entries

    def _parse_properties(self, file_path: str, content: str, profile: str | None) -> list[ConfigEntry]:
        entries: list[ConfigEntry] = []
        lines = content.splitlines()

        for idx, line in enumerate(lines, start=1):
            s = line.strip()
            if not s or s.startswith("#") or s.startswith("!"):
                continue
            if "=" in s:
                k, v = s.split("=", 1)
                key = k.strip()
                val = v.strip()
                entries.append(self._create_entry(file_path, key, val, profile, idx))
            elif ":" in s:
                k, v = s.split(":", 1)
                key = k.strip()
                val = v.strip()
                entries.append(self._create_entry(file_path, key, val, profile, idx))

        return entries

    def _flatten_dict(self, d: dict, parent_key: str = "") -> dict[str, Any]:
        items: list[tuple[str, Any]] = []
        for k, v in d.items():
            new_key = f"{parent_key}.{k}" if parent_key else str(k)
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def _find_key_line_in_yaml(self, lines: list[str], dot_key: str) -> int | None:
        parts = dot_key.split(".")
        last_part = parts[-1]
        first_part = parts[0]

        # Search for first_part then descend or search for full last_part
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith(f"{last_part}:") or stripped.startswith(f"{dot_key}:") or stripped.startswith(f"{first_part}:"):
                return idx
        return 1

    def _create_entry(self, file_path: str, key: str, val: Any, profile: str | None, line_no: int | None) -> ConfigEntry:
        sensitive = is_sensitive_key(key)
        config_key, repo_default, is_placeholder = parse_placeholder(val)

        if is_placeholder:
            if sensitive:
                status = "PROTECTED_CHECK_CONFIG_PORTAL"
            else:
                status = "CHECK_CONFIG_PORTAL"
            repo_value = None
        else:
            if sensitive:
                status = "PROTECTED_REPOSITORY_VALUE"
                repo_value = None
            else:
                status = "KNOWN_FROM_REPOSITORY"
                repo_value = val

        evidence = SourceEvidence(file=file_path, line_start=line_no, line_end=line_no) if line_no else SourceEvidence(file=file_path)

        return ConfigEntry(
            property_key=key,
            status=status,
            repository_value=repo_value,
            config_key=config_key,
            repository_default=repo_default,
            sensitive=sensitive,
            source_file=file_path,
            profile=profile,
            evidence=evidence,
        )
