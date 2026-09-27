"""Transition contract: legacy resolution metadata, v2 verified source bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import fetch_filing
from filing_contracts import FilingFetchError


SHA = hashlib.sha256(b"%PDF-1.4 isolated raw bytes").hexdigest()
DOCUMENT = "urn:company-wiki:document:sha256:" + "d" * 64
SOURCE = "urn:company-wiki:source:sha256:" + SHA


def _resolution(root: Path) -> dict:
    policy = {
        "schema_version": "2.0",
        "reusable_root_kinds": ["directory"],
        "roots": [
            {
                "root_id": "lake",
                "path_ref": str(root / "lake"),
                "reusable_for_filing": True,
            }
        ],
    }
    policy_hash = hashlib.sha256(
        json.dumps(policy, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    policy["policy_hash"] = policy_hash
    return {
        "schema_version": "1.0",
        "status": "reused_exact",
        "reason": "exact_local_match",
        "request_id": "urn:company-wiki:source-request:sha256:" + "1" * 64,
        "matches": [
            {
                "document_id": DOCUMENT,
                "source_id": SOURCE,
                "title": "Acme FY2025",
                "document_kind": "annual_report",
                "published_date": "2026-02-20",
                "https_url": "https://sec.gov/x/2025",
                "canonical_location_id": "urn:company-wiki:location:sha256:" + "2" * 64,
                "canonical_path": str(root / "old-location-no-longer-present.pdf"),
                "snapshot_sha256": SHA,
                "retrieved_at": "2026-02-21T00:00:00Z",
                "provider": "sec",
                "provider_document_id": "doc-1",
                "collector_name": "sec_edgar",
                "collector_version": "1.0",
                "byte_size": len(b"%PDF-1.4 isolated raw bytes"),
                "mime_type": "application/pdf",
                "capture_ready": True,
            }
        ],
        "policy_export": policy,
        "resolution_envelope": {
            "envelope_schema_version": "1.0",
            "outcome": "reused_existing",
            "download_events": 0,
            "policy_hash": policy_hash,
            "bundle_status": "unavailable",
        },
    }


def _request() -> dict:
    return {
        "schema_version": "1.1",
        "company_query": "ACME",
        "market": "US",
        "document_kind": "annual_report",
        "fiscal_year": 2025,
        "as_of_date": "2026-09-27",
    }


def test_legacy_resolution_uses_v2_reader_without_opening_legacy_path(tmp_path, monkeypatch):
    resolution = _resolution(tmp_path)
    calls = []

    def fake_read(**kwargs):
        calls.append(kwargs)
        return {
            "schema_version": "2.0",
            "status": "ok",
            "document_id": DOCUMENT,
            "source_id": SOURCE,
            "content_sha256": SHA,
            "byte_size": len(b"%PDF-1.4 isolated raw bytes"),
            "policy_sha256": resolution["policy_export"]["policy_hash"],
            "read_at": "2026-09-27T00:00:00+00:00",
        }

    monkeypatch.setattr(fetch_filing, "read_source_version", fake_read, raising=False)
    handle = fetch_filing._handle_from_resolution(
        resolution, _request(), tmp_path, verify_source_version=True
    )
    assert len(calls) == 1
    assert calls[0]["document_id"] == DOCUMENT
    assert calls[0]["source_id"] == SOURCE
    assert calls[0]["content_sha256"] == SHA
    assert calls[0]["policy_sha256"] == resolution["policy_export"]["policy_hash"]
    assert handle["source_ref"] == {
        "schema_version": "2.0",
        "document_id": DOCUMENT,
        "source_id": SOURCE,
        "content_sha256": SHA,
        "byte_size": len(b"%PDF-1.4 isolated raw bytes"),
        "mime_type": "application/pdf",
    }
    assert handle["source_read_receipt"]["policy_sha256"] == calls[0]["policy_sha256"]
    assert handle["canonical_path"] == str(tmp_path / "old-location-no-longer-present.pdf")


@pytest.mark.parametrize("missing", ["policy_export", "resolution_envelope"])
def test_v2_mode_requires_pinned_root_policy_and_envelope(tmp_path, monkeypatch, missing):
    resolution = _resolution(tmp_path)
    calls = []
    monkeypatch.setattr(
        fetch_filing, "read_source_version", lambda **kwargs: calls.append(kwargs),
        raising=False,
    )
    del resolution[missing]
    with pytest.raises(FilingFetchError, match="policy|envelope"):
        fetch_filing._handle_from_resolution(
            resolution, _request(), tmp_path, verify_source_version=True
        )
    assert not calls


def test_v2_mode_rejects_envelope_policy_drift_before_read(tmp_path, monkeypatch):
    resolution = _resolution(tmp_path)
    resolution["resolution_envelope"]["policy_hash"] = "f" * 64
    calls = []
    monkeypatch.setattr(
        fetch_filing, "read_source_version", lambda **kwargs: calls.append(kwargs)
    )
    with pytest.raises(FilingFetchError, match="policy_hash"):
        fetch_filing._handle_from_resolution(
            resolution, _request(), tmp_path, verify_source_version=True
        )
    assert not calls


def test_v2_reader_refusal_keeps_resolution_trace(tmp_path, monkeypatch):
    resolution = _resolution(tmp_path)

    def refuse(**kwargs):
        raise FilingFetchError("source reader refused", code="upstream_error")

    monkeypatch.setattr(fetch_filing, "read_source_version", refuse, raising=False)
    with pytest.raises(FilingFetchError) as error:
        fetch_filing._handle_from_resolution(
            resolution, _request(), tmp_path, verify_source_version=True
        )
    assert error.value.resolution_trace == {
        "request_id": resolution["request_id"],
        "status": "reused_exact",
        "reason": "exact_local_match",
    }
