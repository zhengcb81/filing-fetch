"""R6-FF-CAUSE: safe upstream-failure diagnostics for company-wiki CLI calls.

A named producer failure used to collapse to ``ensure exited 1`` + ``fatal``;
the machine cause that company-wiki *did* publish on stderr (the
error-taxonomy ``error_type`` code) was dropped.  This module parses the
ALREADY-BOUNDED stderr of a failed company-wiki subprocess exactly once and
turns it into a fixed six-key ``filing-upstream-cause/1`` diagnostic:

    {"schema_version", "operation", "code",
     "provider_started", "usage_complete", "retry_scope"}

Safety rules (card ff_provider_diagnostics.md):

- The emitted object is built from closed vocabularies only.  Raw stderr,
  exception text, commands, physical directories, URL queries and credentials
  never cross this boundary — an unmapped or malformed payload stays
  ``unknown`` and the pre-existing fatal semantics are untouched.
- ``provider_started`` / ``usage_complete`` use a validated operation-scoped
  acquisition-failure/1 producer diagnostic when present. Otherwise they remain
  ``null`` unless FF proves a typed pre-start failure or deadline before its
  first attempt. Arbitrary transport or cleanup errors never prove zero usage.
- ``retry_scope`` mirrors the pre-existing retry semantics exactly:
  ``catalog_contention`` iff the bounded auto-retry set, ``caller_decision``
  for retryable-but-caller-side classes, ``none`` otherwise.  No failure
  becomes more or less retryable than before.

Code vocabulary: the verified company-wiki public machine codes
(error-taxonomy-1.1: catalog_locked / catalog_busy / db_timeout /
worker_paused / legacy_evidence_archived / fatal, plus the retired-command
emission's maintenance_operation_retired and the N-1 class-name family), the
FF-observed producer conditions below, and ``unknown``.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

UPSTREAM_CAUSE_SCHEMA_VERSION = "filing-upstream-cause/1"
OPERATIONS = frozenset({"identify", "ensure", "resolve", "close-gap", "query", "local_prepare"})
CAUSE_KEYS = frozenset(
    {
        "schema_version",
        "operation",
        "code",
        "provider_started",
        "usage_complete",
        "retry_scope",
    }
)
RETRY_SCOPES = frozenset({"none", "catalog_contention", "caller_decision"})
STAGES = OPERATIONS | {"source_query", "source_operation", "ambiguous", "not_found", "upstream_error"}

# Published acquisition-failure/1 vocabulary, shared by versioned wire contract;
# no runtime import of company-wiki implementation internals.
ACQUISITION_FAILURE_CODES = frozenset({
    "adapter_process_failed", "adapter_timeout", "adapter_output_limit",
    "adapter_response_invalid", "adapter_not_bounded", "upstream_unavailable",
    "network_failed", "budget_exceeded", "provider_failed", "provider_not_configured",
    "invalid_request", "invalid_budget", "invalid_candidate", "missing_scratch",
    "invalid_scratch", "unsupported_language", "unsupported_sec_form", "unsupported_hk_period",
    "identity_mismatch", "invalid_provider_metadata", "primary_missing",
    "fiscal_period_unresolved", "missing_response", "staging_conflict", "sdk_asset_mismatch",
    "deadline_exceeded", "byte_budget_exceeded", "cost_budget_exceeded",
    "unsupported_content_encoding", "incomplete_response", "acquisition_budget_exceeded",
    "acquisition_validation_failed", "canonical_import_failed",
})
_ACQUISITION_FAILURE_KEYS = frozenset({
    "schema_version", "code", "retryable", "provider_started", "usage_complete",
    "acquisition_usage", "usage_scope",
})
_USAGE_KEYS = frozenset({"schema_version", "response_bytes", "cost_usd"})

# stderr error_type -> (filing error code, cause code).  These are the only
# machine codes company-wiki publishes on the failing CLI boundary; anything
# absent here fails closed to fatal/unknown (never copy unverified strings).
_CWP_STDERR_CODES: dict[str, tuple[str, str]] = {
    "catalog_locked": ("catalog_locked", "catalog_locked"),
    "catalog_busy": ("catalog_busy", "catalog_busy"),
    "db_timeout": ("db_timeout", "db_timeout"),
    "worker_paused": ("worker_paused", "worker_paused"),
    "legacy_evidence_archived": ("fatal", "legacy_evidence_archived"),
    "fatal": ("fatal", "fatal"),
    "maintenance_operation_retired": ("fatal", "maintenance_operation_retired"),
    # N-1 legacy emission: exception class names from before the taxonomy.
    "CatalogOperationLockedError": ("catalog_locked", "catalog_locked"),
}

# FF-observed producer conditions the stderr parse can never see, with the
# filing error code the transport handlers already raised.
_PRODUCER_CONDITIONS: dict[str, tuple[str, bool | None, bool | None]] = {
    # The producer process never started: no provider contact was possible,
    # so usage is provably final at zero.
    "producer_start_failed": ("fatal", False, True),
    "producer_deadline_exceeded": ("upstream_error", None, None),
    "producer_output_exceeded": ("upstream_error", None, None),
    "producer_transport_failure": ("upstream_error", None, None),
}

_CATALOG_CONTENTION_CODES = frozenset({"catalog_locked", "catalog_busy", "db_timeout"})
_CALLER_DECISION_CODES = frozenset(
    {
        "worker_paused",
        "producer_deadline_exceeded",
        "producer_output_exceeded",
        "producer_transport_failure",
    }
)
_KNOWN_CAUSE_CODES = (
    frozenset({cause for _, cause in _CWP_STDERR_CODES.values()})
    | frozenset(_PRODUCER_CONDITIONS)
    | ACQUISITION_FAILURE_CODES
    | {"unknown", "local_metadata_gap", "no_registered_local_source", "no_local_match",
       "source_not_found", "invalid_producer_schema"}
)

# Defense-in-depth on top of the transport layer's own stderr cap: payloads
# beyond this stay unparsed (unknown) so a pathological stderr cannot turn
# into pathological parse cost either.
_MAX_STDERR_PARSE_BYTES = 64 * 1024


def _retry_scope(cause_code: str) -> str:
    if cause_code in _CATALOG_CONTENTION_CODES:
        return "catalog_contention"
    if cause_code in _CALLER_DECISION_CODES:
        return "caller_decision"
    return "none"


def _optional_bool(value: Any) -> bool:
    return value is None or isinstance(value, bool)


def build_cause(
    operation: str,
    code: str,
    *,
    provider_started: bool | None = None,
    usage_complete: bool | None = None,
) -> dict[str, Any]:
    """Build the fixed six-key diagnostic from closed vocabularies only."""
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise ValueError(f"unknown upstream operation: {operation!r}")
    if not isinstance(code, str) or code not in _KNOWN_CAUSE_CODES:
        raise ValueError(f"unknown upstream cause code: {code!r}")
    if not _optional_bool(provider_started) or not _optional_bool(usage_complete):
        raise ValueError("upstream evidence flags must be bool or null")
    return {
        "schema_version": UPSTREAM_CAUSE_SCHEMA_VERSION,
        "operation": operation,
        "code": code,
        "provider_started": provider_started,
        "usage_complete": usage_complete,
        "retry_scope": _retry_scope(code),
    }


def _parse_structured(stderr_text: str) -> dict[str, Any] | None:
    """Exactly one bounded JSON parse; never return unstructured error text."""
    if not stderr_text or len(stderr_text.encode("utf-8")) > _MAX_STDERR_PARSE_BYTES:
        return None
    try:
        payload = json.loads(stderr_text)
    except (ValueError, RecursionError):
        return None
    return payload if isinstance(payload, dict) else None


def _map_structured(payload: dict[str, Any] | None) -> tuple[str, str]:
    """Keep legacy generic classification and its bounded retry policy unchanged."""
    if payload is None:
        return ("fatal", "unknown")
    error_type = payload.get("error_type")
    if not isinstance(error_type, str):
        return ("fatal", "unknown")
    mapped = _CWP_STDERR_CODES.get(error_type)
    if mapped is not None:
        return mapped
    if error_type == "RuntimeError" and "paused" in str(payload.get("error", "")):
        return ("worker_paused", "worker_paused")
    return ("fatal", "unknown")


def _valid_acquisition_usage(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != _USAGE_KEYS:
        return False
    if value["schema_version"] != "1.0":
        return False
    response_bytes = value["response_bytes"]
    if isinstance(response_bytes, bool) or not isinstance(response_bytes, int) or response_bytes < 0:
        return False
    cost = value["cost_usd"]
    if not isinstance(cost, str):
        return False
    try:
        amount = Decimal(cost)
    except (InvalidOperation, ValueError):
        return False
    return amount.is_finite() and amount >= 0


def _acquisition_evidence(value: Any) -> tuple[str, bool | None, bool | None] | None:
    """Validate the public seven-field producer DTO, projecting safe evidence only.

    Acquisition usage is operation cumulative, including discovery and fetches;
    incomplete usage is a lower bound. It remains in producer records, not a
    second FF fee ledger. Malformed or unknown schemas never prove usage flags.
    """
    if not isinstance(value, dict) or set(value) != _ACQUISITION_FAILURE_KEYS:
        return None
    if value["schema_version"] != "acquisition-failure/1" or value["usage_scope"] != "operation":
        return None
    if not all(_optional_bool(value[key]) for key in ("retryable", "provider_started", "usage_complete")):
        return None
    if not _valid_acquisition_usage(value["acquisition_usage"]):
        return None
    code = value["code"]
    if not isinstance(code, str):
        return None
    safe_code = code if code in ACQUISITION_FAILURE_CODES else "adapter_process_failed"
    return safe_code, value["provider_started"], value["usage_complete"]


def validated_acquisition_failure(value: Any) -> dict[str, Any] | None:
    """Copy an existing operation observation; no accounting or inferred zero."""
    if _acquisition_evidence(value) is None or value["code"] not in ACQUISITION_FAILURE_CODES:
        return None
    result = dict(value)
    usage = value["acquisition_usage"]
    result["acquisition_usage"] = dict(usage) if usage is not None else None
    return result


def source_condition(operation: str, reason: Any) -> dict[str, Any]:
    """Finite source condition, independent of provider acquisition failures."""
    reasons = {"local_metadata_gap", "no_registered_local_source", "no_local_match",
               "source_not_found", "invalid_producer_schema"}
    code = reason if isinstance(reason, str) and reason in reasons else "unknown"
    local_only = operation in {"query", "local_prepare"} and code != "invalid_producer_schema"
    return build_cause(operation, code, provider_started=False if local_only else None,
                       usage_complete=True if local_only else None)


def classify_stderr(stderr_text: str) -> str:
    """The unchanged generic filing error code, parsed once."""
    return _map_structured(_parse_structured(stderr_text))[0]


def diagnose_stderr(operation: str, stderr_text: str) -> tuple[str, dict[str, Any]]:
    """Parse once; prefer validated producer evidence without changing retries."""
    code, cause, _ = diagnose_stderr_observation(operation, stderr_text)
    return code, cause


def diagnose_stderr_observation(operation: str, stderr_text: str) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """Decode cause and the same existing producer receipt in one bounded parse."""
    payload = _parse_structured(stderr_text)
    ff_code, legacy_cause = _map_structured(payload)
    evidence = _acquisition_evidence(payload.get("acquisition_failure")) if payload else None
    receipt = validated_acquisition_failure(payload.get("acquisition_failure")) if payload else None
    if evidence is None:
        return ff_code, build_cause(operation, legacy_cause), receipt
    safe_code, started, complete = evidence
    projected = build_cause(operation, safe_code, provider_started=started, usage_complete=complete)
    # Generic taxonomy owns retry semantics. Producer retryable is diagnostic,
    # never authorization for FF to issue a second potentially charged request.
    projected["retry_scope"] = _retry_scope(legacy_cause)
    return ff_code, projected, receipt



def diagnose_acquisition_failure(operation: str, value: Any) -> dict[str, Any] | None:
    """Project a top-level returned failure DTO using the stderr validator.

    Normal missing/GAP results contain no such DTO and return no cause. The
    returned object carries no retry authorization; existing result status owns
    that decision. Never scan nested gap plans or error text for a diagnostic.
    """
    evidence = _acquisition_evidence(value)
    if evidence is None:
        return None
    code, started, complete = evidence
    return build_cause(operation, code, provider_started=started, usage_complete=complete)


def condition_cause(
    operation: str,
    condition: str,
    *,
    provider_started: bool | None = None,
    usage_complete: bool | None = None,
) -> tuple[str, dict[str, Any]]:
    """Diagnostics for producer conditions observed by FF itself (no stderr).

    An explicit non-None ``provider_started`` / ``usage_complete`` overrides
    the table default — used only for the provable no-start deadline cutoff.
    """
    try:
        ff_code, started, usage = _PRODUCER_CONDITIONS[condition]
    except KeyError:
        raise ValueError(f"unknown producer condition: {condition!r}") from None
    cause = build_cause(
        operation,
        condition,
        provider_started=started if provider_started is None else provider_started,
        usage_complete=usage if usage_complete is None else usage_complete,
    )
    return ff_code, cause


def _valid_cause_header(value: dict[str, Any]) -> bool:
    if not all(isinstance(value[key], str) for key in ("schema_version", "operation", "code", "retry_scope")):
        return False
    if value["schema_version"] != UPSTREAM_CAUSE_SCHEMA_VERSION:
        return False
    if value["operation"] not in OPERATIONS or value["retry_scope"] not in RETRY_SCOPES:
        return False
    return value["code"] in _KNOWN_CAUSE_CODES


def validated_cause(value: Any) -> dict[str, Any] | None:
    """Return the cause iff it is a well-formed filing-upstream-cause/1 object."""
    if not isinstance(value, dict) or set(value) != CAUSE_KEYS:
        return None
    if not _valid_cause_header(value):
        return None
    if not _optional_bool(value["provider_started"]) or not _optional_bool(
        value["usage_complete"]
    ):
        return None
    return value


__all__ = [
    "UPSTREAM_CAUSE_SCHEMA_VERSION",
    "ACQUISITION_FAILURE_CODES",
    "OPERATIONS",
    "CAUSE_KEYS",
    "RETRY_SCOPES",
    "build_cause",
    "classify_stderr",
    "condition_cause",
    "diagnose_stderr",
    "diagnose_acquisition_failure",
    "validated_cause",
]
