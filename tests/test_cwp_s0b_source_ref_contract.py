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
    "verified_open_receipt_normalized.json": "b27dccb3d8f4adf101d8f66b8feb1dcc98b987ec7993fbcc9c995f865f3d5869",
    "verified_open_bad_sha.json": "f4f34a791ead2775d276435d3093ddfda74bfa324cd34e26f80e0273a1ae8ada",
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


def test_verified_open_receipt_is_distinct_from_source_ref() -> None:
    ref = fixture("source_ref.json")
    receipt = fixture("verified_open_receipt_normalized.json")
    assert receipt["schema_version"] == "2.1"
    assert receipt["status"] == "ok"
    for field in ("source_id", "document_id", "content_sha256", "byte_size"):
        assert receipt[field] == ref[field]
    assert receipt["review"] is None
    assert receipt["policy_sha256"] == "<runtime-sha256>"
    assert receipt["source_read_policy_sha256"] == "<runtime-sha256>"
    assert receipt["read_at"] == "<runtime-utc>"
    with pytest.raises(FilingFetchError):
        _reference(receipt)


def test_verified_open_bad_sha_refusal_has_no_success_receipt() -> None:
    failure = fixture("verified_open_bad_sha.json")
    assert failure == {
        "schema_version": "2.1", "status": "unavailable",
        "reason": "expected_version_mismatch",
    }
    with pytest.raises(FilingFetchError):
        _reference(failure)
