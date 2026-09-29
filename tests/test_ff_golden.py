"""Real FF CLI serializer goldens with fake, network-free CWP outcomes."""

from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_filing
from filing_contracts import FilingFetchError


GOLDEN_DIR = Path(__file__).parent / "golden"
SOURCE_REF = {
    "schema_version": "2.0",
    "document_id": "urn:fixture:document:one",
    "source_id": "urn:fixture:source:one",
    "content_sha256": "a" * 64,
    "byte_size": 123,
    "mime_type": "application/pdf",
}
IDENTITY = {
    "canonical_name": "Acme Inc.", "market": "US", "security_id": "ACME",
    "ticker": "ACME", "exchange": "NASDAQ", "verified": True, "active": True,
}
V1_REQUEST = {
    "schema_version": "1.2", "company_query": "ACME", "market": "US",
    "document_kind": "annual_report", "mode": "exact", "fiscal_year": 2025,
    "as_of_date": "2026-09-29",
}
V2_REQUEST = {
    **V1_REQUEST, "schema_version": "2.0", "filing_intent": "reuse_only",
}
V2_HANDLE = {
    "source_ref": SOURCE_REF, "company_identity": IDENTITY,
    "document_kind": "annual_report", "fiscal_year": 2025,
    "fiscal_period": None, "resolution_outcome": "reused_existing",
    "download_events": 0,
}


def _cases() -> dict[str, tuple[dict, dict | FilingFetchError]]:
    period_only = {
        **V2_REQUEST,
        "companion_transcript": {"intent": "fetch_if_missing", "fiscal_year": 2025},
    }
    exact_companion = {
        **V2_REQUEST,
        "companion_transcript": {
            "intent": "fetch_if_missing", "fiscal_year": 2025, "fiscal_quarter": 2,
            "acquisition_limits": {
                "max_bytes": 1_000_000, "timeout_seconds": 10, "max_cost_usd": "0.00",
            },
        },
    }
    fetch_pending = {
        **V2_REQUEST, "filing_intent": "fetch_if_missing",
        "acquisition_limits": {
            "max_bytes": 5_000_000, "timeout_seconds": 60,
            "max_cost_usd": "0.00",
        },
    }
    gap = {
        "status": "gap", "gap_plan": {"gap_hash": "b" * 64},
        "resolution": {"reason": "metadata_only_gap_plan"},
    }
    return {
        "ff_v1_success": (
            V1_REQUEST, {"document_id": "legacy-doc", "canonical_path": "inside/report.pdf"},
        ),
        "ff_v1_not_found": (
            V1_REQUEST, FilingFetchError("filing missing", code="not_found"),
        ),
        "ff_v2_source_candidate": (V2_REQUEST, V2_HANDLE),
        "ff_v2_period_unresolved": (period_only, V2_HANDLE),
        "ff_v2_transcript_pending": (exact_companion, V2_HANDLE),
        "ff_v2_upstream_error": (
            V2_REQUEST, FilingFetchError("source hash mismatch", code="upstream_error"),
        ),
        "ff_v2_fetch_pending": (fetch_pending, V2_HANDLE),
        "ff_v2_gap": (V2_REQUEST, gap),
    }


def _render(request: dict, outcome: dict | FilingFetchError) -> dict:
    stdin = StringIO(json.dumps(request, ensure_ascii=False))
    stdout = StringIO()
    old_stdin, old_stdout = sys.stdin, sys.stdout
    try:
        sys.stdin, sys.stdout = stdin, stdout
        with patch.object(
            fetch_filing, "resolve_filing",
            side_effect=outcome if isinstance(outcome, FilingFetchError) else None,
            return_value=outcome if isinstance(outcome, dict) else None,
        ):
            exit_code = fetch_filing.main([])
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
    return {"exit_code": exit_code, "payload": json.loads(stdout.getvalue())}


@pytest.mark.parametrize("name", sorted(_cases()))
def test_cli_serializer_golden(name: str) -> None:
    request, outcome = _cases()[name]
    actual = _render(request, outcome)
    expected = json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert actual == expected


if __name__ == "__main__":
    if sys.argv[1:] != ["--write-golden"]:
        raise SystemExit("usage: python tests/test_ff_golden.py --write-golden")
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for case_name, (case_request, case_outcome) in _cases().items():
        data = _render(case_request, case_outcome)
        (GOLDEN_DIR / f"{case_name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="",
        )
