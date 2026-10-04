"""The opt-in filing result is a pathless candidate for one later source read."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import fetch_filing
from filing_contracts import FilingFetchError


BODY = b"%PDF-1.4 candidate only"
SHA = hashlib.sha256(BODY).hexdigest()
DOCUMENT = "urn:company-wiki:document:sha256:" + "d" * 64
SOURCE = "urn:company-wiki:source:sha256:" + SHA


def _request() -> dict:
    return {
        "schema_version": "1.1",
        "company_query": "ACME",
        "market": "US",
        "document_kind": "annual_report",
        "fiscal_year": 2025,
        "as_of_date": "2026-09-27",
    }


def _resolution(root: Path) -> dict:
    return {
        "schema_version": "1.0",
        "status": "reused_exact",
        "reason": "exact_local_match",
        "request_id": "urn:company-wiki:source-request:sha256:" + "1" * 64,
        "source_read_policy_sha256": "e" * 64,
        "matches": [
            {
                "document_id": DOCUMENT,
                "source_id": SOURCE,
                "title": "ACME FY2025 annual",
                "document_kind": "annual_report",
                "fiscal_year": 2025,
                "period_end": "2025-12-31",
                "published_date": "2026-02-20",
                "https_url": "https://sec.gov/x/2025",
                "canonical_location_id": "urn:company-wiki:location:sha256:" + "2" * 64,
                "canonical_path": str(root / "missing-location.pdf"),
                "source_bundle": {"path": str(root / "private" / "bundle.json")},
                "snapshot_sha256": SHA,
                "retrieved_at": "2026-02-21T00:00:00Z",
                "provider": "sec",
                "provider_document_id": "doc-1",
                "collector_name": "sec_edgar",
                "collector_version": "1.0",
                "byte_size": len(BODY),
                "mime_type": "application/pdf",
                "capture_ready": True,
            }
        ],
        "policy_export": {
            "roots": [{"path_ref": str(root / "old-root")}],
            "policy_hash": "a" * 64,
        },
        "resolution_envelope": {
            "envelope_schema_version": "1.0",
            "outcome": "reused_existing",
            "download_events": 0,
            "policy_hash": "b" * 64,
            "bundle_status": "unavailable",
            "bundle": {"path": str(root / "private" / "bundle.json")},
            "prompt_injection_status": "not_reviewed",
        },
    }


def _assert_no_physical_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert not any(word in key for word in ("path", "location", "root"))
            _assert_no_physical_keys(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_physical_keys(item)


def test_v2_candidate_preserves_source_metadata_without_reading_bytes(
    tmp_path, monkeypatch
):
    resolution = _resolution(tmp_path)
    del resolution["policy_export"]
    del resolution["source_read_policy_sha256"]
    read_calls = []
    monkeypatch.setattr(
        fetch_filing,
        "read_source_version",
        lambda **kwargs: read_calls.append(kwargs),
        raising=False,
    )
    handle = fetch_filing._handle_from_resolution(
        resolution, _request(), tmp_path, source_ref_v2=True
    )
    assert read_calls == []
    assert handle["source_ref"] == {
        "schema_version": "2.0",
        "document_id": DOCUMENT,
        "source_id": SOURCE,
        "content_sha256": SHA,
        "byte_size": len(BODY),
        "mime_type": "application/pdf",
    }
    assert handle["title"] == "ACME FY2025 annual"
    assert handle["document_kind"] == "annual_report"
    assert handle["fiscal_year"] == 2025
    assert handle["period_end"] == "2025-12-31"
    assert handle["provider"] == "sec"
    assert handle["provider_document_id"] == "doc-1"
    assert handle["capture_ready"] is True
    assert handle["download_events"] == 0
    assert handle["prompt_injection_status"] == "not_reviewed"
    assert "source_read_receipt" not in handle
    assert "resolution_envelope" not in handle
    _assert_no_physical_keys(handle)


def test_v2_reuse_keeps_partial_capture_as_diagnostic_only(tmp_path):
    resolution = _resolution(tmp_path)
    raw = resolution["matches"][0]
    raw["capture_ready"] = False
    raw["missing_capture_fields"] = ["https_url", "collector_name", "capture_trace"]
    for field in (
        "https_url", "retrieved_at", "provider", "provider_document_id",
        "collector_name", "collector_version",
    ):
        raw.pop(field)
    handle = fetch_filing._handle_from_resolution(
        resolution, _request(), tmp_path, source_ref_v2=True
    )
    assert handle["source_ref"]["content_sha256"] == SHA
    assert handle["published_date"] == "2026-02-20"
    assert handle["capture_ready"] is False
    assert handle.get("byte_verified") is not True


def test_v2_candidate_rejects_unusable_identity_without_opening_bytes(
    tmp_path, monkeypatch
):
    resolution = _resolution(tmp_path)
    resolution["matches"][0]["snapshot_sha256"] = "INVALID"
    monkeypatch.setattr(
        fetch_filing,
        "read_source_version",
        lambda **kwargs: pytest.fail("v2 candidate opened source bytes"),
        raising=False,
    )
    with pytest.raises(FilingFetchError, match="snapshot_sha256"):
        fetch_filing._handle_from_resolution(
            resolution, _request(), tmp_path, source_ref_v2=True
        )


def test_v2_candidate_preserves_committed_download_event(tmp_path):
    resolution = _resolution(tmp_path)
    resolution["resolution_envelope"]["outcome"] = "downloaded_new"
    resolution["resolution_envelope"]["download_events"] = 1
    candidate = fetch_filing._handle_from_resolution(
        resolution, _request(), tmp_path, source_ref_v2=True
    )
    stats = {"calls": 2, "downloads": 0}
    fetch_filing._record_download_events(stats, candidate)
    assert candidate["download_events"] == stats["downloads"] == 1
    assert candidate["resolution_outcome"] == "downloaded_new"
