"""Optional feedback from the owner of a durable FF attempt."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from ff_job_observation import publish_job_observation as publish_job_observation
from ff_persistence import owner_io_path, read_regular_bytes
from ff_runtime_log import caller_coordinates, safe_identity
from ff_runtime_feedback import (
    DEFAULT_JOBS_DIR, OUT_ENV, RULE_CODES, FeedbackRouting, OwnerArgumentParser, observation_directories,
    cli_exit, feedback_wire, observed_cli, publish,
    read_cli_failure, read_native_diagnostic, record_runtime_failure, retained_identity, start_was_offered,
    terminal_was_offered,
)


def _refresh_identity(run, step):
    rid = run["run_id"]
    return retained_identity(rid, "scheduled", step, f"ff-scheduled-refresh/1/{rid}", "ff-scheduled-refresh/1",
                             stored=run.get("feedback_identity"))


def _refresh_summary(run, jobs_dir, file, *, routing: FeedbackRouting | None = None):
    rid = run["run_id"]
    base = _refresh_identity(run, rid)
    outcome = run["state"]
    rows = [dict(base, check_id="refresh-outcome", expected="completed", actual=outcome,
                 disposition="deviation" if outcome == "partial" else "expected")]
    if terminal_was_offered(rows[0], jobs_dir, routing=routing):
        return True
    usage = run.get("usage", {})
    snapshots = [value for key in ("reading_runs", "acquisition_jobs")
                 for value in usage.get(key, {}).values()]
    if snapshots or outcome == "partial":
        known = (snapshots and all(item.get("cost_state") in {"settled", "known", "not_applicable"}
                                   for item in snapshots) and not usage.get("metadata_usage_incomplete"))
        rows.append(dict(base, check_id="refresh-usage", expected="accounted", actual="known" if known else "unknown",
                         disposition="expected" if known else "unknown"))
    return publish(rows, jobs_dir=jobs_dir, file=file, recoverable=True, context=[_refresh_start_row(base)],
                   execution=run.get("diagnostic_execution"), routing=routing)


def _refresh_start_row(base):
    return dict(base, check_id="action-started", expected="started", actual="started",
                disposition="expected", terminal_check_id="refresh-outcome")


def _refresh_item(run, key, failure, jobs_dir, file, *, routing: FeedbackRouting | None = None):
    base = _refresh_identity(run, f"{run['run_id']}/{key}")
    detail = {"schema_version": "ff-failure-detail/1", **failure}
    reason = failure["reason"]
    row = dict(base, check_id="refresh-item-outcome", expected="completed", actual=reason,
               issue_key=reason, disposition="deviation")
    if reason in RULE_CODES:
        row.update(disposition="expected", refusal_code=reason)
    if terminal_was_offered(row, jobs_dir, detail=detail, routing=routing):
        return True
    return publish([row], jobs_dir=jobs_dir, file=file, detail=detail, recoverable=True,
                   execution=run.get("diagnostic_execution"), routing=routing)


def publish_refresh_failure(run, *, jobs_dir, reason, reference, stage, error=None):
    from ff_runtime_feedback import cause_details

    reason = reason if isinstance(reason, str) and re.fullmatch(r"[a-z][a-z0-9_.-]*", reason) else "owner_failure"
    key = _digest([stage, reference, reason])
    failures = run.setdefault("failures", {})
    if key in failures:
        return
    failures[key] = {**cause_details(error, reason=reason), "stage": stage, "reference_hash": _digest(reference)}
    _refresh_item(run, key, failures[key], jobs_dir, os.environ.get(OUT_ENV))


def redeliver_refresh(
    store, visible=(), *, active_run=None, include_retained=False, routing: FeedbackRouting | None = None,
):
    """Offer original native receipts; this path has no acquisition or reading port."""
    try:
        waiting, runs = store.feedback_receipts(visible, include_retained=include_retained)
        offered = set()
        successful = True
        for rid, run in runs.items():
            file = os.environ.get(OUT_ENV) if rid == active_run else None
            delivered = [_refresh_item(run, key, failure, store.root.parent, file, routing=routing)
                         for key, failure in (run.get("failures") or {}).items()]
            if run.get("state") in {"partial", "completed", "superseded"}:
                delivered.append(_refresh_summary(run, store.root.parent, file, routing=routing))
                if all(delivered) and rid in waiting:
                    offered.add(rid)
            elif include_retained:
                base = _refresh_identity(run, rid)
                start = _refresh_start_row(base)
                if not start_was_offered(start, store.root.parent, routing=routing):
                    delivered.append(publish([start], jobs_dir=store.root.parent,
                                             recoverable=True, routing=routing))
            successful &= all(delivered)
        if offered:
            store.acknowledge_feedback(offered)
        return successful
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        # Directory repair and later cold reads can resume. Diagnostics cannot change the slot.
        record_runtime_failure("feedback-flush-refresh", "schedule_receipt_unreadable", error,
                               jobs_dir=store.root.parent, routing=routing)
        return False


def _digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def _write_receipt_once(path: Path, data: bytes) -> bool:
    """Publish a complete owner receipt without replacing a previous decision."""
    path = owner_io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if os.name == "nt":
            os.rename(temporary, path)
        else:
            os.link(temporary, path)
    except FileExistsError:
        return False
    finally:
        temporary.unlink(missing_ok=True)
    return True


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
    path = root / (key + ".json")
    data = (json.dumps(request, ensure_ascii=True, sort_keys=True) + "\n").encode("ascii")
    if not _write_receipt_once(path, data) and owner_io_path(path).read_bytes() != data:
        raise ValueError("conflicting report for the same action")
    return {"recorded": True}


def _job_observation(request: dict, *, kind="reconcile", method="lookup") -> dict:
    owner = "filing-fetch"
    if not isinstance(request, dict) or (
        request.get("schema_version"), request.get("owner"), request.get("kind"), request.get("method")
    ) != ("feedback-action/1", owner, kind, method):
        raise ValueError("not a filing-fetch observation action")
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


def _lookup_job(args: argparse.Namespace, request: dict, *, observation=None) -> dict:
    from ff_job_contracts import FFJobError, project_job_cost, validate_owner_job_id
    from ff_job_store import JobStore

    if observation is None:
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
        original = job.get("feedback_identity")
        if isinstance(original, dict) and caller_coordinates(
            observation["run_id"], observation["attempt_id"],
        ) != caller_coordinates(original.get("run_id"), original.get("attempt_id")):
            return {"state": "unknown"}

        lost = store.run_lost(job) is not None or job.get("status") == "unknown"
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
    original = _refresh_identity(run, run["run_id"])
    if caller_coordinates(observation["run_id"], observation["attempt_id"]) != caller_coordinates(
        original["run_id"], original["attempt_id"],
    ):
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
            "evidence_ref": observation["evidence_ref"], "native_attempt": safe_identity(observation["attempt_id"]),
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
    from ff_direct_run import supports_reference, reconcile_direct_run

    observation = _job_observation(request)
    reference = observation.get("evidence_ref")
    roots = _owner_roots(args.jobs_dir)
    if supports_reference(reference):
        directories = list(dict.fromkeys(path for root in roots for path in observation_directories(root)))
        if args.observations_dir is not None:
            directories = list(dict.fromkeys([args.observations_dir, *directories]))
        return reconcile_direct_run(reference, directories, observation)
    for root in roots:
        root_args = argparse.Namespace(jobs_dir=root)
        if isinstance(reference, str) and reference.startswith(_REFRESH_REFERENCE):
            answer = _lookup_refresh(root_args, observation)
        else:
            answer = _lookup_job(root_args, request, observation=observation)
        if answer["state"] != "unknown":
            return answer
    return {"state": "unknown"}


def _owner_roots(values):
    roots = [values] if isinstance(values, Path) else values or [DEFAULT_JOBS_DIR]
    return list(dict.fromkeys(root.expanduser().resolve() for root in roots))


def _triage_original(args: argparse.Namespace, observation: dict) -> dict | None:
    reference = observation.get("evidence_ref")
    roots = _owner_roots(args.jobs_dir)
    if observation["check_id"] == "execution-outcome":
        directories = [path for root in roots for path in observation_directories(root)]
        if args.observations_dir is not None:
            directories.insert(0, args.observations_dir)
        facts = read_cli_failure(observation, dict.fromkeys(directories))
        if facts is None:
            return None
        missing = ["original_caller", "original_request"]
        if facts["invocation_usage"]["cost_state"] == "unknown":
            missing.append("original_invocation_usage")
        result = {"facts": facts, "missing_evidence": missing}
        if observation["actual"] == "request_error" or "refusal_code" in observation:
            result["gate_review"] = {
                "decision": "needs_evidence",
                "reason": "The original caller and input are absent from the retained diagnostic.",
                "evidence_ref": facts["diagnostic_ref"],
            }
        return result
    if (observation["check_id"] == "refresh-outcome" and observation.get("actual") == "partial"
            and isinstance(reference, str) and reference.startswith(_REFRESH_REFERENCE)):
        for root in roots:
            reply = _lookup_refresh(argparse.Namespace(jobs_dir=root), observation)
            facts = reply.get("result")
            if not isinstance(facts, dict) or facts.get("native_status") != observation["actual"]:
                continue
            missing = ["original_item_failures"]
            if facts["cost_state"] == "unknown":
                missing.append("original_usage")
            names = ("native_status", "job_status", "cost_state", "reason_codes", "counts")
            return {"facts": {name: facts[name] for name in names}, "missing_evidence": missing}
    return None


def _triage_observation(request: dict) -> dict:
    """Only the feedback action DTO belongs in the immutable owner receipt."""
    observation = _job_observation(request, kind="triage", method="submit")
    fields = {"schema_version", "owner", "origin_owner", "run_id", "attempt_id", "step_id", "check_id",
              "expected", "actual", "issue_key", "version", "evidence_ref", "details_ref", "parent_step_id",
              "disposition", "original_occurrence_id", "terminal_check_id", "refusal_code"}
    if (request.keys() != {"schema_version", "owner", "kind", "method", "action_id", "request_digest", "payload"}
            or request["payload"].keys() != {"occurrence_id", "observation"} or observation.keys() - fields
            or any(value is not None and not isinstance(value, str) for value in observation.values())):
        raise ValueError("invalid durable triage action")
    if (observation["owner"] != "filing-fetch" or observation.get("schema_version") != "feedback-observation/1"
            or not observation.get("actual")):
        raise ValueError("not a native filing-fetch outcome")
    return observation


def _triage_name(key: str) -> str:
    return f"triage-{key}.json"


def _read_triage(path: Path) -> dict:
    receipt = json.loads(read_regular_bytes(path))
    request = receipt.get("request") if isinstance(receipt, dict) else None
    observation = _triage_observation(request)
    result = receipt.get("result")
    key = request["action_id"]
    if (path.name != _triage_name(key) or not isinstance(result, dict)
            or result.get("decision") != "needs_evidence"
            or result.get("issue_ref") != f"ff-triage/1/{key}"
            or result.get("evidence_ref") != observation.get("evidence_ref")):
        raise ValueError("invalid triage receipt")
    return receipt


def _record_triage(args: argparse.Namespace, request: dict) -> dict | None:
    observation = _triage_observation(request)
    key = request["action_id"]
    path = args.reports_dir / _triage_name(key)
    try:
        existing = _read_triage(path)
    except FileNotFoundError:
        facts = _triage_original(args, observation)
        if facts is None:
            return None
        result = {
            "decision": "needs_evidence", "issue_ref": f"ff-triage/1/{key}",
            "evidence_ref": observation["evidence_ref"], **facts,
        }
        receipt = {"request": request, "result": result}
        content = (json.dumps(receipt, ensure_ascii=True, sort_keys=True) + "\n").encode("ascii")
        if _write_receipt_once(path, content):
            return result
        existing = _read_triage(path)
    if existing["request"] != request:
        raise ValueError("conflicting triage for the same action")
    return existing["result"]


def _flush_observations(roots, observations_dir=None):
    from ff_direct_run import flush_direct_observations
    from ff_job_observation import flush_job_observations
    from ff_job_store import JobStore
    from ff_refresh_store import RefreshStore

    jobs, direct, slots = [], [], []
    # Each auxiliary installation keeps its own native queue. The primary
    # owner can use its configured override for this invocation.
    primary = (FeedbackRouting.from_process() if observations_dir is None
               else FeedbackRouting(observations_dir.expanduser().resolve()))
    native = FeedbackRouting()
    for position, root in enumerate(roots):
        routing = primary if position == 0 else native
        jobs.extend(flush_job_observations(JobStore(root, initialize=False), routing=routing))
        direct.extend(flush_direct_observations(root, routing=routing))
        slots.append(redeliver_refresh(RefreshStore(root), include_retained=True, routing=routing))
    deferred = jobs.count(False) + direct.count(False) + slots.count(False)
    return {
        "schema_version": "ff-observation-flush/1", "status": "partial" if deferred else "ok",
        "job_offers": jobs.count(True), "direct_offers": direct.count(True), "deferred": deferred,
    }


@observed_cli("feedback", local_only=True)
def main(argv: list[str] | None = None, *, diagnostics) -> int:
    parser = OwnerArgumentParser(description="Filing-fetch owner feedback receipts")
    parser.add_argument("--reports-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    diagnostic = sub.add_parser("get-diagnostic", help="read the original sanitized exception and source identity")
    diagnostic.add_argument("reference")
    diagnostic.add_argument("--observations-dir", type=Path)
    diagnostic.add_argument("--jobs-dir", type=Path, default=DEFAULT_JOBS_DIR)
    for command in ("get-statement-run", "get-direct-run"):
        reader = sub.add_parser(command, help="cold-read the original run or attempt")
        reader.add_argument("reference", nargs="?")
        reader.add_argument("--run-id")
        reader.add_argument("--attempt-id")
        reader.add_argument("--observations-dir", type=Path)
        reader.add_argument("--jobs-dir", type=Path, default=DEFAULT_JOBS_DIR)
    reoffer = sub.add_parser("reoffer-job", help="repair and offer the original durable job observation")
    reoffer.add_argument("--jobs-dir", type=Path, default=DEFAULT_JOBS_DIR)
    reoffer.add_argument("--owner-job-id", required=True)
    flush = sub.add_parser("flush-observations", help="reoffer observations from existing owner receipts only")
    flush.add_argument("--jobs-dir", type=Path, action="append", help="owner state root, repeat as needed")
    flush.add_argument("--observations-dir", type=Path, help="custom observation directory for the primary root")
    sub.add_parser("report")
    sub.add_parser("get-report").add_argument("action_id")
    triage = sub.add_parser("triage", help="record a scoped decision from retained owner evidence")
    triage.add_argument("--jobs-dir", type=Path, action="append", required=True)
    triage.add_argument("--observations-dir", type=Path, help="custom observation directory for the primary root")
    sub.add_parser("get-triage", help="cold-read an original triage action").add_argument("action_id")
    lookup = sub.add_parser("reconcile", help="query the original job or scheduled slot without reacquisition")
    lookup.add_argument("--jobs-dir", type=Path, action="append", required=True)
    lookup.add_argument("--observations-dir", type=Path, help="custom observation directory for the primary root")
    lookup.add_argument("--config", type=Path, help="accepted for legacy deployments; lookup reads receipts only")
    lookup.add_argument("--timeout-seconds", type=float, help="accepted for legacy deployments")
    args = parser.parse_args(argv)
    if args.command == "flush-observations":
        try:
            reply = _flush_observations(_owner_roots(args.jobs_dir), args.observations_dir)
        except (OSError, ValueError, RecursionError) as error:
            record_runtime_failure("feedback-flush", "observation_flush_failed", error, diagnostics=diagnostics)
            print(json.dumps({"error": type(error).__name__}))
            return 1
        print(json.dumps(reply, ensure_ascii=True))
        return int(reply["status"] != "ok")
    if args.command == "reoffer-job":
        from ff_job_contracts import FFJobError, validate_owner_job_id
        from ff_job_observation import load_observed_job
        from ff_job_store import JobStore

        try:
            job_id = validate_owner_job_id(args.owner_job_id)
            store = JobStore(args.jobs_dir.expanduser().resolve(), initialize=False)
            load_observed_job(store, job_id, recover_terminal=True)
        except (FFJobError, OSError) as error:
            record_runtime_failure("feedback-reoffer-job", "job_reoffer_failed", error, jobs_dir=args.jobs_dir,
                                   diagnostics=diagnostics)
            print(json.dumps({"error": type(error).__name__}))
            return 1
        print(json.dumps({"owner_job_id": job_id}))
        return 0
    if args.command in {"get-statement-run", "get-direct-run", "get-diagnostic"}:
        directories = observation_directories(args.jobs_dir)
        if args.observations_dir is not None:
            directories = list(dict.fromkeys([args.observations_dir, *directories]))
    if args.command in {"get-statement-run", "get-direct-run"}:
        from ff_direct_run import STATEMENTS, lookup_direct_run

        if (args.reference is None and not (args.run_id and args.attempt_id)
                or args.reference is not None and (args.run_id is not None or args.attempt_id is not None)):
            parser.error("supply the original reference or both --run-id and --attempt-id")
        value = lookup_direct_run(
            directories, reference=args.reference, run_id=args.run_id, attempt_id=args.attempt_id,
            surface=STATEMENTS if args.command == "get-statement-run" else None,
        )
        print(json.dumps(value, ensure_ascii=True))
        return 0
    if args.command == "get-diagnostic":
        match = re.fullmatch(r"ff-diagnostic/1/(feedback-[a-f0-9]{32})", args.reference)
        if not match:
            parser.error("invalid diagnostic reference")
        value, error = read_native_diagnostic(match[1], directories)
        if value is not None:
            print(json.dumps(feedback_wire(value), ensure_ascii=True))
            return 0
        if error is not None:
            record_runtime_failure("feedback-get-diagnostic", "diagnostic_unreadable", error, jobs_dir=args.jobs_dir,
                                   diagnostics=diagnostics)
        print(json.dumps({"status": "unavailable"}))
        return 1
    if args.command == "reconcile":
        try:
            reply = _lookup(args, json.load(sys.stdin))
        except (OSError, ValueError, RecursionError) as error:
            record_runtime_failure("feedback-reconcile", "reconcile_failed", error, jobs_dir=args.jobs_dir[0],
                                   diagnostics=diagnostics)
            print(json.dumps({"error": type(error).__name__}))
            return 1
        print(json.dumps(reply, ensure_ascii=True))
        return 0
    if args.reports_dir is None:
        parser.error("--reports-dir is required for feedback receipts")
    if args.command in {"report", "triage"}:
        try:
            request = json.load(sys.stdin)
        except (OSError, ValueError, RecursionError) as error:
            record_runtime_failure(f"feedback-{args.command}", f"invalid_{args.command}_request", error,
                                   diagnostics=diagnostics)
            if args.command == "report":
                raise
            print(json.dumps({"error": type(error).__name__}))
            return 1
        key = request.get("action_id") if isinstance(request, dict) else None
    else:
        key = args.action_id
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
        parser.error("invalid feedback action id")
    try:
        if args.command == "triage":
            result = _record_triage(args, request)
            if result is None:
                print(json.dumps({"error": "original_evidence_unavailable"}))
                return 1
            value = {"result": result}
        elif args.command == "get-triage":
            value = {"receipt": _read_triage(args.reports_dir / _triage_name(key))}
        elif args.command == "report":
            value = {"result": _record_report(args.reports_dir, request)}
        else:
            path = owner_io_path(args.reports_dir / (key + ".json"))
            value = {"report": json.loads(path.read_bytes())}
    except (OSError, ValueError, RecursionError) as error:
        if args.command not in {"get-report", "get-triage"} or not isinstance(error, FileNotFoundError):
            reason = "triage_io_failed" if args.command.endswith("triage") else "report_io_failed"
            record_runtime_failure("feedback-" + args.command, reason, error, diagnostics=diagnostics)
        print(json.dumps({"error": type(error).__name__}))
        return 1
    print(json.dumps(value, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_exit(main))
