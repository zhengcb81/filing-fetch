"""Operation-scoped CWP diagnostics consumed once without retry or usage guesses."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_filing
import ff_process_transport as transport
import ff_provider_cause as cause

CODES = {
    "adapter_process_failed", "adapter_timeout", "adapter_output_limit",
    "adapter_response_invalid", "adapter_not_bounded", "upstream_unavailable",
    "network_failed", "budget_exceeded", "provider_failed", "provider_not_configured",
    "invalid_request", "invalid_budget", "invalid_candidate", "missing_scratch",
    "invalid_scratch", "unsupported_language", "unsupported_sec_form", "unsupported_hk_period",
    "identity_mismatch", "invalid_provider_metadata", "primary_missing",
    "fiscal_period_unresolved", "missing_response", "staging_conflict", "sdk_asset_mismatch",
    "deadline_exceeded", "byte_budget_exceeded", "cost_budget_exceeded",
    "unsupported_content_encoding", "incomplete_response", "acquisition_budget_exceeded",
    "acquisition_validation_failed", "canonical_import_failed",
}


def diagnostic(**changes):
    result = dict(schema_version="acquisition-failure/1", code="provider_failed",
                  retryable=True, provider_started=True, usage_complete=True,
                  acquisition_usage={"schema_version": "1.0", "response_bytes": 17,
                                     "cost_usd": "0.0002"}, usage_scope="operation")
    result.update(changes)
    return result


def stderr(diag, error_type="fatal"):
    return json.dumps(dict(status="failed", error_type=error_type,
                           error="secret-key /physical/path?token=secret", retryable=False,
                           acquisition_failure=diag))


@pytest.mark.parametrize("code", sorted(CODES))
def test_valid_diagnostic_closed_codes_are_projected_without_changing_retry(code):
    filing_code, projected = cause.diagnose_stderr("ensure", stderr(diagnostic(code=code)))
    assert filing_code == "fatal"
    assert projected == dict(schema_version="filing-upstream-cause/1", operation="ensure",
                            code=code, provider_started=True, usage_complete=True,
                            retry_scope="none")
    assert set(projected) == cause.CAUSE_KEYS
    assert cause.validated_cause(projected) == projected


def test_stderr_is_parsed_exactly_once_and_catalog_retry_stays_generic():
    text = stderr(diagnostic(code="adapter_timeout", retryable=False), "catalog_busy")
    with patch.object(cause.json, "loads", wraps=json.loads) as parse:
        filing_code, projected = cause.diagnose_stderr("ensure", text)
    assert parse.call_count == 1
    assert filing_code == "catalog_busy"
    assert projected["code"] == "adapter_timeout"
    assert projected["retry_scope"] == "catalog_contention"


@pytest.mark.parametrize("started,complete,usage", [
    (None, None, None), (True, False, {"schema_version": "1.0", "response_bytes": 9,
                                    "cost_usd": "0.1"}),
    (False, True, {"schema_version": "1.0", "response_bytes": 0, "cost_usd": "0"}),
])
def test_bool_null_evidence_and_lower_bounds_are_not_invented(started, complete, usage):
    _, projected = cause.diagnose_stderr("ensure", stderr(diagnostic(
        provider_started=started, usage_complete=complete, acquisition_usage=usage)))
    assert projected["provider_started"] is started
    assert projected["usage_complete"] is complete
    assert set(projected) == cause.CAUSE_KEYS
    assert "acquisition_usage" not in projected


@pytest.mark.parametrize("changes", [
    {"schema_version": "acquisition-failure/2"}, {"usage_scope": "last_child"},
    {"retryable": "true"}, {"provider_started": 1}, {"usage_complete": "yes"},
    {"acquisition_usage": {}},
    {"acquisition_usage": {"schema_version": "2.0", "response_bytes": 1, "cost_usd": "0"}},
    {"acquisition_usage": {"schema_version": "1.0", "response_bytes": True, "cost_usd": "0"}},
    {"acquisition_usage": {"schema_version": "1.0", "response_bytes": -1, "cost_usd": "0"}},
    {"acquisition_usage": {"schema_version": "1.0", "response_bytes": 1, "cost_usd": "NaN"}},
    {"acquisition_usage": {"schema_version": "1.0", "response_bytes": 1, "cost_usd": "Infinity"}},
    {"acquisition_usage": {"schema_version": "1.0", "response_bytes": 1, "cost_usd": "-0.1"}},
    {"acquisition_usage": {"schema_version": "1.0", "response_bytes": 1, "cost_usd": 0}},
    {"acquisition_usage": {"schema_version": "1.0", "response_bytes": 1, "cost_usd": "0", "path": "secret"}},
    {"code": {"nested": "secret"}}, {"code": ["provider_failed"]},
])
def test_invalid_new_diagnostic_falls_back_to_old_generic_with_unknown_usage(changes):
    filing_code, projected = cause.diagnose_stderr("ensure", stderr(diagnostic(**changes), "catalog_busy"))
    assert filing_code == "catalog_busy"
    assert projected["code"] == "catalog_busy"
    assert projected["provider_started"] is None
    assert projected["usage_complete"] is None
    assert projected["retry_scope"] == "catalog_contention"


@pytest.mark.parametrize("diag", [None, [], {}, {"schema_version": "acquisition-failure/1"},
                                   {**diagnostic(), "physical_path": "secret"}])
def test_wrong_seven_field_shape_does_not_leak_or_guess(diag):
    _, projected = cause.diagnose_stderr("ensure", stderr(diag))
    assert projected["code"] == "fatal"
    assert projected["provider_started"] is None
    assert projected["usage_complete"] is None
    assert "secret" not in json.dumps(projected)


@pytest.mark.parametrize("code", ["secret-key /physical/path?token=secret", "provider_failed\\napi_key=secret", "new_code"])
def test_unknown_string_codes_are_normalized_not_copied(code):
    _, projected = cause.diagnose_stderr("ensure", stderr(diagnostic(code=code)))
    assert projected["code"] == "adapter_process_failed"
    assert projected["provider_started"] is True
    assert projected["usage_complete"] is True
    assert code not in json.dumps(projected)


@pytest.mark.parametrize("field", ["code", "operation", "retry_scope", "schema_version"])
def test_untrusted_cause_values_never_raise_typeerror(field):
    obj = cause.build_cause("ensure", "fatal")
    obj[field] = {"nested": "malicious"}
    assert cause.validated_cause(obj) is None


def test_arbitrary_oserror_after_start_never_claims_no_start_or_zero(tmp_path):
    with patch("fetch_filing._run_bounded_json", side_effect=OSError("cleanup failed after execution")):
        with pytest.raises(fetch_filing.FilingFetchError) as caught:
            fetch_filing._run_company_wiki_json(command=["fake"], root=tmp_path,
                                               timeout_seconds=3, action="ensure")
    assert caught.value.code == "fatal"  # old retry semantics stay unchanged
    projected = caught.value.upstream_cause
    assert projected["code"] == "producer_transport_failure"
    assert projected["provider_started"] is None
    assert projected["usage_complete"] is None


def test_actual_popen_failure_has_typed_pre_start_proof():
    with patch.object(transport.subprocess, "Popen", side_effect=OSError("no executable")):
        with pytest.raises(transport.ChildStartFailed):
            transport.run_bounded([sys.executable, "-c", "pass"], timeout_seconds=3)


def test_typed_start_failure_preserves_honest_no_provider_start(tmp_path):
    with patch("fetch_filing._run_bounded_json", side_effect=transport.ChildStartFailed("could not start")):
        with pytest.raises(fetch_filing.FilingFetchError) as caught:
            fetch_filing._run_company_wiki_json(command=["fake"], root=tmp_path,
                                               timeout_seconds=3, action="ensure")
    assert caught.value.code == "fatal"
    assert caught.value.upstream_cause["code"] == "producer_start_failed"
    assert caught.value.upstream_cause["provider_started"] is False
    assert caught.value.upstream_cause["usage_complete"] is True


def test_real_child_executed_before_cleanup_oserror_is_not_no_start(tmp_path):
    marker = tmp_path / "executed"
    cleanup = transport._cleanup
    def fail_after_cleanup(*args):
        cleanup(*args)
        raise OSError("post-start cleanup failed")
    with patch.object(transport, "_cleanup", side_effect=fail_after_cleanup):
        with pytest.raises(fetch_filing.FilingFetchError) as caught:
            fetch_filing._run_company_wiki_json(
                command=[sys.executable, "-B", "-c",
                         "from pathlib import Path; Path('executed').write_text('done'); print('{}')"],
                root=tmp_path, timeout_seconds=10, action="ensure")
    assert marker.read_text() == "done"
    assert caught.value.upstream_cause["provider_started"] is None
    assert caught.value.upstream_cause["usage_complete"] is None
    assert caught.value.upstream_cause["code"] == "producer_transport_failure"



def operation_gap(diag=None):
    payload = dict(operation_schema_version="1.0", operation="ensure", status="gap",
                   request_id="request:gap", outcome="gap", download_events=0,
                   policy_hash=None, source_ref=None, candidate=None,
                   gap_plan={"schema_version": "1.0", "gap_hash": "a"*64,
                             "request_id": "request:gap"})
    if diag is not None:
        payload["acquisition_failure"] = diag
    return payload


def test_returned_failure_gap_keeps_status_and_safe_cause_in_public_v2_envelope():
    from ff_v2_envelope import success_envelope
    payload = operation_gap(diagnostic(usage_complete=False))
    result = fetch_filing._pathless_operation_gap(payload, operation="ensure")
    assert result["status"] == "gap"
    expected = dict(schema_version="filing-upstream-cause/1", operation="ensure",
                    code="provider_failed", provider_started=True, usage_complete=False,
                    retry_scope="none")
    assert result["upstream_cause"] == expected
    envelope = success_envelope({"schema_version": "2.0"}, result, {}, {"calls": 2, "downloads": 0})
    assert envelope["status"] == "gap"
    assert envelope["filing"]["status"] == "gap"
    assert envelope["filing"]["upstream_cause"] == expected
    assert envelope["calls"] == 2 and envelope["downloads"] == 0
    assert "secret" not in json.dumps(envelope)


@pytest.mark.parametrize("diag", [None, diagnostic(schema_version="invalid"),
                                  {**diagnostic(), "physical_path": "secret"}])
def test_normal_or_malformed_diagnostic_gap_stays_a_normal_gap(diag):
    from ff_v2_envelope import success_envelope
    result = fetch_filing._pathless_operation_gap(operation_gap(diag), operation="ensure")
    envelope = success_envelope({}, result, {}, {"calls": 2, "downloads": 0})
    assert envelope["status"] == "gap"
    assert "upstream_cause" not in result
    assert "upstream_cause" not in envelope["filing"]
    assert "secret" not in json.dumps(envelope)


def test_failure_body_reads_only_top_level_diagnostic_not_nested_gap_data():
    payload = operation_gap()
    payload["gap_plan"]["acquisition_failure"] = diagnostic()
    result = fetch_filing._pathless_operation_gap(payload, operation="ensure")
    assert "upstream_cause" not in result


def test_returned_unavailable_attaches_safe_diagnostic_without_retry_upgrade():
    payload = operation_gap(diagnostic(code="canonical_import_failed"))
    payload.update(status="unavailable", outcome=None, gap_plan=None)
    with pytest.raises(fetch_filing.FilingFetchError) as caught:
        fetch_filing._pathless_operation_handle(payload, operation="ensure", request={},
                                                company_identity={}, stats={"downloads": 0, "calls": 2})
    assert caught.value.code == "upstream_error"
    assert caught.value.upstream_cause["code"] == "canonical_import_failed"
    assert caught.value.upstream_cause["retry_scope"] == "none"


def test_public_gap_serializer_ignores_an_unvalidated_cause():
    from ff_v2_envelope import success_envelope
    result = fetch_filing._pathless_operation_gap(operation_gap(), operation="ensure")
    result["upstream_cause"] = {"code": "secret"}
    envelope = success_envelope({}, result, {}, {"calls": 2, "downloads": 0})
    assert "upstream_cause" not in envelope["filing"]



def test_typed_start_failure_remains_oserror_for_existing_transport_callers():
    # ET callers already distinguish no-Popen OSError from started transport
    # failure. A new type must refine that contract, not move it to a different
    # generic TransportError branch with an invented provider-call count.
    assert isinstance(transport.ChildStartFailed("no process"), OSError)
    assert not isinstance(transport.ChildStartFailed("no process"), transport.TransportError)
