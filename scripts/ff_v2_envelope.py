"""Pure serializer for the opt-in filing-fetch v2 response."""

from __future__ import annotations

from typing import Any

from filing_contracts import FilingFetchError, FILING_V2_RESPONSE_SCHEMA_VERSION, _validate_companion_request
from ff_source_ref import validate_source_ref as _reference
from ff_provider_cause import (
    STAGES,
    validated_acquisition_failure,
    validated_acquisition_observation,
    validated_cause,
    validated_request_diagnostic,
)


_TRANSCRIPT_KEYS = (
    "status", "reason", "retryable", "source_ref", "provider", "intent", "acquisition_limits",
    "fiscal_year", "fiscal_quarter", "content_sha256", "locator",
    "provider_document_id", "call_date", "publication_date",
    "as_of_cutoff_verified", "provider_calls",
    "provider_requests", "provider_response_bytes", "provider_usage_complete", "provider_started",
)


def _request_period(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": request.get("mode") or "exact",
        "fiscal_year": request.get("fiscal_year"),
        "fiscal_period": request.get("fiscal_period"),
        "as_of_date": request.get("as_of_date"),
    }


def _transcript_result(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("status"), str):
        raise FilingFetchError("transcript result is invalid", code="upstream_error")
    result = {key: value[key] for key in _TRANSCRIPT_KEYS if key in value}
    if "source_ref" in result:
        result["source_ref"] = _reference(result["source_ref"])
    result.setdefault("retryable", False)
    return result


def success_envelope(
    request: dict[str, Any],
    handle: dict[str, Any],
    transcript: dict[str, Any],
    stats: dict[str, int],
) -> dict[str, Any]:
    """Expose CWP logical source identity and separate filing/transcript outcomes."""
    if not isinstance(handle, dict):
        raise FilingFetchError("filing result is invalid", code="upstream_error")
    if handle.get("status") == "gap":
        plan = handle.get("gap_plan")
        if not isinstance(plan, dict):
            raise FilingFetchError("v2 gap plan is invalid", code="upstream_error")
        filing = {
            "status": "gap",
            "reason": (handle.get("resolution") or {}).get("reason"),
            "gap_hash": plan.get("gap_hash"),
            "download_events": 0,
        }
        # A normal missing GAP has no cause. A diagnosed provider-failure GAP
        # retains its existing status and counts while exposing safe evidence.
        upstream_cause = validated_cause(handle.get("upstream_cause"))
        if upstream_cause is not None:
            filing["upstream_cause"] = dict(upstream_cause)
        receipt = validated_acquisition_failure(handle.get("acquisition_failure"))
        if receipt is not None:
            filing["acquisition_failure"] = receipt
        result = {
            "schema_version": FILING_V2_RESPONSE_SCHEMA_VERSION,
            "status": "gap",
            "request_period": _request_period(request),
            "filing": filing,
            "transcript": {"status": "not_applicable", "reason": "filing_not_capture_ready",
                           "retryable": False},
            "calls": stats["calls"],
            "downloads": stats["downloads"],
        }
        # M3-USAGE: the operation observation is an operation-level account
        # (like calls/downloads), so it rides the envelope top level and never
        # the closed source_candidate filing shape.
        observation = validated_acquisition_observation(handle.get("acquisition_observation"))
        if observation is not None:
            result["acquisition_observation"] = observation
        return result
    ref = _reference(handle.get("source_ref"))
    events = handle.get("download_events", stats["downloads"])
    if type(events) is not int or events not in (0, 1):
        raise FilingFetchError("v2 download count is invalid", code="upstream_error")
    filing = {
        "status": "source_candidate",
        "source_ref": ref,
        "byte_verification": "pending_verified_open",
        "document_kind": handle.get("document_kind"),
        "fiscal_year": handle.get("fiscal_year"),
        "fiscal_period": handle.get("fiscal_period"),
        "resolution_outcome": handle.get("resolution_outcome"),
        "download_events": events,
    }
    result = {
        "schema_version": FILING_V2_RESPONSE_SCHEMA_VERSION,
        "status": "source_candidate",
        "request_period": _request_period(request),
        "filing": filing,
        "transcript": _transcript_result(transcript),
        "calls": stats["calls"],
        "downloads": stats["downloads"],
    }
    # M3-USAGE: operation-level observation sibling at the envelope top level.
    observation = validated_acquisition_observation(handle.get("acquisition_observation"))
    if observation is not None:
        result["acquisition_observation"] = observation
    return result


def _undispatched_companion(request: dict[str, Any]) -> dict[str, Any]:
    option = request.get("companion_transcript")
    if option is None:
        return {"status": "not_requested", "retryable": False}
    try:
        _validate_companion_request(option)
    except (FilingFetchError, TypeError, ValueError):
        return {"status": "request_error", "reason": "invalid_companion_request", "retryable": False}
    if option.get("fiscal_year") is None or option.get("fiscal_quarter") is None:
        return {"status": "period_unresolved", "reason": "exact_fy_q_required", "retryable": False}
    return {"status": "not_run", "reason": "filing_failed_before_companion_dispatch",
            "retryable": False,
            **{key: option[key] for key in ("intent", "fiscal_year", "fiscal_quarter", "provider", "acquisition_limits") if key in option},
            "provider_started": False, "provider_requests": 0,
            "provider_response_bytes": 0, "provider_usage_complete": True}


def error_envelope(
    code: str, reason: str, *, retryable: bool, stats: dict[str, int] | None = None,
    request: dict[str, Any] | None = None,
    upstream_cause: dict[str, Any] | None = None,
    acquisition_failure: dict[str, Any] | None = None,
    stage: str | None = None,
    attempts: int | None = None,
    acquisition_observation: dict[str, Any] | None = None,
    request_diagnostic: dict[str, Any] | None = None,
    producer_exit_code: int | None = None,
) -> dict[str, Any]:
    stats = stats or {"calls": 0, "downloads": 0}
    filing: dict[str, Any] = {"status": code, "reason": reason, "retryable": retryable}
    if type(producer_exit_code) is int:
        filing["producer_exit_code"] = producer_exit_code
    diagnostic = validated_request_diagnostic(request_diagnostic)
    if diagnostic is not None:
        filing["request_diagnostic"] = diagnostic
    # R6-FF-CAUSE: the optional safe machine diagnostic rides inside filing
    # (failures only; a diagnosed failure GAP may carry the same object).
    if upstream_cause is not None:
        filing["upstream_cause"] = upstream_cause
    receipt = validated_acquisition_failure(acquisition_failure)
    if receipt is not None:
        filing["acquisition_failure"] = receipt
    if isinstance(stage, str) and stage in STAGES:
        filing["stage"] = stage
    if type(attempts) is int and attempts >= 0:
        filing["attempts"] = attempts
    result = {
        "schema_version": FILING_V2_RESPONSE_SCHEMA_VERSION,
        "status": code,
        "request_period": _request_period(request or {}),
        "filing": filing,
        "transcript": _undispatched_companion(request or {}),
        "calls": stats["calls"],
        "downloads": stats["downloads"],
    }
    # M3-USAGE: operation-level observation sibling at the envelope top level.
    observation = validated_acquisition_observation(acquisition_observation)
    if observation is not None:
        result["acquisition_observation"] = observation
    return result
