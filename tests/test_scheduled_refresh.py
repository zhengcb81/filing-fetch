from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ff_refresh_policy import due_slot, validate_settings


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ff_scheduled_refresh.py"


def configure_body(**settings):
    return {
        "schema_version": "ff-scheduled-refresh-config/1",
        "settings": {
            "enabled": True,
            "cadence": {"frequency": "daily", "local_time": "07:30", "time_zone": "Europe/London"},
            "roster": {"mode": "universe", "universe_id": "test-universe"},
            "document_kinds": ["annual_report"],
            "transcripts_enabled": True,
            "reading_level": "local",
            "backlog_enabled": True,
            **settings,
        },
    }


def invoke(root, *args, body=None):
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--jobs-dir", str(root), *args],
        input=json.dumps(body) if body is not None else "",
        encoding="utf-8", errors="strict", capture_output=True, timeout=20,
    )
    return result.returncode, json.loads(result.stdout)


def test_control_plane_reads_do_not_create_a_store_or_start_work(tmp_path):
    jobs = tmp_path / "ff-jobs"
    code, status = invoke(jobs, "status")
    assert code == 0
    assert status["schema_version"] == "ff-scheduled-refresh-status/1"
    assert not status["settings"]["enabled"] and status["scheduler"]["state"] == "disabled"
    assert status["revision"] == 0 and status["current_run"] is None and status["last_run"] is None
    assert invoke(jobs, "runs") == (
        0, {"schema_version": "ff-scheduled-refresh-runs/1", "items": [], "next_cursor": None},
    )
    assert not jobs.exists()


def test_config_and_off_tick_are_persistent_no_dispatch_operations(tmp_path):
    jobs = tmp_path / "ff-jobs"
    body = configure_body()
    code, first = invoke(jobs, "configure", "--request-stdin", body=body)
    assert code == 0 and first["settings"]["enabled"] and first["revision"] == 1
    assert first["scheduler"]["state"] == "not_configured"
    assert invoke(jobs, "configure", "--request-stdin", body=body)[1]["revision"] == 1
    # An old revision must not erase a newer configuration edited elsewhere.
    stopped = configure_body(enabled=False)
    assert invoke(jobs, "configure", "--request-stdin", body=stopped)[1]["revision"] == 2
    stale = {**body, "expected_revision": 1}
    code, rejected = invoke(jobs, "configure", "--request-stdin", body=stale)
    assert code == 2 and rejected["error"]["code"] == "config_conflict"
    code, off = invoke(jobs, "tick")
    assert code == 0 and not off["settings"]["enabled"]
    assert off["current_run"] is None and off["last_run"] is None
    assert not (jobs / "jobs").exists()


def test_due_uses_weekday_in_selected_time_zone_and_collapses_missed_weeks():
    cadence = validate_settings(configure_body(cadence={
        "frequency": "weekly", "weekday": 1, "local_time": "07:30", "time_zone": "Europe/London",
    })["settings"])["cadence"]
    before = due_slot(cadence, datetime(2026, 11, 23, 7, 29, tzinfo=timezone.utc))
    after = due_slot(cadence, datetime(2026, 11, 26, 19, 5, tzinfo=timezone.utc))
    assert before.slot_id == "weekly:2026-11-16"
    assert after.slot_id == "weekly:2026-11-23"
    assert after.due_at.isoformat() == "2026-11-23T07:30:00+00:00"
    assert after.next_at.isoformat() == "2026-11-30T07:30:00+00:00"


def test_dst_repeat_keeps_one_slot_and_nonexistent_time_waits_for_real_time():
    cadence = validate_settings(configure_body(cadence={
        "frequency": "daily", "local_time": "01:30", "time_zone": "Europe/London",
    })["settings"])["cadence"]
    first = due_slot(cadence, datetime(2026, 10, 25, 0, 40, tzinfo=timezone.utc))
    second = due_slot(cadence, datetime(2026, 10, 25, 1, 40, tzinfo=timezone.utc))
    assert first == second and first.slot_id == "daily:2026-10-25"
    spring_before = due_slot(cadence, datetime(2026, 3, 29, 1, 29, tzinfo=timezone.utc))
    spring_after = due_slot(cadence, datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc))
    assert spring_before.slot_id == "daily:2026-03-28"
    assert spring_after.slot_id == "daily:2026-03-29"


@pytest.mark.parametrize("roster", [None, {"mode": "universe", "universe_id": ""}])
def test_enabled_schedule_needs_explicit_company_scope(roster):
    with pytest.raises(ValueError, match="roster"):
        validate_settings(configure_body(roster=roster)["settings"])
