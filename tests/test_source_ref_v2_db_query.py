"""Opt-in FF source candidates must come from a DB-only CWP query."""

from __future__ import annotations

import hashlib
import json
import os
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
        "form_type": "10-K", "published_date": "2026-02-20",
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


def test_real_db_only_reuse_accepts_configured_root_with_legacy_labels_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    cwp_root_text = os.environ.get("CWP_V2_CODE_ROOT")
    if not cwp_root_text:
        pytest.skip("set CWP_V2_CODE_ROOT to the isolated CWP checkout")
    cwp_root = Path(cwp_root_text).resolve(strict=True)
    cwp_src = cwp_root / "src"
    monkeypatch.syspath_prepend(str(cwp_src))
    monkeypatch.setenv(
        "PYTHONPATH", str(cwp_src) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    )
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")

    from e2e_support import isolated_wiki
    from company_wiki.source_catalog import SourceCatalog
    from company_wiki.source_catalog.config import load_catalog_config
    from company_wiki.source_catalog.policy_2x import export_policy_2x
    from company_wiki.source_catalog.prompt_injection import record_prompt_injection_review

    monkeypatch.setattr(isolated_wiki, "PRODUCTION_WIKI", cwp_root)
    wiki = isolated_wiki.IsolatedWiki(tmp_path / "wiki")
    text = wiki.config_path.read_text(encoding="utf-8")
    assert "    priority: 10\n" in text
    wiki.config_path.write_text(
        text.replace(
            "    priority: 10\n",
            "    priority: 10\n    reusable_for_filing: false\n",
        ) + "reusable_root_kinds: [directory]\n", encoding="utf-8",
    )
    source = wiki.seed_market("US")
    body = source.read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    wiki.scan()
    catalog = SourceCatalog(load_catalog_config(wiki.config_path))
    try:
        row = catalog.store.fetchone(
            "SELECT d.document_id FROM documents d JOIN sources s "
            "ON s.source_id=d.primary_source_id WHERE s.content_sha256=?",
            (digest,),
        )
        assert row is not None
        policy_hash, _ = export_policy_2x(catalog.config)
        with catalog.store.transaction() as connection:
            record_prompt_injection_review(
                connection, str(row["document_id"]), status="not_detected",
                reviewer="ff-v2-e2e", evidence_sha256=digest,
                source_sha256=digest, policy_hash=policy_hash,
                evidence_payload=body, now="2026-09-27T00:00:00Z",
            )
    finally:
        catalog.close()
    rc, stdout, stderr = wiki.run_fetch({
        "schema_version": "1.1", "company_query": "Apple Inc.",
        "market": "US", "document_kind": "annual_report",
        "fiscal_year": 2025, "as_of_date": "2026-09-27",
    }, extra_args=["--source-ref-v2"])
    assert rc == 0, stderr + stdout
    response = json.loads(stdout)
    assert response["status"] == "capture_ready"
    assert response["handle"]["source_ref"]["content_sha256"] == digest
    assert response["handle"]["download_events"] == response["downloads"] == 0
    assert response["handle"]["prompt_injection_status"] == "not_detected"
    assert wiki.journal_outcomes() == []

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
