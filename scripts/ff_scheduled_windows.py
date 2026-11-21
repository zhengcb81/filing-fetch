"""Install, remove or preview the current user's filing-fetch Windows task."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as xml

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
    return xml.fromstring(result.stdout)


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
    args = _normalized(parser.parse_args(argv))
    if os.name != "nt":
        parser.error("Windows Task Scheduler requires Windows")
    if args.action == "run":
        # pythonw is only the launcher. The normal interpreter keeps stdio for
        # filing-fetch's bounded child transports, with no visible console.
        result = subprocess.run(
            [str(args.python), "-B", str(ENTRY), *_action_args(args), "tick"], cwd=ROOT,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
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
        subprocess.run(["schtasks.exe", "/Delete", "/TN", task_name, "/F"], check=True,
                       timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
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
                subprocess.run(
                    ["schtasks.exe", "/Create", "/TN", task_name, "/XML", str(path),
                     *(["/F"] if existing is not None else [])],
                    stdin=subprocess.DEVNULL, check=True, timeout=20,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
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
