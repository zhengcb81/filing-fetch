"""Offline FF consumer tests from ET main@4924d570 frozen producer goldens."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from et_v2_contract import ETContractError, normalize_et_v2_result


GOLDEN = Path(__file__).parent / "fixtures" / "et_s0b"
MANIFEST_SHA = "2b098b1f53b5d347671ddeda9aa7f8eabb08ca97b539ccbdddf7b3699e7f5453"


def fixture(name: str) -> dict:
    path = GOLDEN / name
    manifest = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    record = manifest["files"][name]
    payload = path.read_bytes()
    assert len(payload) == record["bytes"]
    assert hashlib.sha256(payload).hexdigest() == record["sha256"]
    return json.loads(payload)


def test_producer_manifest_is_exact_frozen_et_commit() -> None:
    assert hashlib.sha256((GOLDEN / "manifest.json").read_bytes()).hexdigest() == MANIFEST_SHA


def test_fmp_fetched_golden_keeps_unverified_as_of_diagnostic() -> None:
    request = fixture("fmp_v2.request.json")
    result = fixture("fmp_v2.fetched.json")
    assert len(result) == 26
    assert "published_date" not in result
    parsed = normalize_et_v2_result(result, request)
    assert parsed["status"] == "fetched"
    assert parsed["producer_result"] is result
    assert parsed["publication_date"] is None
    assert parsed["as_of_cutoff_verified"] is False
    assert parsed["fiscal_period"] == "2026-Q3"
    assert parsed["provider_payload_sha256"] == result["provider_payload_sha256"]
    assert parsed["canonical_content_sha256"] == result["canonical_content_sha256"]


@pytest.mark.parametrize(
    ("name", "status", "reason"),
    [
        ("fmp_v2.credentials_missing.json", "provider_unavailable", "provider_credentials_missing"),
        ("fmp_v2.entitlement_402.json", "provider_unavailable", "provider_entitlement_required"),
        ("fmp_v2.wrong_quarter.json", "provenance_rejected", "provider_identity_or_host"),
    ],
)
def test_fmp_negative_goldens_have_named_independent_result(
    name: str, status: str, reason: str,
) -> None:
    parsed = normalize_et_v2_result(fixture(name), fixture("fmp_v2.request.json"))
    assert parsed == {"status": status, "reason": reason}


def test_fy_only_et_negative_is_request_error_not_inferred_q4() -> None:
    parsed = normalize_et_v2_result(
        fixture("fmp_v2.fy_only_invalid.json"), fixture("fmp_v2.request.json"),
    )
    assert parsed == {"status": "request_error", "reason": "request_schema"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("request_id", "other-request"),
        ("ticker", "AAPL"),
        ("fiscal_period", "2026-Q4"),
        ("as_of_date", "2027-01-01"),
        ("provider_payload_sha256", "0" * 64),
        ("as_of_cutoff_verified", True),
    ],
)
def test_mutated_fmp_fetched_provenance_is_rejected(field: str, value: object) -> None:
    result = copy.deepcopy(fixture("fmp_v2.fetched.json"))
    result[field] = value
    with pytest.raises(ETContractError):
        normalize_et_v2_result(result, fixture("fmp_v2.request.json"))


def test_fmp_extra_field_cannot_silently_change_frozen_26_key_contract() -> None:
    result = fixture("fmp_v2.fetched.json")
    result["published_date"] = result["call_date"]
    with pytest.raises(ETContractError):
        normalize_et_v2_result(result, fixture("fmp_v2.request.json"))
