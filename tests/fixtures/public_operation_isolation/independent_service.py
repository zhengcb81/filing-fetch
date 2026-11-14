"""Independent public-operation service used by MB-FF isolation tests.

This is a *contract stand-in*, not a company-wiki implementation.  It exists
only to observe what filing-fetch actually launches: one argv prefix per
configured operation, one stdin document per request, and no dependency on a
sibling checkout or the production ``config/company_wiki.json``.

Invocation shape (the prefix is supplied by the test's connection config)::

    python -B independent_service.py <operation> [filing-fetch args...]

Every call appends one JSON line to ``MBFF_CALL_LOG`` so the test can assert
the exact operation sequence, argv, cwd and environment actually used.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

FILING_SHA = hashlib.sha256(b"isolated metadata-only source").hexdigest()
FILING_DOCUMENT = "urn:company-wiki:document:sha256:" + FILING_SHA
FILING_SOURCE = "urn:company-wiki:source:sha256:" + FILING_SHA

# The exact bytes the ET stand-in returns; verified-open must reproduce them.
TRANSCRIPT_ORIGINAL = (
    b'{"symbol":"AMD","period":"Q3","year":2026,'
    b'"content":"fixture transcript body"}'
)
TRANSCRIPT_SHA = hashlib.sha256(TRANSCRIPT_ORIGINAL).hexdigest()

IDENTITY: dict[str, Any] = {
    "schema_version": "1.0",
    "status": "resolved",
    "reason": "exact ticker",
    "resolved": {
        "canonical_name": "Advanced Micro Devices, Inc.",
        "market": "US",
        "exchange": "NASDAQ",
        "ticker": "AMD",
        "security_id": "AMD",
        "match_basis": "ticker",
        "matched_value": "AMD",
        "source_name": "SEC",
        "source_url": "https://www.sec.gov/files/company_tickers.json",
        "source_record_id": "urn:company-wiki:security:US:AMD",
        "verified": True,
        "active": True,
    },
}

FILING_REF: dict[str, Any] = {
    "schema_version": "2.0",
    "document_id": FILING_DOCUMENT,
    "source_id": FILING_SOURCE,
    "content_sha256": FILING_SHA,
    "byte_size": 42,
    "mime_type": "application/pdf",
}

FILING_CANDIDATE: dict[str, Any] = {
    "source_ref": FILING_REF,
    "document_id": FILING_DOCUMENT,
    "source_id": FILING_SOURCE,
    "title": "AMD 2025 annual report",
    "document_kind": "annual_report",
    "fiscal_year": 2025,
    "fiscal_period": None,
    "period_end": "2025-12-31",
    "form_type": "10-K",
    "market": "US",
    "security_id": "AMD",
    "published_date": "2026-02-20",
    "https_url": "https://www.sec.gov/Archives/amd/2025",
    "snapshot_sha256": FILING_SHA,
    "byte_size": 42,
    "mime_type": "application/pdf",
    "retrieved_at": "2026-02-21T00:00:00Z",
    "collector_name": "filesystem-catalog-company_raw",
    "collector_version": "1.0.0",
    "provider": "sec",
    "provider_document_id": "amd-2025-10k",
    "capture_ready": True,
    "capture_provenance": "indexed_location_manifest",
    "prompt_injection_status": "not_detected",
}

REQUEST_ID = "urn:company-wiki:source-request:sha256:" + "a" * 64
POLICY_HASH = "b" * 64


def _scenario() -> str:
    return os.environ.get("MBFF_SCENARIO", "query_hit")


def _log(entry: dict[str, Any]) -> None:
    path = os.environ.get("MBFF_CALL_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _read_stdin_json() -> Any:
    raw = sys.stdin.buffer.read()
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        return {"_invalid_utf8_bytes": len(raw)}


def _emit(payload: dict[str, Any], *, code: int = 0) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    raise SystemExit(code)


def _guard() -> None:
    expected = os.environ.get("MBFF_EMPTY_CWD")
    if expected and Path.cwd().resolve() != Path(expected).resolve():
        print(
            f"fixture service cwd mismatch: {Path.cwd()} != {expected}",
            file=sys.stderr,
        )
        raise SystemExit(3)


def _query_payload(status: str) -> dict[str, Any]:
    found = status == "found"
    return {
        "schema_version": "2.0",
        "status": status,
        "reason": "one_local_match" if found else "no_local_match",
        "request_id": REQUEST_ID,
        "matches": [FILING_REF] if found else [],
        "candidates": [FILING_CANDIDATE] if found else [],
        "source_read_policy_sha256": POLICY_HASH,
    }


def _operation_payload() -> dict[str, Any]:
    scenario = _scenario()
    if scenario == "ensure_gap":
        return {
            "operation_schema_version": "1.0",
            "operation": "ensure",
            "status": "gap",
            "request_id": REQUEST_ID,
            "outcome": "gap",
            "download_events": 0,
            "gap_plan": {
                "schema_version": "1.0",
                "gap_hash": "c" * 64,
                "request_id": REQUEST_ID,
            },
        }
    return {
        "operation_schema_version": "1.0",
        "operation": "ensure",
        "status": "completed",
        "request_id": REQUEST_ID,
        "outcome": "reused_existing",
        "download_events": 0,
        "policy_hash": POLICY_HASH,
        "source_ref": FILING_REF,
        "candidate": FILING_CANDIDATE,
    }


def _prepare_payload() -> dict[str, Any]:
    return {
        "schema_version": "local-source-prepare/1",
        "status": "ready",
        "reason": "verified_local_original",
        "source_ref": FILING_REF,
        "blocks_download": False,
        "operations": [],
        "diagnostics": [],
        "download_events": 0,
    }


def _harness_log_path() -> str:
    """The harness-provided call log, constrained to an absolute real file.

    ``MBFF_CALL_LOG`` comes from the test harness; this guard keeps the
    fixture from opening anything relative, traversal-shaped, or missing.
    """
    raw = os.environ.get("MBFF_CALL_LOG", "")
    if not raw:
        return ""
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts or not path.is_file():
        return ""
    return str(path)


def _filing_query_index(log_path: str) -> int:
    """How many filing queries already happened before this one."""
    path = Path(log_path)
    if not path.is_absolute() or ".." in path.parts or not path.is_file():
        return 0
    count = 0
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if item.get("operation") != "query":
                    continue
                stdin = item.get("stdin")
                kind = stdin.get("document_kind") if isinstance(stdin, dict) else None
                if kind != "investor_call_transcript":
                    count += 1
    except OSError:
        return 0
    return max(count - 1, 0)


def _statements_payload(request: dict[str, Any]) -> dict[str, Any]:
    status = os.environ.get("MBFF_STATEMENTS_STATUS", "complete")
    statement_types = request.get("statements") or [
        "income_statement",
        "balance_sheet",
        "cash_flow",
    ]
    statements = []
    for index, name in enumerate(statement_types):
        statement_status = status
        if status == "partial" and index == 0:
            statement_status = "complete"
        statements.append(
            {
                "statement_type": name,
                "status": statement_status if status in {"complete", "partial"} else "not_found",
                "provider": "sina_finance",
                "knowledge_mode": "current_snapshot",
                "point_in_time_quality": "current_snapshot",
                "coverage": {"observed_periods": 36, "pages": 4},
                "usage": {
                    "http_requests": 5,
                    "response_bytes": 196351,
                    "cost_usd": "0.00",
                },
                "reports": [],
            }
        )
    payload = {
        "schema_version": "financial-statements-response/1",
        "status": status,
        "company_identity": {
            "canonical_name": "Advanced Micro Devices, Inc.",
            "market": "US",
            "exchange": "NASDAQ",
            "security_id": "AMD",
        },
        "statements": statements,
        "usage": {
            "http_requests": 5,
            "response_bytes": 196351,
            "cost_usd": "0.00",
        },
        "retrieved_at": "2026-11-12T00:00:00Z",
    }
    if status == "request_error":
        payload["schema_version"] = "financial-statements-response/1"
        payload["error"] = "fixture request refusal"
    return payload


def _transcript_ref(fetched: dict[str, Any]) -> dict[str, Any]:
    digest = fetched["provider_payload_sha256"]
    return {
        "schema_version": "2.0",
        "document_id": "urn:company-wiki:document:sha256:" + digest,
        "source_id": "urn:company-wiki:source:sha256:" + digest,
        "content_sha256": digest,
        "byte_size": int(fetched["content_bytes"]),
        "mime_type": "application/json",
    }


def main(argv: list[str] | None = None) -> int:
    _guard()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        _emit({"status": "fixture_error", "reason": "missing_operation"}, code=3)
    operation = argv[0]
    stdin = _read_stdin_json() if operation in {
        "query",
        "local_prepare",
        "transcript_import",
        "financial_statements",
    } else None
    _log(
        {
            "operation": operation,
            "argv": [operation, *argv[1:]],
            "full_argv": list(sys.argv),
            "cwd": str(Path.cwd()),
            "pythonpath": os.environ.get("PYTHONPATH"),
            "scenario": _scenario(),
            "stdin": stdin,
            "pid": os.getpid(),
            "executable": sys.executable,
        }
    )

    if operation == "catalog":
        subcommand = next(
            (arg for arg in argv[1:] if arg in {"identify", "ensure", "resolve", "close-gap"}),
            "identify",
        )
        if subcommand == "identify":
            _emit(IDENTITY)
        _emit(_operation_payload())

    if operation == "query":
        kind = stdin.get("document_kind") if isinstance(stdin, dict) else None
        if kind == "investor_call_transcript":
            _emit(_query_payload("not_found"))
        log_path = _harness_log_path()
        sequence = [
            item.strip()
            for item in os.environ.get("MBFF_QUERY_SEQUENCE", "found").split(",")
            if item.strip()
        ]
        index = _filing_query_index(log_path) if log_path else 0
        status = sequence[min(index, len(sequence) - 1)]
        _emit(_query_payload(status))

    if operation == "local_prepare":
        _emit(_prepare_payload())

    if operation == "open":
        arguments = argv[1:]
        receipt = {
            "schema_version": "2.1",
            "status": "ok",
            "document_id": _argument(arguments, "--document-id"),
            "source_id": _argument(arguments, "--source-id"),
            "content_sha256": _argument(arguments, "--content-sha256"),
            "byte_size": len(TRANSCRIPT_ORIGINAL),
        }
        sys.stdout.buffer.write(TRANSCRIPT_ORIGINAL)
        sys.stdout.buffer.flush()
        sys.stderr.write(json.dumps(receipt, ensure_ascii=False))
        sys.stderr.flush()
        return 0

    if operation == "transcript_import":
        fetched = stdin.get("transcript_result") if isinstance(stdin, dict) else None
        if not isinstance(fetched, dict):
            _emit(
                {
                    "schema_version": "company-wiki-transcript-import-response/3",
                    "status": "rejected",
                }
            )
        if os.environ.get("MBFF_IMPORT_MODE", "imported") == "rejected":
            _emit(
                {
                    "schema_version": "company-wiki-transcript-import-response/3",
                    "status": "rejected",
                }
            )
        ref = _transcript_ref(fetched)
        _emit(
            {
                "schema_version": "company-wiki-transcript-import-response/3",
                "status": "imported",
                "canonical_status": "imported_new",
                "source_id": ref["source_id"],
                "content_sha256": ref["content_sha256"],
                "provider_payload_sha256": ref["content_sha256"],
                "source_ref": ref,
            }
        )

    if operation == "financial_statements":
        if not isinstance(stdin, dict):
            _emit(
                {
                    "schema_version": "financial-statements-response/1",
                    "status": "request_error",
                    "error": "missing request",
                },
                code=2,
            )
        payload = _statements_payload(stdin)
        diagnostic = os.environ.get("MBFF_STATEMENTS_DIAGNOSTIC_BYTES")
        if diagnostic:
            sys.stderr.write("diagnostic:" + ("x" * int(diagnostic)))
            sys.stderr.flush()
        if payload["status"] == "request_error":
            _emit(payload, code=2)
        _emit(payload)

    _emit(
        {"status": "fixture_error", "reason": "unsupported_operation", "operation": operation},
        code=3,
    )


def _argument(arguments: list[str], flag: str) -> str:
    try:
        return arguments[arguments.index(flag) + 1]
    except (ValueError, IndexError):
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
