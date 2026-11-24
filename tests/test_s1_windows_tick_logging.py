"""S1-03 regression test: Windows scheduled tick must persist child stderr on failure."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ff_scheduled_windows as launcher  # noqa: E402


@pytest.mark.skipif(os.name != "nt", reason="Windows scheduled tick runner")
def test_windows_run_persists_stderr_diagnostic_on_tick_failure(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "ff-jobs"
    fake_entry = tmp_path / "broken_tick.py"
    fake_entry.write_text(
        "import sys\n"
        "sys.stderr.write('Traceback (most recent call last):\\nRuntimeError: synthetic-s1-tick-boom\\n')\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "ENTRY", fake_entry)

    rc = launcher.run(["run", "--python", sys.executable, "--jobs-dir", str(jobs_dir)])

    assert rc == 7
    failure_log = jobs_dir / "logs" / "scheduled_refresh_failures.log"
    assert failure_log.is_file(), "Failing scheduled tick must persist stderr diagnostic log"
    text = failure_log.read_text(encoding="utf-8")
    assert "synthetic-s1-tick-boom" in text
    assert "exit_code=7" in text
