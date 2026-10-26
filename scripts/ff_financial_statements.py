"""Thin client for A-share historical financial statements through company-wiki.

The single bounded subprocess implementation from ``ff_process_transport`` and
the single config resolution from ``ff_configuration`` are reused; this module
owns only the request/response contract for
``financial-statements-request|response/1`` and the CWP CLI invocation.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from ff_configuration import load_connection_root
from ff_process_transport import (
    ChildFailed,
    ChildStartFailed,
    ChildTimeout,
    OutputLimitExceeded,
    TransportError,
    run_bounded_json as _run_bounded_json,
)
from filing_contracts import FilingFetchError

STATEMENTS_REQUEST_SCHEMA_VERSION = "financial-statements-request/1"
STATEMENTS_RESPONSE_SCHEMA_VERSION = "financial-statements-response/1"

STATEMENT_TYPES = ("income_statement", "balance_sheet", "cash_flow")
REPORT_TYPES = ("annual", "semi_annual", "q1", "q3")
INTENTS = ("reuse_only", "fetch_if_missing", "refresh")
KNOWLEDGE_MODES = ("current_snapshot", "point_in_time")
RESPONSE_STATUSES = ("complete", "partial", "not_found", "unavailable")

CWP_MODULE = "company_wiki.source_catalog.financial_statements.cli"

DEFAULT_TIMEOUT_SECONDS = 300.0
MAX_STDOUT_BYTES = 32 * 1024 * 1024


def validate_request(payload: Any) -> dict[str, Any]:
    """One validation owner on the FF side (CWP validates again server-side)."""
    if not isinstance(payload, dict):
        raise FilingFetchError("request must be a JSON object", code="request_error")
    if payload.get("schema_version") != STATEMENTS_REQUEST_SCHEMA_VERSION:
        raise FilingFetchError(
            f"schema_version must be {STATEMENTS_REQUEST_SCHEMA_VERSION}",
            code="request_error",
        )
    allowed_fields = {
        "schema_version", "company_query", "market", "statements", "report_types",
        "period_end_from", "period_end_to", "all_history", "knowledge_mode",
        "as_of_date", "intent", "acquisition_limits", "fields", "continuation",
    }
    unknown = set(payload) - allowed_fields
    if unknown:
        raise FilingFetchError(
            f"unknown request fields: {sorted(unknown)}", code="request_error"
        )
    fields = payload.get("fields")
    if fields is not None:
        if not isinstance(fields, list) or not fields:
            raise FilingFetchError("fields must be a non-empty list", code="request_error")
        if not all(isinstance(item, str) and item.strip() for item in fields):
            raise FilingFetchError(
                "fields items must be non-empty text", code="request_error"
            )
    continuation = payload.get("continuation")
    if continuation is not None and (
        not isinstance(continuation, str) or not continuation.strip()
    ):
        raise FilingFetchError(
            "continuation must be non-empty text", code="request_error"
        )
    if continuation is not None and payload.get("intent", "fetch_if_missing") == "reuse_only":
        raise FilingFetchError(
            "continuation is not supported with reuse_only", code="request_error"
        )
    query = payload.get("company_query")
    if not isinstance(query, str) or not query.strip() or query != query.strip():
        raise FilingFetchError(
            "company_query must be trimmed non-empty text", code="request_error"
        )
    market = payload.get("market", "CN")
    if market != "CN":
        raise FilingFetchError("only market=CN is supported", code="request_error")
    for name, known in (("statements", STATEMENT_TYPES), ("report_types", REPORT_TYPES)):
        values = payload.get(name, list(known))
        if not isinstance(values, list) or not values:
            raise FilingFetchError(f"{name} must be a non-empty list", code="request_error")
        bad = [value for value in values if value not in known]
        if bad:
            raise FilingFetchError(f"unsupported {name}: {bad}", code="request_error")
    intent = payload.get("intent", "fetch_if_missing")
    if intent not in INTENTS:
        raise FilingFetchError(f"unsupported intent: {intent!r}", code="request_error")
    knowledge_mode = payload.get("knowledge_mode", "current_snapshot")
    if knowledge_mode not in KNOWLEDGE_MODES:
        raise FilingFetchError(
            f"unsupported knowledge_mode: {knowledge_mode!r}", code="request_error"
        )
    if payload.get("all_history") and payload.get("period_end_from"):
        raise FilingFetchError(
            "all_history and period_end_from are mutually exclusive",
            code="request_error",
        )
    limits = payload.get("acquisition_limits")
    if intent != "reuse_only":
        if not isinstance(limits, dict):
            raise FilingFetchError(
                "acquisition_limits are required for fetching intents",
                code="request_error",
            )
        for field, kinds in (
            ("max_bytes", int),
            ("timeout_seconds", (int, float)),
        ):
            value = limits.get(field)
            if isinstance(value, bool) or not isinstance(value, kinds) or value <= 0:
                raise FilingFetchError(
                    f"acquisition_limits.{field} must be positive", code="request_error"
                )
        cost = limits.get("max_cost_usd")
        if isinstance(cost, bool) or not isinstance(cost, (str, int)):
            raise FilingFetchError(
                "acquisition_limits.max_cost_usd must be a decimal string",
                code="request_error",
            )
    return payload


def build_cwp_command(root: Path) -> list[str]:
    return [sys.executable, "-m", CWP_MODULE, "--wiki-root", str(root)]


def _valid_error_envelope(stdout: bytes) -> dict[str, Any] | None:
    """Parse a child stdout that carries a structured error envelope."""
    try:
        envelope = json.loads(stdout.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError, AttributeError):
        return None
    if not isinstance(envelope, dict):
        return None
    if envelope.get("schema_version") != STATEMENTS_RESPONSE_SCHEMA_VERSION:
        return None
    if envelope.get("status") not in ("request_error", "config_error", "fatal"):
        return None
    return envelope


def fetch_statements(
    *,
    config_path: Path | None,
    request: dict[str, Any],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run the bounded CWP child and return one validated response envelope."""
    validate_request(request)
    skill_root = Path(__file__).resolve().parents[1]
    if config_path is None:
        config_path = skill_root / "config" / "company_wiki.json"
    root = load_connection_root(Path(config_path), skill_root=skill_root)
    command = build_cwp_command(root)
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    try:
        stdout, stderr, returncode = _run_bounded_json(
            command,
            timeout_seconds=timeout_seconds,
            input_bytes=json.dumps(request, ensure_ascii=False).encode("utf-8"),
            cwd=str(root),
            env=environment,
            stdout_cap_bytes=MAX_STDOUT_BYTES,
        )
    except ChildFailed as exc:
        # W19-R3: a CWP-side request/config refusal is a business answer, not
        # an upstream fault — pass its envelope through with the true status
        # instead of mislabeling it upstream_error/retryable.
        passthrough = _valid_error_envelope(exc.stdout)
        if passthrough is not None:
            return passthrough
        raise FilingFetchError(
            "company-wiki financial statements child exited nonzero",
            code="upstream_error",
            producer_exit_code=exc.returncode,
        ) from exc
    except (ChildTimeout, OutputLimitExceeded, ChildStartFailed, TransportError) as exc:
        raise FilingFetchError(
            f"company-wiki financial statements child failed: {type(exc).__name__}",
            code="upstream_error",
        ) from exc
    try:
        envelope = json.loads(stdout.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FilingFetchError(
            "company-wiki financial statements response was not valid JSON",
            code="upstream_error",
        ) from exc
    if not isinstance(envelope, dict):
        raise FilingFetchError(
            "company-wiki financial statements response must be an object",
            code="upstream_error",
        )
    if envelope.get("schema_version") != STATEMENTS_RESPONSE_SCHEMA_VERSION:
        raise FilingFetchError(
            f"response schema_version must be {STATEMENTS_RESPONSE_SCHEMA_VERSION}",
            code="upstream_error",
        )
    status = envelope.get("status")
    if status not in RESPONSE_STATUSES and status not in (
        "request_error", "config_error", "fatal"
    ):
        raise FilingFetchError(
            f"unknown response status: {status!r}", code="upstream_error"
        )
    return envelope


__all__ = [
    "CWP_MODULE",
    "INTENTS",
    "KNOWLEDGE_MODES",
    "REPORT_TYPES",
    "RESPONSE_STATUSES",
    "STATEMENT_TYPES",
    "STATEMENTS_REQUEST_SCHEMA_VERSION",
    "STATEMENTS_RESPONSE_SCHEMA_VERSION",
    "build_cwp_command",
    "fetch_statements",
    "validate_request",
]
