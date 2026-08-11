"""FC-905-b RED/acceptance tests: envelope trusted-evidence field validation
(consumer side).

The FC-905-a envelope carries prompt_injection_status and parser/llm calls.
filing-fetch must validate them fail-closed and normalize N-1 envelopes
(without the fields) to the explicit honest defaults:

- missing prompt_injection_status -> 'not_reviewed' (explicit, never faked);
- parser_calls/llm_calls absent -> None (evidence absent);
- invalid status / negative or boolean counts -> upstream_error.

RED phase: the new fields pass unvalidated and N-1 envelopes are not
normalized.
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


def _base_envelope(**overrides) -> dict:
    envelope = {
        "envelope_schema_version": "1.0",
        "outcome": "reused_existing",
        "download_events": 0,
        "policy_hash": "a" * 64,
        "activation_epoch": "epoch-1",
        "bundle_status": "unavailable",
        "prompt_injection_status": "not_detected",
        "parser_calls": 0,
        "llm_calls": 0,
    }
    envelope.update(overrides)
    return envelope


# --- N-1: missing fields normalize to explicit honest defaults ----------------


def test_b1_n1_missing_status_normalizes_not_reviewed():
    envelope = _base_envelope()
    del envelope["prompt_injection_status"]
    result = validate_resolution_envelope(envelope)
    assert result["prompt_injection_status"] == "not_reviewed"
    assert "prompt_injection_status" not in envelope  # input untouched


def test_b2_n1_missing_counts_normalize_none():
    envelope = _base_envelope()
    del envelope["parser_calls"]
    del envelope["llm_calls"]
    result = validate_resolution_envelope(envelope)
    assert result["parser_calls"] is None
    assert result["llm_calls"] is None


# --- N: valid FC-905-a envelope passes ----------------------------------------


def test_b3_valid_envelope_passes_verbatim():
    envelope = _base_envelope(prompt_injection_status="detected_and_ignored",
                              parser_calls=2, llm_calls=1)
    assert validate_resolution_envelope(envelope) == envelope


def test_b4_null_counts_accepted():
    envelope = _base_envelope(parser_calls=None, llm_calls=None)
    result = validate_resolution_envelope(envelope)
    assert result["parser_calls"] is None and result["llm_calls"] is None


# --- fail closed: bad values rejected -----------------------------------------


def test_b5_bad_status_rejected():
    with pytest.raises(FilingFetchError) as exc:
        validate_resolution_envelope(
            _base_envelope(prompt_injection_status="maybe"))
    assert exc.value.code == "upstream_error"


def test_b6_negative_counts_rejected():
    for key in ("parser_calls", "llm_calls"):
        with pytest.raises(FilingFetchError):
            validate_resolution_envelope(_base_envelope(**{key: -1}))


def test_b7_boolean_counts_rejected():
    with pytest.raises(FilingFetchError):
        validate_resolution_envelope(_base_envelope(parser_calls=True))
