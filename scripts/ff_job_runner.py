"""Durable job execution and actions for the ff-job/1 façade.

The runner owns every state transition a queued job can take. It calls the
*existing* short-request engine (``fetch_filing.resolve_filing`` for
filing.acquire, ``ff_financial_statements.fetch_statements`` for
statements.acquire) through their public library entry points.

Declared execution semantics:

- ``run_job`` executes exactly one queued job under the per-job lock, bounded
  by ``--timeout-seconds``. A second ``run`` on the same job is a no-op (the
  terminal record is returned untouched) — this is the "same idempotency_key
  never acquires twice" guarantee at execution level (G-m8-FF-03).
- ``cancel`` is queued-only. The engine is one bounded subprocess call with
  no interruption point; a running job advertises no actions and completes
  or times out under its own budget.
- ``retry`` resets a failed/cancelled job to queued only when the recorded
  spend evidence proves a re-run cannot double-spend.
- ``reconcile`` (G-m8-FF-04) serves unknown jobs only: it re-checks the
  owner's actual state through the read-only reuse path of the same engine
  and then lands a terminal state. It never dispatches a download.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ff_job_contracts import (
    FFJobError,
    build_cost_view,
    build_result_view,
    companion_may_acquire,
    cost_for_pending,
    error_view_from_exception,
    job_spend_intent,
    retry_eligible,
    validate_action,
)
from ff_job_store import JobStore, now_iso
from filing_contracts import FilingFetchError

_MAX_ACTIONS = 50
_MAX_EVENTS = 50
_NO_PROVIDER = {"provider_started": False, "usage_complete": True}


def _iso_deadline(seconds: float) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=seconds)
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _fresh_evidence() -> dict[str, Any]:
    return {
        "phase_reached": None,
        "provider_started": None,
        "usage_complete": None,
        "cost_usd": None,
        "download_events": None,
    }


def _event(record: dict, event: str, detail: dict[str, Any] | None = None) -> dict:
    entry = {"at": now_iso(), "event": event}
    if detail:
        entry["detail"] = detail
    record["events"] = [*record.get("events", []), entry][-_MAX_EVENTS:]
    return record


def _record_action(record: dict, action: str, idempotency_key: str) -> bool:
    """Append an action receipt. Returns False when this exact receipt was
    already recorded (caller then replays idempotently without re-applying)."""
    for entry in record.get("actions", []):
        if entry.get("action") == action and entry.get("idempotency_key") == idempotency_key:
            return False
    record["actions"] = [
        *record.get("actions", []),
        {"at": now_iso(), "action": action, "idempotency_key": idempotency_key},
    ][-_MAX_ACTIONS:]
    return True


def run_job(
    store: JobStore,
    owner_job_id: str,
    *,
    config_path: Path | None,
    timeout_seconds: float,
) -> tuple[dict, bool]:
    """Execute one queued job. Returns (record, executed).

    ``executed=False`` means the call was an idempotent no-op: the job was
    already terminal and the durable record is returned untouched. The lock
    is held for the whole engine call so concurrent runs serialize.
    """
    lock = store.acquire_lock(owner_job_id, timeout_seconds=10.0)
    try:
        record = store.load(owner_job_id)
        if record is None:
            raise FFJobError(f"unknown owner_job_id: {owner_job_id}", code="request_error")
        status = record.get("status")
        if status in {"succeeded", "failed", "cancelled"}:
            return record, False
        if status == "running":
            raise FFJobError(
                f"job {owner_job_id} is already running in another process",
                code="request_error",
            )
        if status == "unknown":
            raise FFJobError(
                "job state is unknown; reconcile is the only allowed action",
                code="request_error",
            )
        record["attempts"] = record.get("attempts", 0) + 1
        record["status"] = "running"
        record["status_known"] = True
        record["started_at"] = record.get("started_at") or now_iso()
        record["run_deadline_at"] = _iso_deadline(timeout_seconds)
        record["owner_pid"] = os.getpid()
        record["heartbeat_at"] = now_iso()
        record["provider_phase_reached"] = False
        spend_intent = job_spend_intent(record["kind"], record["request"])
        record["cost"], record["cost_state"] = cost_for_pending(spend_intent, "running")
        record["spend_evidence"] = _fresh_evidence()
        _event(record, "run_started", {
            "pid": record["owner_pid"],
            "timeout_seconds": timeout_seconds,
        })
        store.append_log(owner_job_id, {"event": "run_started", "pid": record["owner_pid"]})
        record = store.write_locked(record)
        return (
            _execute(store, record, config_path=config_path, timeout_seconds=timeout_seconds),
            True,
        )
    finally:
        lock.release()


def _execute(
    store: JobStore,
    record: dict,
    *,
    config_path: Path | None,
    timeout_seconds: float,
) -> dict:
    owner_job_id = record["owner_job_id"]
    stats: dict[str, int] = {"calls": 0, "downloads": 0}
    try:
        if record["kind"] == "filing.acquire":
            envelope, stats = _run_filing_engine(
                record["request"], config_path=config_path,
                timeout_seconds=timeout_seconds, stats=stats,
            )
        else:
            envelope, stats = _run_statements_engine(
                record["request"], config_path=config_path, timeout_seconds=timeout_seconds,
            )
    except FilingFetchError as exc:
        return _land_terminal(
            store, record, stats=stats, observation=_observation_of(exc),
            error=error_view_from_exception(exc, owner_job_id),
        )
    except Exception as exc:  # noqa: BLE001 - an honest terminal failure envelope
        error = {
            "code": "fatal",
            "message": f"{type(exc).__name__}: {exc}",
            "owner": "filing-fetch",
            "retryable": False,
            "next_actions": ["reconcile"],
            "correlation_id": owner_job_id,
        }
        return _land_terminal(store, record, stats=stats, observation=None, error=error)
    result = build_result_view(record["kind"], envelope, stats)
    return _land_terminal(
        store, record, stats=stats,
        observation=_envelope_observation(record["kind"], record["request"], envelope),
        error=None, result=result, envelope=envelope,
    )


def _run_filing_engine(
    request: dict[str, Any],
    *,
    config_path: Path | None,
    timeout_seconds: float,
    stats: dict[str, int],
) -> tuple[dict[str, Any], dict[str, int]]:
    """One bounded v2 filing resolution through the unchanged public engine."""
    from fetch_filing import complete_filing_v2, filing_operation_deadline, resolve_filing

    deadline = filing_operation_deadline(request, timeout_seconds=timeout_seconds)
    resolved_context: dict = {}
    handle = resolve_filing(
        request=request,
        config_path=config_path,
        context_out=resolved_context,
        timeout_seconds=timeout_seconds,
        stats=stats,
        source_ref_v2=True,
        deadline=deadline,
    )
    envelope = complete_filing_v2(
        request=request, handle=handle, config_path=config_path, deadline=deadline, stats=stats,
        request_context=resolved_context.get("context"),
    )
    stats["downloads"] = envelope.get("downloads", stats["downloads"])
    return envelope, stats


def _run_statements_engine(
    request: dict[str, Any],
    *,
    config_path: Path | None,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, int]]:
    """One bounded financial-statements request through the unchanged engine."""
    from ff_financial_statements import fetch_statements

    envelope = fetch_statements(
        config_path=config_path, request=request, timeout_seconds=timeout_seconds,
    )
    # One bounded company-wiki child per request; the provider's own traffic
    # is accounted inside the envelope's usage block, not here.
    stats = {"calls": 1, "downloads": 0}
    return envelope, stats


def _envelope_observation(
    kind: str, request: dict[str, Any], envelope: dict[str, Any],
) -> dict[str, Any] | None:
    """Use producer usage for each stage that can spend."""
    if kind == "statements.acquire":
        usage = envelope.get("usage")
        if not isinstance(usage, dict):
            return None
        requests = usage.get("http_requests")
        if type(requests) is not int:
            return None
        return {
            "provider_started": requests > 0,
            "usage_complete": True,
            "cost_usd": usage.get("cost_usd"),
        }

    filing = envelope.get("filing") or {}
    observation = (envelope.get("acquisition_observation") or filing.get("acquisition_failure")
                   or filing.get("upstream_cause"))
    if request["filing_intent"] == "reuse_only":
        observation = _NO_PROVIDER
    if not companion_may_acquire(request):
        return observation

    transcript = envelope.get("transcript") or {}
    if transcript.get("status") in {
        "not_requested", "not_applicable", "not_run", "period_unresolved",
        "reused", "unknown_publication", "contract_pending", "ambiguous",
    } or (transcript.get("provider_started") is False
          and transcript.get("provider_usage_complete") is True):
        return observation

    # The transcript result exposes usage but not a complete fee account.
    # A known filing cost cannot stand in for the combined job cost.
    started = ((observation or {}).get("provider_started") is True
               or transcript.get("provider_started") is True)
    return {"provider_started": True if started else None, "usage_complete": False}


def _observation_of(exc: FilingFetchError) -> dict[str, Any] | None:
    if exc.acquisition_observation is not None or exc.acquisition_failure is not None:
        return exc.acquisition_observation or exc.acquisition_failure
    cause = exc.upstream_cause or {}
    if cause.get("operation", exc.stage) in {"identify", "query", "local_prepare", "resolve"}:
        return _NO_PROVIDER
    return exc.upstream_cause


def terminal_cost(intent: str, evidence: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Project the recorded spend evidence of a finished engine run."""
    return build_cost_view(intent, evidence)


