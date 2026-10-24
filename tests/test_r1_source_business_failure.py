"""R1 fail-first coverage of bounded business failures; no provider calls."""

from __future__ import annotations

from copy import deepcopy
import json
import sys
import time

import pytest

import fetch_filing as ff
import ff_local_source_prepare as local
import ff_process_transport as transport
from ff_v2_envelope import error_envelope
from filing_contracts import FilingFetchError
from test_source_ref_v2_db_query import _operation_v2


def request():
    return {
        "schema_version": "2.0",
        "company_query": "Fixture Co",
        "market": "HK",
        "document_kind": "semi_annual_report",
        "fiscal_year": 2026,
        "fiscal_period": "H1",
        "as_of_date": "2026-10-21",
        "filing_intent": "reuse_only",
        "companion_transcript": {
            "intent": "fetch_if_missing",
            "fiscal_year": 2026,
            "fiscal_quarter": 2,
            "provider": "fmp",
            "acquisition_limits": {"max_bytes": 100000, "timeout_seconds": 10, "max_cost_usd": "0"},
        },
    }


def prepared(status="unavailable", reason="local_candidate_limit"):
    return {
        "schema_version": "local-source-prepare/1",
        "status": status,
        "reason": reason,
        "source_ref": None,
        "blocks_download": True,
        "operations": [],
        "diagnostics": [],
        "download_events": 0,
    }


def local_read_budget():
    return {
        "schema_version": "local-read-budget/1",
        "operation": "local_read_budget",
        "usage_scope": "local_original_verification",
        "phase": "source_group_discovery",
        "reason": "local_source_group_limit",
        "limits": {
            "max_candidates": 16, "max_bytes": 268435456,
            "timeout_seconds": 30.0, "max_discovery_groups": 256,
            "max_discovery_entries": 4096,
        },
        "consumed": {
            "candidates": 0, "charged_read_bytes": 0, "observed_charge_bytes": 0,
            "discovery_groups": 257, "discovery_entries": 0, "elapsed_seconds": 0.125,
        },
        "triggered_bound": "max_discovery_groups",
    }


def child(payload, rc=2):
    return [
        sys.executable,
        "-S",
        "-c",
        "import json,sys; print(json.dumps(" + repr(payload) + ")); sys.exit(" + str(rc) + ")",
    ]


def test_real_nonzero_query_retains_named_cold_catalog_reason(tmp_path, monkeypatch):
    payload = {
        "schema_version": "2.0",
        "status": "unavailable",
        "reason": "catalog_unavailable",
        "matches": [],
        "candidates": [],
    }
    real_transport = transport.run_bounded_json
    monkeypatch.setattr(
        ff,
        "_run_bounded_json",
        lambda command, **kwargs: real_transport(child(payload), **{**kwargs, "input_bytes": None}),
    )
    with pytest.raises(FilingFetchError) as caught:
        ff._run_source_query(
            root=tmp_path,
            normalized_request={"entity": "Fixture Co"},
            deadline=time.monotonic() + 20,
            stats={"calls": 0, "downloads": 0},
        )
    assert caught.value.upstream_cause["code"] == "catalog_unavailable"
    assert caught.value.upstream_cause["provider_started"] is False
    assert caught.value.producer_exit_code == 2


def test_real_nonzero_local_prepare_preserves_limit(tmp_path):
    def actual_transport(command, **kwargs):
        return transport.run_bounded_json(child(prepared(), 1), **{**kwargs, "input_bytes": None})

    with pytest.raises(FilingFetchError) as caught:
        local.prepare_existing_local_source(
            root=tmp_path,
            source_request={"entity": "Fixture Co"},
            deadline=time.monotonic() + 20,
            stats={"calls": 0, "downloads": 0},
            transport=actual_transport,
            physical_fields=ff._contains_physical_field,
        )
    assert caught.value.upstream_cause["code"] == "local_candidate_limit"
    assert caught.value.producer_exit_code == 1


def test_operation_accepts_current_closed_local_preparation():
    payload = _operation_v2(status="blocked", outcome=None)
    payload["local_preparation"] = {
        "status": "blocked",
        "reason": "local_metadata_gap",
        "blocks_download": True,
        "causes": ["publication_date_unknown"],
    }
    assert ff._validated_operation(payload, "ensure") == payload
    with pytest.raises(FilingFetchError) as caught:
        ff._pathless_operation_handle(
            payload,
            operation="ensure",
            request=request(),
            company_identity={},
            stats={"calls": 0, "downloads": 0},
        )
    assert caught.value.code == "source_blocked"
    assert caught.value.upstream_cause["code"] == "local_metadata_gap"
    assert caught.value.upstream_cause["provider_started"] is False


