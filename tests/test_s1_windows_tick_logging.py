"""S2 regression for the Windows launcher-owned scheduled tick diagnostics."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ff_scheduled_windows as launcher  # noqa: E402


def test_unhandled_custom_exception_retains_last_frame_and_ignores_multiline_body(tmp_path):
    entry = tmp_path / "child.py"
    entry.write_text(
        "import sqlite3\n"
        "class FilingFetchError(Exception): pass\n"
        "try:\n"
        "    raise sqlite3.OperationalError('inner private data')\n"
        "except sqlite3.OperationalError as err:\n"
        "    raise FilingFetchError('detail private data\\nValueError: misleading') from err\n",
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, "-B", str(entry)], capture_output=True, timeout=15)
    facts = launcher._tick_failure(result.returncode, result.stderr)
    assert facts == {
        "exit_code": 1,
        "stderr_form": "python_traceback",
        "exception_type": "FilingFetchError",
        "last_frame": {"file": "child.py", "line": 6},
    }
    assert "private" not in json.dumps(facts) and str(tmp_path) not in json.dumps(facts)


def _isolate_feedback(monkeypatch):
    for key in os.environ:
        if key.startswith("RESEARCH_FEEDBACK_"):
            monkeypatch.delenv(key)


@pytest.mark.skipif(os.name != "nt", reason="Windows scheduled tick runner")
def test_windows_failure_is_data_minimal_and_cold_readable(tmp_path, monkeypatch):
    _isolate_feedback(monkeypatch)
    jobs_dir = tmp_path / "ff-jobs"
    calls = tmp_path / "calls"
    monkeypatch.setenv("FF_S2_TEST_CALLS", str(calls))
    fake_entry = tmp_path / "broken_tick.py"
    fake_entry.write_text(
        "import os, pathlib, sys\n"
        "with pathlib.Path(os.environ['FF_S2_TEST_CALLS']).open('a') as calls:\n"
        "    calls.write('called\\n')\n"
        "sys.stdout.write('fake-business-document-marker\\n')\n"
        "sys.stderr.write('Authorization: Bearer fake-header-secret-marker\\n')\n"
        "import traceback\n"
        "try:\n"
        "    raise RuntimeError('fake-error-body-marker')\n"
        "except RuntimeError:\n"
        "    traceback.print_exc()\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "ENTRY", fake_entry)

    rc = launcher.run(["run", "--python", sys.executable, "--jobs-dir", str(jobs_dir)])

    assert rc == 7
    failure_log = jobs_dir / "logs" / "scheduled_refresh_failures.log"
    assert failure_log.is_file()
    text = failure_log.read_text(encoding="utf-8")
    assert all(marker not in text for marker in (
        "fake-business-document-marker", "fake-header-secret-marker", "fake-error-body-marker",
    ))
    logged = json.loads(text)
    assert logged["event"] == "windows-tick"
    assert logged["child_process"] == {
        "exit_code": 7, "stderr_form": "python_traceback", "builtin_exception": "RuntimeError",
        "exception_type": "RuntimeError", "last_frame": {"file": "broken_tick.py", "line": 8},
    }

    observations = jobs_dir / "observations"
    packet, = observations.glob("*.jsonl")
    observation = json.loads(packet.read_text(encoding="utf-8"))
    assert observation["actual"] == "tick_exit_7"
    assert observation["evidence_ref"].startswith("ff-cli/1/")
    assert logged["evidence_ref"] == observation["evidence_ref"]
    reference = observation["details_ref"]
    command = [
        sys.executable, "-B", str(SCRIPTS / "ff_job_feedback.py"), "get-diagnostic", reference,
        "--observations-dir", str(observations),
    ]
    for _ in range(2):
        cold = subprocess.run(command, capture_output=True, check=True, timeout=20)
        detail = json.loads(cold.stdout)
        assert detail["child_process"] == logged["child_process"]
        assert detail["run_id"] == observation["run_id"]
        assert detail["causes"] == []
        assert b"fake-" not in cold.stdout + cold.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == ["called"]
    assert not (jobs_dir / "scheduled").exists()

    # An explicitly requested new tick gets its own occurrence. Both cold reads
    # above left the original attempt untouched.
    frozen = packet.read_bytes()
    assert launcher.run(["run", "--python", sys.executable, "--jobs-dir", str(jobs_dir)]) == 7
    two_rows = [json.loads(line) for line in failure_log.read_text(encoding="utf-8").splitlines()]
    assert two_rows[0] == logged and two_rows[1]["evidence_ref"] != logged["evidence_ref"]
    assert packet.read_bytes() == frozen and len(list(observations.glob("*.jsonl"))) == 2
    assert calls.read_text(encoding="utf-8").splitlines() == ["called", "called"]


@pytest.mark.skipif(os.name != "nt", reason="Windows scheduled tick runner")
def test_windows_failure_log_survives_unavailable_outbox(tmp_path, monkeypatch):
    _isolate_feedback(monkeypatch)
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "observations").write_text("not a directory", encoding="utf-8")
    fake_entry = tmp_path / "broken_tick.py"
    fake_entry.write_text("raise SystemExit(9)\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "ENTRY", fake_entry)

    assert launcher.run(["run", "--python", sys.executable, "--jobs-dir", str(jobs_dir)]) == 9
    log = jobs_dir / "logs" / "scheduled_refresh_failures.log"
    assert json.loads(log.read_bytes())["child_process"] == {"exit_code": 9, "stderr_form": "empty"}
    assert (jobs_dir / "observations").read_text(encoding="utf-8") == "not a directory"


@pytest.mark.skipif(os.name != "nt", reason="Windows scheduled tick runner")
def test_windows_success_keeps_original_exit_and_no_failure_log(tmp_path, monkeypatch):
    _isolate_feedback(monkeypatch)
    jobs_dir = tmp_path / "jobs"
    rc = launcher.run([
        "run", "--python", sys.executable, "--jobs-dir", str(jobs_dir),
        "--config", str(tmp_path / "filings.json"),
        "--refresh-config", str(tmp_path / "refresh.json"),
    ])
    assert rc == 0
    assert not (jobs_dir / "logs").exists()
    assert not (jobs_dir / "observations").exists()
