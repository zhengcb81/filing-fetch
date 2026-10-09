"""W08: preserve producer observations, not a second fee ledger or raw text."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_filing as fetch  # noqa: E402
import ff_local_source_prepare as local  # noqa: E402
import ff_v2_envelope as envelope  # noqa: E402


def diagnostic(*, complete=True, count=17, code="upstream_unavailable"):
    return {"schema_version": "acquisition-failure/1", "code": code, "retryable": False,
            "provider_started": True, "usage_complete": complete, "usage_scope": "operation",
            "acquisition_usage": None if count is None else {"schema_version": "1.0", "response_bytes": count, "cost_usd": "0.03"}}


@pytest.mark.parametrize("complete,count,code", [(True, 17, "upstream_unavailable"),
    (False, 36, "adapter_timeout"), (None, None, "provider_failed"), (True, 92, "canonical_import_failed")])
def test_actual_child_failure_keeps_scoped_receipt_without_replay(tmp_path, complete, count, code):
    dto = diagnostic(complete=complete, count=count, code=code)
    output = {"status": "failed", "error_type": "fatal", "error": "https://invalid/?api_key=synthetic-w08-secret", "acquisition_failure": dto}
    marker = tmp_path / "attempts.txt"
    script = tmp_path / "producer.py"
    script.write_text("import sys\nfrom pathlib import Path\np=Path(" + repr(str(marker)) + ")\np.write_text(p.read_text()+'x' if p.exists() else 'x')\nsys.stderr.write(" + repr(json.dumps(output)) + ")\nraise SystemExit(1)\n", encoding="utf-8")
    stats = {"calls": 0, "downloads": 0}
    with pytest.raises(fetch.FilingFetchError) as caught:
        fetch._run_company_wiki_json_retry(command=[sys.executable, "-B", str(script)], root=tmp_path,
                                          action="ensure", deadline=time.monotonic() + 10, stats=stats)
    error = caught.value
    assert getattr(error, "acquisition_failure", None) == dto
    assert error.upstream_cause["code"] == code
    assert error.upstream_cause["usage_complete"] is complete
    assert stats == {"calls": 1, "downloads": 0} and marker.read_text() == "x"
    assert "synthetic-w08-secret" not in str(error)


def gap(dto):
    return {"operation_schema_version": "1.0", "operation": "ensure", "status": "gap", "request_id": "synthetic-one",
            "outcome": "gap", "download_events": 0, "policy_hash": None, "source_ref": None, "candidate": None,
            "gap_plan": {"schema_version": "1.0", "request_id": "synthetic-one", "gap_hash": "a" * 64}, "acquisition_failure": dto}


def test_returned_gap_keeps_same_producer_receipt_in_v2():
    dto = diagnostic(complete=False, count=36)
    handle = fetch._pathless_operation_gap(gap(dto), operation="ensure")
    result = envelope.success_envelope({}, handle, {"status": "not_applicable"}, {"calls": 2, "downloads": 0})
    assert result["filing"].get("acquisition_failure") == dto
    assert result["filing"]["upstream_cause"]["usage_complete"] is False
    assert result["calls"] == 2 and result["downloads"] == 0


def test_v2_error_restores_existing_stage_attempt_and_receipt():
    dto = diagnostic()
    cause = {"schema_version": "filing-upstream-cause/1", "operation": "ensure", "code": "upstream_unavailable",
             "provider_started": True, "usage_complete": True, "retry_scope": "none"}
    error = fetch.FilingFetchError("safe fixed text", code="fatal", stage="ensure", attempts=1,
                                   upstream_cause=cause, acquisition_failure=dto)
    result = envelope.error_envelope(error.code, str(error), retryable=error.retryable, stats={"calls": 2, "downloads": 0},
        upstream_cause=error.upstream_cause, acquisition_failure=error.acquisition_failure, stage=error.stage, attempts=error.attempts)
    assert {key: result["filing"][key] for key in ("stage", "attempts", "acquisition_failure")} == {
        "stage": "ensure", "attempts": 1, "acquisition_failure": dto}


@pytest.mark.parametrize("reason,expected", [("local_metadata_gap", "local_metadata_gap"),
    ("no_registered_local_source", "no_registered_local_source"), ("api_key=synthetic-w08-secret", "unknown")])
def test_local_condition_is_safe_machine_subtype(reason, expected):
    payload = {"schema_version": "local-source-prepare/1", "status": "blocked", "reason": reason,
               "source_ref": None, "blocks_download": True, "operations": [], "diagnostics": [], "download_events": 0}
    with pytest.raises(fetch.FilingFetchError) as caught:
        local._validated(payload, lambda value: False)
    assert caught.value.upstream_cause["operation"] == "local_prepare"
    assert caught.value.upstream_cause["code"] == expected
    assert caught.value.upstream_cause["provider_started"] is False
    assert caught.value.upstream_cause["usage_complete"] is True
    assert "synthetic-w08-secret" not in str(caught.value)


def test_invalid_operation_schema_has_finite_condition_without_usage_inference():
    with pytest.raises(fetch.FilingFetchError) as caught:
        fetch._validated_operation({"operation_schema_version": "new-unsupported"}, "ensure")
    assert caught.value.upstream_cause["code"] == "invalid_producer_schema"
    assert caught.value.upstream_cause["provider_started"] is None
    assert caught.value.upstream_cause["usage_complete"] is None


@pytest.mark.parametrize("alteration", [{"usage_scope": "invocation"}, {"code": "api_key=synthetic-w08-secret"},
    {"acquisition_usage": {"schema_version": "1.0", "response_bytes": True, "cost_usd": "0"}},
    {"acquisition_usage": {"schema_version": "1.0", "response_bytes": 3, "cost_usd": "NaN"}},
    {"extra": "https://invalid/?api_key=synthetic-w08-secret"}])
def test_malformed_observation_never_published(tmp_path, alteration):
    dto = {**diagnostic(), **alteration}
    raw = json.dumps({"status": "failed", "error_type": "fatal", "acquisition_failure": dto})
    script = tmp_path / "producer.py"
    script.write_text("import sys\nsys.stderr.write(" + repr(raw) + ")\nraise SystemExit(1)\n", encoding="utf-8")
    with pytest.raises(fetch.FilingFetchError) as caught:
        fetch._run_company_wiki_json(command=[sys.executable, "-B", str(script)], root=tmp_path, action="ensure", timeout_seconds=10)
    assert getattr(caught.value, "acquisition_failure", None) is None
    assert "synthetic-w08-secret" not in str(caught.value)


@pytest.mark.parametrize("body", ["not-json", "[]", '{"unexpected":"body"}'])
def test_invalid_provider_wire_keeps_named_schema_diagnostic(tmp_path, body):
    script = tmp_path / "producer.py"
    script.write_text("print(" + repr(body) + ")\n", encoding="utf-8")
    with pytest.raises(fetch.FilingFetchError) as caught:
        result = fetch._run_company_wiki_json(command=[sys.executable, "-B", str(script)], root=tmp_path, action="ensure", timeout_seconds=10)
        fetch._validated_operation(result, "ensure")
    assert caught.value.upstream_cause["code"] == "invalid_producer_schema"
    assert getattr(caught.value, "acquisition_failure", None) is None


def test_invalid_local_wire_is_different_from_real_metadata_gap():
    with pytest.raises(fetch.FilingFetchError) as caught:
        local._validated({"schema_version": "unknown"}, lambda value: False)
    assert caught.value.upstream_cause["code"] == "invalid_producer_schema"
