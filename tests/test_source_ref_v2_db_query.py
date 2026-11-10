"""Opt-in FF source candidates must come from a DB-only CWP query."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from unittest.mock import patch
from support import bounded_side_effect

import pytest

import fetch_filing
from filing_contracts import FilingFetchError


SHA = hashlib.sha256(b"isolated metadata-only source").hexdigest()
DOCUMENT = "urn:company-wiki:document:sha256:" + SHA
SOURCE = "urn:company-wiki:source:sha256:" + SHA


def _wiki(tmp_path: Path) -> Path:
    root = tmp_path / "wiki"
    config = root / "config"
    config.mkdir(parents=True)
    (config / "source_catalog.yaml").write_text("schema_version: '1.0'\n", encoding="utf-8")
    return root


def _request() -> dict:
    return {
        "schema_version": "1.1", "company_query": "AMD", "market": "US",
        "document_kind": "annual_report", "fiscal_year": 2025,
        "as_of_date": "2026-07-18",
    }


def _v2_request(*, intent: str = "fetch_if_missing") -> dict:
    return {
        **_request(),
        "schema_version": "2.0",
        "filing_intent": intent,
        "acquisition_limits": {
            "max_bytes": 5_000_000,
            "timeout_seconds": 60,
            "max_cost_usd": "1.00",
        },
    }


def _identity() -> dict:
    return {
        "schema_version": "1.0", "status": "resolved", "reason": "exact ticker",
        "resolved": {
            "canonical_name": "Advanced Micro Devices, Inc.",
            "market": "US", "exchange": "NASDAQ", "ticker": "AMD",
            "security_id": "AMD", "match_basis": "ticker",
            "matched_value": "AMD", "source_name": "SEC",
            "source_url": "https://www.sec.gov/files/company_tickers.json",
            "source_record_id": "urn:company-wiki:security:US:AMD",
            "verified": True, "active": True,
        },
    }


def _ref() -> dict:
    return {
        "schema_version": "2.0", "document_id": DOCUMENT,
        "source_id": SOURCE, "content_sha256": SHA, "byte_size": 42,
        "mime_type": "application/pdf",
    }


def _candidate() -> dict:
    return {
        "source_ref": _ref(), "document_id": DOCUMENT,
        "source_id": SOURCE, "title": "AMD 2025 annual report",
        "document_kind": "annual_report", "fiscal_year": 2025,
        "fiscal_period": None, "period_end": "2025-12-31",
        "form_type": "10-K", "market": "US", "security_id": "AMD",
        "published_date": "2026-02-20",
        "https_url": "https://www.sec.gov/Archives/amd/2025",
        "snapshot_sha256": SHA, "byte_size": 42,
        "mime_type": "application/pdf",
        "retrieved_at": "2026-02-21T00:00:00Z",
        "collector_name": "filesystem-catalog-company_raw",
        "collector_version": "1.0.0", "provider": "sec",
        "provider_document_id": "amd-2025-10k",
        "capture_ready": True, "capture_provenance": "indexed_location_manifest",
        "prompt_injection_status": "not_detected",
    }


def _query(status: str = "found", candidate: dict | None = None) -> dict:
    return {
        "schema_version": "2.0", "status": status,
        "reason": "one_local_match" if status == "found" else "no_local_match",
        "request_id": "urn:company-wiki:source-request:sha256:" + "a" * 64,
        "matches": [_ref()] if status == "found" else [],
        "candidates": [candidate or _candidate()] if status == "found" else [],
        "source_read_policy_sha256": "b" * 64,
    }


def _completed(payload: dict, rc: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], rc, json.dumps(payload), "")


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_company_wiki_identity_contract_accepts_compatible_versions(version: str) -> None:
    payload = _identity()
    payload["schema_version"] = version
    assert fetch_filing._resolved_company_identity(payload)["security_id"] == "AMD"


def test_company_wiki_identity_contract_rejects_unsupported_version() -> None:
    payload = _identity()
    payload["schema_version"] = "1.2"
    with pytest.raises(FilingFetchError, match="schema_version is unsupported"):
        fetch_filing._resolved_company_identity(payload)


def test_reuse_queries_db_only_without_resolve_or_source_bytes(tmp_path: Path) -> None:
    root = _wiki(tmp_path)
    stats = {"calls": 0, "downloads": 0}
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([_completed(_identity()), _completed(_query())]),
    ) as run, patch.object(
        Path, "read_bytes", side_effect=AssertionError("FF opened source bytes")
    ):
        handle = fetch_filing.resolve_filing(
            request=_request(), company_wiki_root=root,
            source_ref_v2=True, stats=stats,
        )
    commands = [call.args[0] for call in run.call_args_list]
    assert len(commands) == stats["calls"] == 2
    assert "identify" in commands[0]
    assert "company_wiki.source_catalog.source_query_cli" in commands[1]
    assert "resolve" not in commands[1] and "ensure" not in commands[1]
    source_query = json.loads(run.call_args_list[1].kwargs["input_bytes"])
    assert source_query["entity"] == "Advanced Micro Devices, Inc."
    assert source_query["market"] == "US"
    assert source_query["security_id"] == "AMD"
    assert source_query["fiscal_year"] == 2025
    assert source_query["allow_download"] is False
    assert handle["source_ref"] == _ref()
    assert handle["company_identity"]["security_id"] == "AMD"
    assert handle["download_events"] == stats["downloads"] == 0
    assert handle["prompt_injection_status"] == "not_detected"
    assert "source_read_policy_sha256" not in handle
    assert "canonical_path" not in json.dumps(handle)


def test_cross_market_request_keeps_listing_and_source_identity_separate(tmp_path: Path) -> None:
    request = _v2_request(intent="reuse_only")
    request.pop("acquisition_limits")
    request.update({
        "company_query": "BABA", "source_market": "HK",
        "form_type": "20-F", "fiscal_period": "FY",
    })
    listing = _identity()
    listing["resolved"].update({
        "canonical_name": "Alibaba Group Holding Limited", "ticker": "BABA",
        "security_id": "BABA", "matched_value": "BABA",
        "issuer_link_id": "issuer-link-v1:" + "a" * 64,
    })
    source = json.loads(json.dumps(listing))
    source["resolved"].update({
        "market": "HK", "exchange": "HKEX", "ticker": "09988",
        "security_id": "09988", "source_name": "HKEX",
        "source_url": "https://www.hkexnews.hk/",
        "source_record_id": "urn:company-wiki:security:HK:09988",
        "matched_value": "BABA",
    })
    candidate = _candidate()
    candidate.update({
        "title": "Alibaba FY2025 annual report", "market": "HK",
        "security_id": "09988", "form_type": "20-F", "fiscal_period": "FY",
        "issuer_link_id": "issuer-link-v1:" + "a" * 64,
    })
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([
            _completed(listing), _completed(source), _completed(_query(candidate=candidate)),
        ]),
    ) as run:
        handle = fetch_filing.resolve_filing(
            request=request, company_wiki_root=_wiki(tmp_path), source_ref_v2=True,
        )

    assert len(run.call_args_list) == 3
    identity_commands = [call.args[0] for call in run.call_args_list[:2]]
    assert identity_commands[0][identity_commands[0].index("--market") + 1] == "US"
    assert identity_commands[1][identity_commands[1].index("--market") + 1] == "HK"
    source_request = json.loads(run.call_args_list[2].kwargs["input_bytes"])
    assert source_request["market"] == "HK"
    assert source_request["security_id"] == "09988"
    assert source_request["form_type"] == "20-F"
    assert source_request["fiscal_period"] == "FY"
    assert handle["company_identity"]["market"] == "US"
    assert handle["source_identity"]["market"] == "HK"
    assert handle["source_identity"]["security_id"] == "09988"


def test_initial_identity_must_match_selected_listing_market_before_source_lookup(
    tmp_path: Path,
) -> None:
    request = _v2_request(intent="reuse_only")
    request.pop("acquisition_limits")
    request.update({"company_query": "BABA", "source_market": "HK"})
    wrong_market_identity = _identity()
    wrong_market_identity["resolved"].update({
        "canonical_name": "Alibaba Group Holding Limited",
        "market": "HK", "exchange": "HKEX", "ticker": "09988",
        "security_id": "09988",
    })

    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([_completed(wrong_market_identity)]),
    ) as run:
        with pytest.raises(FilingFetchError) as error:
            fetch_filing.resolve_filing(
                request=request, company_wiki_root=_wiki(tmp_path), source_ref_v2=True,
            )

    assert error.value.stage == "identify"
    assert "selected listing market" in str(error.value)
    assert len(run.call_args_list) == 1
    assert "identify" in run.call_args_list[0].args[0]


def test_cross_market_source_identity_must_link_to_selected_issuer(tmp_path: Path) -> None:
    request = _v2_request(intent="reuse_only")
    request.pop("acquisition_limits")
    request.update({"company_query": "SHARED", "source_market": "HK"})
    listing = _identity()
    listing["resolved"].update({
        "canonical_name": "Issuer One Holdings", "ticker": "ONE",
        "security_id": "ONE", "matched_value": "SHARED",
        "issuer_link_id": "issuer-link-v1:" + "a" * 64,
    })
    source = json.loads(json.dumps(listing))
    source["resolved"].update({
        "canonical_name": "Issuer Two Holdings", "market": "HK",
        "exchange": "HKEX", "ticker": "00002", "security_id": "00002",
        "source_name": "HKEX", "source_url": "https://www.hkexnews.hk/",
        "source_record_id": "urn:company-wiki:security:HK:00002",
        "issuer_link_id": "issuer-link-v1:" + "b" * 64,
    })

    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([_completed(listing), _completed(source)]),
    ) as run:
        with pytest.raises(FilingFetchError) as error:
            fetch_filing.resolve_filing(
                request=request, company_wiki_root=_wiki(tmp_path), source_ref_v2=True,
            )

    assert error.value.stage == "source_identify"
    assert len(run.call_args_list) == 2


@pytest.mark.parametrize("missing_side", ["listing", "source", "both"])
def test_cross_market_identity_without_shared_link_is_not_proven(
    tmp_path: Path, missing_side: str,
) -> None:
    request = _v2_request(intent="reuse_only")
    request.pop("acquisition_limits")
    request.update({"company_query": "SHARED", "source_market": "HK"})
    listing = _identity()
    listing["resolved"].update({
        "canonical_name": "Shared Company Limited", "ticker": "SHR",
        "security_id": "SHR", "matched_value": "SHARED",
        "issuer_link_id": "issuer-link-v1:" + "a" * 64,
    })
    source = json.loads(json.dumps(listing))
    source["resolved"].update({
        "market": "HK", "exchange": "HKEX", "ticker": "00001",
        "security_id": "00001", "source_name": "HKEX",
        "source_url": "https://www.hkexnews.hk/",
        "source_record_id": "urn:company-wiki:security:HK:00001",
        "matched_value": "SHARED",
    })
    if missing_side in {"listing", "both"}:
        listing["resolved"].pop("issuer_link_id")
    if missing_side in {"source", "both"}:
        source["resolved"].pop("issuer_link_id")

    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([_completed(listing), _completed(source)]),
    ) as run:
        with pytest.raises(FilingFetchError) as error:
            fetch_filing.resolve_filing(
                request=request, company_wiki_root=_wiki(tmp_path), source_ref_v2=True,
            )

    assert error.value.stage == "source_identify"
    assert len(run.call_args_list) == 2


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [("form_type", "10-Q"), ("fiscal_period", "Q1"), ("market", None),
     ("security_id", "WRONG")],
)
def test_candidate_must_match_requested_source_market_and_period(
    tmp_path: Path, field: str, bad_value: object,
) -> None:
    candidate = _candidate()
    candidate[field] = bad_value
    request = {**_request(), "form_type": "10-K", "fiscal_period": "FY"}
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([
            _completed(_identity()), _completed(_query(candidate=candidate)),
        ]),
    ):
        with pytest.raises(FilingFetchError):
            fetch_filing.resolve_filing(
                request=request, company_wiki_root=_wiki(tmp_path), source_ref_v2=True,
            )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [("form_type", 10), ("form_type", "  "), ("fiscal_period", ["FY"]),
     ("fiscal_period", " ")],
)
def test_explicit_form_and_period_constraints_require_trimmed_text(
    tmp_path: Path, field: str, bad_value: object,
) -> None:
    request = _v2_request()
    request[field] = bad_value
    with patch("fetch_filing._run_bounded_json") as run:
        with pytest.raises(FilingFetchError) as error:
            fetch_filing.resolve_filing(
                request=request, company_wiki_root=_wiki(tmp_path), source_ref_v2=True,
            )
    assert error.value.code == "request_error"
    run.assert_not_called()


@pytest.mark.parametrize(
    ("status", "code"),
    [("not_found", "not_found"), ("ambiguous", "ambiguous"),
     ("blocked", "source_blocked"), ("unavailable", "upstream_error")],
)
def test_query_status_fails_closed_without_legacy_resolve(
    tmp_path: Path, status: str, code: str,
) -> None:
    payload = _query(status)
    payload["candidates"] = []
    payload["matches"] = []
    rc = 2 if status in {"blocked", "unavailable"} else 0
    if rc:
        # An error receipt belongs to this exact normalized public request,
        # rather than the historical fixture's unrelated placeholder digest.
        from ff_source_failure import source_request_id
        payload["request_id"] = source_request_id({
            "entity": "Advanced Micro Devices, Inc.", "market": "US", "security_id": "AMD",
            "document_kind": "annual_report", "fiscal_year": 2025, "as_of_date": "2026-07-18",
        })
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([_completed(_identity()), _completed(payload, rc)]),
    ) as run:
        with pytest.raises(FilingFetchError) as error:
            fetch_filing.resolve_filing(
                request=_request(), company_wiki_root=_wiki(tmp_path),
                source_ref_v2=True,
            )
    assert error.value.code == code
    assert len(run.call_args_list) == 2
    assert "source_query_cli" in " ".join(run.call_args_list[1].args[0])


@pytest.mark.parametrize(
    ("change", "code"),
    [("sha_drift", "upstream_error"), ("path_leak", "upstream_error")],
)
def test_query_candidate_requires_identity_and_pathless_shape(
    tmp_path: Path, change: str, code: str,
) -> None:
    candidate = _candidate()
    if change == "sha_drift":
        candidate["snapshot_sha256"] = "0" * 64
    else:
        candidate["canonical_path"] = str(tmp_path / "private" / "report.pdf")
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([_completed(_identity()), _completed(_query(candidate=candidate))]),
    ) as run:
        with pytest.raises(FilingFetchError) as error:
            fetch_filing.resolve_filing(
                request=_request(), company_wiki_root=_wiki(tmp_path),
                source_ref_v2=True,
            )
    assert len(run.call_args_list) == 2
    assert error.value.code == code


@pytest.mark.parametrize("review_status", ["not_reviewed", "detected_and_ignored"])
def test_review_state_is_diagnostic_for_unverified_v2_candidate(
    tmp_path: Path, review_status: str,
) -> None:
    candidate = _candidate()
    candidate["prompt_injection_status"] = review_status
    candidate["capture_ready"] = False
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([_completed(_identity()), _completed(_query(candidate=candidate))]),
    ) as run:
        handle = fetch_filing.resolve_filing(
            request=_request(), company_wiki_root=_wiki(tmp_path),
            source_ref_v2=True,
        )
    assert len(run.call_args_list) == 2
    assert handle["source_ref"] == _ref()
    assert handle["prompt_injection_status"] == review_status
    assert handle["byte_verified"] is False
    assert handle["capture_ready"] is False


@pytest.mark.parametrize("include_capture_ready", [True, False], ids=["false", "missing"])
def test_missing_capture_descriptors_and_source_url_do_not_block_v2_candidate(
    tmp_path: Path, include_capture_ready: bool,
) -> None:
    candidate = _candidate()
    if include_capture_ready:
        candidate["capture_ready"] = False
    else:
        candidate.pop("capture_ready")
    candidate["missing_capture_fields"] = [
        "https_url", "retrieved_at", "provider", "collector_name", "collector_version",
    ]
    for field in (
        "https_url", "retrieved_at", "provider", "provider_document_id",
        "collector_name", "collector_version",
    ):
        candidate.pop(field)
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([_completed(_identity()), _completed(_query(candidate=candidate))]),
    ):
        handle = fetch_filing.resolve_filing(
            request=_request(), company_wiki_root=_wiki(tmp_path),
            source_ref_v2=True,
        )
    assert handle["source_ref"] == _ref()
    assert handle["snapshot_sha256"] == _ref()["content_sha256"]
    assert handle["published_date"] == "2026-02-20"
    assert handle.get("capture_ready") is not True
    assert handle["byte_verified"] is False


def test_candidate_without_explicit_title_does_not_guess_from_filename(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    candidate["title"] = None
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([_completed(_identity()), _completed(_query(candidate=candidate))]),
    ):
        handle = fetch_filing.resolve_filing(
            request=_request(), company_wiki_root=_wiki(tmp_path),
            source_ref_v2=True,
        )
    assert handle["title"] is None



def _operation_v2(
    *,
    operation: str = "ensure",
    status: str = "completed",
    outcome: str = "reused_after_discovery",
    download_events: int = 0,
    gap_plan: dict | None = None,
    policy_hash: str | None = "b" * 64,
) -> dict:
    return {
        "operation_schema_version": "1.0",
        "operation": operation,
        "status": status,
        "request_id": "urn:req:operation-v2",
        "outcome": outcome,
        "download_events": download_events,
        "policy_hash": policy_hash,
        "source_ref": _ref() if status == "completed" else None,
        "candidate": _candidate() if status == "completed" else None,
        "gap_plan": gap_plan,
    }


def _latest_request() -> dict:
    return {
        "schema_version": "1.2",
        "company_query": "AMD",
        "market": "US",
        "document_kind": "annual_report",
        "mode": "latest_as_of",
        "as_of_date": "2026-09-27",
    }


def test_latest_as_of_uses_pathless_provider_ensure_without_download(tmp_path: Path) -> None:
    stats = {"calls": 0, "downloads": 0}
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([_completed(_identity()), _completed(_operation_v2())]),
    ) as run, patch.object(
        Path, "read_bytes", side_effect=AssertionError("FF opened source bytes")
    ):
        handle = fetch_filing.resolve_filing(
            request=_latest_request(), company_wiki_root=_wiki(tmp_path),
            source_ref_v2=True, stats=stats, pause_worker=False,
        )
    commands = [call.args[0] for call in run.call_args_list]
    assert len(commands) == stats["calls"] == 2
    assert "ensure" in commands[1]
    assert "--source-ref-v2" in commands[1]
    assert "--mode" in commands[1]
    assert commands[1][commands[1].index("--mode") + 1] == "latest_as_of"
    assert "--allow-download" not in commands[1]
    assert "source_query_cli" not in " ".join(commands[1])
    assert stats["downloads"] == handle["download_events"] == 0
    assert handle["source_ref"] == _ref()
    assert handle["operation_receipt"]["outcome"] == "reused_after_discovery"
    assert "canonical_path" not in str(handle)


def test_latest_as_of_pathless_provider_gap_stays_structured_without_download(
    tmp_path: Path,
) -> None:
    gap = {
        "schema_version": "1.0",
        "request_id": "urn:req:operation-v2",
        "as_of_date": "2026-09-27",
        "document_kind": "annual_report",
        "entity": "Advanced Micro Devices, Inc.",
        "market": "US",
        "missing": [{"provider": "sec", "provider_document_id": "acc-2025"}],
        "newer_revision": [],
        "future": [],
        "gap_hash": "c" * 64,
    }
    operation = _operation_v2(status="gap", outcome="gap", gap_plan=gap)
    operation["source_ref"] = None
    operation["candidate"] = None
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([_completed(_identity()), _completed(operation)]),
    ) as run:
        result = fetch_filing.resolve_filing(
            request=_latest_request(), company_wiki_root=_wiki(tmp_path),
            source_ref_v2=True, pause_worker=False,
        )
    ensure_command = run.call_args_list[1].args[0]
    assert "ensure" in ensure_command
    assert "--source-ref-v2" in ensure_command
    assert "--allow-download" not in ensure_command
    assert result["status"] == "gap"
    assert result["gap_plan"]["gap_hash"] == "c" * 64
    assert result["resolution"]["reason"] == "metadata_only_gap_plan"
    assert "canonical_path" not in str(result)


def test_v2_explicit_bounded_intent_reaches_cwp_ensure(
    tmp_path: Path,
) -> None:
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([_completed(_identity()), _completed(_operation_v2())]),
    ) as run:
        result = fetch_filing.resolve_filing(
            request=_v2_request(), company_wiki_root=_wiki(tmp_path),
            allow_download=True, source_ref_v2=True, pause_worker=False,
        )
    command = run.call_args_list[1].args[0]
    assert "ensure" in command
    assert "--source-ref-v2" in command
    assert "--allow-download" in command
    assert "--acquisition-config" in command
    assert result["source_ref"] == _ref()
    assert result["download_events"] == 0
    assert "canonical_path" not in json.dumps(result)


def test_v2_request_rejects_legacy_per_document_authorization(tmp_path: Path) -> None:
    request = _v2_request()
    request["authorization"] = {
        "provider": "sec", "allowed_accessions": ["acc-2025"],
        "max_items": 1, "max_bytes": 5_000_000,
        "expires_at": "2099-01-01T00:00:00Z",
    }
    with patch("fetch_filing._run_bounded_json") as run:
        with pytest.raises(FilingFetchError) as error:
            fetch_filing.resolve_filing(
                request=request, company_wiki_root=_wiki(tmp_path),
                allow_download=True, source_ref_v2=True, pause_worker=False,
            )
    assert error.value.code == "request_error"
    run.assert_not_called()


@pytest.mark.parametrize(
    ("change", "code"),
    [("version", "upstream_error"), ("path_leak", "upstream_error"),
     ("ref_mismatch", "upstream_error")],
)
def test_operation_v2_rejects_drift_and_path_leaks(
    tmp_path: Path, change: str, code: str,
) -> None:
    payload = _operation_v2()
    if change == "version":
        payload["operation_schema_version"] = "2.0"
    elif change == "path_leak":
        payload["candidate"]["nested"] = {"canonical_path": "private/x.pdf"}
    else:
        payload["candidate"]["source_ref"]["content_sha256"] = "0" * 64
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect([_completed(_identity()), _completed(payload)]),
    ):
        with pytest.raises(FilingFetchError) as error:
            fetch_filing.resolve_filing(
                request=_request(), company_wiki_root=_wiki(tmp_path), source_ref_v2=True,
            )
    assert error.value.code == code
