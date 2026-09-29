"""Contract tests for the opt-in FF v2 envelope and independent companions."""

from __future__ import annotations

from io import StringIO
import json
import sys

import pytest

import fetch_filing
from filing_contracts import FilingFetchError, validate_request


SOURCE_REF = {
    "schema_version": "2.0",
    "document_id": "urn:test:document:one",
    "source_id": "urn:test:source:one",
    "content_sha256": "a" * 64,
    "byte_size": 123,
    "mime_type": "application/pdf",
}


def request(*, companion: dict | None = None) -> dict:
    value = {
        "schema_version": "2.0",
        "company_query": "ACME",
        "market": "US",
        "document_kind": "annual_report",
        "mode": "exact",
        "fiscal_year": 2025,
        "as_of_date": "2026-09-29",
        "filing_intent": "reuse_only",
    }
    if companion is not None:
        value["companion_transcript"] = companion
    return value


def run_main(monkeypatch: pytest.MonkeyPatch, value: dict, args: list[str] | None = None):
    stdin = StringIO(json.dumps(value))
    stdout = StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    rc = fetch_filing.main(args or [])
    return rc, json.loads(stdout.getvalue())


def _filing() -> dict:
    return {
        "source_ref": dict(SOURCE_REF),
        "document_kind": "annual_report",
        "fiscal_year": 2025,
        "fiscal_period": None,
        "resolution_outcome": "reused_existing",
        "download_events": 0,
        "company_identity": {
            "canonical_name": "Acme Inc.", "market": "US", "security_id": "ACME",
            "ticker": "ACME", "exchange": "NASDAQ", "verified": True, "active": True,
        },
    }


def test_v2_request_uses_one_filing_intent_and_rejects_legacy_authorization() -> None:
    validate_request(request())
    legacy_grant = request()
    legacy_grant["authorization"] = {
        "provider": "sec", "allowed_accessions": ["a"], "max_items": 1,
        "max_bytes": 1, "expires_at": "2099-01-01T00:00:00Z",
    }
    with pytest.raises(FilingFetchError):
        validate_request(legacy_grant)


def test_v1_default_json_and_exit_code_remain_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict] = []
    def fake_resolve(**kwargs):
        seen.append(kwargs)
        return {"document_id": "legacy", "canonical_path": "inside/legacy.pdf"}
    monkeypatch.setattr(fetch_filing, "resolve_filing", fake_resolve)
    old = {
        "schema_version": "1.2", "company_query": "ACME", "market": "US",
        "document_kind": "annual_report", "mode": "exact", "fiscal_year": 2025,
        "as_of_date": "2026-09-29",
    }
    rc, output = run_main(monkeypatch, old)
    assert rc == 0
    assert output == {
        "schema_version": "1.1", "status": "capture_ready",
        "handle": {"document_id": "legacy", "canonical_path": "inside/legacy.pdf"},
        "calls": 0, "downloads": 0,
    }
    assert seen[0]["source_ref_v2"] is False


def test_v2_no_companion_is_pathless_and_calls_no_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict] = []
    def fake_resolve(**kwargs):
        seen.append(kwargs)
        return _filing()
    monkeypatch.setattr(fetch_filing, "resolve_filing", fake_resolve)
    monkeypatch.setattr(
        "transcript_companion.resolve_companion_transcript",
        lambda **kwargs: pytest.fail("unrequested transcript must not be called"),
    )
    rc, output = run_main(monkeypatch, request())
    assert rc == 0
    assert output["schema_version"] == "2.0"
    assert output["filing"]["status"] == "source_candidate"
    assert output["filing"]["source_ref"] == SOURCE_REF
    assert output["filing"]["byte_verification"] == "pending_verified_open"
    assert output["transcript"]["status"] == "not_requested"
    assert "canonical_path" not in json.dumps(output)
    assert seen[0]["source_ref_v2"] is True
    assert seen[0]["allow_download"] is False


def test_fy_only_companion_is_period_unresolved_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fetch_filing, "resolve_filing", lambda **kwargs: _filing())
    monkeypatch.setattr(
        "transcript_companion.resolve_companion_transcript",
        lambda **kwargs: pytest.fail("FY-only must not call ET or CWP importer"),
    )
    rc, output = run_main(monkeypatch, request(companion={
        "intent": "fetch_if_missing", "fiscal_year": 2025,
    }))
    assert rc == 0
    assert output["filing"]["status"] == "source_candidate"
    assert output["transcript"]["status"] == "period_unresolved"
    assert output["downloads"] == 0


