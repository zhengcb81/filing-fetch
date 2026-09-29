"""FF consumer contract against CWP commit 3dd41e1 SourceRef producer goldens."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ff_v2_envelope import _reference, success_envelope
from filing_contracts import FilingFetchError


GOLDEN = Path(__file__).parent / "fixtures" / "cwp_source_v2"
SHAS = {
    "source_ref.json": "aca22689b9369151932d8402614c48d0122a8049fee3015b420264bcfd335cf1",
    "source_ref_bad_sha.json": "45f2f3a6dfaec665ebb6ac85eb2127093092a367031952f5c7e83bc477d714d1",
}


def fixture(name: str) -> dict:
    payload = (GOLDEN / name).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == SHAS[name]
    return json.loads(payload)


def test_real_cwp_source_ref_is_pathless_unverified_candidate() -> None:
    ref = fixture("source_ref.json")
    assert _reference(ref) == ref
    result = success_envelope(
        {
            "mode": "exact", "fiscal_year": 2025, "fiscal_period": None,
            "as_of_date": "2026-09-29",
        },
        {
            "source_ref": ref, "document_kind": "annual_report",
            "fiscal_year": 2025, "fiscal_period": None,
            "resolution_outcome": "reused_existing", "download_events": 0,
        },
        {"status": "not_requested"},
        {"calls": 2, "downloads": 0},
    )
    assert result["filing"]["source_ref"] == ref
    assert result["filing"]["byte_verification"] == "pending_verified_open"
    assert result["downloads"] == 0
    assert "path" not in json.dumps(result).lower()


def test_real_cwp_bad_sha_is_rejected_before_ff_envelope() -> None:
    ref = fixture("source_ref_bad_sha.json")
    with pytest.raises(FilingFetchError):
        _reference(ref)
