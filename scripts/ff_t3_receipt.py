"""Owner T3 assurance execution and read-only receipt lookup."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from functools import partial
import hashlib
from io import TextIOBase
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Protocol
import warnings

from ff_persistence import acquire_file_lock, atomic_write_json, owner_io_path
from ff_process_tree import pid_is_alive
from ff_runtime_feedback import (
    OwnerArgumentParser, cause_details, cli_exit, observed_cli, record_runtime_failure,
)
from ff_t3_native import T3_CASES, run_cases
from ff_runtime_log import diagnostic_fields as _diagnostic_fields, diagnostic_view as _diagnostic_view

SCHEMA = "ff-t3-assurance/1"
PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT / ".ff_t3_assurance"
DEFAULT_CONFIG = PROJECT / "config/company_wiki.json"
_CASE_RESULTS = ("passed", "failed", "blocked")
_CASE_REASONS = {"assertion_failed", "test_error", "test_skipped", "unexpected_success", "workspace_not_configured"}
_RUN_REASONS = {
    "case_results_incomplete", "case_execution_blocked", "executor_failed",
    "owner_interrupted", "test_suite_unavailable",
}
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_RECEIPT_NAME = re.compile(r"[0-9]{8}T[0-9]{12}Z--[a-f0-9]{64}\.json")
class CaseReporter(Protocol):
    def __call__(
        self, case: str, outcome: str, reason: str | None, detail: dict | None = None,
    ) -> None: ...


def _id(value: str) -> str:
    if not _RUN_ID.fullmatch(value):
        raise ValueError("invalid_run_id")
    return value


def _key(run_id: str) -> str:
    return hashlib.sha256(_id(run_id).encode("ascii")).hexdigest()


def _existing(root: Path, key: str) -> Path:
    try:
        candidates = [
            path for path in owner_io_path(root).iterdir()
            if _RECEIPT_NAME.fullmatch(path.name) and path.name.endswith("--" + key + ".json")
        ]
    except FileNotFoundError:
        candidates = []
    return max(candidates, key=lambda path: path.name, default=root / (key + ".json"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _owner_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and re.fullmatch(r"[a-f0-9]{40}", revision) else "unknown"


def _load(path: Path, run_id: str | None) -> dict | None:
    try:
        value = json.loads(owner_io_path(path).read_bytes())
    except FileNotFoundError:
        return None
    except (OSError, ValueError, RecursionError) as error:
        reason = "receipt_unreadable"
        return {"schema_version": SCHEMA, "run_id": run_id, "state": "unknown",
                "reason": reason, "diagnostic": cause_details(error, reason=reason)}
    if isinstance(value, dict) and value.get("schema_version") == SCHEMA:
        stored_id = value.get("run_id")
        if (isinstance(stored_id, str) and _RUN_ID.fullmatch(stored_id)
                and (run_id is None or stored_id == run_id)
                and path.stem.rsplit("--", 1)[-1] == _key(stored_id)):
            return value
    return {"schema_version": SCHEMA, "run_id": run_id,
            "state": "unknown", "reason": "receipt_unreadable"}


def _evidence(run_id: str, case: str) -> str:
    return f"ff-t3/{run_id}/{case}"


def _suite_output_view(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    observed = {key: value.get(key) is True for key in ("stdout_observed", "stderr_observed")}
    notices = value.get("warnings")
    typed_warnings = []
    if isinstance(notices, list):
        for item in notices:
            warning = _diagnostic_fields(item, labels=("type", "file"), numbers=("line",))
            if {"type", "file", "line"} <= warning.keys():
                typed_warnings.append(warning)
    if any(observed.values()) or typed_warnings:
        return {**observed, "warnings": typed_warnings}
    return None


def _case_view(run_id: str, case: str, value: object) -> dict | None:
    if not isinstance(value, dict) or value.get("outcome") not in _CASE_RESULTS:
        return None
    outcome = value["outcome"]
    expected = _evidence(run_id, case) if outcome != "blocked" else None
    if value.get("evidence_ref") != expected:
        return None
    reason = value.get("reason")
    safe_reason = reason if isinstance(reason, str) and reason in _CASE_REASONS else None
    case_result = {"outcome": outcome, "evidence_ref": expected, "reason": safe_reason}
    diagnostic = _diagnostic_view(value.get("diagnostic"))
    if diagnostic is not None:
        case_result["diagnostic"] = diagnostic
    return case_result


def _project(value: dict) -> dict:
    run_id = value["run_id"]
    state = value.get("state")
    if state == "unknown" and value.get("reason") == "receipt_unreadable":
        public = {"schema_version": SCHEMA, "run_id": run_id, "state": state,
                  "reason": "receipt_unreadable"}
        diagnostic = _diagnostic_view(value.get("diagnostic"))
        if diagnostic is not None:
            public["diagnostic"] = diagnostic
        return public
    if value.get("mode") not in ("live", "offline") or state not in (
        "running", "completed", "blocked", "unknown",
    ):
        return {"schema_version": SCHEMA, "run_id": run_id, "state": "unknown",
                "reason": "receipt_unreadable"}

    raw_cases = value.get("cases")
    cases = {}
    if isinstance(raw_cases, dict):
        for case in T3_CASES:
            row = _case_view(run_id, case, raw_cases.get(case))
            if row is not None:
                cases[case] = row

    reason = value.get("reason")
    if state == "running":
        pid = value.get("owner_pid")
        if type(pid) is not int or pid <= 0 or not pid_is_alive(pid):
            state, reason = "unknown", "owner_interrupted"
    if state == "completed" and set(cases) != set(T3_CASES):
        state, reason = "blocked", "case_results_incomplete"
    if state == "completed" and any(row["outcome"] == "blocked" for row in cases.values()):
        state, reason = "blocked", "case_execution_blocked"

    revision = value.get("owner_revision")
    completed = value.get("completed_at")
    if not isinstance(revision, str) or not re.fullmatch(r"[a-f0-9]{40}", revision):
        revision = "unknown"
    if isinstance(completed, str):
        try:
            completed = datetime.fromisoformat(completed).isoformat()
        except ValueError:
            completed = None
    else:
        completed = None
    public = {"schema_version": SCHEMA, "run_id": run_id, "owner_revision": revision,
              "mode": value["mode"], "state": state, "completed_at": completed,
              "cases": cases}
    started = value.get("started_at")
    if isinstance(started, str):
        try:
            public["started_at"] = datetime.fromisoformat(started).isoformat()
        except ValueError:
            pass
    diagnostic = _diagnostic_view(value.get("diagnostic"))
    if diagnostic is not None:
        public["diagnostic"] = diagnostic
    suite_output = _suite_output_view(value.get("suite_output"))
    if suite_output is not None:
        public["suite_output"] = suite_output
    if isinstance(reason, str) and reason in _RUN_REASONS:
        public["reason"] = reason
    return public


def get_receipt(root: Path, run_id: str) -> dict:
    """Look up the prior run. A missing read does not create a file or directory."""
    value = _load(_existing(root, _key(run_id)), run_id)
    if value is None:
        return {"schema_version": SCHEMA, "run_id": run_id, "state": "missing"}
    return _project(value)


def get_latest_receipt(root: Path) -> dict:
    """Use the stored run-start order, including a subsequently damaged result."""
    try:
        paths = [
            path for path in owner_io_path(root).iterdir() if _RECEIPT_NAME.fullmatch(path.name)
        ]
    except FileNotFoundError:
        paths = []
    if not paths:
        return {"schema_version": SCHEMA, "run_id": None, "state": "missing"}
    latest = max(paths, key=lambda path: path.name)
    value = _load(latest, None)
    if value is None:
        value = {"schema_version": SCHEMA, "run_id": None, "state": "unknown",
                 "reason": "receipt_unreadable"}
    return _project(value)


def _run_once(
    root: Path, run_id: str, execute: Callable[[CaseReporter], dict | None], *, mode: str = "offline",
    diagnostics=None,
) -> dict:
    key = _key(run_id)
    # Reuse an existing claim, including an unreadable or interrupted one.
    prior = _load(_existing(root, key), run_id)
    if prior is not None:
        return _project(prior)

    owner_io_path(root).mkdir(parents=True, exist_ok=True)
    with acquire_file_lock(root / (key + ".lock"), timeout_seconds=5):
        prior = _load(_existing(root, key), run_id)
        if prior is not None:
            return _project(prior)
        started = datetime.now(UTC)
        path = root / (started.strftime("%Y%m%dT%H%M%S%fZ") + "--" + key + ".json")
        cases: dict[str, dict] = {}
        value: dict[str, Any] = {
            "schema_version": SCHEMA, "run_id": run_id, "owner_revision": _owner_revision(),
            "started_at": started.isoformat(), "mode": mode, "state": "running",
            "completed_at": None, "cases": cases, "owner_pid": os.getpid(),
        }
        atomic_write_json(path, value)

    def report(
        case: str, outcome: str, reason: str | None, detail: dict | None = None,
    ) -> None:
        if case not in T3_CASES or outcome not in _CASE_RESULTS or case in cases:
            return
        cases[case] = {
            "outcome": outcome,
            "evidence_ref": _evidence(run_id, case) if outcome != "blocked" else None,
            "reason": reason if reason in _CASE_REASONS else None,
        }
        if detail is not None:
            cases[case]["diagnostic"] = detail
        atomic_write_json(path, value)
        if mode == "live" and outcome != "passed":
            record_runtime_failure("t3-" + case, reason or outcome, run_id=run_id, detail=detail, diagnostics=diagnostics)

    reason: str | None
    try:
        suite_output = execute(report)
    except OSError:
        raise
    except Exception as error:
        state, reason = "blocked", "executor_failed"
        value["diagnostic"] = cause_details(error, reason=reason)
    else:
        if suite_output:
            value["suite_output"] = suite_output
        if set(cases) != set(T3_CASES):
            state, reason = "blocked", "case_results_incomplete"
        elif any(row["outcome"] == "blocked" for row in cases.values()):
            state, reason = "blocked", "case_execution_blocked"
        else:
            state, reason = "completed", None
    value.update(state=state, reason=reason, completed_at=_now())
    atomic_write_json(path, value)
    if mode == "live" and state == "blocked" and reason != "case_execution_blocked":
        record_runtime_failure("t3-run-live", reason, run_id=run_id, detail=value.get("diagnostic"),
                               diagnostics=diagnostics)
    return _project(value)


class _ObservedOutput(TextIOBase):
    """Recognize an incidental stream without storing messages or provider data."""

    written = False

    def write(self, value: str) -> int:
        if value:
            self.written = True
        return len(value)


def _execute_native_suite(report: CaseReporter, *, config: Path, run_id: str) -> dict:
    out, err = _ObservedOutput(), _ObservedOutput()
    notices: dict[tuple[str, str, int], dict] = {}

    def observe_warning(_message, category, filename, lineno, file=None, line=None):
        name, basename = category.__name__, Path(filename).name
        notices[(name, basename, lineno)] = {"type": name, "file": basename, "line": lineno}

    with warnings.catch_warnings(), redirect_stdout(out), redirect_stderr(err):
        warnings.showwarning = observe_warning
        run_cases(report, config=config, run_id=run_id)
    return {"stdout_observed": out.written, "stderr_observed": err.written, "warnings": list(notices.values())}


def _live_exit(value: dict) -> int:
    cases = value.get("cases", {})
    if any(case["outcome"] == "failed" for case in cases.values()):
        return 1
    if (value.get("mode") == "live" and value.get("state") == "completed"
            and set(cases) == set(T3_CASES)
            and all(case["outcome"] == "passed" for case in cases.values())):
        return 0
    return 2


@observed_cli("t3", local_only=True)
def main(argv: list[str] | None = None, *, diagnostics) -> int:
    parser = OwnerArgumentParser(description=__doc__)
    parser.add_argument("--receipts-dir", type=Path, default=DEFAULT_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    get = commands.add_parser("get").add_mutually_exclusive_group(required=True)
    get.add_argument("--run-id")
    get.add_argument("--latest", action="store_true")
    live = commands.add_parser("run-live")
    live.add_argument("--run-id", required=True)
    live.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)
    error_exit = None
    try:
        if args.command == "get":
            value = (get_latest_receipt(args.receipts_dir) if args.latest
                     else get_receipt(args.receipts_dir, args.run_id))
        else:
            execute = partial(_execute_native_suite, config=args.config, run_id=args.run_id)
            value = _run_once(args.receipts_dir, args.run_id, execute, mode="live", diagnostics=diagnostics)
    except ValueError as error:
        record_runtime_failure("t3-" + args.command, "invalid_run_id", error, run_id=args.run_id,
                               diagnostics=diagnostics)
        value = {"schema_version": SCHEMA, "state": "blocked", "reason": "invalid_run_id"}
        error_exit = 2
    except OSError as error:
        reason = "receipt_io_failed"
        detail = cause_details(error, reason=reason)
        record_runtime_failure("t3-" + args.command, reason, run_id=args.run_id, detail=detail,
                               diagnostics=diagnostics)
        value = {"schema_version": SCHEMA, "run_id": args.run_id,
                 "state": "unknown", "reason": reason, "diagnostic": _diagnostic_view(detail)}
        error_exit = 2 if args.command == "run-live" else 1

    print(json.dumps(value, ensure_ascii=True))
    if error_exit is not None:
        return error_exit
    if args.command == "run-live":
        return _live_exit(value)
    return 2 if value["state"] == "missing" else 0


if __name__ == "__main__":
    raise SystemExit(cli_exit(main))
