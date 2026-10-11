"""W04: named request failures are typed diagnostics, not retry permission."""
from __future__ import annotations

from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_filing as fetch  # noqa: E402
import ff_provider_cause as cause  # noqa: E402
from filing_contracts import FilingFetchError, validate_request  # noqa: E402


def request(**updates):
    value = {
        "schema_version": "2.0", "company_query": "Sample", "market": "US",
        "document_kind": "annual_report", "as_of_date": "2026-10-08",
        "filing_intent": "reuse_only", "mode": "exact", "fiscal_year": 2026,
    }
    value.update(updates)
    return value


def limits(**updates):
    value = {"max_bytes": 41943040, "timeout_seconds": 180, "max_cost_usd": "0.00"}
    value.update(updates)
    return value


def diagnostic(reason, field_path):
    return {"schema_version": "filing-request-diagnostic/1",
            "reason": reason, "field_path": field_path}


CASES = [
    (request(fiscal_year=None), "exact_requires_fiscal_year", "fiscal_year"),
    (request(mode="latest_as_of", acquisition_limits=limits()),
     "latest_forbids_fiscal_year", "fiscal_year"),
    (request(mode="latest_as_of", fiscal_year=None),
     "latest_reuse_requires_acquisition_limits", "acquisition_limits"),
    (request(mode="latest_as_of", fiscal_year=None, acquisition_limits=limits(max_bytes=True)),
     "acquisition_limits_invalid", "acquisition_limits.max_bytes"),
    (request(filing_intent="fetch_if_missing", acquisition_limits=limits(timeout_seconds=0)),
     "acquisition_limits_invalid", "acquisition_limits.timeout_seconds"),
    (request(filing_intent="fetch_if_missing", acquisition_limits=limits(max_cost_usd="NaN")),
     "acquisition_limits_invalid", "acquisition_limits.max_cost_usd"),
    (request(filing_intent="fetch_if_missing", acquisition_limits={}),
     "acquisition_limits_invalid", "acquisition_limits"),
    (request(acquisition_limits=limits()), "acquisition_limits_invalid", "acquisition_limits"),
]


@pytest.mark.parametrize("value,reason,path", CASES)
def test_request_validation_carries_exact_typed_reason_without_input_copy(value, reason, path):
    with pytest.raises(FilingFetchError) as caught:
        validate_request(value)
    exc = caught.value
    assert exc.code == "request_error"
    assert exc.retryable is False
    assert exc.request_diagnostic == diagnostic(reason, path)
    assert exc.upstream_cause is None
    assert exc.acquisition_observation is None
    assert exc.acquisition_failure is None
    assert "Sample" not in json.dumps(exc.request_diagnostic)


@pytest.mark.parametrize("version,case", [(version, case) for version in ["1.2", "2.0"]
    for case in CASES[:4] if not (version == "1.2" and case[1] == "latest_reuse_requires_acquisition_limits")])
def test_public_failure_envelopes_keep_status_and_zero_calls(monkeypatch, version, case):
    value, reason, path = case
    value = deepcopy(value)
    value["schema_version"] = version
    if version == "1.2":
        value.pop("filing_intent")
    def forbidden(**kwargs):
        pytest.fail("request validation must finish before any CWP process or provider")
    monkeypatch.setattr(fetch, "_run_company_wiki_json_retry", forbidden)
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(value)))
    output = StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    assert fetch.main([]) == 2
    payload = json.loads(output.getvalue())
    detail = payload["filing"] if version == "2.0" else payload
    assert detail["request_diagnostic"] == diagnostic(reason, path)
    assert payload["status"] == detail["status"] == "request_error"
    assert detail["retryable"] is False
    assert payload["calls"] == payload["downloads"] == 0
    assert "source_ref" not in detail
    assert "upstream_cause" not in detail
    assert "acquisition_observation" not in payload


@pytest.mark.parametrize("bad", [
    {"schema_version": "filing-request-diagnostic/1", "reason": "secret_token", "field_path": "fiscal_year"},
    {"schema_version": "filing-request-diagnostic/1", "reason": "exact_requires_fiscal_year", "field_path": "acquisition_limits"},
    {"schema_version": "filing-request-diagnostic/1", "reason": "acquisition_limits_invalid", "field_path": "authorization.token"},
    {"schema_version": "filing-request-diagnostic/1", "reason": [], "field_path": "fiscal_year"},
    {**diagnostic("exact_requires_fiscal_year", "fiscal_year"), "request_body": "SECRET"},
    {**diagnostic("exact_requires_fiscal_year", "fiscal_year"), "schema_version": "bad"},
])
def test_closed_diagnostic_rejects_unknown_reason_path_type_and_extra_fields(bad):
    assert cause.validated_request_diagnostic(bad) is None
    with pytest.raises(TypeError):
        FilingFetchError("generic", code="request_error", request_diagnostic=bad)


def test_legacy_error_strings_are_never_parsed_into_a_typed_diagnostic(monkeypatch):
    text = "schema 1.2 requests require mode or fiscal_year SECRET_TOKEN https://host/?token=secret"
    exc = FilingFetchError(text, code="request_error")
    assert exc.request_diagnostic is None
    def fail(**kwargs):
        raise exc
    monkeypatch.setattr(fetch, "resolve_filing", fail)
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(request())))
    output = StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    assert fetch.main([]) == 2
    detail = json.loads(output.getvalue())["filing"]
    assert "request_diagnostic" not in detail
    assert "upstream_cause" not in detail


def test_diagnostic_does_not_expand_the_old_six_field_cause():
    old = cause.build_cause("ensure", "unknown")
    assert set(old) == cause.CAUSE_KEYS
    assert old["provider_started"] is old["usage_complete"] is None
    assert cause.validated_cause({**old, "field_path": "fiscal_year"}) is None
    assert old["retry_scope"] == "none"


def test_valid_latest_reuse_limits_preserve_discovery_route():
    value = request(mode="latest_as_of", fiscal_year=None, acquisition_limits=limits())
    validate_request(value)
    assert fetch._use_source_query(True, False, value) is False
    assert fetch._use_source_query(True, False, request()) is True


def test_companion_limits_do_not_impersonate_filing_limits():
    value = request(companion_transcript={
        "intent": "fetch_if_missing", "fiscal_year": 2026, "fiscal_quarter": 4,
        "acquisition_limits": limits(max_bytes=False),
    })
    with pytest.raises(FilingFetchError) as caught:
        validate_request(value)
    assert caught.value.request_diagnostic is None
    assert caught.value.code == "request_error"


def test_diagnostic_input_is_copied_and_revalidated_before_serialization(monkeypatch):
    original = diagnostic("exact_requires_fiscal_year", "fiscal_year")
    exc = FilingFetchError("fixed validation message", code="request_error", request_diagnostic=original)
    original["field_path"] = "SECRET"
    assert exc.request_diagnostic == diagnostic("exact_requires_fiscal_year", "fiscal_year")
    exc.request_diagnostic["field_path"] = "SECRET"
    def fail(**kwargs):
        raise exc
    monkeypatch.setattr(fetch, "resolve_filing", fail)
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(request())))
    output = StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    assert fetch.main([]) == 2
    detail = json.loads(output.getvalue())["filing"]
    assert "request_diagnostic" not in detail
    assert "SECRET" not in output.getvalue()