def _land_terminal(
    store: JobStore,
    record: dict,
    *,
    stats: dict[str, int],
    observation: dict[str, Any] | None,
    error: dict[str, Any] | None,
    result: dict[str, Any] | None = None,
    envelope: dict[str, Any] | None = None,
) -> dict:
    """Write the engine outcome as one durable terminal transition.

    Success and business failure both count as a completed engine execution;
    an unexpected crash leaves execution_count untouched so the audit trail
    distinguishes "engine answered" from "run process died".
    """
    spend_intent = job_spend_intent(record["kind"], record["request"])
    downloads = stats.get("downloads", 0)
    observation = _NO_PROVIDER if spend_intent == "reuse_only" else (observation or {})
    started = observation.get("provider_started")
    complete = observation.get("usage_complete")
    receipt_complete = type(started) is bool and complete is True
    phase_reached = True if started is True or downloads > 0 else (
        False if receipt_complete else None
    )
    evidence = {
        "phase_reached": phase_reached,
        "provider_started": started,
        "usage_complete": complete,
        "cost_usd": observation.get("cost_usd"),
        "download_events": downloads if receipt_complete or downloads > 0 else None,
    }
    cost, cost_state = terminal_cost(spend_intent, evidence)
    unknown = error is not None and spend_intent != "reuse_only" and not receipt_complete
    record["status"] = "unknown" if unknown else ("succeeded" if error is None else "failed")
    record["status_known"] = not unknown
    if error is not None and unknown:
        error = dict(error, retryable=False, next_actions=["reconcile"])
    record["spend_evidence"] = evidence
    record["provider_phase_reached"] = phase_reached is True
    record["cost"] = cost
    record["cost_state"] = cost_state
    record["error"] = error
    record["result"] = result
    record["execution_count"] = record.get("execution_count", 0) + 1
    record["heartbeat_at"] = now_iso()
    outcome = envelope.get("status") if isinstance(envelope, dict) else None
    _event(record, "run_finished", {"status": record["status"], "engine_status": outcome})
    store.append_log(record["owner_job_id"], {
        "event": "run_finished",
        "status": record["status"],
        "engine_status": outcome,
        "calls": stats.get("calls", 0),
        "downloads": downloads,
    })
    record["owner_pid"] = None
    return store.write_locked(record)


