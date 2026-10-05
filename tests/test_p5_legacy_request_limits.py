"""Legacy response/gap shapes stay unchanged; explicit resource limits are shared."""
from __future__ import annotations

import pytest
from filing_contracts import FilingFetchError, validate_request


def _request(version):
    request = dict(schema_version=version, company_query="ACME", market="US",
                   document_kind="annual_report", fiscal_year=2025, as_of_date="2026-09-30")
    if version == "1.2":
        request["mode"] = "exact"
    return request


@pytest.mark.parametrize("version", ["1.1", "1.2"])
def test_legacy_explicit_limits_use_existing_validated_budget_contract(version):
    request = _request(version)
    request["acquisition_limits"] = dict(max_bytes=5_000_000, timeout_seconds=30,
                                         max_cost_usd="0")
    validate_request(request)


@pytest.mark.parametrize("version", ["1.1", "1.2"])
@pytest.mark.parametrize("invalid", [
    dict(max_bytes=True, timeout_seconds=30, max_cost_usd="0"),
    dict(max_bytes=5_000_000, timeout_seconds=float("nan"), max_cost_usd="0"),
    dict(max_bytes=5_000_000, timeout_seconds=30, max_cost_usd="-1"),
])
def test_legacy_limits_do_not_bypass_existing_byte_time_cost_validation(version, invalid):
    request = _request(version)
    request["acquisition_limits"] = invalid
    with pytest.raises(FilingFetchError, match="invalid acquisition_limits") as caught:
        validate_request(request)
    assert caught.value.code == "request_error"

