"""Public CLI of the filing-fetch durable job façade (protocol ``ff-job/1``).

Subcommands (fixed argv, one JSON response on stdout; Dashboard's MODULE-m8-FF
adapter binds exactly this surface). The deployment knobs ``--jobs-dir`` and
``--pretty`` are global options and must precede the subcommand:

    ff_job.py [--jobs-dir DIR] [--pretty] submit [--request-file PATH]
    ff_job.py [--jobs-dir DIR] [--pretty] run --owner-job-id ID
              [--config PATH] [--timeout-seconds S]
    ff_job.py [--jobs-dir DIR] [--pretty] get_status --owner-job-id ID
    ff_job.py [--jobs-dir DIR] [--pretty] allowed_actions --owner-job-id ID
    ff_job.py [--jobs-dir DIR] [--pretty] act --owner-job-id ID
              --action cancel|retry|reconcile --idempotency-key KEY
              [--config PATH] [--timeout-seconds S]
    ff_job.py [--jobs-dir DIR] [--pretty] list_jobs [--cursor ID] [--limit N]

Exit codes follow the house convention: 0 = a valid answer (including a
business-level failed/cancelled job state), 2 = request/config error (named
envelope), 1 = fatal/unexpected. ``submit`` reads one ff-job/1 body from
stdin or ``--request-file``; everything else is pure argv. No request carries
paths, command strings, or credentials — engine configuration arrives only
through the operator's ``--config`` deployment knob.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

from ff_job_contracts import (
    FFJobError,
    FF_JOB_SCHEMA_VERSION,
    build_job_view,
    validate_action,
    validate_idempotency_key,
    validate_owner_job_id,
    validate_submit_body,
)
from ff_job_runner import act, run_job
from ff_job_store import JobStore

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JOBS_DIR = SKILL_ROOT / ".ff_jobs"


def _store(args: argparse.Namespace) -> JobStore:
    return JobStore(Path(args.jobs_dir).expanduser().resolve())


def _read_body(args: argparse.Namespace) -> dict:
    try:
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="strict")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="strict")
        raw = (
            Path(args.request_file).read_text(encoding="utf-8")
            if args.request_file
            else sys.stdin.read()
        )
        payload = json.loads(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise FFJobError(f"invalid request: {exc}", code="request_error") from exc
    return validate_submit_body(payload)


def _emit(payload: dict, *, pretty: bool) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if pretty else None)
    sys.stdout.write("\n")


def _error_payload(command: str, exc: FFJobError) -> dict:
    return {
        "schema_version": FF_JOB_SCHEMA_VERSION,
        "command": command,
        "status": exc.code,
        "error": {
            "code": exc.code,
            "message": str(exc),
            "owner": "filing-fetch",
            "retryable": exc.retryable,
            "next_actions": ["fix_request_and_resubmit"] if exc.code == "request_error" else ["check_ff_config_registration"],
            "correlation_id": "",
        },
    }


def _view_payload(command: str, record: dict, *, fresh_actions: list[str] | None = None, **extra: object) -> dict:
    payload = {
        "schema_version": FF_JOB_SCHEMA_VERSION,
        "command": command,
        "status": "ok",
        "owner_job_id": record.get("owner_job_id"),
        "job": build_job_view(record, fresh_actions=fresh_actions),
    }
    payload.update(extra)
    return payload


def _cmd_submit(args: argparse.Namespace) -> int:
    body = _read_body(args)
    store = _store(args)
    record, replayed = store.create_job(body, command_id=body["command_id"])
    _emit(_view_payload("submit", record, idempotent_replay=replayed), pretty=args.pretty)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    validate_owner_job_id(args.owner_job_id)
    store = _store(args)
    record, executed = run_job(
        store,
        args.owner_job_id,
        config_path=Path(args.config).expanduser().resolve() if args.config else None,
        timeout_seconds=args.timeout_seconds,
    )
    _emit(_view_payload("run", record, engine_executed=executed), pretty=args.pretty)
    return 0


def _cmd_get_status(args: argparse.Namespace) -> int:
    validate_owner_job_id(args.owner_job_id)
    store = _store(args)
    record, _ = store.load_checked(args.owner_job_id, fix=True)
    _emit(_view_payload("get_status", record), pretty=args.pretty)
    return 0


def _cmd_allowed_actions(args: argparse.Namespace) -> int:
    validate_owner_job_id(args.owner_job_id)
    store = _store(args)
    record, _ = store.load_checked(args.owner_job_id, fix=True)
    from ff_job_contracts import allowed_actions_for

    actions = allowed_actions_for(record)
    payload = _view_payload("allowed_actions", record, fresh_actions=actions)
    payload["actions"] = actions
    _emit(payload, pretty=args.pretty)
    return 0


def _cmd_act(args: argparse.Namespace) -> int:
    validate_owner_job_id(args.owner_job_id)
    validate_action(args.action)
    validate_idempotency_key(args.idempotency_key)
    store = _store(args)
    record, replayed = act(
        store,
        args.owner_job_id,
        action=args.action,
        idempotency_key=args.idempotency_key,
        config_path=Path(args.config).expanduser().resolve() if args.config else None,
        timeout_seconds=args.timeout_seconds,
    )
    _emit(_view_payload("act", record, action=args.action, idempotent_replay=replayed),
          pretty=args.pretty)
    return 0


def _cmd_list_jobs(args: argparse.Namespace) -> int:
    store = _store(args)
    limit = max(1, min(100, args.limit))
    items: list[dict] = []
    next_cursor: str | None = None
    all_ids = list(store.iter_job_ids())
    for owner_job_id in all_ids:
        if args.cursor is not None and owner_job_id <= args.cursor:
            continue
        record = store.load(owner_job_id)
        if record is None:
            continue
        if len(items) >= limit:
            next_cursor = items[-1]["owner_job_id"] if items else args.cursor
            break
        items.append(build_job_view(record))
    # The page envelope is the frozen Dashboard PageInfo shape: next_cursor
    # plus a snapshot id for the set this page was cut from, the exact total
    # of durable jobs, and an explicit exactness word.
    snapshot = hashlib.sha256("\n".join(all_ids).encode("utf-8")).hexdigest()[:16]
    _emit({
        "schema_version": FF_JOB_SCHEMA_VERSION,
        "command": "list_jobs",
        "status": "ok",
        "items": items,
        "page": {
            "next_cursor": next_cursor,
            "snapshot_id": f"ffjobs-{snapshot}",
            "total": len(all_ids),
            "total_status": "exact",
        },
    }, pretty=args.pretty)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ff-job",
        description=(
            "Durable job façade over filing-fetch acquisition (protocol ff-job/1): "
            "submit acquire jobs, run them with the bounded engine, query status "
            "cross-process, apply declared actions, list the job directory."
        ),
    )
    parser.add_argument(
        "--jobs-dir", default=str(DEFAULT_JOBS_DIR),
        help="durable job store directory (default: <skill_root>/.ff_jobs)",
    )
    parser.add_argument("--pretty", action="store_true", help="indent the JSON response")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_submit_parser(subparsers)
    _add_run_parser(subparsers)
    _add_status_parser(subparsers)
    _add_actions_parser(subparsers)
    _add_act_parser(subparsers)
    _add_list_parser(subparsers)
    return parser


def _add_submit_parser(subparsers) -> None:
    submit = subparsers.add_parser(
        "submit", help="persist one ff-job/1 acquire submission (never runs the engine)",
    )
    submit.add_argument("--request-file", type=Path, default=None,
                        help="read the ff-job/1 body from file instead of stdin")
    submit.set_defaults(handler=_cmd_submit)


def _add_run_parser(subparsers) -> None:
    run = subparsers.add_parser(
        "run", help="execute one queued job with the bounded engine (blocking)",
    )
    run.add_argument("--owner-job-id", required=True)
    run.add_argument("--config", type=Path, default=None,
                     help="path to company_wiki.json (operator deployment knob)")
    run.add_argument("--timeout-seconds", type=float, default=900.0,
                     help="overall engine budget for this run (default: 900)")
    run.set_defaults(handler=_cmd_run)


def _add_status_parser(subparsers) -> None:
    status = subparsers.add_parser(
        "get_status", help="cross-process JobView for one owner_job_id",
    )
    status.add_argument("--owner-job-id", required=True)
    status.set_defaults(handler=_cmd_get_status)


def _add_actions_parser(subparsers) -> None:
    actions = subparsers.add_parser(
        "allowed_actions", help="declared actions for one owner_job_id",
    )
    actions.add_argument("--owner-job-id", required=True)
    actions.set_defaults(handler=_cmd_allowed_actions)


def _add_act_parser(subparsers) -> None:
    act_parser = subparsers.add_parser(
        "act", help="apply one declared action (cancel | retry | reconcile)",
    )
    act_parser.add_argument("--owner-job-id", required=True)
    act_parser.add_argument("--action", required=True,
                            help="cancel (queued only) | retry (zero-spend evidence) | reconcile (unknown only)")
    act_parser.add_argument("--idempotency-key", required=True,
                            help="action idempotency key (JobActionRequest)")
    act_parser.add_argument("--config", type=Path, default=None,
                            help="path to company_wiki.json (reconcile owner query)")
    act_parser.add_argument("--timeout-seconds", type=float, default=300.0,
                            help="budget for the reconcile owner query (default: 300)")
    act_parser.set_defaults(handler=_cmd_act)


def _add_list_parser(subparsers) -> None:
    listing = subparsers.add_parser(
        "list_jobs", help="bounded job page, ordered by owner_job_id",
    )
    listing.add_argument("--cursor", default=None,
                         help="return jobs strictly after this owner_job_id")
    listing.add_argument("--limit", type=int, default=50, help="page size 1..100 (default: 50)")
    listing.set_defaults(handler=_cmd_list_jobs)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "timeout_seconds", None) is not None:
        if args.timeout_seconds <= 0 or not math.isfinite(args.timeout_seconds):
            print("error: timeout-seconds must be positive and finite", file=sys.stderr)
            return 2
    try:
        return args.handler(args)
    except FFJobError as exc:
        _emit(_error_payload(args.command, exc), pretty=args.pretty)
        return 2
    except Exception as exc:  # noqa: BLE001 - fatal exits 1 per house convention
        _emit({
            "schema_version": FF_JOB_SCHEMA_VERSION,
            "command": getattr(args, "command", "unknown"),
            "status": "fatal",
            "error": {
                "code": "fatal",
                "message": f"{type(exc).__name__}: {exc}",
                "owner": "filing-fetch",
                "retryable": False,
                "next_actions": ["reconcile"],
                "correlation_id": "",
            },
        }, pretty=args.pretty)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
