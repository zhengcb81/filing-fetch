"""Public control surface and bounded tick for scheduled company documents."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from ff_job_feedback import redeliver_refresh
from ff_persistence import LockBusy
from ff_runtime_feedback import DEFAULT_JOBS_DIR, OwnerArgumentParser, cli_exit, cli_failure, observed_cli
from ff_refresh_policy import RUNS_SCHEMA, STATUS_SCHEMA, due_slot, parse_config_request, slot_consumed, utc_text
from ff_refresh_store import ConfigConflict, RefreshStateError, RefreshStore, summarize_run


SKILL_ROOT = Path(__file__).resolve().parents[1]


def _status(store: RefreshStore, deployment_path: Path, now: datetime) -> dict:
    state = store.load()
    settings = state["settings"]
    configured = deployment_path.is_file()
    enabled = settings["enabled"]
    host_state = "disabled" if not enabled else "not_configured"
    reasons = []
    limits = None
    next_due = None
    host = store.host_receipt() or {}
    registered = host.get("registered") is True
    if enabled:
        slot = due_slot(settings["cadence"], now)
        last = state["last_slot"]
        next_due = utc_text(slot.next_at if slot_consumed(last, slot, settings) else slot.due_at)
        if not configured:
            reasons.append("schedule_deployment_missing")
    if configured:
        from ff_refresh_owners import load_deployment

        try:
            limits = load_deployment(deployment_path).status_limits()
            host_state = ("registered" if registered else "manual") if enabled else "disabled"
            if enabled and not registered:
                reasons.append("scheduler_installation_not_observed")
        except ValueError:
            reasons.append("schedule_deployment_invalid")
    return {
        "schema_version": STATUS_SCHEMA, "settings": settings, "revision": state["revision"],
        "scheduler": {"state": host_state, "registered": registered,
                      "task_name": host.get("task_name"), "next_check_at": None}, "next_due_at": next_due,
        "current_run": summarize_run(state["current"]) if state["current"] is not None else None,
        "last_run": state["last_run"], "effective_limits": limits, "reason_codes": reasons,
    }


def _parser() -> argparse.ArgumentParser:
    parser = OwnerArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=SKILL_ROOT / "config/company_wiki.json")
    parser.add_argument("--refresh-config", type=Path, help="default: scheduled_refresh.json next to --config")
    parser.add_argument("--jobs-dir", type=Path, default=DEFAULT_JOBS_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    configure = sub.add_parser("configure")
    configure.add_argument("--request-stdin", action="store_true", required=True)
    runs = sub.add_parser("runs")
    runs.add_argument("--cursor")
    runs.add_argument("--limit", type=int, default=50)
    sub.add_parser("tick")
    return parser


def run_command(args: argparse.Namespace, *, diagnostics=None) -> dict:
    store = RefreshStore(args.jobs_dir.resolve())
    config_path = args.config.resolve()
    deployment = (args.refresh_config or config_path.with_name("scheduled_refresh.json")).resolve()
    clock = datetime.now(timezone.utc)
    if args.command == "runs":
        if args.limit < 1:
            raise ValueError("limit must be positive")
        rows, cursor = store.history(args.cursor, args.limit)
        return {"schema_version": RUNS_SCHEMA, "items": rows, "next_cursor": cursor}
    if args.command == "configure":
        settings, revision = parse_config_request(json.load(sys.stdin))
        store.configure(settings, revision)
    if args.command == "tick":
        redeliver_refresh(store)
    if args.command == "tick" and store.load()["settings"]["enabled"] and deployment.is_file():
        from ff_refresh_owners import OwnerPorts, load_deployment
        from ff_refresh_runner import run_tick

        options = load_deployment(deployment)
        try:
            run_tick(store, OwnerPorts(config_path, args.jobs_dir.resolve(), options), options, now=clock)
        except LockBusy:
            return {
                **_status(store, deployment, clock),
                "tick_result": "already_running",
            }
    result = _status(store, deployment, clock)
    if args.command == "tick" and "schedule_deployment_missing" in result.get("reason_codes", ()):
        cli_failure("refresh-tick", "schedule_deployment_missing", jobs_dir=args.jobs_dir, no_dispatch=True,
                    diagnostics=diagnostics)
    return result


@observed_cli("scheduled-refresh")
def main(argv: list[str] | None = None, *, diagnostics) -> int:
    args = _parser().parse_args(argv)
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    code = 0
    try:
        result = run_command(args, diagnostics=diagnostics)
    except (ValueError, LockBusy, RefreshStateError, OSError) as exc:
        if isinstance(exc, ConfigConflict):
            reason = "config_conflict"
        elif isinstance(exc, LockBusy):
            reason = "schedule_state_busy"
        elif isinstance(exc, (RefreshStateError, OSError)):
            reason = "schedule_state_unavailable"
        else:
            reason = "request_error"
        cli_failure("refresh-" + args.command, reason, exc, jobs_dir=args.jobs_dir, diagnostics=diagnostics)
        result = {"schema_version": STATUS_SCHEMA, "error": {"code": reason, "owner": "filing-fetch"}}
        code = 2
    except Exception as exc:
        cli_failure("refresh-" + args.command, "fatal", exc, jobs_dir=args.jobs_dir, diagnostics=diagnostics)
        raise
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(cli_exit(main))
