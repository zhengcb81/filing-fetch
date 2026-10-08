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
- ``provider_started`` / ``usage_complete`` are only non-null where FF itself
  can prove no producer subprocess ran (spawn failure; deadline gone before
  the first attempt) — usage is then final at zero.  When a producer actually
  ran they stay ``null``: company-wiki's public stderr emission carries no
  such fields today (findings G1/G2), and production code never guesses.
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
from typing import Any

UPSTREAM_CAUSE_SCHEMA_VERSION = "filing-upstream-cause/1"
OPERATIONS = frozenset({"identify", "ensure", "resolve", "close-gap", "query"})
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
    | {"unknown"}
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
    if operation not in OPERATIONS:
        raise ValueError(f"unknown upstream operation: {operation!r}")
    if code not in _KNOWN_CAUSE_CODES:
        raise ValueError(f"unknown upstream cause code: {code!r}")
    return {
        "schema_version": UPSTREAM_CAUSE_SCHEMA_VERSION,
        "operation": operation,
        "code": code,
        "provider_started": provider_started,
        "usage_complete": usage_complete,
        "retry_scope": _retry_scope(code),
    }


def _classified(stderr_text: str) -> tuple[str, str]:
    """The (filing code, cause code) pair for a bounded stderr payload."""
    if not stderr_text or len(stderr_text) > _MAX_STDERR_PARSE_BYTES:
        return ("fatal", "unknown")
    mapped = _map_structured(stderr_text)
    if mapped is None:
        return ("fatal", "unknown")
    return mapped


def _map_structured(stderr_text: str) -> tuple[str, str] | None:
    """Map one structured error-taxonomy payload; None when not mappable.

    The raw ``error`` text is read ONLY for the legacy RuntimeError+paused
    classification and never leaves this function.
    """
    try:
        payload = json.loads(stderr_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    error_type = payload.get("error_type")
    if not isinstance(error_type, str):
        return None
    mapped = _CWP_STDERR_CODES.get(error_type)
    if mapped is not None:
        return mapped
    if error_type == "RuntimeError" and "paused" in str(payload.get("error", "")):
        return ("worker_paused", "worker_paused")
    return None


def classify_stderr(stderr_text: str) -> str:
    """The filing error code alone (compat wrapper for the old classifier)."""
    return _classified(stderr_text)[0]


def diagnose_stderr(operation: str, stderr_text: str) -> tuple[str, dict[str, Any]]:
    """One bounded parse of a failed company-wiki subprocess stderr.

    Returns ``(filing_error_code, upstream_cause)``.  Malformed, oversized,
    mixed or non-object payloads fail closed: filing code ``fatal`` and cause
    code ``unknown`` — exactly the pre-lane classifier behavior.
    """
    ff_code, cause_code = _classified(stderr_text)
    return ff_code, build_cause(operation, cause_code)


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
    "OPERATIONS",
    "CAUSE_KEYS",
    "RETRY_SCOPES",
    "build_cause",
    "classify_stderr",
    "condition_cause",
    "diagnose_stderr",
    "validated_cause",
]
