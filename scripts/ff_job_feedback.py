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

OUTCOME = "job-outcome"


def publish_job_observation(record: dict, *, started: bool) -> None:
    file = os.environ.get("RESEARCH_FEEDBACK_OUT")
    if not file:
        return
    job_id, attempt = record["owner_job_id"], record["attempts"]
    base = {
        "schema_version": "feedback-observation/1",
        "owner": "filing-fetch",
        "run_id": os.environ.get("RESEARCH_FEEDBACK_RUN_ID") or job_id,
        "attempt_id": os.environ.get("RESEARCH_FEEDBACK_ATTEMPT_ID") or str(attempt),
        "step_id": f"{job_id}/{attempt}",
        "evidence_ref": f"ff-job/1/{job_id}",
        "version": "ff-job/1",
    }
    if started:
        rows = [dict(base, check_id="action-started", expected="started", actual="started",
                     disposition="expected", terminal_check_id=OUTCOME)]
    else:
        outcome = record["status"] if record["status_known"] else "unknown"
        cost = record["cost_state"]
        rows = [
            dict(base, check_id=OUTCOME, expected="terminal", actual=outcome,
                 disposition="unknown" if outcome == "unknown" else "expected"),
            dict(base, check_id="job-usage", expected="accounted", actual=cost,
                 disposition="unknown" if cost == "unknown" else "expected"),
        ]
    try:
        # One caller supplies one exclusive file. When the process dies after
        # starting, the original reference has already reached the sidecar.
        with Path(file).open("ab") as stream:
            stream.write(b"".join((json.dumps(row, ensure_ascii=True) + "\n").encode("ascii") for row in rows))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        # Diagnostics remain optional; the native owner record is authoritative.
        pass


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Filing-fetch owner feedback receipts")
    parser.add_argument("--reports-dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("report")
    sub.add_parser("get-report").add_argument("action_id")
    lookup = sub.add_parser("reconcile", help="query the original job and recorded usage without reacquisition")
    lookup.add_argument("--jobs-dir", type=Path, required=True)
    lookup.add_argument("--config", type=Path, help="owner configuration for catalog-only recovery of a lost job")
    lookup.add_argument("--timeout-seconds", type=float, default=10.0)
    args = parser.parse_args()
    if args.command == "reconcile":
        if not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0:
            parser.error("reconcile timeout must be finite and positive")
        try:
            reply = _lookup_job(args, json.load(sys.stdin))
        except (OSError, ValueError, RecursionError) as error:
            print(json.dumps({"error": type(error).__name__}))
            return 1
        print(json.dumps(reply, ensure_ascii=True))
        return 0
    if args.reports_dir is None:
        parser.error("--reports-dir is required for reports")
    if args.command == "report":
        request = json.load(sys.stdin)
        key = request.get("action_id") if isinstance(request, dict) else None
    else:
        key = args.action_id
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
        parser.error("invalid feedback action id")
    try:
        value = ({"result": _record_report(args.reports_dir, request)} if args.command == "report"
                 else {"report": json.loads((args.reports_dir / (key + ".json")).read_bytes())})
    except (OSError, ValueError) as error:
        print(json.dumps({"error": type(error).__name__}))
        return 1
    print(json.dumps(value, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
