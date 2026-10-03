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
    rc, output = run_main(monkeypatch, request(), args=["--allow-download"])
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
    monkeypatch.setattr(fetch_filing, "_resolve_v2_companion", lambda **kwargs: {
        "status": "provider_unavailable", "reason": "provider_entitlement_required",
        "retryable": False, "provider_calls": 1,
    })
    rc, output = run_main(monkeypatch, request(companion={
        "intent": "fetch_if_missing", "fiscal_year": 2025, "fiscal_quarter": 2,
        "acquisition_limits": {
            "max_bytes": 1_000_000, "timeout_seconds": 10, "max_cost_usd": "1.00",
        },
    }))
    assert rc == 0
    assert output["filing"]["status"] == "source_candidate"
    assert output["filing"]["source_ref"] == SOURCE_REF
    assert output["transcript"]["status"] == "provider_unavailable"
    assert output["transcript"]["reason"] == "provider_entitlement_required"
    assert output["transcript"]["provider_calls"] == 1

def test_v2_fetch_intent_is_forwarded_as_one_explicit_cwp_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict] = []
    monkeypatch.setattr(fetch_filing, "resolve_filing", lambda **kwargs: (seen.append(kwargs), _filing())[1])
    value = request()
    value["filing_intent"] = "fetch_if_missing"
    value["acquisition_limits"] = {
        "max_bytes": 5_000_000, "timeout_seconds": 60, "max_cost_usd": "1.00",
    }
    rc, output = run_main(monkeypatch, value)
    assert rc == 0
    assert output["filing"]["status"] == "source_candidate"
    assert seen[0]["allow_download"] is True
    assert seen[0]["source_ref_v2"] is True

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
    monkeypatch.setattr(fetch_filing, "_resolve_v2_companion", lambda **kwargs: {
        "status": "provider_unavailable", "reason": "provider_entitlement_required",
        "retryable": False, "provider_calls": 1,
    })
    rc, output = run_main(monkeypatch, request(companion={
        "intent": "fetch_if_missing", "fiscal_year": 2025, "fiscal_quarter": 2,
        "acquisition_limits": {
            "max_bytes": 1_000_000, "timeout_seconds": 10, "max_cost_usd": "1.00",
        },
    }))
    assert rc == 0
    assert output["filing"]["status"] == "source_candidate"
    assert output["transcript"]["status"] == "provider_unavailable"

def test_v2_library_call_forwards_fetch_to_cwp_ensure(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "company-wiki"
    (root / "config").mkdir(parents=True)
    (root / "config" / "source_catalog.yaml").write_text("fixture", encoding="utf-8")
    calls: list[dict] = []

    def fake_call(**kwargs):
        calls.append(kwargs)
        if kwargs["action"] == "identify":
            return {
                "schema_version": fetch_filing.COMPANY_WIKI_IDENTITY_SCHEMA_VERSION,
                "status": "resolved",
                "resolved": {
                    "canonical_name": "Acme Inc.", "market": "US", "exchange": "NASDAQ",
                    "ticker": "ACME", "security_id": "ACME", "match_basis": "ticker",
                    "matched_value": "ACME", "source_name": "fixture",
                    "source_url": "https://example.test/security/ACME",
                    "source_record_id": "fixture:acme", "verified": True, "active": True,
                },
            }
        return {"status": "gap"}

    monkeypatch.setattr(fetch_filing, "_run_company_wiki_json_retry", fake_call)
    monkeypatch.setattr(
        fetch_filing, "_pathless_operation_gap", lambda payload, **kwargs: {"status": "gap"},
    )
    value = request()
    value["filing_intent"] = "fetch_if_missing"
    value["acquisition_limits"] = {
        "max_bytes": 5_000_000, "timeout_seconds": 60, "max_cost_usd": "1.00",
    }
    result = fetch_filing.resolve_filing(
        request=value, company_wiki_root=root, source_ref_v2=True,
        allow_download=True, pause_worker=False,
    )
    assert result == {"status": "gap"}
    ensure = next(call for call in calls if call["action"] == "ensure")
    assert "--source-ref-v2" in ensure["command"]
    assert "--allow-download" in ensure["command"]

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