def test_ensure_local_read_budget_reaches_existing_local_observation_envelope():
    operation = local_read_budget()
    payload = _operation_v2(status="blocked", outcome=None)
    payload["local_preparation"] = {
        "status": "blocked", "reason": "local_source_group_limit",
        "blocks_download": True, "causes": [], "local_read_budget": operation,
    }
    assert ff._validated_operation(payload, "ensure") == payload
    with pytest.raises(FilingFetchError) as caught:
        ff._pathless_operation_handle(
            payload,
            operation="ensure",
            request=request(),
            company_identity={},
            stats={"calls": 0, "downloads": 0},
        )
    observation = caught.value.local_preparation_observation
    assert observation["schema_version"] == "filing-local-preparation-observation/1"
    assert observation["local_read_limits"] == {
        "max_candidates": 16, "max_bytes": 268435456, "timeout_seconds": 30.0,
    }
    assert observation["operations"] == [operation]
    assert observation["operations"][0]["triggered_bound"] == "max_discovery_groups"
    assert observation["operations"][0]["consumed"]["discovery_groups"] == 257
    assert observation["local_io_usage"] is None
    assert caught.value.upstream_cause["provider_started"] is False
    assert caught.value.upstream_cause["usage_complete"] is True


@pytest.mark.parametrize(
    "change",
    [
        {"path": "hidden/original.pdf"},
        {"extra": "not part of contract"},
        {"local_read_budget": {"schema_version": "local-read-budget/1", "operation": "local_read_budget"}},
        {"blocks_download": False},
        {"status": "completed"},
        {"reason": "hidden/original.pdf"},
        {"causes": ["unwanted/key"]},
    ],
)
def test_local_preparation_extension_stays_closed(change):
    payload = _operation_v2(status="blocked", outcome=None)
    payload["local_preparation"] = {
        "status": "blocked",
        "reason": "local_metadata_gap",
        "blocks_download": True,
        "causes": [],
    }
    payload["local_preparation"].update(change)
    with pytest.raises(FilingFetchError):
        ff._validated_operation(payload, "ensure")


def test_requested_companion_is_not_run_when_filing_failed():
    result = error_envelope(
        "upstream_error",
        "company-wiki ensure unavailable",
        retryable=False,
        request=request(),
        stats={"calls": 2, "downloads": 0},
    )
    companion = result["transcript"]
    assert companion["status"] == "not_run"
    assert companion["reason"] == "filing_failed_before_companion_dispatch"
    for key in ("intent", "fiscal_year", "fiscal_quarter", "provider", "acquisition_limits"):
        assert companion[key] == request()["companion_transcript"][key]
    assert companion["retryable"] is False and companion["provider_started"] is False
    assert companion["provider_requests"] == 0
    req = deepcopy(request())
    del req["companion_transcript"]
    assert error_envelope("upstream_error", "failed", retryable=False, request=req)[
        "transcript"
    ] == {"status": "not_requested", "retryable": False}
    req["companion_transcript"] = {"intent": "reuse_only", "fiscal_year": 2026}
    assert (
        error_envelope("upstream_error", "failed", retryable=False, request=req)["transcript"][
            "status"
        ]
        == "period_unresolved"
    )


@pytest.mark.parametrize(
    "payload",
    [
        [],
        "<html>bad</html>",
        {"schema_version": "9", "status": "blocked"},
        {
            "schema_version": "2.0",
            "status": "found",
            "reason": "catalog_unavailable",
            "matches": [],
            "candidates": [],
        },
        {
            "schema_version": "2.0",
            "status": "unavailable",
            "reason": "catalog_unavailable",
            "matches": [],
            "candidates": [],
            "path": "bad.pdf",
        },
        {
            "schema_version": "2.0",
            "status": "unavailable",
            "reason": "catalog_unavailable",
            "matches": [],
            "candidates": [],
            "request_id": "wrong-request",
        },
    ],
)
def test_nonzero_query_never_accepts_wrong_schema_request_or_storage(
    tmp_path, monkeypatch, payload
):
    monkeypatch.setattr(
        ff,
        "_run_bounded_json",
        lambda *a, **kw: (_ for _ in ()).throw(
            transport.ChildFailed("failed", returncode=2, stdout=json.dumps(payload).encode())
        ),
    )
    with pytest.raises(FilingFetchError) as caught:
        ff._run_source_query(
            root=tmp_path,
            normalized_request={"entity": "Fixture Co"},
            deadline=time.monotonic() + 5,
            stats={"calls": 0, "downloads": 0},
        )
    assert caught.value.upstream_cause["code"] == "invalid_producer_schema"


