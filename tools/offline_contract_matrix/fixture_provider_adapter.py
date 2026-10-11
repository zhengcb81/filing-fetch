"""Owned fixture-provider adapter (CWP ``json_command_v1``) for financial reports.

Test-harness only. It stands in for a market download tool at the *fixture
provider boundary*: it synthesises the supplier response (a candidate and a
downloaded original) while the real CWP ``ensure``/import path runs unchanged.
This is "only simulate the provider response", not a replacement for the CWP
acquisition service.

Invocation (from CWP ``JsonCommandAdapter``)::

    python fixture_provider_adapter.py discover
    python fixture_provider_adapter.py fetch --staging-dir <ABS dir>

stdin is the canonical request/candidate JSON; stdout is one JSON response. The
adapter echoes an identity matching the market's configured name/version. It
serves a valid synthetic PDF / HTML / TXT original (never a ``%PDF`` placeholder)
and, being a bounded adapter, emits a valid ``acquisition_usage`` on every
response.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

# Reuse the valid-original builders from the sibling fixture_builder.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_builder import (  # noqa: E402
    make_valid_html,
    make_valid_pdf,
    make_valid_txt,
    RETRIEVED_AT,
)

ADAPTER_VERSION = "1.0.0"
_NAME_BY_MARKET = {"CN": "w06-fixture-cn", "HK": "w06-fixture-hk", "US": "w06-fixture-us"}

# document_kind -> (mime, ext, builder key)
_KIND_STYLE = {
    "annual_report": ("application/pdf", "pdf"),
    "semi_annual_report": ("application/pdf", "pdf"),
    "quarterly_report": ("application/pdf", "pdf"),
    "regulatory_filing": ("application/pdf", "pdf"),
    "prospectus": ("application/pdf", "pdf"),
    "equity_offering_prospectus": ("application/pdf", "pdf"),
    "convertible_bond_prospectus": ("application/pdf", "pdf"),
    "investor_relations": ("text/html", "html"),
    "investor_call_transcript": ("text/plain", "txt"),
}


def _identity(market: str) -> dict:
    name = _NAME_BY_MARKET.get((market or "").upper(), "w06-fixture-cn")
    return {"name": name, "version": ADAPTER_VERSION}


def _state() -> dict:
    path = os.environ.get("W06_MATRIX_STATE")
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _render_original(document_kind: str, title: str) -> tuple[bytes, str]:
    mime, style = _KIND_STYLE.get(document_kind, ("application/pdf", "pdf"))
    if style == "pdf":
        return make_valid_pdf(title), mime
    if style == "html":
        return make_valid_html(title, "Synthetic investor-relations document."), mime
    return make_valid_txt(title, "Synthetic original-language text."), mime


def _usage(response_bytes: int) -> dict:
    return {
        "schema_version": "1.0",
        "response_bytes": int(response_bytes),
        "cost_usd": "0",
    }


def _discover(payload: dict) -> dict:
    market = payload.get("market", "CN")
    scenario = _state().get("provider_scenario", "serve")
    body = {
        "schema_version": "1.0",
        "status": "ok",
        "adapter": _identity(market),
        "acquisition_usage": _usage(0),
    }
    if scenario == "empty":
        body["candidates"] = []
        return body
    document_kind = payload.get("document_kind", "annual_report")
    fiscal_year = payload.get("fiscal_year", 2026)
    candidate = {
        "candidate_id": f"w06-{market.lower()}-{document_kind}-{fiscal_year}",
        "provider": payload.get("provider") or "w06fixture",
        "provider_document_id": f"w06-{market.lower()}-{fiscal_year}",
        "market": market,
        "title": f"Synthetic {document_kind} {fiscal_year}",
        "source_url": f"https://fixture.invalid/w06/{market.lower()}/{document_kind}/{fiscal_year}",
        "document_kind": document_kind,
        "filing_date": payload.get("as_of_date", "2026-01-01"),
        "fiscal_year": fiscal_year,
    }
    for optional in ("form_type", "fiscal_period", "language"):
        if payload.get(optional) is not None:
            candidate[optional] = payload[optional]
    body["candidates"] = [candidate]
    return body


def _fetch(argv: list[str]) -> dict:
    try:
        staging = Path(argv[argv.index("--staging-dir") + 1])
    except (ValueError, IndexError):
        return {
            "schema_version": "1.0", "status": "failed",
            "adapter": _identity("CN"),
            "error": {"code": "fixture_adapter_usage", "message": "missing --staging-dir",
                      "retryable": False},
        }
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {}
    market = payload.get("market", "CN")
    document_kind = payload.get("document_kind", "annual_report")
    fiscal_year = payload.get("fiscal_year", 2026)
    title = f"Synthetic {document_kind} {fiscal_year}"
    content, mime = _render_original(document_kind, title)

    staging.mkdir(parents=True, exist_ok=True)
    ext = {"application/pdf": ".pdf", "text/html": ".html", "text/plain": ".txt"}[mime]
    final = staging / f"w06-original{ext}"
    final.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    receipt = {
        "candidate_id": payload.get("candidate_id", "w06-candidate"),
        "provider": payload.get("provider") or "w06fixture",
        "provider_document_id": payload.get("provider_document_id", f"w06-{market.lower()}-{fiscal_year}"),
        "source_url": payload.get("source_url", f"https://fixture.invalid/w06/{market.lower()}"),
        "staged_path": str(final),
        "content_sha256": digest,
        "byte_size": len(content),
        "mime_type": mime,
        "retrieved_at": RETRIEVED_AT,
        "http_status": 200,
        "adapter_name": _identity(market)["name"],
        "adapter_version": ADAPTER_VERSION,
        "etag": None,
        "last_modified": None,
    }
    return {
        "schema_version": "1.0",
        "status": "ok",
        "adapter": _identity(market),
        "receipt": receipt,
        # Bounded adapters must charge at least the staged response bytes.
        "acquisition_usage": _usage(len(content)),
    }


def main(argv: list[str]) -> int:
    action = argv[0] if argv else ""
    payload = {}
    if action == "discover":
        payload = {}
        try:
            payload = json.loads(sys.stdin.read())
        except ValueError:
            payload = {}
        response = _discover(payload)
    elif action == "fetch":
        response = _fetch(argv[1:])
    else:
        response = {
            "schema_version": "1.0", "status": "failed", "adapter": _identity("CN"),
            "error": {"code": "fixture_adapter_usage", "message": f"unknown action {action}",
                      "retryable": False},
        }
    _log(action, payload, response)
    sys.stdout.write(json.dumps(response, ensure_ascii=False))
    return 0


def _log(action: str, payload: dict, response: dict) -> None:
    scratch = os.environ.get("W06_MATRIX_SCRATCH")
    if not scratch:
        return
    try:
        path = Path(scratch) / "adapter_invocations.log"
        entry = {"action": action, "request_kind": payload.get("document_kind"),
                 "request_year": payload.get("fiscal_year"), "request_market": payload.get("market"),
                 "scenario": _state().get("provider_scenario"),
                 "status": response.get("status"),
                 "n_candidates": len(response.get("candidates", [])),
                 "has_receipt": bool(response.get("receipt"))}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
