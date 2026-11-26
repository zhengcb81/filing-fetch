"""Offline F4 drain proof for filing-fetch's public automatic maintenance argv."""

from __future__ import annotations

import argparse
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile


FF = Path(__file__).resolve().parents[3]
OWNER = "filing-fetch"


def run(cwp: Path, scratch: Path) -> dict:
    spec = importlib.util.spec_from_file_location("ff_fixture", FF / "tests/test_ff_runtime_lifecycle.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.SCRIPTS = scratch / "scripts"
    shutil.copytree(FF / "scripts", fixture.SCRIPTS, ignore=shutil.ignore_patterns("__pycache__"))
    case = fixture.Case(scratch, "ok")
    case.env.update(RESEARCH_FEEDBACK_RUN_ID="original-missing-outbox", RESEARCH_FEEDBACK_ATTEMPT_ID="a1")
    case.env["PYTHONPATH"] = os.pathsep.join((str(cwp), str(cwp / "src")))
    case.env.pop("FMP_API_KEY", None)
    default_jobs = scratch / ".ff_jobs"
    default_out = default_jobs / "observations"
    default_jobs.mkdir()
    for blocked in (case.inbox, default_out):
        blocked.write_text("occupied", encoding="utf-8")
    action = case.invoke("fetch_statements.py", "--config", str(case.config), body=fixture.REQUEST)
    assert action.returncode == 0, action.stderr
    assert json.loads(action.stdout)["status"] == "complete"

    config = scratch / "host.json"
    hosts = scratch / "hosts.json"
    missing_root = scratch / "unused-jobs"
    args = ("--jobs-dir", str(default_jobs), "--jobs-dir", str(missing_root), "--observations-dir", str(case.inbox))
    config.write_text(json.dumps({
        "state": "host.sqlite",
        "owners": {OWNER: {
            "cwd": str(scratch), "timeout_seconds": 25,
            "native_observation_dirs": [str(case.inbox), str(default_out)],
            "actions": {
                "flush-observations": case.argv("ff_job_feedback.py", "flush-observations", *args),
                "reconcile": case.argv("ff_job_feedback.py", "reconcile", *args),
            },
        }},
    }), encoding="utf-8")
    python = [sys.executable, "-B"]
    hosts.write_text(json.dumps({
        OWNER: python + ["-m", "tools.feedback_loop.local_host", "--config", str(config), "rpc"],
    }), encoding="utf-8")
    command = python + [
        "-m", "tools.feedback_loop.intake", "--settings", str(config), "--hosts", str(hosts),
        "--wait-seconds", "10", "drain",
    ]

    def drain():
        result = subprocess.run(command, env=case.env, cwd=cwp, capture_output=True, timeout=40, check=True)
        return json.loads(result.stdout)

    blocked = drain()
    assert blocked["processed"] == 0
    for obstacle in (case.inbox, default_out):
        obstacle.unlink()
    first = drain()
    packets = list(case.inbox.glob("feedback-*.jsonl"))
    assert len(packets) == 1, (first, [p.name for p in default_out.glob("*")])
    marker = packets[0]
    packet = marker.read_bytes()
    rows = [json.loads(line) for line in packet.splitlines()]
    assert {row["run_id"] for row in rows} == {"original-missing-outbox"}
    assert {row["attempt_id"] for row in rows} == {"a1"}
    assert first["processed"] == len(rows) and first["remaining"] == 0
    for _ in range(2):
        assert case.flush(default_jobs).returncode == 0
    again = drain()
    with closing(sqlite3.connect(scratch / "host.sqlite")) as db:
        count = db.execute("SELECT count(*) FROM actions WHERE json_extract(request, '$.kind') = 'observe'").fetchone()[0]
    assert count == len(rows) and again["processed"] == 0 and again["remaining"] == 0
    assert marker.read_bytes() == packet and case.count() == 1 and not missing_root.exists()
    return {"business_exit": action.returncode, "calls": case.count(), "flushed_rows": len(rows),
            "durable_observations": count, "duplicate_rows": again["processed"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwp-root", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="f4-ff-flush-") as directory:
        print(json.dumps(run(args.cwp_root.expanduser().resolve(), Path(directory))))
