"""FC-903 RED/acceptance tests: N/N-1 envelope bundle contract (consumer).

filing-fetch must accept BOTH envelope generations:

- N  (FC-902 company-wiki):  envelope carries bundle_status + bundle_hash +
  bundle (SourceBundle to_dict) when artifacts were reusable.
- N-1 (pre-FC-902 company-wiki): the envelope either lacks bundle_status
  entirely or carries bundle_status='unavailable' without bundle fields.

Rules:

- An envelope WITHOUT bundle_status is normalized to the EXPLICIT honest
  'unavailable' — never a faked empty-green 'available'.
- bundle_status='available' REQUIRES a SHA-256 bundle_hash AND a bundle dict
  whose bundle_hash matches (fail closed — fabricated evidence never passes).
- Artifact validity is NOT re-decided here: the bundle's valid/invalid
  handles are forwarded verbatim (shape contract only).

RED phase: an N-1 envelope without bundle_status is rejected
(upstream_error) and a malformed 'available' bundle passes unchecked.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FILING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FILING_ROOT / "scripts"))

from filing_contracts import (  # noqa: E402
    FilingFetchError,
    validate_resolution_envelope,
)

_SHA = "a" * 64


def _base_envelope(**overrides) -> dict:
    envelope = {
        "envelope_schema_version": "1.0",
        "outcome": "reused_existing",
        "download_events": 0,
        "policy_hash": "b" * 64,
        "activation_epoch": "epoch-7",
        "bundle_status": "unavailable",
    }
    envelope.update(overrides)
    return envelope


def _available_envelope() -> dict:
    return _base_envelope(
        bundle_status="available",
        bundle_hash=_SHA,
        bundle={
            "schema_version": "1.0",
            "source": {"document_id": "doc-1", "primary_source_id": "src-1",
                       "source_sha256": "c" * 64, "as_of_date": "2025-12-31"},
            "valid_handles": {
                "normalized": {"artifact_role": "normalized", "reusable": True,
                               "content_sha256": "d" * 64},
            },
            "invalid": {},
            "bundle_hash": _SHA,
        },
    )


# --- N-1: old company-wiki without bundle_status ------------------------------


def test_fc903_01_n1_envelope_without_bundle_status_normalized():
    """An N-1 envelope that omits bundle_status is accepted and normalized to
    the explicit honest 'unavailable' — never faked as 'available'."""
    old = _base_envelope()
    del old["bundle_status"]
    result = validate_resolution_envelope(old)  # must not raise
    assert result["bundle_status"] == "unavailable"
    assert result is not old  # normalized copy, input untouched


def test_fc903_02_n1_without_bundle_status_never_faked_available():
    """The normalized N-1 envelope reports unavailable, and the original input
    dict is not mutated (callers may share it)."""
    old = _base_envelope()
    del old["bundle_status"]
    validate_resolution_envelope(old)
    assert "bundle_status" not in old  # input left untouched


# --- N: FC-902 envelope with real bundle --------------------------------------


def test_fc903_03_n_available_envelope_passes_verbatim():
    """An FC-902 envelope with a well-formed available bundle validates and is
    returned unchanged (forwarding fidelity)."""
    envelope = _available_envelope()
    result = validate_resolution_envelope(envelope)
    assert result == envelope
    assert result["bundle"]["bundle_hash"] == envelope["bundle_hash"]


# --- fail closed: fabricated 'available' is rejected --------------------------


def test_fc903_04_available_without_bundle_hash_rejected():
    """bundle_status='available' without a SHA-256 bundle_hash is upstream
    error — an available claim needs its evidence."""
    with pytest.raises(FilingFetchError) as exc:
        validate_resolution_envelope(
            _base_envelope(bundle_status="available"))
    assert exc.value.code == "upstream_error"


def test_fc903_05_available_with_malformed_bundle_hash_rejected():
    """A non-hash bundle_hash (short, uppercase, placeholder) is rejected."""
    with pytest.raises(FilingFetchError):
        validate_resolution_envelope(
            _base_envelope(bundle_status="available", bundle_hash="not-a-hash",
                           bundle={}))


def test_fc903_06_available_without_bundle_dict_rejected():
    """bundle_status='available' but no bundle dict is a fabricated claim."""
    with pytest.raises(FilingFetchError):
        validate_resolution_envelope(
            _base_envelope(bundle_status="available", bundle_hash=_SHA))


def test_fc903_07_available_with_mismatched_bundle_hash_rejected():
    """The bundle dict's bundle_hash must equal the envelope's — a drift is
    a tamper/fabrication signal."""
    bundle = _available_envelope()["bundle"]
    with pytest.raises(FilingFetchError):
        validate_resolution_envelope(
            _base_envelope(bundle_status="available", bundle_hash=_SHA,
                           bundle={**bundle, "bundle_hash": "f" * 64}))


# --- N-1: unavailable without bundle fields stays valid -----------------------


def test_fc903_08_unavailable_without_bundle_fields_ok():
    """FC-704-era envelope: bundle_status='unavailable' with no bundle_hash /
    bundle keys is valid (the honest N-1 shape)."""
    envelope = _base_envelope()  # unavailable, no bundle fields
    assert validate_resolution_envelope(envelope)["bundle_status"] == "unavailable"


# --- artifact validity is NOT re-decided --------------------------------------


def test_fc903_09_artifact_validity_not_redecided():
    """The bundle's valid/invalid handles are forwarded verbatim — filing-fetch
    validates contract shape only and never re-decides artifact validity."""
    envelope = _available_envelope()
    result = validate_resolution_envelope(envelope)
    assert result["bundle"]["valid_handles"] == envelope["bundle"]["valid_handles"]
    assert result["bundle"]["invalid"] == envelope["bundle"]["invalid"]
