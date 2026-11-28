"""Observe durable job transitions outside the authoritative store."""

from __future__ import annotations

import os

from ff_job_contracts import FFJobError
from ff_job_store import JobStore
from ff_runtime_feedback import (
    OUT_ENV, RULE_CODES, feedback_wire, publish, record_runtime_failure, retained_identity, start_was_offered,
    terminal_was_offered,
    warn_diagnostic_unavailable,
)
from ff_runtime_log import execution_view


OUTCOME = "job-outcome"


def _job_identity(record):
    jid, attempt = record["owner_job_id"], record["attempts"]
    return retained_identity(jid, attempt, f"{jid}/{attempt}", f"ff-job/1/{jid}", "ff-job/1",
                             stored=record.get("feedback_identity"))


def append_job_diagnostic(store: JobStore, record: dict, entry: dict) -> None:
    base = feedback_wire(_job_identity(record))
    execution = execution_view(record.get("diagnostic_execution"))
    identity = {key: base[key] for key in ("run_id", "attempt_id", "step_id", "evidence_ref")}
    try:
        store.append_log(record["owner_job_id"], {**identity, **(execution or {}), **entry})
    except (OSError, ValueError) as error:
        base["step_id"] += "/job-log/" + entry["event"]
        if record_runtime_failure("job-log", "job_log_unavailable", error,
                                  jobs_dir=store.jobs_dir, base=base, execution=execution):
            warn_diagnostic_unavailable(f"job log {record['owner_job_id']}", error, scope=base)


def load_observed_job(store: JobStore, owner_job_id: str, *, recover_terminal: bool = False) -> dict:
    record, changed = store.load_checked(owner_job_id, fix=True)
    if changed or (recover_terminal and record.get("attempts")):
        publish_job_observation(record, started=False, jobs_dir=store.jobs_dir, recover_only=not changed)
    return record


def publish_job_observation(record: dict, *, started: bool, jobs_dir=None, recover_only=False) -> bool | None:
    base = _job_identity(record)
    statements = record.get("statement_feedback")
    recoverable = (
        record["status"] in {"failed", "unknown"} or bool(statements)
        or record["status"] == "succeeded" and record.get("feedback_delivery_tracked") is True
    )
    detail = statements or record.get("failure_detail")
    start = [dict(base, check_id="action-started", expected="started", actual="started",
                  disposition="expected", terminal_check_id=OUTCOME)]
    file = None if recover_only else os.environ.get(OUT_ENV)
    if started:
        if recover_only and (start_was_offered(base, jobs_dir) or terminal_was_offered(base, jobs_dir)):
            return None
        return publish(start, file=file, jobs_dir=jobs_dir, recoverable=recover_only)
    if recover_only and (not recoverable or terminal_was_offered(base, jobs_dir, require_detail=bool(detail))):
        return None
    outcome = record["status"] if record["status_known"] else "unknown"
    cost = record["cost_state"]
    error = record.get("error") or {}
    code = error.get("code")
    cause = error.get("upstream_cause") or {}
    diagnostic = record.get("failure_detail") or {}
    rule = diagnostic.get("owner_reason") or cause.get("code") or code
    refusal = rule if rule in RULE_CODES else None
    disposition = "unknown" if outcome == "unknown" else "deviation" if outcome == "failed" else "expected"
    business = dict(base, check_id=OUTCOME, expected="terminal", actual=outcome, disposition=disposition)
    rows = [business, dict(base, check_id="job-usage", expected="accounted", actual=cost,
                          disposition="unknown" if cost == "unknown" else "expected")]
    if code:
        if outcome == "unknown":
            business = dict(base, check_id="job-failure", expected="completed", actual=code, disposition="deviation")
            rows.append(business)
        business["issue_key"] = code
        if refusal:
            business.update(disposition="expected", refusal_code=refusal)
    result_status = (record.get("result") or {}).get("status")
    if statements:
        from ff_statement_feedback import statement_rows

        rows.extend(statement_rows(base, statements, summarize=True))
    elif not code and result_status in {"unavailable", "partial", "config_error", "request_error", "fatal", "upstream_error"}:
        rows.append(dict(base, check_id="job-failure", expected="completed", actual=result_status,
                         disposition="deviation", issue_key=result_status))
    return publish(rows, file=file, jobs_dir=jobs_dir, context=start, detail=detail,
                   recoverable=recoverable, detail_for_all=bool(statements),
                   execution=record.get("diagnostic_execution"))


def flush_job_observations(store: JobStore) -> list[bool]:
    """Only inspect the existing attempt and reoffer its recorded feedback."""
    results = []
    for job_id in store.iter_job_ids():
        try:
            record, _ = store.load_checked(job_id, fix=False)
            if not record.get("attempts") or record["status"] in {"queued", "cancelled"}:
                continue
            delivered = publish_job_observation(record, started=record["status"] == "running",
                                                jobs_dir=store.jobs_dir, recover_only=True)
            if delivered is not None:
                results.append(delivered)
        except (FFJobError, OSError, KeyError, TypeError, ValueError) as error:
            record_runtime_failure("feedback-flush-job", "job_receipt_unreadable", error,
                                   jobs_dir=store.jobs_dir, run_id=job_id)
            results.append(False)
    return results
