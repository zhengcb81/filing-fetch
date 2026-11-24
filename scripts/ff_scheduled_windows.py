"""Install, remove or preview the current user's filing-fetch Windows task."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import os
from ff_runtime_feedback import cli_failure, parse_arguments
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as xml
from xml.parsers.expat import errors as xml_errors

from ff_refresh_policy import utc_text
from ff_refresh_store import RefreshStore


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts/ff_scheduled_refresh.py"
NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"
DESCRIPTION = "Filing-fetch scheduled document refresh"
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


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "install", "remove", "run"), default="preview", nargs="?")
    parser.add_argument("--config", type=Path, default=ROOT / "config/company_wiki.json")
    parser.add_argument("--refresh-config", type=Path)
    parser.add_argument("--jobs-dir", type=Path, default=ROOT / ".ff_jobs")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--task-name")
    args = _normalized(parse_arguments(parser, argv, "windows-task"))
    try:
        return _run_action(parser, args)
    except SystemExit as exc:
        if exc.code:
            cli_failure("windows-" + args.action, "task_control_failed", exc, jobs_dir=args.jobs_dir)
        raise
    except Exception as exc:
        cli_failure("windows-" + args.action, "task_launch_failed", exc, jobs_dir=args.jobs_dir)
        raise


_SECRET_REDACT_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|authorization|password)(\s*[:=]\s*)([^\s,;\"']+)"
)
_FAILURE_LOG_MAX_BYTES = 2 * 1024 * 1024
_FAILURE_TAIL_CHARS = 8 * 1024


def _redact_text(text: str) -> str:
    return _SECRET_REDACT_RE.sub(r"\1\2[REDACTED]", text)


def _persist_tick_failure_log(jobs_dir: Path, returncode: int, stdout_bytes: bytes, stderr_bytes: bytes) -> None:
    log_dir = jobs_dir / "logs"
    log_path = log_dir / "scheduled_refresh_failures.log"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        if log_path.is_file() and log_path.stat().st_size >= _FAILURE_LOG_MAX_BYTES:
            rotated = log_path.with_suffix(".log.1")
            try:
                if rotated.exists():
                    rotated.unlink()
                log_path.replace(rotated)
            except OSError:
                pass
        stderr_text = _redact_text(stderr_bytes.decode("utf-8", errors="replace"))[-_FAILURE_TAIL_CHARS:]
        stdout_text = _redact_text(stdout_bytes.decode("utf-8", errors="replace"))[-_FAILURE_TAIL_CHARS:]
        timestamp = utc_text(datetime.now(timezone.utc))
        entry = (
            f"[{timestamp}] windows-tick failed exit_code={returncode}\n"
            f"--- stderr ---\n{stderr_text.rstrip() or '<empty>'}\n"
            f"--- stdout ---\n{stdout_text.rstrip() or '<empty>'}\n\n"
        )
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(entry)
    except OSError as exc:
        sys.stderr.write(f"warning: failed to persist scheduled refresh failure log: {type(exc).__name__}\n")


def _run_action(parser, args):
    if os.name != "nt":
        parser.error("Windows Task Scheduler requires Windows")
    if args.action == "run":
        # pythonw is only the launcher. The normal interpreter keeps stdio for
        # filing-fetch's bounded child transports, with no visible console.
        result = subprocess.run(
            [str(args.python), "-B", str(ENTRY), *_action_args(args), "tick"], cwd=ROOT,
            stdin=subprocess.DEVNULL, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            _persist_tick_failure_log(
                args.jobs_dir,
                result.returncode,
                result.stdout or b"",
                result.stderr or b"",
            )
            cli_failure(
                "windows-tick",
                "tick_exit_" + str(result.returncode),
                RuntimeError(f"scheduled refresh tick exited with code {result.returncode}"),
                jobs_dir=args.jobs_dir,
            )
        return result.returncode
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
    arguments = ["-B", str(Path(__file__).resolve()), "run", "--python", str(args.python), *_action_args(args)]
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
    raise SystemExit(run())
