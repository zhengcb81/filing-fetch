"""Durable owner T3 assurance results using synthetic, offline execution only."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
import subprocess
import sys
from threading import Event
import unittest

import pytest

import ff_t3_receipt as receipt


def _succeed(report):
    for case in reversed(receipt.T3_CASES):
        report(case, "passed", None)


def test_offline_owner_run_retains_four_cases_and_never_restarts(tmp_path):
    calls = []

    def execute(report):
        calls.append("started")
        _succeed(report)

    first = receipt._run_once(tmp_path, "weekly-one", execute)
    assert first["mode"] == "offline"
    assert first["state"] == "completed"
    assert set(first["cases"]) == set(receipt.T3_CASES)
    assert all(row["outcome"] == "passed" and row["evidence_ref"]
               for row in first["cases"].values())
    before = {file.name: file.read_bytes() for file in tmp_path.iterdir()}
    assert receipt.get_receipt(tmp_path, "weekly-one") == first
    assert receipt._run_once(tmp_path, "weekly-one", execute) == first
    assert {file.name: file.read_bytes() for file in tmp_path.iterdir()} == before
    assert calls == ["started"]


def test_get_missing_receipt_has_no_write(tmp_path, capsys):
    path = tmp_path / "unused"
    assert receipt.main(["--receipts-dir", str(path), "get", "--run-id", "missing"]) == 2
    value = json.loads(capsys.readouterr().out)
    assert value == {"schema_version": "ff-t3-assurance/1", "run_id": "missing", "state": "missing"}
    assert not path.exists()


def test_same_count_different_case_is_partial_not_complete(tmp_path):
    def execute(report):
        for case in ("cn_annual", "hk_annual", "us_annual", "unrelated"):
            report(case, "passed", None)

    value = receipt._run_once(tmp_path, "wrong-case", execute)
    assert value["state"] == "blocked"
    assert value["reason"] == "case_results_incomplete"
    assert set(value["cases"]) == {"cn_annual", "hk_annual", "us_annual"}


def test_known_failure_and_blocked_cleanup_independent(tmp_path):
    def execute(report):
        report("cn_annual", "failed", "assertion_failed")
        report("hk_annual", "blocked", "test_skipped")
        report("us_annual", "passed", None)
        report("corrupt_original", "passed", None)

    value = receipt._run_once(tmp_path, "mix", execute)
    assert value["state"] == "blocked"
    assert value["cases"]["cn_annual"]["outcome"] == "failed"
    assert value["cases"]["hk_annual"]["outcome"] == "blocked"
    assert value["cases"]["us_annual"]["outcome"] == "passed"


def test_abrupt_process_death_preserves_partial_and_refuses_second_execution(tmp_path):
    script_dir = str(Path(receipt.__file__).resolve().parent)
    child = r"""
import os
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
import ff_t3_receipt as receipt

def execution(report):
    report("cn_annual", "passed", None)
    os._exit(29)

