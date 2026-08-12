"""FC-1204-a: close branch-coverage gaps in the contract + guard paths.

Baseline (findings 61): fetch_filing.py 87% / filing_contracts.py 91% /
TOTAL 88% against the pre-existing fail_under=90.  These tests exercise the
missing defensive branches: authorization block validation, envelope
taxonomy edges, handle containment edges, and the client guard rails.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

FILING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FILING_ROOT / "scripts"))

from fetch_filing import _command_arguments, resolve_filing  # noqa: E402
from filing_contracts import (  # noqa: E402
    FilingFetchError,
    validate_handle,
    validate_request,
    validate_resolution_envelope,
)


def _request(**overrides) -> dict:
    request = {
        "schema_version": "1.2",
        "company_query": "Acme",
        "document_kind": "annual_report",
        "as_of_date": "2026-12-31",
        "fiscal_year": 2025,
    }
    request.update(overrides)
    return request


def _authorization(**overrides) -> dict:
    auth = {
        "provider": "cninfo",
        "allowed_accessions": ["acc-1"],
        "max_items": 3,
        "max_bytes": 10_000_000,
        "expires_at": "2026-12-31",
    }
    auth.update(overrides)
    return auth


# --- authorization block (filing_contracts 146-167) -------------------------


def test_authorization_must_be_an_object():
    with pytest.raises(FilingFetchError, match="authorization must be an object"):
        validate_request(_request(authorization="nope"))


def test_authorization_missing_fields_rejected():
    with pytest.raises(FilingFetchError, match="authorization missing field"):
        validate_request(_request(authorization={"provider": "cninfo"}))


def test_authorization_accessions_must_be_nonempty_string_list():
    with pytest.raises(FilingFetchError, match="allowed_accessions"):
        validate_request(_request(authorization=_authorization(allowed_accessions=[])))


def test_authorization_caps_must_be_positive_integers():
    for bad in (True, 0, -1, "3"):
        with pytest.raises(FilingFetchError, match="max_items"):
            validate_request(_request(authorization=_authorization(max_items=bad)))
    with pytest.raises(FilingFetchError, match="max_bytes"):
        validate_request(_request(authorization=_authorization(max_bytes=0)))


def test_valid_authorization_block_passes():
    validate_request(_request(authorization=_authorization()))  # must not raise


# --- envelope taxonomy edges (filing_contracts 232-301) ----------------------


def _envelope(**overrides) -> dict:
    envelope = {
        "envelope_schema_version": "1.0",
        "outcome": "reused_existing",
        "download_events": 0,
        "policy_hash": "b" * 64,
        "activation_epoch": "epoch-1",
        "bundle_status": "unavailable",
        "prompt_injection_status": "not_detected",
        "parser_calls": 0,
        "llm_calls": 0,
    }
    envelope.update(overrides)
    return envelope


def test_envelope_must_be_an_object():
    with pytest.raises(FilingFetchError, match="resolution_envelope must be an object"):
        validate_resolution_envelope("nope")  # type: ignore[arg-type]


def test_envelope_schema_version_mismatch_rejected():
    with pytest.raises(FilingFetchError, match="schema_version"):
        validate_resolution_envelope(_envelope(envelope_schema_version="9.9"))


def test_envelope_outcome_outside_taxonomy_rejected():
    with pytest.raises(FilingFetchError, match="outside the taxonomy"):
        validate_resolution_envelope(_envelope(outcome="maybe"))


def test_envelope_policy_hash_malformed_rejected():
    with pytest.raises(FilingFetchError, match="policy_hash"):
        validate_resolution_envelope(_envelope(policy_hash="ABCD"))


def test_envelope_activation_epoch_must_be_text_or_null():
    with pytest.raises(FilingFetchError, match="activation_epoch"):
        validate_resolution_envelope(_envelope(activation_epoch=7))


def test_envelope_bundle_status_outside_enum_rejected():
    with pytest.raises(FilingFetchError, match="bundle_status"):
        validate_resolution_envelope(_envelope(bundle_status="sometimes"))


def test_envelope_available_requires_matching_bundle_hash():
    with pytest.raises(FilingFetchError, match="bundle_hash"):
        validate_resolution_envelope(
            _envelope(bundle_status="available", bundle_hash="x" * 64)
        )


def test_envelope_available_bundle_dict_must_match_hash():
    sha = "c" * 64
    with pytest.raises(FilingFetchError, match="bundle_hash"):
        validate_resolution_envelope(
            _envelope(
                bundle_status="available",
                bundle_hash=sha,
                bundle={"bundle_hash": "d" * 64},
            )
        )


# --- handle containment edges (filing_contracts 381-412) ---------------------


def _handle(**overrides) -> dict:
    handle = {
        "request_id": "req-1",
        "document_id": "urn:doc:1",
        "source_id": "urn:src:1",
        "title": "Annual",
        "published_date": "2026-03-20",
        "https_url": "https://example.com/f.pdf",
        "canonical_path": "companies/Acme/raw/f.pdf",
        "snapshot_sha256": "e" * 64,
        "retrieved_at": "2026-07-01T00:00:00Z",
        "provider": "cninfo",
        "provider_document_id": "p-1",
        "collector_name": "c",
        "collector_version": "1.0",
        "byte_size": 10,
        "mime_type": "application/pdf",
        "capture_ready": True,
    }
    handle.update(overrides)
    return handle


def test_handle_invalid_canonical_path_rejected(tmp_path: Path):
    with pytest.raises(FilingFetchError, match="canonical_path"):
        validate_handle(
            _handle(canonical_path="\x00bad"),
            _request(),
            wiki_root=tmp_path,
        )


def test_handle_policy_snapshot_without_expected_hash_rejected(tmp_path: Path):
    with pytest.raises(FilingFetchError, match="expected_policy_hash"):
        validate_handle(
            _handle(),
            _request(),
            wiki_root=tmp_path,
            policy_snapshot={"roots": []},
            expected_policy_hash=None,
        )


def test_handle_policy_snapshot_hash_mismatch_rejected(tmp_path: Path):
    with pytest.raises(FilingFetchError, match="hash mismatch"):
        validate_handle(
            _handle(),
            _request(),
            wiki_root=tmp_path,
            policy_snapshot={"schema_version": "2.0", "roots": []},
            expected_policy_hash="f" * 64,
        )


# --- client guard rails (fetch_filing 53-178, 595-605, 657) ------------------


def test_fiscal_year_bool_rejected_in_command_arguments():
    request = {
        "entity": "Acme Inc",
        "document_kind": "annual_report",
        "as_of_date": "2026-12-31",
        "fiscal_year": True,
    }
    with pytest.raises(FilingFetchError, match="fiscal_year must be an integer"):
        _command_arguments(request)


def test_resolve_filing_rejects_combined_root_and_config(tmp_path: Path):
    with pytest.raises(ValueError, match="cannot be combined"):
        resolve_filing(
            request=_request(),
            company_wiki_root=tmp_path,
            config_path=tmp_path / "cfg.json",
        )


def test_resolve_filing_rejects_non_dict_request():
    with pytest.raises(TypeError, match="request must be a dict"):
        resolve_filing(request="nope")  # type: ignore[arg-type]


def test_resolve_filing_rejects_non_bool_allow_download():
    with pytest.raises(TypeError, match="allow_download must be boolean"):
        resolve_filing(request=_request(), allow_download=1)  # type: ignore[arg-type]


def test_resolve_filing_rejects_invalid_timeout():
    for bad in (0, -5, float("inf")):
        with pytest.raises(ValueError, match="timeout_seconds"):
            resolve_filing(request=_request(), timeout_seconds=bad)
