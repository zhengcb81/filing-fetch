"""Acceptance counterexamples: optional diagnostics must never mask a cause."""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ff_provider_cause import validated_acquisition_observation as validate  # noqa: E402


def _observation(**changes):
    value = {
        "schema_version": "acquisition-observation/1", "usage_scope": "operation",
        "outcome": "failed", "provider_started": True, "usage_complete": True,
        "wire_body_bytes": 10, "wire_usage_complete": True, "entity_body_bytes": 20,
        "http_exchanges": 1, "http_exchanges_complete": True, "cost_usd": None,
        "http_observation": None,
    }
    value.update(changes)
    return value


@pytest.mark.parametrize("outcome", [[], {}])
def test_unhashable_outcome_is_dropped_without_masking_primary_error(outcome):
    assert validate(_observation(outcome=outcome)) is None


def test_exchange_count_is_integer_across_all_three_responsibility_layers():
    assert validate(_observation(http_exchanges=None)) is None
    assert validate(_observation(http_exchanges=0, http_exchanges_complete=None)) is not None


import json  # noqa: E402
from ff_provider_cause import diagnose_stderr_observation  # noqa: E402


def test_malformed_observation_does_not_erase_independent_primary_failure():
    receipt = {"schema_version": "acquisition-failure/1", "code": "upstream_unavailable",
               "retryable": False, "provider_started": True, "usage_complete": False,
               "acquisition_usage": None, "usage_scope": "operation"}
    payload = {"status": "failed", "error_type": "fatal", "error": "bounded primary failure",
               "acquisition_failure": receipt, "acquisition_observation": _observation(outcome=[])}
    _code, cause, preserved, observation = diagnose_stderr_observation("ensure", json.dumps(payload))
    assert cause["code"] == "upstream_unavailable"
    assert preserved == receipt
    assert observation is None