# ---------------------------------------------------------------------------
# Actions (G-m8-FF-02 / G-m8-FF-04)
# ---------------------------------------------------------------------------


def act(
    store: JobStore,
    owner_job_id: str,
    *,
    action: str,
    idempotency_key: str,
    config_path: Path | None = None,
    timeout_seconds: float = 300.0,
) -> tuple[dict, bool]:
    """Apply one declared action; returns (record, replayed).

    ``replayed=True`` means this (action, idempotency_key) receipt was already
    applied and the current durable state is returned without re-applying.
    """
    validate_action(action)
    if action == "reconcile":
        return reconcile(store, owner_job_id, idempotency_key=idempotency_key,
                         config_path=config_path, timeout_seconds=timeout_seconds)
    lock = store.acquire_lock(owner_job_id, timeout_seconds=5.0)
    try:
        record = store.load(owner_job_id)
        if record is None:
            raise FFJobError(f"unknown owner_job_id: {owner_job_id}", code="request_error")
        for entry in record.get("actions", []):
            if entry.get("action") == action and entry.get("idempotency_key") == idempotency_key:
                return record, True
        if action == "cancel":
            return _act_cancel(store, record, idempotency_key), False
        return _act_retry(store, record, idempotency_key), False
    finally:
        lock.release()