def test_companion_failure_does_not_rollback_filing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch_filing, "resolve_filing", lambda **kwargs: _filing())
    rc, output = run_main(monkeypatch, request(companion={
        "intent": "fetch_if_missing", "fiscal_year": 2025, "fiscal_quarter": 2,
        "acquisition_limits": {
            "max_bytes": 1_000_000, "timeout_seconds": 10, "max_cost_usd": "0.00",
        },
    }))
    assert rc == 0
    assert output["filing"]["status"] == "source_candidate"
    assert output["filing"]["source_ref"] == SOURCE_REF
    assert output["filing"]["byte_verification"] == "pending_verified_open"
    assert output["transcript"]["status"] == "contract_pending"
    assert output["transcript"]["reason"] == "cwp_fmp_import_contract_pending"


def test_v2_fetch_intent_waits_for_frozen_request_plan_without_source_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fetch_filing, "resolve_filing",
        lambda **kwargs: pytest.fail("unfrozen acquisition must not call CWP"),
    )
    value = request()
    value["filing_intent"] = "fetch_if_missing"
    value["acquisition_limits"] = {
        "max_bytes": 5_000_000, "timeout_seconds": 60,
        "max_cost_usd": "0.00",
    }
    rc, output = run_main(monkeypatch, value)
    assert rc == 2
    assert output["schema_version"] == "2.0"
    assert output["filing"]["status"] == "contract_pending"
    assert output["downloads"] == 0


def test_v2_fetch_intent_requires_byte_time_and_cost_caps() -> None:
    value = request()
    value["filing_intent"] = "fetch_if_missing"
    with pytest.raises(FilingFetchError):
        validate_request(value)
    value["acquisition_limits"] = {
        "max_bytes": 5_000_000, "timeout_seconds": 60,
        "max_cost_usd": "0.00",
    }
    validate_request(value)
    for name, invalid in [
        ("max_bytes", True), ("timeout_seconds", 0),
        ("max_cost_usd", "-1.00"),
    ]:
        bad = json.loads(json.dumps(value))
        bad["acquisition_limits"][name] = invalid
        with pytest.raises(FilingFetchError):
            validate_request(bad)


def test_provider_failure_is_child_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch_filing, "resolve_filing", lambda **kwargs: _filing())
    monkeypatch.setattr(
        "transcript_companion.resolve_companion_transcript",
        lambda **kwargs: {
            "status": "provider_unavailable", "reason": "entitlement_required",
            "retryable": False,
        },
    )
    rc, output = run_main(monkeypatch, request(companion={
        "intent": "fetch_if_missing", "fiscal_year": 2025, "fiscal_quarter": 2,
        "acquisition_limits": {
            "max_bytes": 1_000_000, "timeout_seconds": 10, "max_cost_usd": "0.00",
        },
    }))
    assert rc == 0
    assert output["filing"]["status"] == "source_candidate"
    assert output["transcript"]["status"] == "provider_unavailable"
    assert output["transcript"]["reason"] == "entitlement_required"


def test_v2_library_call_cannot_bypass_pending_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fetch_filing, "load_company_wiki_root",
        lambda **kwargs: pytest.fail("v2 pending fetch must not open CWP"),
    )
    value = request()
    value["filing_intent"] = "fetch_if_missing"
    value["acquisition_limits"] = {
        "max_bytes": 5_000_000, "timeout_seconds": 60,
        "max_cost_usd": "0.00",
    }
    with pytest.raises(FilingFetchError) as error:
        fetch_filing.resolve_filing(
            request=value, source_ref_v2=True, allow_download=True,
        )
    assert error.value.code == "contract_pending"


def test_v2_library_request_requires_pathless_mode() -> None:
    with pytest.raises(FilingFetchError) as error:
        fetch_filing.resolve_filing(request=request())
    assert error.value.code == "request_error"



def test_exact_companion_fetch_requires_independent_byte_time_cost_caps() -> None:
    value = request(companion={
        "intent": "fetch_if_missing", "fiscal_year": 2025, "fiscal_quarter": 2,
    })
    with pytest.raises(FilingFetchError):
        validate_request(value)
    value["companion_transcript"]["acquisition_limits"] = {
        "max_bytes": 1_000_000, "timeout_seconds": 10, "max_cost_usd": "0.00",
    }
    validate_request(value)
    for name, invalid in [
        ("max_bytes", True), ("timeout_seconds", 0), ("max_cost_usd", "-1.00"),
    ]:
        bad = json.loads(json.dumps(value))
        bad["companion_transcript"]["acquisition_limits"][name] = invalid
        with pytest.raises(FilingFetchError):
            validate_request(bad)


def test_fy_only_companion_needs_no_caps_because_it_never_fetches() -> None:
    validate_request(request(companion={
        "intent": "fetch_if_missing", "fiscal_year": 2025,
    }))
