"""WU-4.1: versioned FilingRequest with explicit mode (exact / latest_as_of).

RED phase: ``mode`` is not part of the 1.1 schema, so a latest_as_of
request is rejected today (unknown field) — the semantic "latest" cannot
be expressed. After the fix:

- schema_version "1.2" with ``mode``:
    "exact"        → fiscal_year REQUIRED (no null-year guessing);
    "latest_as_of" → fiscal_year FORBIDDEN (latest is defined by
                     as_of_date + document_kind + provider calendar).
- legacy 1.1 clients (no mode) keep working as exact semantics with a
  deprecation path: fiscal_year must be present.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


FILING_ROOT = Path(__file__).resolve().parents[1]


def _request(mode: str | None, fiscal_year: object = 2025) -> dict:
    req = {
        "schema_version": "1.2",
        "company_query": "AMD",
        "document_kind": "annual_report",
        "as_of_date": "2026-07-18",
    }
    if mode is not None:
        req["mode"] = mode
    if fiscal_year is not None:
        req["fiscal_year"] = fiscal_year
    return req


@pytest.fixture()
def contracts():
    sys.path.insert(0, str(FILING_ROOT / "scripts"))
    import filing_contracts

    return filing_contracts


def test_exact_mode_requires_fiscal_year(contracts) -> None:
    """mode=exact without fiscal_year must be rejected (null-year guessing
    was the old AMBIGUOUS trap)."""
    req = _request("exact", fiscal_year=None)
    with pytest.raises(contracts.FilingFetchError) as exc:
        contracts.validate_request(req)
    assert "fiscal_year" in str(exc.value)


def test_latest_as_of_mode_forbids_fiscal_year(contracts) -> None:
    """mode=latest_as_of with fiscal_year must be rejected — latest is
    derived from as_of_date + kind, never from an explicit year."""
    req = _request("latest_as_of", fiscal_year=2025)
    with pytest.raises(contracts.FilingFetchError) as exc:
        contracts.validate_request(req)
    assert "fiscal_year" in str(exc.value)


def test_latest_as_of_mode_requires_as_of_date(contracts) -> None:
    req = _request("latest_as_of", fiscal_year=None)
    del req["as_of_date"]
    with pytest.raises(contracts.FilingFetchError) as exc:
        contracts.validate_request(req)
    assert "as_of_date" in str(exc.value)


def test_exact_mode_valid(contracts) -> None:
    """mode=exact + fiscal_year is the modern exact request."""
    contracts.validate_request(_request("exact", fiscal_year=2025))


def test_latest_as_of_mode_valid(contracts) -> None:
    """mode=latest_as_of without fiscal_year is valid."""
    contracts.validate_request(_request("latest_as_of", fiscal_year=None))


def test_unknown_mode_rejected(contracts) -> None:
    req = _request("fuzzy", fiscal_year=None)
    with pytest.raises(contracts.FilingFetchError) as exc:
        contracts.validate_request(req)
    assert "mode" in str(exc.value)


def test_legacy_11_without_mode_keeps_legacy_behavior(contracts) -> None:
    """A legacy 1.1 request (no mode) keeps old behavior: fiscal_year may be
    absent (exact-any-year) — no behavior change for old clients, but new
    callers must use schema 1.2 + explicit mode."""
    req = _request(None, fiscal_year=None)
    req["schema_version"] = "1.1"
    contracts.validate_request(req)


def test_legacy_11_with_fiscal_year_still_valid(contracts) -> None:
    req = _request(None, fiscal_year=2025)
    req["schema_version"] = "1.1"
    contracts.validate_request(req)


def test_schema_12_without_mode_requires_fiscal_year(contracts) -> None:
    """A 1.2 request without mode must not silently guess latest: fiscal_year
    is required (mode defaults to exact semantics)."""
    req = _request(None, fiscal_year=None)
    with pytest.raises(contracts.FilingFetchError) as exc:
        contracts.validate_request(req)
    assert "fiscal_year" in str(exc.value)
