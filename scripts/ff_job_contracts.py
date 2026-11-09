"""ff-job/1 contracts: the durable job façade over the existing short-request engine.

This module owns the request/response vocabulary of the public job layer
(OWNERPKG-FILING-FETCH-01, G-m8-FF-01..04 + G-m8-COMMON-01/02/03). It is purely
additive: the engine requests carried inside ``ff-job/1`` submissions are
validated by the *existing* request validators (``filing_contracts.validate_request``
for v2 filing requests, ``ff_financial_statements.validate_request`` for
financial-statements requests), so job submissions can never drift from the
semantics Dashboard already depends on.

Owner-native declarations (honest vocabulary, not aspirational):

- Execution is a two-step model: ``submit`` persists a queued job and never
  runs the engine; ``run --owner-job-id`` executes one queued job with the
  bounded engine under the caller's config/deployment knobs.
- Supported actions are exactly ``cancel`` / ``retry`` / ``reconcile``.
  ``cancel`` is offered only while a job is queued: the engine is a single
  bounded subprocess call with no interruption point, so a running job cannot
  be cancelled mid-flight and honestly advertises no actions at all.
  ``resume`` is NOT offered for the same reason.
- ``recovery_capability`` is ``durable_owner_job`` for both acquire kinds,
  backed by the durable store, the retry guard, and reconcile's read-only
  owner queries against the CWP durable catalog. The legacy single-shot CLIs
  (``fetch_filing.py`` / ``fetch_statements.py``) remain ``short_request_only``
  and are untouched by this layer.
- A job whose status is ``unknown`` (owning run process died or stalled past
  its declared deadline) allows exactly one action: ``reconcile``. Reconcile
  re-checks the owner's actual state through read-only queries; it never
  re-sends a download.

No request field may carry a filesystem path, command string, or credential
(COMMON-01). Engine configuration arrives only through the operator's CLI
deployment knobs (``--config``, ``--jobs-dir``), which Dashboard registers as
ff_config/ff_root — never through job payloads.
"""

from __future__ import annotations

import re
from typing import Any

from filing_contracts import FilingFetchError, FILING_V2_REQUEST_SCHEMA_VERSION, validate_request
from ff_financial_statements import validate_request as validate_statements_request
from ff_source_candidate import contains_physical_field as _contains_physical_field

FF_JOB_SCHEMA_VERSION = "ff-job/1"
JOB_OWNER_NAME = "filing-fetch"

JOB_KINDS = ("filing.acquire", "statements.acquire")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled", "unknown")
JOB_ACTIONS = ("cancel", "retry", "reconcile")
# resume is deliberately absent; see module docstring.
RECOVERY_CAPABILITY = "durable_owner_job"

# Cost states (G-m8-FF-03 / G-m8-COMMON-03).
COST_STATES = ("known", "unknown", "not_applicable")

# A run that has gone silent past its own declared deadline plus this grace
# is reported as unknown by the store's lazily-evaluated liveness check.
RUN_STALENESS_GRACE_SECONDS = 120.0

_MAX_TEXT = 256
_IDEMPOTENCY_KEY_RE = re.compile(r"[A-Za-z0-9._:~/-]{1,256}")
_OWNER_JOB_ID_RE = re.compile(r"ffjob-[0-9a-f]{12}")

_SUBMIT_BODY_FIELDS = frozenset({"schema_version", "command_id", "kind", "idempotency_key", "request"})
_ERROR_FIELDS = frozenset({"code", "message", "owner", "retryable", "next_actions", "correlation_id"})
# The Dashboard DecimalValue contract, field for field.
_COST_FIELDS = frozenset(
    {"value", "currency", "unit", "scale", "period_start", "period_end", "period_kind",
     "fiscal_year", "basis", "scenario", "actual_or_forecast", "analysis_subject_id"}
)
_RESULT_KIND_FIELDS = {
    "filing.acquire": frozenset(
        {"kind", "status", "resolution_outcome", "download_events", "source_ref", "gap_hash",
         "reason", "calls", "downloads", "derived_by"}
    ),
    "statements.acquire": frozenset(
        {"kind", "status", "statement_count", "usage", "calls"}
    ),
}
# The statements envelope carries its usage account as one nested block.
_STATEMENTS_USAGE_FIELDS = ("http_requests", "response_bytes", "cost_usd")
# Closed next-action hints per error code; never free text.
_NEXT_ACTIONS = {
    "not_found": ["correct_scope_and_resubmit"],
    "ambiguous": ["resubmit_with_disambiguation"],
    "identity_error": ["resubmit_with_market_or_ticker"],
    "request_error": ["fix_request_and_resubmit"],
    "config_error": ["check_ff_config_registration"],
    "upstream_error": ["retry_then_reconcile"],
    "source_blocked": ["reconcile"],
    "fatal": ["reconcile"],
}


