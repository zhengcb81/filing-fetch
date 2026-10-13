"""One bounded configuration/path implementation for FF runtime and diagnostics.

Connection roots remain explicit absolute paths. Optional ET/key locations may
be relative to their selected config. This module only resolves locations;
credential bytes and source policy belong to their existing responsible layers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

from filing_contracts import COMPANY_WIKI_CONFIG_SCHEMA_VERSION, FilingFetchError

MAX_CONFIG_BYTES = 64 * 1024
_TOKEN = re.compile(r"\$\{([^}]+)\}")


def read_json_object(path: Path, *, label: str = "company-wiki config") -> dict[str, Any]:
    """Read at most limit + 1 bytes; invalid text never escapes as decoder errors."""
    try:
        selected = path.expanduser().resolve(strict=True)
        if not selected.is_file():
            raise FilingFetchError(f"{label} must be a file", code="config_error")
        with selected.open("rb") as stream:
            raw = stream.read(MAX_CONFIG_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise FilingFetchError(
            f"{label} does not exist or is unreadable: {path}", code="config_error"
        ) from exc
    if len(raw) > MAX_CONFIG_BYTES:
        raise FilingFetchError(
            f"{label} exceeds the {MAX_CONFIG_BYTES} byte limit", code="config_error"
        )
    try:
        payload = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, ValueError) as exc:
        raise FilingFetchError(
            f"invalid {label}: {type(exc).__name__}", code="config_error"
        ) from exc
    if not isinstance(payload, dict):
        raise FilingFetchError(f"{label} must be an object", code="config_error")
    return payload


def expand_config_path(
    value: object,
    *,
    field: str,
    skill_root: Path,
    config_path: Path | None = None,
    absolute: bool = False,
) -> Path:
    """Expand only existing tokens, never cwd-based relative deployment paths."""
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise FilingFetchError(f"{field} must be non-empty trimmed text", code="config_error")
    tokens = {
        "SKILL_ROOT": str(skill_root),
        "USER_PROFILE": os.environ.get("USERPROFILE") or str(Path.home()),
    }

    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        if token not in tokens:
            raise FilingFetchError(f"unsupported token in {field}: {token}", code="config_error")
        return tokens[token]

    expanded = _TOKEN.sub(replace, value)
    if "${" in expanded:
        raise FilingFetchError(f"unsupported or incomplete token in {field}", code="config_error")
    path = Path(expanded).expanduser()
    if path.is_absolute():
        return path
    if absolute or config_path is None:
        raise FilingFetchError(
            f"{field} must be absolute after token expansion", code="config_error"
        )
    return config_path.expanduser().resolve(strict=True).parent / path


def validate_company_wiki_root(root: Path) -> Path:
    if not isinstance(root, Path):
        raise TypeError("company_wiki_root must be pathlib.Path")
    try:
        resolved = root.expanduser().resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise FilingFetchError(
            f"configured company_wiki_root does not exist: {root}", code="config_error"
        ) from exc
    if not resolved.is_dir():
        raise FilingFetchError(
            "configured company_wiki_root must be a directory", code="config_error"
        )
    if not (resolved / "config" / "source_catalog.yaml").is_file():
        raise FilingFetchError(
            "configured company_wiki_root lacks config/source_catalog.yaml", code="config_error"
        )
    return resolved


def load_connection_root(config_path: Path, *, skill_root: Path) -> Path:
    payload = read_json_object(config_path)
    required = {"schema_version", "company_wiki_root"}
    optional = {"fmp_api_key_file", "earnings_transcripts_tool"}
    if not required <= set(payload) or not set(payload) <= required | optional:
        raise FilingFetchError(
            "company-wiki config must contain schema_version/company_wiki_root and only optional "
            "fmp_api_key_file/earnings_transcripts_tool (no independent allowed_handle_roots)",
            code="config_error",
        )
    if payload["schema_version"] != COMPANY_WIKI_CONFIG_SCHEMA_VERSION:
        raise FilingFetchError(
            f"company-wiki config schema_version must be {COMPANY_WIKI_CONFIG_SCHEMA_VERSION}",
            code="config_error",
        )
    for field in optional & set(payload):
        value = payload[field]
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise FilingFetchError(
                f"company-wiki config {field} must be non-empty trimmed text", code="config_error"
            )
    return validate_company_wiki_root(
        expand_config_path(
            payload["company_wiki_root"],
            field="company-wiki config company_wiki_root",
            skill_root=skill_root,
            absolute=True,
        )
    )
