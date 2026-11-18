"""Controlled mock connector for the short-request feedback tests.

This is a contract stand-in, not a company-wiki implementation.  It exists so
``fetch_filing.py`` can run through its real CLI boundary with an isolated
deployment: one argv prefix per configured operation, one stdin document per
request, no sibling checkout and no production configuration.

Invocation shape (the prefix comes from the test's connection config)::

    python -B connector.py <operation> [filing-fetch args...]

Every call appends one JSON line to ``FF_SHORT_CALL_LOG``.  The filing scenario
is selected by ``FF_SHORT_SCENARIO``; the transcript tool is the shared
independent ET stand-in, which logs its own ``et_tool`` rows.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

FILING_SHA = hashlib.sha256(b"short feedback fixture source").hexdigest()
FILING_DOCUMENT = "urn:company-wiki:document:sha256:" + FILING_SHA
FILING_SOURCE = "urn:company-wiki:source:sha256:" + FILING_SHA
REQUEST_ID = "urn:company-wiki:source-request:sha256:" + "a" * 64
POLICY_HASH = "b" * 64

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

ZERO_OBSERVATION: dict[str, Any] = {
    "schema_version": "acquisition-observation/1",
    "usage_scope": "operation",
    "outcome": "reused_before_download",
    "provider_started": False,
    "usage_complete": True,
    "wire_body_bytes": 0,
    "wire_usage_complete": True,
    "entity_body_bytes": 0,
    "http_exchanges": 0,
    "http_exchanges_complete": True,
    "cost_usd": "0.00",
    "http_observation": None,
}

USED_OBSERVATION: dict[str, Any] = {
    "schema_version": "acquisition-observation/1",
    "usage_scope": "operation",
    "outcome": "downloaded_new",
    "provider_started": True,
    "usage_complete": True,
    "wire_body_bytes": 2841,
    "wire_usage_complete": True,
    "entity_body_bytes": 8192,
    "http_exchanges": 3,
    "http_exchanges_complete": True,
    "cost_usd": "0.0004",
    "http_observation": {
        "status_code": 200,
        "mime_type": "application/pdf",
        "content_encoding": "gzip",
        "wire_content_length": 2841,
    },
}

CORRUPT_FAILURE: dict[str, Any] = {
    "schema_version": "acquisition-failure/1",
    "code": "canonical_import_failed",
    "retryable": False,
    "provider_started": False,
    "usage_complete": True,
    "usage_scope": "operation",
    "acquisition_usage": {
        "schema_version": "1.0",
        "response_bytes": 8192,
        "cost_usd": "0.00",
    },
}


def _scenario() -> str:
    return os.environ.get("FF_SHORT_SCENARIO", "reuse_hit")


def _log(entry: dict[str, Any]) -> None:
    path = os.environ.get("FF_SHORT_CALL_LOG")
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
    expected = os.environ.get("FF_SHORT_EMPTY_CWD")
    if expected and Path.cwd().resolve() != Path(expected).resolve():
        print(f"fixture connector cwd mismatch: {Path.cwd()} != {expected}", file=sys.stderr)
        raise SystemExit(3)


def _argument(arguments: list[str], flag: str) -> str:
    try:
        return arguments[arguments.index(flag) + 1]
    except (ValueError, IndexError):
        return ""


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


def _completed(observation: dict[str, Any] | None, *, outcome: str, events: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "operation_schema_version": "1.0",
        "operation": "ensure",
        "status": "completed",
        "request_id": REQUEST_ID,
        "outcome": outcome,
        "download_events": events,
        "policy_hash": POLICY_HASH,
        "source_ref": FILING_REF,
        "candidate": FILING_CANDIDATE,
        "gap_plan": None,
    }
    if observation is not None:
        payload["acquisition_observation"] = observation
    return payload


def _operation_v2() -> dict[str, Any]:
    scenario = _scenario()
    if scenario == "latest_reuse":
        return _completed(None, outcome="reused_after_discovery", events=0)
    if scenario in {"zero_filing", "zero_companion"}:
        return _completed(ZERO_OBSERVATION, outcome="reused_existing", events=0)
    if scenario == "download":
        return _completed(USED_OBSERVATION, outcome="downloaded_new", events=1)
    if scenario == "corrupt":
        return {
            "operation_schema_version": "1.0",
            "operation": "ensure",
            "status": "unavailable",
            "request_id": REQUEST_ID,
            "outcome": None,
            "download_events": 0,
            "source_ref": None,
            "candidate": None,
            "gap_plan": None,
            "acquisition_failure": CORRUPT_FAILURE,
        }
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
    _emit({"status": "fixture_error", "reason": "unsupported_scenario",
           "scenario": scenario}, code=3)


def _legacy_operation() -> dict[str, Any]:
    scenario = _scenario()
    if scenario == "ensure_gap":
        return {
            "status": "gap",
            "acquisition": {
                "gap_plan": {"schema_version": "1.0", "gap_hash": "c" * 64},
            },
            "resolution": {
                "request_id": REQUEST_ID,
                "status": "missing",
                "reason": "metadata_only_gap_plan",
            },
        }
    _emit({"status": "fixture_error", "reason": "unsupported_legacy_scenario",
           "scenario": scenario}, code=3)


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
        "query", "local_prepare", "transcript_import",
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
            "feedback_out": os.environ.get("RESEARCH_FEEDBACK_OUT"),
            "feedback_run_id": os.environ.get("RESEARCH_FEEDBACK_RUN_ID"),
            "feedback_attempt_id": os.environ.get("RESEARCH_FEEDBACK_ATTEMPT_ID"),
        }
    )

    if operation == "catalog":
        subcommand = next(
            (arg for arg in argv[1:] if arg in {"identify", "ensure", "resolve", "close-gap"}),
            "identify",
        )
        if subcommand == "identify":
            _emit(IDENTITY)
        if "--source-ref-v2" in argv:
            _emit(_operation_v2())
        _emit(_legacy_operation())

    if operation == "query":
        kind = stdin.get("document_kind") if isinstance(stdin, dict) else None
        if kind == "investor_call_transcript":
            _emit(_query_payload("not_found"))
        if _scenario() == "query_miss":
            _emit(_query_payload("not_found"))
        _emit(_query_payload("found"))

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
            _emit({"schema_version": "company-wiki-transcript-import-response/3",
                   "status": "rejected"})
        ref = _transcript_ref(fetched)
        _emit({
            "schema_version": "company-wiki-transcript-import-response/3",
            "status": "imported",
            "canonical_status": "imported_new",
            "source_id": ref["source_id"],
            "content_sha256": ref["content_sha256"],
            "provider_payload_sha256": ref["content_sha256"],
            "source_ref": ref,
        })

    _emit({"status": "fixture_error", "reason": "unsupported_operation",
           "operation": operation}, code=3)


if __name__ == "__main__":
    raise SystemExit(main())
