"""Install, remove or preview the current user's filing-fetch Windows task."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as xml
from xml.parsers.expat import errors as xml_errors

from ff_process_transport import ChildFailed, ChildTimeout, run_bounded
from ff_refresh_policy import utc_text
from ff_refresh_store import RefreshStore
from ff_runtime_feedback import OwnerArgumentParser, cli_exit, cli_failure, observed_cli


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts/ff_scheduled_refresh.py"
NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"
DESCRIPTION = "Filing-fetch scheduled document refresh"
DEFAULT_TICK_TIMEOUT_SECONDS = 600
TICK_TIMEOUT_EXIT = 124
_NS = {"t": NAMESPACE}
xml.register_namespace("", NAMESPACE)


def _node(parent, name, text=None, **attributes):
    element = xml.SubElement(parent, f"{{{NAMESPACE}}}{name}", attributes)
    element.text = text
    return element


def _identity() -> tuple[str, str]:
    result = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"], capture_output=True, check=True,
        encoding="mbcs", timeout=8, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    name, sid = next(csv.reader(result.stdout.splitlines()))
    if not sid.startswith("S-"):
        raise ValueError("Windows user SID is unavailable")
    return name, sid


def task_definition(*, sid: str, task_name: str, launcher: Path, arguments: list[str]) -> str:
    task = xml.Element(f"{{{NAMESPACE}}}Task", {"version": "1.3"})
    registration = _node(task, "RegistrationInfo")
    _node(registration, "Description", DESCRIPTION)
    _node(registration, "URI", "\\" + task_name)
    triggers = _node(task, "Triggers")
    periodic = _node(triggers, "TimeTrigger")
    _node(_node(periodic, "Repetition"), "Interval", "PT30M")
    _node(periodic, "StartBoundary", (datetime.now() + timedelta(minutes=1)).isoformat(timespec="seconds"))
    logon = _node(triggers, "LogonTrigger")
    _node(logon, "UserId", sid)
    _node(logon, "Delay", "PT1M")
    principal = _node(_node(task, "Principals"), "Principal", id="Author")
    for name, value in (("UserId", sid), ("LogonType", "InteractiveToken"), ("RunLevel", "LeastPrivilege")):
        _node(principal, name, value)
    settings = _node(task, "Settings")
    for name, value in (
        ("MultipleInstancesPolicy", "IgnoreNew"), ("DisallowStartIfOnBatteries", "false"),
        ("StopIfGoingOnBatteries", "false"), ("StartWhenAvailable", "true"),
        ("ExecutionTimeLimit", "PT0S"), ("Enabled", "true"),
    ):
        _node(settings, name, value)
    execution = _node(_node(task, "Actions", Context="Author"), "Exec")
    _node(execution, "Command", str(launcher))
    _node(execution, "Arguments", subprocess.list2cmdline(arguments))
    _node(execution, "WorkingDirectory", str(ROOT))
    return xml.tostring(task, encoding="unicode")


def _query_task(task_name: str) -> xml.Element | None:
    result = subprocess.run(
        ["schtasks.exe", "/Query", "/TN", task_name, "/XML"],
        capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        return None
    try:
        return xml.fromstring(result.stdout)
    except xml.ParseError as exc:
        if exc.code != xml_errors.codes[xml_errors.XML_ERROR_INCORRECT_ENCODING]:
            raise
    # Redirected schtasks may write OEM console bytes while leaving the
    # task definition's UTF-16 declaration intact.
    return xml.fromstring(result.stdout.decode("oem"))


def _change_task(parser: argparse.ArgumentParser, arguments: list[str], *, timeout: float) -> None:
    result = subprocess.run(
        ["schtasks.exe", *arguments], stdin=subprocess.DEVNULL, capture_output=True,
        timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        message = (result.stderr or result.stdout).decode("oem", errors="replace").strip()
        parser.error(f"schtasks {arguments[0]} failed (exit {result.returncode}) {message}".rstrip())


def _find(task: xml.Element, field: str) -> str | None:
    return task.findtext(field, namespaces=_NS)


def _registered_task(task: xml.Element, task_name: str, name: str, sid: str) -> bool:
    return (_find(task, "t:RegistrationInfo/t:Description") == DESCRIPTION
            and _find(task, "t:RegistrationInfo/t:URI") == "\\" + task_name
            and _find(task, "t:Principals/t:Principal/t:UserId") in (name, sid))


def _action_args(args: argparse.Namespace) -> list[str]:
    return ["--config", str(args.config), "--refresh-config", str(args.refresh_config),
            "--jobs-dir", str(args.jobs_dir)]


def _normalized(args: argparse.Namespace) -> argparse.Namespace:
    args.python = args.python.resolve()
    args.config = args.config.resolve()
    args.refresh_config = (args.refresh_config or args.config.with_name("scheduled_refresh.json")).resolve()
    args.jobs_dir = args.jobs_dir.resolve()
    return args


def _positive_seconds(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite duration")
    return result


@observed_cli("windows-task")
def run(argv=None, *, diagnostics) -> int:
    parser = OwnerArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "install", "remove", "run"), default="preview", nargs="?")
    parser.add_argument("--config", type=Path, default=ROOT / "config/company_wiki.json")
    parser.add_argument("--refresh-config", type=Path)
    parser.add_argument("--jobs-dir", type=Path, default=ROOT / ".ff_jobs")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--task-name")
    parser.add_argument(
        "--tick-timeout-seconds", type=_positive_seconds, default=DEFAULT_TICK_TIMEOUT_SECONDS,
        help="Windows watchdog deadline for the complete tick process (default: %(default)s)",
    )
    args = _normalized(parser.parse_args(argv))
    try:
        return _run_action(parser, args, diagnostics=diagnostics)
    except SystemExit as exc:
        if exc.code:
            cli_failure("windows-" + args.action, "task_control_failed", exc, jobs_dir=args.jobs_dir, diagnostics=diagnostics)
        raise
    except Exception as exc:
        cli_failure("windows-" + args.action, "task_launch_failed", exc, jobs_dir=args.jobs_dir, diagnostics=diagnostics)
        raise


def _run_action(parser, args, *, diagnostics=None):
    if os.name != "nt":
        parser.error("Windows Task Scheduler requires Windows")
    if args.action == "run":
        if not args.python.is_file():
            raise FileNotFoundError("configured tick interpreter is not a file")
        # Use the shared process owner so a timed-out launcher also reaps descendants.
        command = [str(args.python), "-B", str(ENTRY), *_action_args(args), "tick"]
        try:
            run_bounded(
                command, timeout_seconds=args.tick_timeout_seconds, cwd=str(ROOT), discard_stdout=True,
            )
        except ChildTimeout as exc:
            cli_failure("windows-tick", "tick_timeout", exc, jobs_dir=args.jobs_dir, diagnostics=diagnostics)
            return TICK_TIMEOUT_EXIT
        except ChildFailed as exc:
            cli_failure("windows-tick", f"tick_exit_{exc.returncode}", exc, jobs_dir=args.jobs_dir, diagnostics=diagnostics)
            return exc.returncode
        return 0
    name, sid = _identity()
    task_name = args.task_name or f"FilingFetch-ScheduledRefresh-{sid}"
    if any(char in "\\/" or ord(char) < 32 for char in task_name):
        parser.error("task name must be a single Windows task name")
    launcher = args.python.with_name("pythonw.exe")
    if not launcher.is_file():
        candidate = shutil.which("pythonw.exe")
        if candidate is None:
            parser.error("Windows scheduled refresh requires an installed pythonw.exe")
        launcher = Path(candidate)
    arguments = [
        "-B", str(Path(__file__).resolve()), "run", "--python", str(args.python),
        "--tick-timeout-seconds", str(args.tick_timeout_seconds), *_action_args(args),
    ]
    definition = task_definition(sid=sid, task_name=task_name, launcher=launcher, arguments=arguments)
    if args.action == "preview":
        print(json.dumps({"action": "preview", "task_name": task_name, "definition": definition}))
        return 0
    existing = _query_task(task_name)
    if existing is not None and not _registered_task(existing, task_name, name, sid):
        parser.error("the task name belongs to a different Windows task")
    if args.action == "remove":
        if existing is None:
            parser.error("scheduled task state could not be confirmed; no registration receipt changed")
        _change_task(parser, ["/Delete", "/TN", task_name, "/F"], timeout=15)
    else:
        target = xml.fromstring(definition)
        action = "t:Actions/t:Exec/"
        differs = existing is None or any(
            _find(existing, field) != _find(target, field) for field in (
                action + "Command", action + "Arguments", action + "WorkingDirectory",
                "t:Settings/t:MultipleInstancesPolicy", "t:Triggers/t:TimeTrigger/t:Repetition/t:Interval",
            )
        )
        if differs:
            with tempfile.TemporaryDirectory(prefix="sr-task-") as directory:
                path = Path(directory) / "task.xml"
                path.write_text('<?xml version="1.0" encoding="UTF-16"?>\n' + definition, encoding="utf-16")
                arguments = ["/Create", "/TN", task_name, "/XML", str(path)]
                if existing is not None:
                    arguments.append("/F")
                _change_task(parser, arguments, timeout=20)
            observed = _query_task(task_name)
            if observed is None or not _registered_task(observed, task_name, name, sid):
                parser.error("newly created task could not be confirmed")
    receipt = {"registered": args.action == "install", "task_name": task_name,
               "observed_at": utc_text(datetime.now(timezone.utc))}
    RefreshStore(args.jobs_dir).record_host(receipt)
    print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_exit(run))
