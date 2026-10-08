"""Exact-period transcript orchestration with a replaceable transport."""

from __future__ import annotations

from typing import Any, NamedTuple, Protocol, cast

from ff_v2_envelope import _reference
from filing_contracts import FilingFetchError, _validate_acquisition_limits


class TranscriptTransport(Protocol):
    def lookup_exact(self, **kwargs: Any) -> dict[str, Any] | None: ...

    def acquire_exact(self, **kwargs: Any) -> dict[str, Any]: ...


class _Ready(NamedTuple):
    option: dict[str, Any]
    identity: dict[str, Any]
    year: int
    quarter: int


def _result(
    status: str, *, reason: str | None = None, retryable: bool = False,
    **fields: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status, "retryable": retryable}
    if reason is not None:
        result["reason"] = reason
    result.update(fields)
    return result


def _valid_period(option: dict[str, Any]) -> tuple[int, int] | None:
    year = option.get("fiscal_year")
    quarter = option.get("fiscal_quarter")
    if type(year) is not int or not 1900 <= year <= 2100:
        return None
    if type(quarter) is not int or quarter not in {1, 2, 3, 4}:
        return None
    return year, quarter


def _option_error(option: dict[str, Any]) -> dict[str, Any] | None:
    intent = option.get("intent")
    if intent not in {"reuse_only", "fetch_if_missing"}:
        return _result("request_error", reason="invalid_transcript_intent")
    provider = option.get("provider")
    if provider not in (None, "fmp"):
        return _result("request_error", reason="unsupported_transcript_provider")
    try:
        _validate_acquisition_limits(intent, option.get("acquisition_limits"))
    except FilingFetchError:
        return _result("request_error", reason="invalid_acquisition_limits")
    return None


def _identity_error(identity: object) -> dict[str, Any] | None:
    if not isinstance(identity, dict) or identity.get("verified") is not True:
        return _result("not_applicable", reason="verified_security_unavailable")
    if identity.get("active") is not True:
        return _result("not_applicable", reason="active_security_unavailable")
    return None


def _prepare(
    request: dict[str, Any], filing_handle: dict[str, Any],
) -> _Ready | dict[str, Any]:
    option = request.get("companion_transcript")
    if option is None:
        return _result("not_requested")
    if not isinstance(option, dict):
        return _result("period_unresolved", reason="exact_fy_q_required")
    period = _valid_period(option)
    if period is None:
        return _result("period_unresolved", reason="exact_fy_q_required")
    error = _option_error(option)
    if error is not None:
        return error
    identity = filing_handle.get("company_identity")
    error = _identity_error(identity)
    if error is not None:
        return error
    return _Ready(option, cast(dict[str, Any], identity), *period)


def _optional_fields(source: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {name: source[name] for name in names if name in source}


def _lookup_resolved(
    existing: dict[str, Any], year: int, quarter: int,
) -> dict[str, Any]:
    status = existing["status"]
    try:
        ref = _reference(existing.get("source_ref"))
    except FilingFetchError:
        return _result("upstream_error", reason="transcript_lookup_contract")
    fields = _optional_fields(existing, (
        "provider", "publication_date", "as_of_cutoff_verified", "provider_calls",
    ))
    if status == "unknown_publication":
        fields["as_of_cutoff_verified"] = False
        return _result(
            "unknown_publication", reason="publication_date_unknown",
            source_ref=ref, fiscal_year=year, fiscal_quarter=quarter, **fields,
        )
    return _result(
        "reused", source_ref=ref, fiscal_year=year, fiscal_quarter=quarter, **fields,
    )


def _lookup_unavailable(existing: dict[str, Any]) -> dict[str, Any]:
    status = "ambiguous" if existing["status"] == "ambiguous" else "upstream_error"
    return _result(
        status, reason=existing.get("reason") or "transcript_lookup_unavailable",
    )


def _lookup_legacy(existing: object, year: int, quarter: int) -> dict[str, Any]:
    try:
        ref = _reference(existing)
    except FilingFetchError:
        return _result("upstream_error", reason="transcript_lookup_contract")
    return _result(
        "reused", source_ref=ref, fiscal_year=year, fiscal_quarter=quarter,
    )


def _lookup(
    transport: TranscriptTransport, arguments: dict[str, Any],
    year: int, quarter: int,
) -> dict[str, Any] | None:
    try:
        existing = transport.lookup_exact(**arguments)
    except Exception:
        return _result("upstream_error", reason="transcript_lookup_failed", retryable=True)
    if existing is None:
        return None
    if isinstance(existing, dict) and existing.get("status") in {
        "found", "unknown_publication",
    }:
        return _lookup_resolved(existing, year, quarter)
    if isinstance(existing, dict) and existing.get("status") in {
        "ambiguous", "blocked", "unavailable", "upstream_error",
    }:
        return _lookup_unavailable(existing)
    return _lookup_legacy(existing, year, quarter)


def _acquire(
    transport: TranscriptTransport, arguments: dict[str, Any], ready: _Ready,
) -> dict[str, Any]:
    try:
        fetched = transport.acquire_exact(
            **arguments, acquisition_limits=ready.option["acquisition_limits"],
        )
    except Exception as exc:
        return _result("upstream_error", reason=f"transcript_acquisition_failed:{type(exc).__name__}", retryable=True)
    if not isinstance(fetched, dict):
        return _result("upstream_error", reason="transcript_acquisition_contract")
    status = fetched.get("status")
    if status == "downloaded":
        try:
            ref = _reference(fetched.get("source_ref"))
        except FilingFetchError:
            return _result("upstream_error", reason="transcript_import_source_ref")
        return _result(
            "downloaded", source_ref=ref,
            fiscal_year=ready.year, fiscal_quarter=ready.quarter,
            **_optional_fields(fetched, (
                "provider", "provider_document_id", "call_date",
                "publication_date", "as_of_cutoff_verified", "provider_calls",
                "provider_requests", "provider_response_bytes", "provider_usage_complete",
            )),
        )
    if status in {"provider_unavailable", "not_found", "upstream_error"}:
        return _result(
            status, reason=str(fetched.get("reason") or status),
            retryable=fetched.get("retryable") is True,
            **_optional_fields(fetched, ("provider_calls", "provider_requests", "provider_response_bytes", "provider_usage_complete")),
        )
    return _result("upstream_error", reason="transcript_acquisition_contract")


def resolve_companion_transcript(
    *,
    request: dict[str, Any], filing_handle: dict[str, Any],
    transport: TranscriptTransport | None = None,
) -> dict[str, Any]:
    """Reuse an exact transcript, then acquire at most once if requested."""
    prepared = _prepare(request, filing_handle)
    if not isinstance(prepared, _Ready):
        return prepared
    if transport is None:
        return _result("contract_pending", reason="cwp_fmp_import_contract_pending")
    arguments = {
        "identity": prepared.identity,
        "filing_source_ref": filing_handle.get("source_ref"),
        "fiscal_year": prepared.year,
        "fiscal_quarter": prepared.quarter,
        "as_of_date": request.get("as_of_date"),
        "provider": prepared.option.get("provider") or "fmp",
    }
    existing = _lookup(transport, arguments, prepared.year, prepared.quarter)
    if existing is not None:
        return existing
    if prepared.option["intent"] == "reuse_only":
        return _result("not_found", reason="exact_transcript_missing")
    return _acquire(transport, arguments, prepared)
