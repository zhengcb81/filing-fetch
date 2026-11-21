"""Exact-period transcript orchestration with a replaceable transport."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, NamedTuple, Protocol, cast

from ff_source_ref import validate_source_ref
from filing_contracts import FilingFetchError, validate_acquisition_limits


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
        validate_acquisition_limits(intent, option.get("acquisition_limits"))
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
        ref = validate_source_ref(existing.get("source_ref"))
    except FilingFetchError:
        return _result("upstream_error", reason="transcript_lookup_contract")
    fields = _optional_fields(existing, (
        "provider", "publication_date", "as_of_cutoff_verified", "provider_calls",
        "qualification", "excluded_candidates",
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
        **_optional_fields(existing, (
            "provider_calls", "excluded_candidates", "excluded_publication_statuses",
        )),
    )


def _lookup_legacy(existing: object, year: int, quarter: int) -> dict[str, Any]:
    try:
        ref = validate_source_ref(existing)
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
            ref = validate_source_ref(fetched.get("source_ref"))
        except FilingFetchError:
            return _result("upstream_error", reason="transcript_import_source_ref")
        return _result(
            "downloaded", source_ref=ref,
            fiscal_year=ready.year, fiscal_quarter=ready.quarter,
            **_optional_fields(fetched, (
                "provider", "provider_document_id", "call_date",
                "publication_date", "as_of_cutoff_verified", "provider_calls",
                "provider_requests", "provider_response_bytes", "provider_usage_complete", "provider_started",
            )),
        )
    if status in {"provider_unavailable", "not_found", "upstream_error"}:
        return _result(
            status, reason=str(fetched.get("reason") or status),
            retryable=fetched.get("retryable") is True,
            **_optional_fields(fetched, ("provider_calls", "provider_requests", "provider_response_bytes", "provider_usage_complete", "provider_started")),
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
    return _resolve_exact(
        prepared, request.get("as_of_date"), transport, filing_handle.get("source_ref"),
    )


def _resolve_exact(
    prepared: _Ready, as_of_date: str | None, transport: TranscriptTransport,
    filing_source_ref: dict | None, *, track_local_usage: bool = False,
) -> dict[str, Any]:
    arguments = {
        "identity": prepared.identity,
        "filing_source_ref": filing_source_ref,
        "fiscal_year": prepared.year,
        "fiscal_quarter": prepared.quarter,
        "as_of_date": as_of_date,
        # Omitted stays omitted: reuse is source-neutral locally, and the
        # acquisition provider is the transport's separate FMP decision.
        "provider": prepared.option.get("provider"),
    }
    existing = _lookup(transport, arguments, prepared.year, prepared.quarter)
    if existing is not None:
        if track_local_usage:
            existing.update(provider_started=False, provider_usage_complete=True,
                            provider_requests=0, provider_response_bytes=0)
        return existing
    if prepared.option["intent"] == "reuse_only":
        result = _result("not_found", reason="exact_transcript_missing")
        if track_local_usage:
            result.update(provider_started=False, provider_usage_complete=True,
                          provider_requests=0, provider_response_bytes=0)
        return result
    return _acquire(transport, arguments, prepared)


def validate_standalone_transcript_request(request: dict) -> None:
    fields = {"schema_version", "identity", "fiscal_year", "fiscal_quarter", "as_of_date",
              "intent", "provider", "acquisition_limits"}
    if request.get("schema_version") != "ff-transcript-request/1" or set(request) - fields:
        raise FilingFetchError("invalid exact transcript request", code="request_error")
    if _valid_period(request) is None:
        raise FilingFetchError("transcripts require an exact fiscal_year and fiscal_quarter",
                               code="request_error")
    identity = request.get("identity")
    if (
        not isinstance(identity, dict)
        or set(identity) - {"entity_id", "listing_id", "ticker", "market", "exchange"}
        or identity.get("market") not in ("CN", "HK", "US")
        or any(
            not isinstance(identity.get(key), str) or not identity[key] or identity[key].strip() != identity[key]
            for key in ("entity_id", "listing_id", "ticker")
        )
        or "exchange" in identity and (not isinstance(identity["exchange"], str) or not identity["exchange"])
    ):
        raise FilingFetchError("transcript request needs an explicit listing", code="request_error")
    as_of = request.get("as_of_date")
    try:
        if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of:
            raise ValueError
    except ValueError as exc:
        raise FilingFetchError("transcript as_of_date must be YYYY-MM-DD", code="request_error") from exc
    option_error = _option_error(request)
    if option_error is not None:
        raise FilingFetchError(option_error["reason"], code="request_error")


def fetch_standalone_transcript(
    request: dict, *, config_path: Path | None, timeout_seconds: float, stats: dict[str, int],
) -> dict:
    """Use the original transcript transport after verified listing lookup."""
    from fetch_filing import (
        DEFAULT_COMPANY_WIKI_CONFIG, filing_operation_deadline, identify_company, load_company_wiki_root,
    )
    from transcript_tool_transport import EarningsTranscriptsTransport

    validate_standalone_transcript_request(request)
    deadline = filing_operation_deadline(request, timeout_seconds=timeout_seconds)
    selected = request["identity"]
    try:
        root = load_company_wiki_root(config_path=config_path)
        query = {
            "company_query": selected["ticker"], "market": selected["market"],
            "exchange": selected.get("exchange"), "document_kind": "earnings_transcript",
            "as_of_date": request["as_of_date"],
        }
        identity = identify_company(request=query, root=root, deadline=deadline, stats=stats)
        if identity["ticker"].casefold() != selected["ticker"].casefold():
            raise FilingFetchError("transcript listing ticker differs from resolved ticker",
                                   code="identity_error")
        transport = EarningsTranscriptsTransport(
            wiki_root=root, config_path=config_path or DEFAULT_COMPANY_WIKI_CONFIG, deadline=deadline,
        )
    except FilingFetchError as exc:
        exc.stage = "identify"
        raise
    result = _resolve_exact(
        _Ready(request, identity, request["fiscal_year"], request["fiscal_quarter"]),
        request["as_of_date"], transport, None, track_local_usage=True,
    )
    stats["calls"] += transport.company_wiki_calls
    stats["downloads"] += int(result["status"] == "downloaded")
    return result
