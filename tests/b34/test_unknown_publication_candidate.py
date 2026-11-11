"""Controlled public-boundary regressions; never verify source bytes or availability."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import fetch_filing
from ff_source_candidate import validate_source_candidate
from filing_contracts import FilingFetchError, validate_handle, validate_handle_metadata
from support import bounded_side_effect
from test_bundle_compat import _base_handle
from test_source_ref_v2_db_query import (
    _candidate, _completed, _identity, _latest_request, _operation_v2, _query,
    _ref, _request, _wiki,
)


def candidate_with_unknown_date():
    return {**_candidate(), "published_date": None, "capture_ready": False}


@pytest.mark.parametrize("route", ["query", "ensure"])
def test_unknown_publication_reaches_later_verified_open_without_claiming_ready(tmp_path, route):
    candidate = candidate_with_unknown_date()
    if route == "query":
        request, payload = _request(), _query(candidate=candidate)
    else:
        request, payload = _latest_request(), _operation_v2()
        payload["candidate"] = candidate
    stats = {"calls": 0, "downloads": 0}
    with patch("fetch_filing._run_bounded_json", side_effect=bounded_side_effect([
        _completed(_identity()), _completed(payload),
    ])) as transport, patch.object(Path, "read_bytes", side_effect=AssertionError("opened bytes")):
        result = fetch_filing.resolve_filing(
            request=request, company_wiki_root=_wiki(tmp_path),
            source_ref_v2=True, stats=stats, pause_worker=False,
        )
    assert len(transport.call_args_list) == stats["calls"] == 2
    assert stats["downloads"] == 0
    assert result["source_ref"] == _ref()
    assert result["published_date"] is None
    assert result["retrieved_at"] == candidate["retrieved_at"]
    assert result["capture_ready"] is False
    assert result["byte_verified"] is False
    assert "source_read_receipt" not in result
    assert "availability" not in result


@pytest.mark.parametrize("value", ["", "null", "2026-02-30", "2030-01-01", "2026-02-20T00:00:00Z", 42, True])
def test_unknown_date_exception_does_not_admit_bad_or_future_dates(value):
    candidate = {**candidate_with_unknown_date(), "published_date": value}
    with pytest.raises(FilingFetchError):
        validate_source_candidate(candidate, _ref(), request_id="controlled-request",
                                  request=_request(), company_identity=_identity()["resolved"],
                                  context="query")


def test_missing_date_is_distinct_from_explicit_unknown():
    candidate = candidate_with_unknown_date()
    del candidate["published_date"]
    with pytest.raises(FilingFetchError, match="missing required"):
        validate_source_candidate(candidate, _ref(), request_id="controlled-request",
                                  request=_request(), company_identity=_identity()["resolved"],
                                  context="query")


def test_default_metadata_validation_still_requires_publication_date():
    handle = {**candidate_with_unknown_date(), "request_id": "controlled-request"}
    with pytest.raises(FilingFetchError, match="published_date"):
        validate_handle_metadata(handle, _request())


def test_legacy_verified_handle_still_requires_publication_date(tmp_path):
    handle = _base_handle(tmp_path, published_date=None)
    with pytest.raises(FilingFetchError, match="published_date"):
        validate_handle(handle, _request(), tmp_path)


@pytest.mark.parametrize(("field", "value"), [
    ("snapshot_sha256", "a" * 64), ("byte_size", 43), ("mime_type", "text/plain"),
    ("document_kind", "quarterly_report"), ("fiscal_year", 2024),
    ("security_id", "OTHER"), ("canonical_path", "/controlled/private/document.pdf"),
])
def test_unknown_date_does_not_weaken_ref_scope_or_path_guards(field, value):
    candidate = {**candidate_with_unknown_date(), field: value}
    with pytest.raises(FilingFetchError):
        validate_source_candidate(candidate, _ref(), request_id="controlled-request",
                                  request=_request(), company_identity=_identity()["resolved"],
                                  context="query")


@pytest.mark.parametrize(("field", "value"), [
    ("form_type", "10-Q"), ("fiscal_period", "Q1"),
    ("market", "HK"), ("issuer_link_id", "issuer-link-v1:" + "b" * 64),
])
def test_unknown_publication_preserves_current_period_and_issuer_bindings(field, value):
    link = "issuer-link-v1:" + "a" * 64
    identity = {**_identity()["resolved"], "issuer_link_id": link}
    request = {**_request(), "source_market": "US", "form_type": "10-K", "fiscal_period": "FY"}
    candidate = {**candidate_with_unknown_date(), "form_type": "10-K",
                 "fiscal_period": "FY", "issuer_link_id": link, field: value}
    with pytest.raises(FilingFetchError):
        validate_source_candidate(candidate, _ref(), request_id="controlled-request",
                                  request=request, company_identity=identity,
                                  source_identity=identity, context="query")