def test_real_nonzero_ensure_retains_business_failure_and_request_binding(tmp_path):
    from ff_source_failure import source_request_id

    current = {
        "entity": "Fixture Co",
        "market": "HK",
        "security_id": "09999",
        "document_kind": "semi_annual_report",
        "fiscal_year": 2026,
        "fiscal_period": "H1",
        "as_of_date": "2026-10-21",
    }
    payload = _operation_v2(status="unavailable", outcome=None)
    payload["request_id"] = source_request_id(current)
    payload["local_preparation"] = {
        "status": "unavailable",
        "reason": "local_candidate_limit",
        "blocks_download": True,
        "causes": [],
    }
    with pytest.raises(FilingFetchError) as caught:
        ff._run_company_wiki_json(
            command=child(payload),
            root=tmp_path,
            timeout_seconds=20,
            action="ensure",
            source_request=current,
        )
    assert caught.value.upstream_cause["code"] == "local_candidate_limit"
    assert caught.value.upstream_cause["provider_started"] is False
    assert caught.value.producer_exit_code == 2
    payload["request_id"] = "urn:company-wiki:source-request:sha256:" + "0" * 64
    with pytest.raises(FilingFetchError) as invalid:
        ff._run_company_wiki_json(
            command=child(payload),
            root=tmp_path,
            timeout_seconds=20,
            action="ensure",
            source_request=current,
        )
    assert invalid.value.upstream_cause["code"] == "invalid_producer_schema"


@pytest.mark.parametrize(
    "change",
    [
        {"operation": "close-gap"},
        {"path": "raw.pdf"},
        {"extra": "unknown"},
        {"status": "completed"},
    ],
)
def test_nonzero_ensure_does_not_accept_wrong_action_or_success(tmp_path, change):
    from ff_source_failure import source_request_id

    current = {"entity": "Other Co", "document_kind": "annual_report", "as_of_date": "2026-10-21"}
    payload = _operation_v2(status="unavailable", outcome=None)
    payload["request_id"] = source_request_id(current)
    payload.update(change)
    with pytest.raises(FilingFetchError) as caught:
        ff._run_company_wiki_json(
            command=child(payload),
            root=tmp_path,
            timeout_seconds=20,
            action="ensure",
            source_request=current,
        )
    assert caught.value.upstream_cause["code"] == "invalid_producer_schema"


def test_real_malformed_and_truncated_query_json_is_contract_failure(tmp_path, monkeypatch):
    real = transport.run_bounded_json
    command = [sys.executable, "-S", "-c", 'import sys;print("{\\"schema_version\\":");sys.exit(2)']
    monkeypatch.setattr(
        ff,
        "_run_bounded_json",
        lambda original, **kwargs: real(command, **{**kwargs, "input_bytes": None}),
    )
    with pytest.raises(FilingFetchError) as caught:
        ff._run_source_query(
            root=tmp_path,
            normalized_request={"entity": "Fixture Co"},
            deadline=time.monotonic() + 20,
            stats={"calls": 0, "downloads": 0},
        )
    assert caught.value.upstream_cause["code"] == "invalid_producer_schema"
    assert caught.value.producer_exit_code == 2


def test_synthetic_nonzero_success_local_prepare_is_not_reused(tmp_path):
    from test_local_source_prepare import _prepared

    def command(*args, **kwargs):
        raise transport.ChildFailed(
            "not a successful exit", returncode=2, stdout=json.dumps(_prepared()).encode()
        )

    with pytest.raises(FilingFetchError, match="nonzero"):
        local.prepare_existing_local_source(
            root=tmp_path,
            source_request={},
            deadline=time.monotonic() + 10,
            stats={"calls": 0, "downloads": 0},
            transport=command,
            physical_fields=ff._contains_physical_field,
        )


def test_public_request_fingerprints_match_native_cwp_freeze():
    from pathlib import Path
    from ff_source_failure import source_request_id

    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "r1_source_request_fingerprints.json").read_text(
            encoding="utf-8"
        )
    )
    for case in fixture["cases"]:
        assert source_request_id(case["request"]) == case["request_id"]


@pytest.mark.parametrize("change", [{"download_events": False}, {"outcome": "downloaded_new"}])
def test_nonzero_operation_accounting_must_be_consistent(tmp_path, change):
    from ff_source_failure import source_request_id

    current = {"entity": "Fixture Co", "document_kind": "annual_report", "as_of_date": "2026-10-21"}
    payload = _operation_v2(status="unavailable", outcome=None)
    payload["request_id"] = source_request_id(current)
    payload["local_preparation"] = {
        "status": "unavailable",
        "reason": "local_candidate_limit",
        "blocks_download": True,
        "causes": [],
    }
    payload.update(change)
    with pytest.raises(FilingFetchError) as caught:
        ff._run_company_wiki_json(
            command=child(payload),
            root=tmp_path,
            timeout_seconds=20,
            action="ensure",
            source_request=current,
        )
    assert caught.value.upstream_cause["code"] == "invalid_producer_schema"
    assert caught.value.upstream_cause["provider_started"] is None