def _act_cancel(store: JobStore, record: dict, idempotency_key: str) -> dict:
    status = record.get("status")
    if status == "unknown":
        raise FFJobError("unknown_requires_reconcile", code="request_error")
    if status != "queued":
        raise FFJobError(
            "cancel is only offered while queued; the engine is one bounded "
            "subprocess call with no interruption point",
            code="request_error",
        )
    record["status"] = "cancelled"
    record["status_known"] = True
    spend_intent = job_spend_intent(record["kind"], record["request"])
    evidence = {**_NO_PROVIDER, "download_events": 0}
    cost, cost_state = terminal_cost(spend_intent, evidence)
    record["spend_evidence"] = evidence
    record["cost"] = cost
    record["cost_state"] = cost_state
    _record_action(record, "cancel", idempotency_key)
    _event(record, "cancelled", {"idempotency_key": idempotency_key})
    store.append_log(record["owner_job_id"], {"event": "cancelled"})
    record["owner_pid"] = None
    return store.write_locked(record)


def _act_retry(store: JobStore, record: dict, idempotency_key: str) -> dict:
    status = record.get("status")
    if status == "unknown":
        raise FFJobError("unknown_requires_reconcile", code="request_error")
    if status not in {"failed", "cancelled"}:
        raise FFJobError("retry is only offered on failed or cancelled jobs", code="request_error")
    if not retry_eligible(record):
        raise FFJobError(
            "retry refused: recorded spend evidence does not prove a re-run "
            "is free of prior spend",
            code="request_error",
        )
    record["status"] = "queued"
    record["status_known"] = True
    record["error"] = None
    record["cost"] = None
    record["cost_state"] = "not_applicable"
    record["spend_evidence"] = _fresh_evidence()
    record["provider_phase_reached"] = False
    record["owner_pid"] = None
    record["run_deadline_at"] = None
    _record_action(record, "retry", idempotency_key)
    _event(record, "retry_queued", {"idempotency_key": idempotency_key})
    store.append_log(record["owner_job_id"], {"event": "retry_queued"})
    return store.write_locked(record)


def reconcile(
    store: JobStore,
    owner_job_id: str,
    *,
    idempotency_key: str,
    config_path: Path | None,
    timeout_seconds: float,
) -> tuple[dict, bool]:
    """Re-check the owner's actual state for an unknown job (never re-sends).

    The read-only reuse path of the same engine answers whether the filing /
    statements data now exists in the durable company-wiki catalog; the answer
    lands as succeeded/failed with the prior spend evidence carried forward.
    """
    record, _ = store.load_checked(owner_job_id, fix=True)
    # The action receipt is checked BEFORE the status gate: a replayed
    # reconcile must return the landed state, not a refusal.
    for entry in record.get("actions", []):
        if entry.get("action") == "reconcile" and entry.get("idempotency_key") == idempotency_key:
            return record, True
    if record.get("status") != "unknown":
        raise FFJobError(
            "reconcile is only offered on jobs whose status is unknown",
            code="request_error",
        )
    lock = store.acquire_lock(owner_job_id, timeout_seconds=10.0)
    try:
        current = store.load(owner_job_id)
        if current is None:
            raise FFJobError(f"unknown owner_job_id: {owner_job_id}", code="request_error")
        if current.get("status") != "unknown":
            # Another process reconciled first: replay idempotently.
            return current, True
        for entry in current.get("actions", []):
            if entry.get("action") == "reconcile" and entry.get("idempotency_key") == idempotency_key:
                return current, True
        status, error, result = _reconcile_query(
            current["kind"], current["request"], owner_job_id=owner_job_id,
            config_path=config_path, timeout_seconds=timeout_seconds,
        )
        current["status"] = status
        current["status_known"] = True
        current["error"] = error
        current["result"] = result
        if result is not None:
            current["derived_by"] = "reconcile_read_only"
        # Cost stays with the lost run's evidence: a reconcile query is
        # read-only and cannot certify the interrupted run's spend.
        _record_action(current, "reconcile", idempotency_key)
        _event(current, "reconciled", {"landed_status": status})
        store.append_log(owner_job_id, {"event": "reconciled", "landed_status": status})
        current["owner_pid"] = None
        return store.write_locked(current), False
    finally:
        lock.release()