receipt._run_once(Path(sys.argv[2]), "lost", execution)
"""
    run = subprocess.run(
        [sys.executable, "-B", "-c", child, script_dir, str(tmp_path)],
        capture_output=True, timeout=20, check=False,
    )
    assert run.returncode == 29, run.stderr.decode("utf-8", errors="replace")
    persisted, = tmp_path.glob("*.json")
    before = persisted.read_bytes()
    recovered = receipt.get_receipt(tmp_path, "lost")
    assert recovered["state"] == "unknown"
    assert recovered["reason"] == "owner_interrupted"
    assert tuple(recovered["cases"]) == ("cn_annual",)
    assert persisted.read_bytes() == before
    cold = subprocess.run(
        [sys.executable, "-B", str(Path(script_dir) / "ff_t3_receipt.py"),
         "--receipts-dir", str(tmp_path), "get", "--run-id", "lost"],
        cwd=tmp_path, capture_output=True, timeout=20, check=False,
    )
    assert cold.returncode == 0 and json.loads(cold.stdout) == recovered
    assert persisted.read_bytes() == before

    def never(_report):
        pytest.fail("a claimed run must never execute again")

    assert receipt._run_once(tmp_path, "lost", never) == recovered
    assert persisted.read_bytes() == before


def test_old_optional_diagnostics_are_safely_ignored(tmp_path):
    result = receipt._run_once(tmp_path, "old", _succeed)
    path, = tmp_path.glob("*.json")
    stored = json.loads(path.read_bytes())
    stored["diagnostic"] = {"old": "sensitive-path-token"}
    stored["cases"]["cn_annual"]["trace"] = "sensitive-path-token"
    path.write_text(json.dumps(stored), encoding="utf-8")

    assert receipt.get_receipt(tmp_path, "old") == result
    assert "sensitive-path-token" in path.read_text(encoding="utf-8")


def test_damaged_receipt_never_reopens_a_claim(tmp_path):
    receipt._run_once(tmp_path, "damaged", _succeed)
    stored, = tmp_path.glob("*.json")
    stored.write_bytes(b"{")

    def never(_report):
        pytest.fail("unknown persisted bytes cannot authorize a repeated run")

    result = receipt._run_once(tmp_path, "damaged", never)
    assert result["state"] == "unknown" and result["reason"] == "receipt_unreadable"
    assert stored.read_bytes() == b"{"

def test_existing_running_record_never_calls_another_executor(tmp_path):
    started = Event()
    finish = Event()

    def execute(report):
        started.set()
        assert finish.wait(10), "the test must release the owner execution"
        _succeed(report)

    def never(_report):
        pytest.fail("existing owner run must not launch extra work")

    with ThreadPoolExecutor(max_workers=1) as executor:
        original = executor.submit(receipt._run_once, tmp_path, "still-running", execute)
        try:
            assert started.wait(10)
            prior = receipt.get_receipt(tmp_path, "still-running")
            assert prior["state"] == "running"
            assert receipt._run_once(tmp_path, "still-running", never) == prior
        finally:
            finish.set()
        assert original.result(10)["state"] == "completed"


def test_native_dispatch_shape_can_be_replayed_offline(tmp_path, monkeypatch):
    fixture = tmp_path / "tests" / "test_e2e_download.py"
    fixture.parent.mkdir()
    methods = "\n".join(
        f"    def {method}(self): self.assertEqual(os.environ['FILING_FETCH_E2E_DOWNLOAD'], '1')"
        for method in receipt.T3_CASES.values()
    )
    fixture.write_text(
        "import os, unittest\n"
        "class DownloadE2E(unittest.TestCase):\n" + methods + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(receipt, "PROJECT", tmp_path)
    monkeypatch.setenv("FILING_FETCH_E2E_DOWNLOAD", "0")

    def fixture_execution(report):
        receipt._execute_native_suite(report)

    value = receipt._run_once(tmp_path / "receipts", "fixture-dispatch", fixture_execution)
    assert value["mode"] == "offline" and value["state"] == "completed"
    assert set(value["cases"]) == set(receipt.T3_CASES)
    assert os.environ["FILING_FETCH_E2E_DOWNLOAD"] == "0"


def test_native_warnings_are_cold_readable_without_emitting_raw_streams(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "tests" / "test_e2e_download.py"
    fixture.parent.mkdir()
    methods = "\n".join(f"    def {method}(self): pass" for method in receipt.T3_CASES.values())
    fixture.write_text(
        "import sys, unittest, warnings\n"
        "print('private stdout')\n"
        "print('private stderr', file=sys.stderr)\n"
        "warnings.warn('private warning body', ResourceWarning)\n"
        "class DownloadE2E(unittest.TestCase):\n" + methods + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(receipt, "PROJECT", tmp_path)
    monkeypatch.setenv("FILING_FETCH_E2E_DOWNLOAD", "0")
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("always", ResourceWarning)
        command = ["--receipts-dir", str(tmp_path / "receipt")]
        assert receipt.main([*command, "run-live", "--run-id", "synthetic-native"]) == 0
    first = capsys.readouterr()
    assert receipt.main([*command, "get", "--latest"]) == 0
    cold = capsys.readouterr()
    assert cold.out == first.out and cold.err == first.err == ""
    value = json.loads(cold.out)
    assert value["suite_output"] == {
        "stdout_observed": True, "stderr_observed": True,
        "warnings": [{"type": "ResourceWarning", "file": "test_e2e_download.py", "line": 4}],
    }
    assert "private" not in cold.out


def test_latest_io_error_includes_cause_without_path_or_new_receipt(tmp_path, monkeypatch, capsys):
    def fail(_root):
        raise PermissionError(13, "private failure text", str(tmp_path / "private-path"))

    monkeypatch.setattr(receipt, "get_latest_receipt", fail)
    assert receipt.main(["--receipts-dir", str(tmp_path), "get", "--latest"]) == 1
    streams = capsys.readouterr()
    value = json.loads(streams.out)
    assert value["state"] == "unknown" and value["reason"] == "receipt_io_failed"
    assert value["diagnostic"]["causes"][0]["type"] == "PermissionError"
    assert value["diagnostic"]["causes"][0]["errno"] == 13
    assert streams.err == "" and "private" not in streams.out
    assert not list(tmp_path.iterdir())


def test_structured_unittest_events_reflect_cleanup_and_redact_raw_failure():
    observed = {}

    diagnostics = {}

    def received(case, outcome, reason, detail):
        observed[case] = (outcome, reason)
        if detail is not None:
            diagnostics[case] = detail

    class Fixture(unittest.TestCase):
        def test_download_cn_annual_report(self):
            self.addCleanup(self.fail, "secret-cleanup-detail")

        def test_download_hk_annual_report(self):
            self.skipTest("secret-skip-detail")

        def test_download_us_annual_report(self):
            raise RuntimeError("secret-exception-detail")

        def test_download_rejects_corrupted_local_copy(self):
            self.addCleanup(lambda: None)

    suite = unittest.TestSuite(Fixture(name) for name in receipt.T3_CASES.values())
    suite.run(receipt._CaseResults(received))
    assert observed == {
        "cn_annual": ("failed", "assertion_failed"),
        "hk_annual": ("blocked", "test_skipped"),
        "us_annual": ("failed", "test_error"),
        "corrupt_original": ("passed", None),
    }
    assert diagnostics["cn_annual"]["causes"][0]["type"] == "AssertionError"
    assert diagnostics["us_annual"]["causes"][0]["type"] == "RuntimeError"
    assert "secret-" not in json.dumps(diagnostics)


def test_latest_uses_claim_start_and_does_not_hide_a_damaged_newest(tmp_path, monkeypatch, capsys):
    class Clock(datetime):
        current = datetime(2026, 11, 25, 9, 0, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current

    monkeypatch.setattr(receipt, "datetime", Clock)
    command = ["--receipts-dir", str(tmp_path), "get", "--latest"]
    assert receipt.main(command) == 2
    assert json.loads(capsys.readouterr().out)["state"] == "missing"

    previous = receipt._run_once(tmp_path, "old-week", _succeed)
    Clock.current = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
    latest = receipt._run_once(tmp_path, "recent-week", _succeed)
    older_path = receipt._existing(tmp_path, receipt._key("old-week"))
    newer_path = receipt._existing(tmp_path, receipt._key("recent-week"))
    os.utime(older_path, (2_000_000_000, 2_000_000_000))
    assert receipt.main(command) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == latest and result["started_at"] > previous["started_at"]

    newer_path.write_bytes(b"{")
    assert receipt.main(command) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["state"] == "unknown" and result["reason"] == "receipt_unreadable"
    assert newer_path.read_bytes() == b"{"


def test_cli_distingishes_lookup_and_execution_of_existing_runs(tmp_path, capsys):
    def failure(report):
        report("cn_annual", "failed", "assertion_failed")

    failed = receipt._run_once(tmp_path, "failed", failure)
    good = receipt._run_once(tmp_path, "offline-only", _succeed)
    prefix = ["--receipts-dir", str(tmp_path)]
    assert receipt.main([*prefix, "get", "--run-id", "failed"]) == 0
    assert json.loads(capsys.readouterr().out) == failed

    # Both IDs already exist. These requests must never invoke the native suite.
    assert receipt.main([*prefix, "run-live", "--run-id", "failed"]) == 1
    assert json.loads(capsys.readouterr().out) == failed
    assert receipt.main([*prefix, "run-live", "--run-id", "offline-only"]) == 2
    assert json.loads(capsys.readouterr().out) == good

    finished_live = {**good, "mode": "live"}  # pure exit-code test, never persisted/emitted
    assert receipt._live_exit(finished_live) == 0
    assert receipt._live_exit({**finished_live, "state": "unknown"}) == 2
    assert receipt._live_exit({**finished_live, "cases": {}}) == 2


def test_public_case_evidence_contains_cold_sanitized_diagnostic(tmp_path):
    def execute(report):
        try:
            raise PermissionError(13, "secret-owner-message", str(tmp_path / "secret-owner-path"))
        except PermissionError as error:
            detail = receipt.cause_details(error, reason="test_error")
        report("cn_annual", "failed", "test_error", detail)

    first = receipt._run_once(tmp_path, "owner-cause", execute)
    cold = subprocess.run(
        [sys.executable, "-B", str(Path(receipt.__file__).resolve()),
         "--receipts-dir", str(tmp_path), "get", "--run-id", "owner-cause"],
        cwd=tmp_path, timeout=20, capture_output=True, check=False,
    )
    assert cold.returncode == 0 and json.loads(cold.stdout) == first
    case = json.loads(cold.stdout)["cases"]["cn_annual"]
    assert case["evidence_ref"] == "ff-t3/owner-cause/cn_annual"
    assert case["diagnostic"]["causes"][0]["type"] == "PermissionError"
    assert case["diagnostic"]["causes"][0]["errno"] == 13
    assert b"secret-owner" not in cold.stdout


def test_malformed_legacy_diagnostic_cannot_publish_paths_or_free_text(tmp_path):
    def execute(report):
        report("cn_annual", "failed", "test_error", {
            "schema_version": "ff-failure-detail/1",
            "reason": "test_error",
            "owner_reason": "reader_unavailable",
            "message": "secret-message",
            "causes": [
                "secret-legacy-string",
                {"relation": "raised", "type": "OSError", "errno": 2,
                 "message": "secret-cause",
                 "frames": [{"file": str(tmp_path / "secret-path.py"), "function": "owner_stage",
                             "line": 123, "message": "secret-frame"}]},
            ],
        })

    value = receipt._run_once(tmp_path, "old-details", execute)
    observed = value["cases"]["cn_annual"]["diagnostic"]
    assert observed["owner_reason"] == "reader_unavailable"
    assert observed["causes"] == [{
        "relation": "raised", "type": "OSError", "errno": 2,
        "frames": [{"function": "owner_stage", "line": 123}],
    }]
    assert "secret-" not in json.dumps(value)
