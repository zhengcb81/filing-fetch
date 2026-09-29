"""Exact FY/Q companion orchestration with an injectable, offline transport."""

from __future__ import annotations

from typing import Any

import pytest

from transcript_companion import resolve_companion_transcript


FIL_REF = {
    "schema_version": "2.0", "document_id": "urn:filing:document",
    "source_id": "urn:filing:source", "content_sha256": "a" * 64,
    "byte_size": 100, "mime_type": "application/pdf",
}
TXT_REF = {
    "schema_version": "2.0", "document_id": "urn:transcript:document",
    "source_id": "urn:transcript:source", "content_sha256": "b" * 64,
    "byte_size": 60, "mime_type": "text/plain",
}


def request(*, intent: str = "fetch_if_missing", quarter: int | None = 2) -> dict:
    companion: dict[str, Any] = {"intent": intent, "fiscal_year": 2025}
    if quarter is not None:
        companion["fiscal_quarter"] = quarter
        if intent == "fetch_if_missing":
            companion["acquisition_limits"] = {
                "max_bytes": 1_000_000, "timeout_seconds": 10, "max_cost_usd": "0.00",
            }
    return {"as_of_date": "2026-09-29", "companion_transcript": companion}


def filing() -> dict:
    return {
        "source_ref": FIL_REF,
        "company_identity": {
            "canonical_name": "Acme Inc.", "market": "US", "security_id": "ACME",
            "ticker": "ACME", "exchange": "NASDAQ", "verified": True, "active": True,
        },
    }


class FakeTransport:
    def __init__(self, *, existing: dict | None = None, acquired: dict | None = None):
        self.existing = existing
        self.acquired = acquired or {"status": "downloaded", "source_ref": TXT_REF}
        self.calls: list[tuple[str, dict]] = []

    def lookup_exact(self, **kwargs):
        self.calls.append(("lookup", kwargs))
        return self.existing

    def acquire_exact(self, **kwargs):
        self.calls.append(("acquire", kwargs))
        return self.acquired


def test_no_companion_does_not_touch_transport() -> None:
    transport = FakeTransport()
    result = resolve_companion_transcript(
        request={"as_of_date": "2026-09-29"}, filing_handle=filing(),
        transport=transport,
    )
    assert result["status"] == "not_requested"
    assert transport.calls == []


def test_fy_only_period_is_unresolved_and_zero_calls() -> None:
    transport = FakeTransport()
    result = resolve_companion_transcript(
        request=request(quarter=None), filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "period_unresolved"
    assert transport.calls == []


def test_existing_exact_transcript_is_reused_without_fetch() -> None:
    transport = FakeTransport(existing=TXT_REF)
    result = resolve_companion_transcript(
        request=request(), filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "reused"
    assert result["source_ref"] == TXT_REF
    assert [name for name, _ in transport.calls] == ["lookup"]
    assert transport.calls[0][1]["fiscal_year"] == 2025
    assert transport.calls[0][1]["fiscal_quarter"] == 2


def test_missing_exact_transcript_fetches_once_and_replay_reuses() -> None:
    transport = FakeTransport()
    first = resolve_companion_transcript(
        request=request(), filing_handle=filing(), transport=transport,
    )
    assert first["status"] == "downloaded"
    assert [name for name, _ in transport.calls] == ["lookup", "acquire"]
    assert transport.calls[1][1]["fiscal_quarter"] == 2
    transport.existing = TXT_REF
    second = resolve_companion_transcript(
        request=request(), filing_handle=filing(), transport=transport,
    )
    assert second["status"] == "reused"
    assert [name for name, _ in transport.calls] == ["lookup", "acquire", "lookup"]


def test_provider_unavailable_is_separate_child_result() -> None:
    transport = FakeTransport(acquired={
        "status": "provider_unavailable", "reason": "entitlement_required",
        "retryable": False,
    })
    result = resolve_companion_transcript(
        request=request(), filing_handle=filing(), transport=transport,
    )
    assert result == {
        "status": "provider_unavailable", "reason": "entitlement_required",
        "retryable": False,
    }
    assert [name for name, _ in transport.calls] == ["lookup", "acquire"]


def test_default_transport_waits_for_producer_contract_without_network() -> None:
    result = resolve_companion_transcript(
        request=request(), filing_handle=filing(),
    )
    assert result == {
        "status": "contract_pending", "reason": "cwp_fmp_import_contract_pending",
        "retryable": False,
    }


def test_lookup_failure_is_child_error_not_filing_exception() -> None:
    class BrokenTransport(FakeTransport):
        def lookup_exact(self, **kwargs):
            raise RuntimeError("provider secret should not leak")
    result = resolve_companion_transcript(
        request=request(), filing_handle=filing(), transport=BrokenTransport(),
    )
    assert result == {
        "status": "upstream_error", "reason": "transcript_lookup_failed",
        "retryable": True,
    }


@pytest.mark.parametrize("period", [0, 5, True])
def test_invalid_quarter_is_rejected_before_transport(period: Any) -> None:
    transport = FakeTransport()
    value = request()
    value["companion_transcript"]["fiscal_quarter"] = period
    result = resolve_companion_transcript(
        request=value, filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "period_unresolved"
    assert transport.calls == []



def test_direct_companion_fetch_without_caps_makes_zero_transport_calls() -> None:
    transport = FakeTransport()
    value = request()
    del value["companion_transcript"]["acquisition_limits"]
    result = resolve_companion_transcript(
        request=value, filing_handle=filing(), transport=transport,
    )
    assert result == {
        "status": "request_error", "reason": "invalid_acquisition_limits",
        "retryable": False,
    }
    assert transport.calls == []


def test_companion_limits_reach_acquisition_once() -> None:
    transport = FakeTransport()
    value = request()
    result = resolve_companion_transcript(
        request=value, filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "downloaded"
    assert [name for name, _ in transport.calls] == ["lookup", "acquire"]
    assert transport.calls[1][1]["acquisition_limits"] == (
        value["companion_transcript"]["acquisition_limits"]
    )
