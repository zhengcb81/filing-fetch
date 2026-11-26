"""Replay scope for the public request contracts, with no opaque request data."""

from __future__ import annotations

import math
from pathlib import Path
import re
import sys


_LABELS = {
    "schema_version", "company_query", "market", "source_market", "exchange", "document_kind",
    "as_of_date", "period_end_from", "period_end_to", "form_type", "fiscal_period", "language",
    "provider", "provider_document_id", "mode", "filing_intent", "intent", "knowledge_mode",
}
_LISTS = {"statements", "report_types", "fields", "allowed_accessions"}
_INTEGERS = {"fiscal_year", "fiscal_quarter", "max_bytes", "max_items"}
_CHILDREN = {
    "acquisition_limits": {"max_bytes", "timeout_seconds", "max_cost_usd"},
    "authorization": {"provider", "allowed_accessions", "max_items", "max_bytes"},
    "companion_transcript": {"intent", "fiscal_year", "fiscal_quarter", "provider", "acquisition_limits"},
}
_CREDENTIAL = re.compile(
    r"(?i)authorization|api[_ -]?key|bearer\s|password|credential|(?<!\w)(?:sk-|gh[pousr]_|github_pat_)"
    r"|[A-Za-z0-9_]{28,}"
)
_LABEL = re.compile(r"[\w .,&+()'\-]{1,160}")
_UNRECORDED = object()


def read_request_bytes(request_file: Path | None) -> bytes:
    if request_file is not None:
        return request_file.read_bytes()
    stream = getattr(sys.stdin, "buffer", None)
    return stream.read() if stream is not None else sys.stdin.read().encode("utf-8")


def _safe_label(value) -> bool:
    return isinstance(value, str) and bool(_LABEL.fullmatch(value)) and not _CREDENTIAL.search(value)


def _safe_value(key, value, withheld, prefix):
    if key == "schema_version":
        return (value if isinstance(value, str) and re.fullmatch(r"\d+\.\d+|financial-statements-request/1", value)
                else _UNRECORDED)
    if key in _LABELS and _safe_label(value):
        return value
    if key in _LISTS and isinstance(value, list) and all(_safe_label(item) for item in value):
        return value
    if key in _INTEGERS and type(value) is int:
        return value
    if key == "all_history" and type(value) is bool:
        return value
    if key == "timeout_seconds" and (type(value) is int or type(value) is float and math.isfinite(value)):
        return value
    if key == "max_cost_usd" and isinstance(value, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
        return value
    if key in _CHILDREN and isinstance(value, dict):
        return _project(value, _CHILDREN[key], withheld, prefix + key + ".")
    return _UNRECORDED


def _project(value, fields, withheld, prefix=""):
    result = {}
    for key, raw in value.items():
        if key not in fields:
            withheld.add(prefix + ("continuation" if key == "continuation" else "unrecognized_field"))
            continue
        safe = _safe_value(key, raw, withheld, prefix)
        if safe is _UNRECORDED:
            withheld.add(prefix + key)
        else:
            result[key] = safe
    return result


def replay_input(value: object, *, request_file: Path | None) -> dict:
    source = "request_file" if request_file is not None else "stdin"
    if not isinstance(value, dict):
        return {"source": source, "request": None, "withheld": ["non_object"]}
    withheld: set[str] = set()
    fields = _LABELS | _LISTS | _INTEGERS | _CHILDREN.keys() | {"all_history"}
    request = _project(value, fields, withheld)
    return {"source": source, "request": request, "withheld": sorted(withheld)}
