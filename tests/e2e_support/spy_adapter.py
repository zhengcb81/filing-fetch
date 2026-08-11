"""FC-803: cross-process spy provider adapter (json_command_v1).

A real subprocess adapter the IsolatedWiki acquisition config can point
at: every invocation (discover/fetch) appends one JSONL line to the log
given by SPY_ADAPTER_LOG (action + payload + argv), discovery returns
scripted candidates from SPY_ADAPTER_FIXTURE (a JSON file keyed by
market), and fetch writes a deterministic PDF into the staging dir and
echoes a matching receipt.  SPY_ADAPTER_FAULT=provider_unavailable makes
discovery exit non-zero with the structured 1.0 error JSON (LT-05).

This is the spy provider for the REAL cross-process chain: the filing
resolution runs through the actual company-wiki CLI subprocesses, and the
fetch/write counts come from this spy's log — no network, no mocks.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def _log(action: str, payload: dict, argv: list[str]) -> None:
    path = os.environ.get("SPY_ADAPTER_LOG")
    if not path:
        return
    entry = {
        "action": action,
        "payload": payload,
        "argv": argv,
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _candidate_for(market: str, request: dict) -> list[dict]:
    fixture = os.environ.get("SPY_ADAPTER_FIXTURE")
    if not fixture:
        return []
    payload = json.loads(Path(fixture).read_text(encoding="utf-8"))
    candidates = payload.get(market, [])
    out = []
    for spec in candidates:
        if request.get("fiscal_year") is not None and spec.get(
            "fiscal_year"
        ) != request.get("fiscal_year"):
            continue
        candidate = dict(spec)
        candidate.setdefault("provider", "spy")
        candidate.setdefault("market", market)
        candidate.setdefault("entity", request.get("entity"))
        candidate.setdefault("source_url", "https://spy.example/" + spec["provider_document_id"])
        candidate.setdefault("document_kind", request.get("document_kind"))
        candidate.setdefault("form_type", spec.get("form_type", "annual_report"))
        candidate.setdefault("filing_date", spec.get("filing_date", "2026-04-15"))
        candidate.setdefault("fiscal_year", spec.get("fiscal_year"))
        out.append(candidate)
    return out


def _adapter_object() -> dict:
    return {
        "name": "spy-provider",
        "version": "1.0.0",
    }


def _ok(payload: dict) -> None:
    sys.stdout.write(json.dumps({
        "schema_version": "1.0",
        "status": "ok",
        "adapter": _adapter_object(),
        **payload,
    }, ensure_ascii=False))
    sys.stdout.write("\n")


def _fail(code: str, message: str) -> int:
    sys.stderr.write(json.dumps({
        "schema_version": "1.0",
        "error_code": code,
        "error": message,
        "retryable": True,
        "adapter": _adapter_object(),
    }, ensure_ascii=False))
    sys.stderr.write("\n")
    return 1


def main(argv: list[str]) -> int:
    action = argv[1] if len(argv) > 1 else ""
    payload = json.loads(sys.stdin.read() or "{}")
    _log(action, payload, argv)
    if os.environ.get("SPY_ADAPTER_FAULT") == "provider_unavailable":
        return _fail("provider_unavailable", "spy provider is offline (LT-05)")
    if action == "discover":
        market = str(payload.get("market") or "")
        _ok({"candidates": _candidate_for(market, payload)})
        return 0
    if action == "fetch":
        staging = None
        if "--staging-dir" in argv:
            staging = Path(argv[argv.index("--staging-dir") + 1])
        else:
            return _fail("missing_staging_dir", "fetch requires --staging-dir")
        staging.mkdir(parents=True, exist_ok=True)
        body = b"%PDF-1.4 spy-provider " + str(
            payload.get("provider_document_id", "doc")
        ).encode("utf-8")
        staged = staging / f"{payload.get('provider_document_id', 'doc')}.pdf"
        staged.write_bytes(body)
        receipt = {
            "schema_version": "1.0",
            "candidate_id": payload.get("candidate_id"),
            "provider": payload.get("provider", "spy"),
            "provider_document_id": payload.get("provider_document_id"),
            "source_url": payload.get("source_url"),
            "staged_path": str(staged),
            "content_sha256": hashlib.sha256(body).hexdigest(),
            "byte_size": len(body),
            "mime_type": "application/pdf",
            "retrieved_at": "2026-08-11T00:00:00Z",
            "http_status": 200,
            "adapter_name": "spy-provider",
            "adapter_version": "1.0.0",
        }
        _ok({"receipt": receipt})
        return 0
    return _fail("unknown_action", f"unknown action: {action}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