def _reconcile_query(
    kind: str,
    request: dict[str, Any],
    *,
    owner_job_id: str,
    config_path: Path | None,
    timeout_seconds: float,
) -> tuple[str, dict[str, Any] | None, dict[str, Any]]:
    """One read-only owner query; returns (status, error, result)."""
    stats: dict[str, int] = {"calls": 0, "downloads": 0}
    try:
        if kind == "filing.acquire":
            envelope, stats = _reconcile_filing(request, config_path=config_path,
                                                timeout_seconds=timeout_seconds, stats=stats)
            status = "succeeded" if envelope.get("status") == "source_candidate" else "failed"
            code = "not_found" if envelope.get("status") == "gap" else "upstream_error"
            reason = (envelope.get("filing") or {}).get("reason") or envelope.get("status")
        else:
            envelope, stats = _reconcile_statements(request, config_path=config_path,
                                                    timeout_seconds=timeout_seconds)
            landed = envelope.get("status")
            status = "succeeded" if landed in {"complete", "partial"} else "failed"
            code = "not_found" if landed == "not_found" else "upstream_error"
            reason = landed
    except FilingFetchError as exc:
        # Even the read-only check failed: the job stays unknown, fail closed.
        raise FFJobError(f"reconcile query failed: {exc}", code=exc.code) from exc
    error = None
    if status == "failed":
        error = {
            "code": code,
            "message": f"reconcile read-only query confirms absence: {reason}",
            "owner": "filing-fetch",
            "retryable": code == "upstream_error",
            "next_actions": (["correct_scope_and_resubmit"] if code == "not_found"
                             else ["retry_then_reconcile"]),
            "correlation_id": owner_job_id,
        }
    result = build_result_view(kind, envelope, stats)
    return status, error, result


def _reconcile_filing(
    request: dict[str, Any],
    *,
    config_path: Path | None,
    timeout_seconds: float,
    stats: dict[str, int],
) -> tuple[dict[str, Any], dict[str, int]]:
    from fetch_filing import resolve_filing
    from ff_v2_envelope import success_envelope

    read_only = {key: value for key, value in request.items()
                 if key not in {"acquisition_limits", "companion_transcript"}}
    read_only["filing_intent"] = "reuse_only"
    handle = resolve_filing(
        request=read_only, config_path=config_path, timeout_seconds=timeout_seconds,
        stats=stats, source_ref_v2=True,
    )
    envelope = success_envelope(
        read_only, handle, {"status": "not_requested", "retryable": False}, stats,
    )
    return envelope, stats


def _reconcile_statements(
    request: dict[str, Any],
    *,
    config_path: Path | None,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, int]]:
    from ff_financial_statements import fetch_statements

    read_only = {key: value for key, value in request.items()
                 if key not in {"acquisition_limits", "continuation"}}
    read_only["intent"] = "reuse_only"
    envelope = fetch_statements(
        config_path=config_path, request=read_only, timeout_seconds=timeout_seconds,
    )
    stats = {"calls": 1, "downloads": 0}
    return envelope, stats


__all__ = ["act", "reconcile", "run_job"]
