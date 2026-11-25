"""Optional feedback from the owner of a durable FF attempt."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

from ff_runtime_feedback import (
    DEFAULT_JOBS_DIR, DIR_ENV, OUT_ENV, RULE_CODES, identity, parse_arguments, publish,
    record_runtime_failure, terminal_was_offered,
)

OUTCOME = "job-outcome"


def _refresh_identity(run, step):
    rid = run["run_id"]
    original = run.get("feedback_identity") or {}
    return {
        "schema_version": "feedback-observation/1", "owner": "filing-fetch",
        "run_id": original.get("run_id", rid), "attempt_id": original.get("attempt_id", "scheduled"),
        "step_id": step, "evidence_ref": f"ff-scheduled-refresh/1/{rid}", "version": "ff-scheduled-refresh/1",
    }


def _refresh_summary(run, jobs_dir, file):
    rid = run["run_id"]
    base = _refresh_identity(run, rid)
    if terminal_was_offered(base, jobs_dir):
        return True
    outcome = run["state"]
    rows = [dict(base, check_id="refresh-outcome", expected="completed", actual=outcome,
                 disposition="deviation" if outcome == "partial" else "expected")]
    usage = run.get("usage", {})
    snapshots = [value for key in ("reading_runs", "acquisition_jobs")
                 for value in usage.get(key, {}).values()]
    if snapshots or outcome == "partial":
        known = (snapshots and all(item.get("cost_state") in {"settled", "known", "not_applicable"}
                                   for item in snapshots) and not usage.get("metadata_usage_incomplete"))
        rows.append(dict(base, check_id="refresh-usage", expected="accounted", actual="known" if known else "unknown",
                         disposition="expected" if known else "unknown"))
    return publish(rows, jobs_dir=jobs_dir, file=file, recoverable=True)


def _refresh_item(run, key, failure, jobs_dir, file):
    base = _refresh_identity(run, f"{run['run_id']}/{key}")
    if terminal_was_offered(base, jobs_dir):
        return True
    reason = failure["reason"]
    row = dict(base, check_id="refresh-item-outcome", expected="completed", actual=reason,
               issue_key=reason, disposition="deviation")
    if reason in RULE_CODES:
        row.update(disposition="expected", refusal_code=reason)
    # Historical receipts may carry only the actual stage, reason and reference.
    detail = {"schema_version": "ff-failure-detail/1", **failure}
    return publish([row], jobs_dir=jobs_dir, file=file, detail=detail, recoverable=True)


def publish_refresh_failure(run, *, jobs_dir, reason, reference, stage, error=None):
    from ff_runtime_feedback import cause_details

    reason = reason if isinstance(reason, str) and re.fullmatch(r"[a-z][a-z0-9_.-]*", reason) else "owner_failure"
    key = _digest([stage, reference, reason])
    failures = run.setdefault("failures", {})
    if key in failures:
        return
    failures[key] = {**cause_details(error, reason=reason), "stage": stage, "reference_hash": _digest(reference)}
    _refresh_item(run, key, failures[key], jobs_dir, os.environ.get(OUT_ENV))


def redeliver_refresh(store, visible=(), *, active_run=None):
    """Offer original native receipts; this path has no acquisition or reading port."""
    try:
        waiting, runs = store.feedback_receipts(visible)
        offered = set()
        for rid, run in runs.items():
            file = os.environ.get(OUT_ENV) if rid == active_run else None
            delivered = [_refresh_item(run, key, failure, store.root.parent, file)
                         for key, failure in (run.get("failures") or {}).items()]
            if run.get("state") in {"partial", "completed", "superseded"}:
                delivered.append(_refresh_summary(run, store.root.parent, file))
                if all(delivered) and rid in waiting:
                    offered.add(rid)
        if offered:
            store.acknowledge_feedback(offered)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        # Directory repair and later cold reads can resume. Diagnostics cannot change the slot.
        return


def publish_job_observation(record: dict, *, started: bool, jobs_dir=None, recover_only=False) -> None:
    jid, attempt = record["owner_job_id"], record["attempts"]
    base = identity(jid, attempt, f"{jid}/{attempt}", f"ff-job/1/{jid}", "ff-job/1")
    # Bind the native original even if a new, independently labelled cold process discovers the loss.
    base.update(record.get("feedback_identity", {}))
    statements = record.get("statement_feedback")
    recoverable = record["status"] in {"failed", "unknown"} or bool(statements)
    if recover_only and (not recoverable or terminal_was_offered(base, jobs_dir)):
        return
    start = [dict(base, check_id="action-started", expected="started", actual="started",
                  disposition="expected", terminal_check_id=OUTCOME)]
    file = None if recover_only else os.environ.get(OUT_ENV)
    if started:
        publish(start, file=file, jobs_dir=jobs_dir)
        return
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
    publish(rows, file=file, jobs_dir=jobs_dir, context=start, detail=statements or record.get("failure_detail"),
            detail_for_all=bool(statements))


def _digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def _record_report(root: Path, request: dict) -> dict:
    key = request["action_id"]
    payload = request.get("payload")
    if (request.get("schema_version"), request.get("owner"), request.get("kind"), request.get("method")) != (
        "feedback-action/1", "filing-fetch", "report", "submit",
    ):
        raise ValueError("not a filing-fetch report")
    names = ("occurrence_id", "original_occurrence_id", "origin_owner", "issue_ref", "fixed_version", "evidence_ref")
    if (not isinstance(payload, dict) or payload.get("verdict") not in ("verified", "regressed")
            or any(not isinstance(payload.get(name), str) or not payload[name].strip() for name in names)):
        raise ValueError("not a bound consumer replay result")
    scope = [payload["occurrence_id"], "filing-fetch", payload["issue_ref"], payload["fixed_version"], payload["verdict"]]
    if key != _digest(["report", "filing-fetch", *scope]) or request.get("request_digest") != _digest(
        ["filing-fetch", "report", key, payload],
    ):
        raise ValueError("report identity mismatch")
    root.mkdir(parents=True, exist_ok=True)
    path = root / (key + ".json")
    data = (json.dumps(request, ensure_ascii=True, sort_keys=True) + "\n").encode("ascii")
    with tempfile.NamedTemporaryFile(dir=root, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        try:
            if os.name == "nt":
                os.rename(temporary, path)
            else:
                os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError("conflicting report for the same action") from None
    finally:
        temporary.unlink(missing_ok=True)
    return {"recorded": True}


def _job_observation(request: dict) -> dict:
    owner, kind = "filing-fetch", "reconcile"
    if not isinstance(request, dict) or (
        request.get("schema_version"), request.get("owner"), request.get("kind"), request.get("method")
    ) != ("feedback-action/1", owner, kind, "lookup"):
        raise ValueError("not a filing-fetch lookup")
    payload = request.get("payload")
    observation = payload.get("observation") if isinstance(payload, dict) else None
    if not isinstance(observation, dict):
        raise ValueError("missing job observation")
    origin = observation.get("origin_owner", observation.get("owner"))
    scope = [observation.get(key) for key in ("run_id", "attempt_id", "step_id", "check_id")]
    identity = [observation.get("owner"), origin, *scope]
    key, occurrence = request.get("action_id"), payload.get("occurrence_id")
    if (origin != owner or not all(isinstance(part, str) and part.strip() for part in identity)
            or occurrence != _digest(identity) or key != _digest([kind, owner, occurrence])
            or request.get("request_digest") != _digest([owner, kind, key, payload])):
        raise ValueError("job observation identity mismatch")
    return observation


def _lookup_job(args: argparse.Namespace, request: dict) -> dict:
    from ff_job_contracts import FFJobError, project_job_cost, validate_owner_job_id
    from ff_job_runner import reconcile
    from ff_job_store import JobStore

    observation = _job_observation(request)
    reference = observation.get("evidence_ref")
    if not isinstance(reference, str) or not reference.startswith("ff-job/1/"):
        return {"state": "unknown"}
    try:
        job_id = validate_owner_job_id(reference.removeprefix("ff-job/1/"))
        store = JobStore(args.jobs_dir.expanduser().resolve(), initialize=False)
        job = store.load(job_id)
        if job is None or job.get("owner_job_id") != job_id:
            return {"state": "unknown"}
        attempt = job.get("attempts")
        if type(attempt) is not int or attempt <= 0 or observation["step_id"] != f"{job_id}/{attempt}":
            return {"state": "unknown"}

        lost = store.run_lost(job) is not None or job.get("status") == "unknown"
        if lost and args.config is not None:
            job, _ = reconcile(
                store, job_id, idempotency_key=f"feedback-reconcile/{job_id}/{attempt}",
                config_path=args.config.expanduser().resolve(), timeout_seconds=args.timeout_seconds,
                expected_attempt=attempt,
            )
            lost = job.get("status") == "unknown"
        if job.get("status") == "running" and not lost:
            return {"state": "pending"}
        if lost or job.get("status_known") is not True or job.get("status") not in ("succeeded", "failed", "cancelled"):
            return {"state": "unknown"}
        cost, state = project_job_cost(job)
    except (FFJobError, OSError):
        return {"state": "unknown"}

    evidence = job.get("spend_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    usage = {key: evidence[key] if type(evidence.get(key)) is bool else None
             for key in ("provider_started", "usage_complete")}
    downloads = evidence.get("download_events")
    usage["download_events"] = downloads if type(downloads) is int and downloads >= 0 else None
    known = state in ("known", "not_applicable")
    return {"state": "done", "result": {
        "status": "known" if known else "cost_unknown", "job_status": job["status"],
        "cost_state": state if known else "unknown", "cost": cost if known else None,
        "evidence_ref": reference, "owner_job_id": job_id, "native_attempt": attempt,
        "execution_count": job.get("execution_count", 0),
        "recorded_usage": usage,
        "new_provider_requests": 0, "new_downloads": 0, "new_cost_usd": "0.00",
    }}


_REFRESH_REFERENCE = "ff-scheduled-refresh/1/"
_SLOT_RUN = re.compile(r"sr-\d{8}T\d{6}Z-[0-9a-f]{10}")
_FINISHED_REFRESH = {"partial", "completed", "superseded"}
_ACCOUNTED = {"settled", "known", "not_applicable"}


def _slot_binding(run: dict, observation: dict) -> str | None:
    """Return "" for the slot, a recorded failure key for one sub-item, or None for any other original."""
    identity = run.get("feedback_identity")
    original = identity if isinstance(identity, dict) else {}
    if (observation["run_id"] != original.get("run_id", run["run_id"])
            or observation["attempt_id"] != original.get("attempt_id", "scheduled")):
        return None
    step = observation["step_id"]
    if step == run["run_id"]:
        return ""
    item = step.removeprefix(run["run_id"] + "/")
    return item if item != step and item and "/" not in item else None


def _dispatched_job(store, owner_id: object, run_id: str) -> tuple[str, dict] | None:
    """Bind one recorded acquisition job to a scheduled dispatch of this slot."""
    from ff_job_contracts import FFJobError

    if not isinstance(owner_id, str):
        return None
    try:
        job = store.load(owner_id)
    except (FFJobError, OSError):
        return None
    if not isinstance(job, dict) or job.get("owner_job_id") != owner_id:
        return None
    actions, command = job.get("actions"), job.get("command_id")
    if command == run_id:
        dispatched = "original"
    elif isinstance(actions, list) and any(
        isinstance(action, dict) and action.get("action") == "retry"
        and action.get("idempotency_key") == f"{run_id}-retry-{owner_id}" for action in actions
    ):
        dispatched = "retry"
    elif isinstance(command, str) and _SLOT_RUN.fullmatch(command):
        # Another slot's job reused as-is; its cost was accounted at that slot and is only read here.
        dispatched = "reused"
    else:
        return None
    return dispatched, job


def _refresh_usage(run: dict, jobs_dir: Path) -> tuple[bool, list[dict]]:
    """Account a slot from the sub-calls it recorded itself; one unknown or unbound call keeps it unknown."""
    from ff_job_contracts import FFJobError, project_job_cost
    from ff_job_store import JobStore

    usage = run.get("usage")
    if not isinstance(usage, dict):
        return False, []
    store = JobStore(jobs_dir, initialize=False)
    items: list[dict] = []
    known = True
    for group in ("acquisition_jobs", "reading_runs"):
        snapshots = usage.get(group, {})
        if not isinstance(snapshots, dict):
            return False, items
        for owner_id, snapshot in snapshots.items():
            recorded = snapshot.get("cost_state") if isinstance(snapshot, dict) else None
            item: dict = {"kind": group[:-1], "id": owner_id,
                    "cost_state": recorded if recorded in _ACCOUNTED else "unknown"}
            if group == "acquisition_jobs":
                bound = _dispatched_job(store, owner_id, run["run_id"])
                item["dispatch"] = "unbound" if bound is None else bound[0]
                if bound is None:
                    item["cost_state"] = None
                else:
                    job = bound[1]
                    evidence = job.get("spend_evidence")
                    evidence = evidence if isinstance(evidence, dict) else {}
                    status = job.get("status")
                    item["job_status"] = status if job.get("status_known") is True and isinstance(status, str) else "unknown"
                    item["recorded_usage"] = {key: evidence[key] if type(evidence.get(key)) is bool else None
                                              for key in ("provider_started", "usage_complete")}
                    downloads = evidence.get("download_events")
                    item["recorded_usage"]["download_events"] = (
                        downloads if type(downloads) is int and downloads >= 0 else None)
                    if item["cost_state"] != "unknown":
                        # Native job rules decide; a zero copied into the slot cannot settle a later unknown.
                        try:
                            native = project_job_cost(job)[1]
                        except FFJobError:
                            native = None
                        item["cost_state"] = native if native in ("known", "not_applicable") else "unknown"
            known &= item["cost_state"] in _ACCOUNTED
            items.append(item)
    # A job dispatched by this very slot but missing from its usage is an unaccounted sub-item.
    # The reverse check is bound by the original run identity, never by date or company.
    listed = usage.get("acquisition_jobs")
    listed = set(listed) if isinstance(listed, dict) else set()
    for job_id in store.iter_job_ids():
        job = store.load(job_id)
        if not isinstance(job, dict) or job.get("owner_job_id") != job_id or job_id in listed:
            continue
        actions = job.get("actions")
        attached = job.get("command_id") == run["run_id"] or (
            isinstance(actions, list) and any(
                isinstance(action, dict) and action.get("action") == "retry"
                and action.get("idempotency_key") == f"{run['run_id']}-retry-{job_id}"
                for action in actions
            )
        )
        if attached:
            items.append({"kind": "acquisition_job", "id": job_id, "dispatch": "unlisted", "cost_state": None})
            known = False
    # The same native rule as the offered refresh-usage row, plus every dispatched call accounted.
    if not items or usage.get("metadata_usage_incomplete"):
        known = False
    return known, items


def _refresh_outcome(run: dict, counts: dict, failures: dict, item: str) -> str | None:
    """Native ``partial`` has no cross-repository value: report the proven end of the asked sub-item."""
    if item:
        failure = failures.get(item)
        reason = failure.get("reason") if isinstance(failure, dict) else None
        return "failed" if isinstance(reason, str) and reason else None
    if counts["pending"] or run.get("active_action") is not None:
        # A sub-item was never settled; the slot's zero elsewhere cannot stand in for it.
        return "unconfirmed"
    if run["state"] == "superseded":
        return "cancelled"
    if run["state"] == "completed":
        return "failed" if counts["failed"] or failures else "succeeded"
    return "failed" if counts["failed"] or failures else "unconfirmed"


def _lookup_refresh(args: argparse.Namespace, observation: dict) -> dict:
    """Cold-read one original scheduled slot. A readable receipt is evidence, never business success."""
    from ff_job_contracts import FFJobError
    from ff_refresh_store import COUNTS, RefreshStateError, RefreshStore

    run_id = observation["evidence_ref"].removeprefix(_REFRESH_REFERENCE)
    if not _SLOT_RUN.fullmatch(run_id):
        return {"state": "unknown"}
    try:
        store = RefreshStore(args.jobs_dir.expanduser().resolve())
        run = store.receipt(run_id)
        if run is None:
            return {"state": "pending"} if store.current(run_id) is not None else {"state": "unknown"}
        item = _slot_binding(run, observation)
        raw_counts = run.get("counts")
        failures = run.get("failures")
        failures = failures if isinstance(failures, dict) else {}
        if (item is None or run.get("state") not in _FINISHED_REFRESH or not isinstance(raw_counts, dict)
                or any(type(raw_counts.get(name)) is not int or raw_counts[name] < 0 for name in COUNTS)):
            return {"state": "unknown"}
        counts = {name: raw_counts[name] for name in COUNTS}
        known, items = _refresh_usage(run, args.jobs_dir.expanduser().resolve())
        outcome = _refresh_outcome(run, counts, failures, item)
        if outcome is None:
            return {"state": "unknown"}
        known &= counts["pending"] == 0
        codes = run.get("reason_codes")
        result = {
            "status": "known" if known else "cost_unknown", "job_status": outcome,
            "cost_state": ("not_applicable" if all(row["cost_state"] == "not_applicable" for row in items)
                           else "known") if known else "unknown",
            "evidence_ref": observation["evidence_ref"], "native_attempt": observation["attempt_id"],
            "native_status": run["state"], "counts": counts, "items": items,
            "reason_codes": [code for code in codes if isinstance(code, str)] if isinstance(codes, list) else [],
        }
        if item:
            stage = failures[item].get("stage")
            result["item"] = {"key": item, "reason": failures[item]["reason"],
                              "stage": stage if isinstance(stage, str) else None}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, FFJobError, RefreshStateError):
        # An unreadable original stays unknown; nothing here repairs it or starts work.
        return {"state": "unknown"}
    return {"state": "done", "result": result}


def _lookup(args: argparse.Namespace, request: dict) -> dict:
    observation = _job_observation(request)
    reference = observation.get("evidence_ref")
    if isinstance(reference, str) and reference.startswith(_REFRESH_REFERENCE):
        return _lookup_refresh(args, observation)
    return _lookup_job(args, request)


def main() -> int:
    parser = argparse.ArgumentParser(description="Filing-fetch owner feedback receipts")
    parser.add_argument("--reports-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    diagnostic = sub.add_parser("get-diagnostic", help="read the original sanitized exception and source identity")
    diagnostic.add_argument("reference")
    diagnostic.add_argument("--observations-dir", type=Path)
    diagnostic.add_argument("--jobs-dir", type=Path, default=DEFAULT_JOBS_DIR)
    sub.add_parser("report")
    sub.add_parser("get-report").add_argument("action_id")
    lookup = sub.add_parser("reconcile", help="query the original job or scheduled slot without reacquisition")
    lookup.add_argument("--jobs-dir", type=Path, required=True)
    lookup.add_argument("--config", type=Path, help="owner configuration for catalog-only recovery of a lost job")
    lookup.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parse_arguments(parser, None, "feedback", local_only=True)
    if args.command == "get-diagnostic":
        match = re.fullmatch(r"ff-diagnostic/1/(feedback-[a-f0-9]{32})", args.reference)
        if not match:
            parser.error("invalid diagnostic reference")
        root = args.observations_dir or (Path(os.environ[DIR_ENV]) if os.environ.get(DIR_ENV) else None)
        for directory in dict.fromkeys([root, args.jobs_dir / "observations"]):
            if directory is None:
                continue
            try:
                value = json.loads((directory / (match[1] + ".cause.json")).read_bytes())
            except FileNotFoundError:
                continue
            except (OSError, ValueError) as error:
                record_runtime_failure("feedback-get-diagnostic", "diagnostic_unreadable", error, jobs_dir=args.jobs_dir)
                break
            print(json.dumps(value, ensure_ascii=True))
            return 0
        print(json.dumps({"status": "unavailable"}))
        return 1
    if args.command == "reconcile":
        if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
            parser.error("reconcile timeout must be finite and positive")
        try:
            reply = _lookup(args, json.load(sys.stdin))
        except (OSError, ValueError, RecursionError) as error:
            record_runtime_failure("feedback-reconcile", "reconcile_failed", error, jobs_dir=args.jobs_dir)
            print(json.dumps({"error": type(error).__name__}))
            return 1
        print(json.dumps(reply, ensure_ascii=True))
        return 0
    if args.reports_dir is None:
        parser.error("--reports-dir is required for reports")
    if args.command == "report":
        try:
            request = json.load(sys.stdin)
        except (OSError, ValueError, RecursionError) as error:
            record_runtime_failure("feedback-report", "invalid_report_request", error)
            raise
        key = request.get("action_id") if isinstance(request, dict) else None
    else:
        key = args.action_id
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
        parser.error("invalid feedback action id")
    try:
        value = ({"result": _record_report(args.reports_dir, request)} if args.command == "report"
                 else {"report": json.loads((args.reports_dir / (key + ".json")).read_bytes())})
    except (OSError, ValueError) as error:
        if args.command != "get-report" or not isinstance(error, FileNotFoundError):
            record_runtime_failure("feedback-" + args.command, "report_io_failed", error)
        print(json.dumps({"error": type(error).__name__}))
        return 1
    print(json.dumps(value, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
