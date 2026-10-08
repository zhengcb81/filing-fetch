"""Pure serializer for the opt-in filing-fetch v2 response."""

from __future__ import annotations

import re
from typing import Any

from filing_contracts import FilingFetchError, FILING_V2_RESPONSE_SCHEMA_VERSION


_REF_KEYS = frozenset({
    "schema_version", "document_id", "source_id", "content_sha256",
    "byte_size", "mime_type",
})
_TRANSCRIPT_KEYS = (
    "status", "reason", "retryable", "source_ref", "provider",
    "fiscal_year", "fiscal_quarter", "content_sha256", "locator",
    "provider_document_id", "call_date", "publication_date",
    "as_of_cutoff_verified", "provider_calls",
    "provider_requests", "provider_response_bytes", "provider_usage_complete",
)


def _ref_shape(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _REF_KEYS:
        raise FilingFetchError("v2 SourceRef shape is invalid", code="upstream_error")
    if value.get("schema_version") != "2.0":
        raise FilingFetchError("v2 SourceRef version is unsupported", code="upstream_error")
    return value


def _ref_sha(value: dict[str, Any]) -> str:
    sha = value.get("content_sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise FilingFetchError("v2 SourceRef SHA is invalid", code="upstream_error")
    return sha


def _ref_ids(value: dict[str, Any], sha: str) -> None:
    for field, kind in (("document_id", "document"), ("source_id", "source")):
        identifier = value[field]
        prefix = f"urn:company-wiki:{kind}:sha256:"
        if identifier.startswith("urn:company-wiki:"):
            if not identifier.startswith(prefix) or identifier[len(prefix):] != sha:
                raise FilingFetchError(
                    f"v2 SourceRef {field} does not match content SHA",
                    code="upstream_error",
                )


def _ref_size(value: dict[str, Any]) -> None:
    size = value.get("byte_size")
    if type(size) is not int or size < 0:
        raise FilingFetchError("v2 SourceRef byte size is invalid", code="upstream_error")


def _reference(value: object) -> dict[str, Any]:
    ref = _ref_shape(value)
    for field in ("document_id", "source_id", "mime_type"):
        text = ref.get(field)
        if not isinstance(text, str) or not text.strip():
            raise FilingFetchError(f"v2 SourceRef {field} is invalid", code="upstream_error")
    _ref_ids(ref, _ref_sha(ref))
    _ref_size(ref)
    return dict(ref)


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
        return {
            "schema_version": FILING_V2_RESPONSE_SCHEMA_VERSION,
            "status": "gap",
            "request_period": _request_period(request),
            "filing": filing,
            "transcript": {"status": "not_applicable", "reason": "filing_not_capture_ready",
                           "retryable": False},
            "calls": stats["calls"],
            "downloads": stats["downloads"],
        }
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
    return {
        "schema_version": FILING_V2_RESPONSE_SCHEMA_VERSION,
        "status": "source_candidate",
        "request_period": _request_period(request),
        "filing": filing,
        "transcript": _transcript_result(transcript),
        "calls": stats["calls"],
        "downloads": stats["downloads"],
    }


def error_envelope(
    code: str, reason: str, *, retryable: bool, stats: dict[str, int] | None = None,
    request: dict[str, Any] | None = None,
    upstream_cause: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stats = stats or {"calls": 0, "downloads": 0}
    filing: dict[str, Any] = {"status": code, "reason": reason, "retryable": retryable}
    # R6-FF-CAUSE: the optional safe machine diagnostic rides inside filing
    # (failures only; success/gap envelopes never carry it).
    if upstream_cause is not None:
        filing["upstream_cause"] = upstream_cause
    return {
        "schema_version": FILING_V2_RESPONSE_SCHEMA_VERSION,
        "status": code,
        "request_period": _request_period(request or {}),
        "filing": filing,
        "transcript": {"status": "not_requested", "retryable": False},
        "calls": stats["calls"],
        "downloads": stats["downloads"],
    }