class FFJobError(FilingFetchError):
    """Job-layer refusal. Codes stay inside the existing FF error taxonomy."""


def _job_required_text(value: Any, field: str, *, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise FFJobError(f"{field} must be non-empty trimmed text", code="request_error")
    if len(value) > _MAX_TEXT:
        raise FFJobError(f"{field} must be at most {_MAX_TEXT} characters", code="request_error")
    if any(ord(ch) < 0x20 for ch in value):
        raise FFJobError(f"{field} must not contain control characters", code="request_error")
    if pattern is not None and not pattern.fullmatch(value):
        raise FFJobError(f"{field} has an unsupported shape", code="request_error")
    return value


def validate_idempotency_key(value: Any) -> str:
    return _job_required_text(value, "idempotency_key", pattern=_IDEMPOTENCY_KEY_RE)


def validate_owner_job_id(value: Any) -> str:
    return _job_required_text(value, "owner_job_id", pattern=_OWNER_JOB_ID_RE)


def validate_action(value: Any) -> str:
    if value not in JOB_ACTIONS:
        raise FFJobError(
            f"action must be one of {', '.join(JOB_ACTIONS)} (resume is not offered)",
            code="request_error",
        )
    return value


def validate_submit_body(payload: Any) -> dict[str, Any]:
    """Validate one ff-job/1 submission and return the canonical body.

    The inner ``request`` is validated by the *existing* engine validators so
    job submissions cannot drift from the short-request contracts (red line
    §3-1). Filing jobs must be v2 (``schema_version`` ``2.0``); the job layer
    does not carry legacy v1 requests. Financial-statements jobs carry the
    unchanged ``financial-statements-request/1`` payload, plus the same
    decimal-fee discipline the filing contract already enforces.
    """
    if not isinstance(payload, dict):
        raise FFJobError("submit body must be a JSON object", code="request_error")
    unknown = set(payload) - _SUBMIT_BODY_FIELDS
    if unknown:
        raise FFJobError(f"unknown submit field(s): {', '.join(sorted(unknown))}", code="request_error")
    if payload.get("schema_version") != FF_JOB_SCHEMA_VERSION:
        raise FFJobError(f"schema_version must be {FF_JOB_SCHEMA_VERSION}", code="request_error")
    command_id = _job_required_text(payload.get("command_id"), "command_id")
    kind = payload.get("kind")
    if kind not in JOB_KINDS:
        raise FFJobError(f"kind must be one of {', '.join(JOB_KINDS)}", code="request_error")
    idempotency_key = validate_idempotency_key(payload.get("idempotency_key"))
    request = payload.get("request")
    if not isinstance(request, dict):
        raise FFJobError("request must be a JSON object", code="request_error")
    if kind == "filing.acquire":
        if request.get("schema_version") != FILING_V2_REQUEST_SCHEMA_VERSION:
            raise FFJobError(
                "filing.acquire jobs carry v2 requests "
                f"(schema_version {FILING_V2_REQUEST_SCHEMA_VERSION})",
                code="request_error",
            )
        try:
            validate_request(request)
        except FilingFetchError as exc:
            raise FFJobError(str(exc), code=exc.code) from exc
    else:
        try:
            validate_statements_request(request)
        except FilingFetchError as exc:
            raise FFJobError(str(exc), code=exc.code) from exc
        _validate_statements_fee_ceiling(request)
    return {
        "schema_version": FF_JOB_SCHEMA_VERSION,
        "command_id": command_id,
        "kind": kind,
        "idempotency_key": idempotency_key,
        "request": request,
    }


def _validate_statements_fee_ceiling(request: dict[str, Any]) -> None:
    """G-m8-FF-01: fetching statements jobs obey the same <=2dp fee string."""
    intent = request.get("intent", "fetch_if_missing")
    limits = request.get("acquisition_limits")
    if intent == "reuse_only" or not isinstance(limits, dict):
        return
    cost = limits.get("max_cost_usd")
    if not isinstance(cost, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?", cost):
        raise FFJobError(
            "acquisition_limits.max_cost_usd must be a decimal string with at most 2 decimals",
            code="request_error",
        )


def job_intent(kind: str, request: dict[str, Any]) -> str:
    """The spend-driving intent of a submitted job (closed vocabulary)."""
    if kind == "filing.acquire":
        return request["filing_intent"]
    return request.get("intent", "fetch_if_missing")


def companion_may_acquire(request: dict[str, Any]) -> bool:
    option = request.get("companion_transcript")
    return isinstance(option, dict) and option.get("intent") == "fetch_if_missing"


def job_spend_intent(kind: str, request: dict[str, Any]) -> str:
    """Include all acquiring phases while preserving the submitted filing intent."""
    if kind == "filing.acquire" and companion_may_acquire(request):
        return "fetch_if_missing"
    return job_intent(kind, request)


def _error_view(code: str, message: str, retryable: bool, correlation_id: str) -> dict[str, Any]:
    """Project a failure in the Dashboard ApiError shape (owner-native fill)."""
    return {
        "code": code,
        "message": message,
        "owner": JOB_OWNER_NAME,
        "retryable": retryable,
        "next_actions": list(_NEXT_ACTIONS.get(code, ["reconcile"])),
        "correlation_id": correlation_id,
    }


def error_view_from_exception(exc: FilingFetchError, correlation_id: str) -> dict[str, Any]:
    return _error_view(exc.code, str(exc), exc.retryable, correlation_id)


def cost_for_pending(intent: str, status: str) -> tuple[dict[str, Any] | None, str]:
    """Cost projection before a terminal receipt exists.

    Queued jobs have not spent and may still spend: no cost dimension yet.
    Running jobs may be spending right now: unknown until the engine lands.
    reuse_only jobs have no cost dimension in any state.
    """
    if intent == "reuse_only":
        return None, "not_applicable"
    if status == "queued":
        return None, "not_applicable"
    return None, "unknown"


def _complete_zero_spend(evidence: dict[str, Any]) -> bool:
    return (evidence.get("provider_started") is False
            and evidence.get("usage_complete") is True
            and type(evidence.get("download_events")) is int
            and evidence["download_events"] == 0)


def build_cost_view(intent: str, evidence: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Project recorded spend evidence into the terminal (cost, cost_state).

    A complete no-start observation proves zero. A complete provider
    observation with a reported fee proves the actual cost. Partial or
    missing observations cannot certify an acquiring job's cost.
    """
    if intent == "reuse_only":
        return None, "not_applicable"
    if _complete_zero_spend(evidence):
        return _known_cost("0.00", "engine_zero_evidence")
    if evidence.get("provider_started") is True and evidence.get("usage_complete") is True:
        cost_usd = evidence.get("cost_usd")
        if isinstance(cost_usd, str) and cost_usd:
            return _known_cost(cost_usd, "provider_reported")
    return None, "unknown"


def _known_cost(value: str, basis: str) -> tuple[dict[str, Any], str]:
    cost = {
        "value": value,
        "currency": "USD",
        "unit": "USD",
        "scale": None,
        "period_start": None,
        "period_end": None,
        "period_kind": None,
        "fiscal_year": None,
        "basis": basis,
        "scenario": None,
        # A job's cost is money actually spent by this acquisition, never a
        # projection; the contract enum needs the explicit word.
        "actual_or_forecast": "actual",
        "analysis_subject_id": None,
    }
    if set(cost) != _COST_FIELDS:  # pragma: no cover - shape guard
        raise FFJobError("cost projection shape drifted", code="fatal")
    return cost, "known"


def retry_eligible(record: dict[str, Any]) -> bool:
    """True when re-running the job cannot double-spend.

    A queued cancellation before an attempt can be retried. Once an attempt
    exists, only its complete zero-spend evidence authorizes another run.
    """
    return (record.get("attempts", 0) == 0
            or _complete_zero_spend(record.get("spend_evidence") or {}))


def allowed_actions_for(record: dict[str, Any]) -> list[str]:
    """Dashboard-facing allowed_actions.

    ``unknown`` strictly allows reconcile; ``running`` advertises nothing
    (the engine is one bounded subprocess call with no interruption point —
    an honest facade does not sell a cancel it cannot deliver); terminal
    failed/cancelled jobs offer retry only when the recorded spend evidence
    proves a re-run cannot double-spend.
    """
    status = record.get("status")
    if status == "unknown":
        return ["reconcile"]
    if status in {"queued"}:
        return ["cancel"]
    if status in {"failed", "cancelled"}:
        return ["retry"] if retry_eligible(record) else []
    return []


def build_job_view(record: dict[str, Any], *, fresh_actions: list[str] | None = None) -> dict[str, Any]:
    """Project the durable record into the Dashboard JobView field set.

    Required contract fields first (owner_job_id/status/status_known/
    allowed_actions/cost/cost_state/recovery_capability/error plus command
    identity and timestamps), then owner-native extensions (kind/intent/
    idempotency_key/attempts/execution_count/result). ``fresh_actions`` lets
    the store pass an already-liveness-checked action list so the view never
    contradicts the state the store just fixed.
    """
    actions = allowed_actions_for(record) if fresh_actions is None else fresh_actions
    view = {
        "command_id": record.get("command_id"),
        "owner": JOB_OWNER_NAME,
        "owner_job_id": record.get("owner_job_id"),
        "status": record.get("status"),
        "status_known": record.get("status_known", True),
        "allowed_actions": actions,
        "started_at": record.get("started_at"),
        "updated_at": record.get("updated_at"),
        "cost": record.get("cost"),
        "cost_state": record.get("cost_state"),
        "error": record.get("error"),
        "recovery_capability": record.get("recovery_capability", RECOVERY_CAPABILITY),
        "kind": record.get("kind"),
        "intent": record.get("intent"),
        "idempotency_key": record.get("idempotency_key"),
        "attempts": record.get("attempts", 0),
        "execution_count": record.get("execution_count", 0),
        "result": record.get("result"),
    }
    if record.get("derived_by") is not None:
        view["derived_by"] = record["derived_by"]
    result = view.get("result")
    if result is not None:
        _assert_pathless(result, "result")
    cost = view.get("cost")
    if cost is not None and set(cost) != _COST_FIELDS:
        raise FFJobError("stored cost shape is invalid", code="fatal")
    if record.get("attempts", 0) > 0:
        evidence = record.get("spend_evidence") or {}
        request = record.get("request")
        legacy_zero_without_evidence = (
            isinstance(cost, dict) and cost.get("basis") == "engine_zero_evidence"
            and not _complete_zero_spend(evidence)
        )
        legacy_companion_not_counted = (
            view["status"] in {"succeeded", "failed", "unknown"}
            and view["cost_state"] == "not_applicable" and view["kind"] == "filing.acquire"
            and isinstance(request, dict) and companion_may_acquire(request)
        )
        if legacy_zero_without_evidence or legacy_companion_not_counted:
            view["cost"], view["cost_state"] = None, "unknown"
    error = view.get("error")
    if error is not None and set(error) != _ERROR_FIELDS:
        raise FFJobError("stored error shape is invalid", code="fatal")
    return view


def build_result_view(kind: str, envelope: dict[str, Any], stats: dict[str, int]) -> dict[str, Any]:
    """Project the engine envelope into the job's pathless result context.

    The projection is a closed-field whitelist that additionally must pass the
    engine's own physical-location guard — a leaked path fails the terminal
    transition instead of reaching Dashboard (fail closed).

    The two engines report different shapes, and the projection reads what
    each actually publishes:

    - filing.acquire: the v2 envelope keeps the filing facts in a nested
      ``filing`` block (status / resolution_outcome / download_events /
      source_ref / gap_hash), while calls/downloads stay at the top level.
    - statements.acquire: the envelope keeps its usage account in a nested
      ``usage`` block (http_requests / response_bytes / cost_usd) next to a
      ``statements`` list.
    """
    fields = _RESULT_KIND_FIELDS[kind]
    source: dict[str, Any] = envelope
    if kind == "filing.acquire":
        nested = envelope.get("filing")
        if isinstance(nested, dict):
            source = {**envelope, **nested}
    projected: dict[str, Any] = {"kind": kind}
    for name in fields - {"kind"}:
        value = source.get(name)
        if value is not None:
            projected[name] = value
    if kind == "statements.acquire":
        statements = envelope.get("statements")
        projected["statement_count"] = len(statements) if isinstance(statements, list) else 0
        usage = envelope.get("usage")
        if isinstance(usage, dict):
            projected["usage"] = {
                name: usage[name] for name in _STATEMENTS_USAGE_FIELDS if name in usage
            }
    projected["calls"] = stats.get("calls", 0)
    projected["downloads"] = stats.get("downloads", 0)
    _assert_pathless(projected, "result")
    return projected


def _assert_pathless(payload: dict[str, Any], label: str) -> None:
    if _contains_physical_field(payload):
        raise FFJobError(f"job {label} leaked a physical location", code="fatal")


__all__ = [
    "FF_JOB_SCHEMA_VERSION",
    "FFJobError",
    "JOB_ACTIONS",
    "JOB_KINDS",
    "JOB_OWNER_NAME",
    "JOB_STATUSES",
    "RECOVERY_CAPABILITY",
    "RUN_STALENESS_GRACE_SECONDS",
    "allowed_actions_for",
    "build_cost_view",
    "build_job_view",
    "build_result_view",
    "cost_for_pending",
    "error_view_from_exception",
    "job_intent",
    "retry_eligible",
    "validate_action",
    "validate_idempotency_key",
    "validate_owner_job_id",
    "validate_submit_body",
]
