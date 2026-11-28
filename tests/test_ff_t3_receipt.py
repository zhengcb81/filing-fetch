"""Durable owner T3 assurance results using synthetic, offline execution only."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Event

import pytest

from ff_runtime_feedback import owner_child_environment
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
import shutil
import sys
sys.path.insert(0, sys.argv[1])
import ff_t3_native as native
import ff_t3_receipt as receipt
def execution(report):
    report("cn_annual", "passed", None)
    os._exit(29)

receipt._run_once(Path(sys.argv[2]), "lost", execution)
"""
    run = subprocess.run(
        [sys.executable, "-B", "-c", child, script_dir, str(tmp_path)],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=20, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
        cwd=tmp_path, stdin=subprocess.DEVNULL, capture_output=True, timeout=20, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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


def test_installed_t3_executes_bound_owner_protocol_once_without_tests(tmp_path):
    shipped = tmp_path / "scripts"
    shutil.copytree(Path(receipt.__file__).parent, shipped)
    owner = tmp_path / "workspace_owner.py"
    owner.write_text(r"""
import json, sys
from pathlib import Path

root = Path(__file__).parent
request = json.load(sys.stdin)
assert request.pop("schema_version") == "cwp-t3-workspace-request/1"
case = request["case_id"]
workspace_id = "isolated-" + case
proof = root / workspace_id
with (root / "actions.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(request) + chr(10))
operation = request["operation"]
response = {"schema_version": "cwp-t3-workspace/1", **request, "workspace_id": workspace_id}
if operation == "open":
    proof.mkdir()
    response.update(status="opened", connection={
        "cwd": str(proof),
        "commands": {"catalog": [sys.executable, "-B", str(Path(__file__))]},
    })
elif operation == "observe":
    assert request["workspace_id"] == workspace_id and proof.is_dir()
    facts = {"no_residue": True, "downloaded_new": 1, "sha256": "a" * 64, "source_id": "source-" + case,
             "mtime_ns": 1722448888, "provenance_complete": True, "reused_before_download": True}
    if case == "corrupt_original":
        facts.update(corrupt_original_unchanged=True, downloaded_new=0)
    response.update(status="observed", facts=facts)
else:
    assert operation == "close" and request["workspace_id"] == workspace_id
    proof.rmdir()
    response.update(status="closed")
print(json.dumps(response))
""", encoding="utf-8")
    (shipped / "fetch_filing.py").write_text(r"""
import argparse, json, sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--config", type=Path, required=True)
parser.add_argument("--jobs-dir", type=Path, required=True)
parser.add_argument("--timeout-seconds", type=int, required=True)
parser.add_argument("--allow-download", action="store_true")
args = parser.parse_args()
config = json.loads(args.config.read_text())["connection"]
workspace = Path(config["cwd"])
assert workspace.is_dir() and "catalog" in config["commands"]
request = json.load(sys.stdin)
assert args.timeout_seconds == 180
assert args.jobs_dir.parent == args.config.parent
if args.allow_download:
    assert request["acquisition_limits"] == {
        "max_bytes": 52428800, "timeout_seconds": 180, "max_cost_usd": "0",
    }
calls = workspace.parent / "fetch.jsonl"
previous = calls.read_text().splitlines() if calls.exists() else []
with calls.open("a", encoding="utf-8") as stream:
    stream.write(workspace.name + chr(10))
if workspace.name == "isolated-corrupt_original":
    mode = "ensure" if args.allow_download else "reuse"
    print(json.dumps({"status": "upstream_error", "downloads": 0,
                      "upstream_cause": {"operation": mode, "provider_started": False}}))
    sys.exit(2)
print(json.dumps({"status": "capture_ready", "downloads": int(workspace.name not in previous),
                  "handle": {"capture_ready": True, "snapshot_sha256": "a" * 64,
                             "source_id": workspace.name.replace("isolated-", "source-", 1)}}))
""", encoding="utf-8")
    config = tmp_path / "connection.json"
    config.write_text(json.dumps({"schema_version": "1.0", "connection": {
        "cwd": str(tmp_path), "commands": {"t3_workspace": [sys.executable, "-B", str(owner)]},
    }}), encoding="utf-8")
    command = [sys.executable, "-B", str(shipped / "ff_t3_receipt.py"),
               "--receipts-dir", str(tmp_path / "receipts")]
    options = ["run-live", "--run-id", "original", "--config", str(config)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    def invoke(*action):
        result = subprocess.run(
            [*command, *action], cwd=tmp_path, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=48, check=False, creationflags=flags,
        )
        if result.returncode != 0:
            pytest.fail(result.stdout.decode("ascii"))
        return json.loads(result.stdout)
    first = invoke(*options)
    assert first["mode"] == "live" and first["state"] == "completed"
    assert set(first["cases"]) == set(receipt.T3_CASES)
    assert all(row["outcome"] == "passed" for row in first["cases"].values())
    assert invoke(*options) == invoke("get", "--run-id", "original") == first
    actions = [json.loads(line) for line in (tmp_path / "actions.jsonl").read_text().splitlines()]
    for case in receipt.T3_CASES:
        chosen = [action for action in actions if action["case_id"] == case]
        expected = ["open", "observe", "close"] if case == "corrupt_original" else [
            "open", "observe", "observe", "close",
        ]
        assert [action["operation"] for action in chosen] == expected
        assert {action["run_id"] for action in chosen} == {"original"}
    assert len((tmp_path / "fetch.jsonl").read_text().splitlines()) == 8
    assert not list(tmp_path.glob("isolated-*"))
    assert not (tmp_path / "tests").exists()


def test_lost_open_reply_closes_original_scope_without_dispatch(tmp_path):
    owner = tmp_path / "workspace_owner.py"
    owner.write_text(r'''
import json
from pathlib import Path
import sys

request = json.load(sys.stdin)
run, case, operation = (request[k] for k in ("run_id", "case_id", "operation"))
root = Path(__file__).parent
scope = root / (run + "-" + case)
with (root / "actions.jsonl").open("a", encoding="utf-8") as trace:
    trace.write(json.dumps([operation, run, case]) + "\n")
if operation == "open":
    scope.mkdir()
    print("{")  # The provider opened the workspace, but FF lost the reply.
elif operation == "close":
    assert "workspace_id" not in request
    scope.rmdir()
    print(json.dumps({"schema_version": "cwp-t3-workspace/1", "operation": operation,
                      "run_id": run, "case_id": case, "status": "closed",
                      "workspace_id": "t3-" + "a" * 32}))
else:
    raise AssertionError("Unexpected dispatch after a lost open response")
''', encoding="utf-8")
    config = tmp_path / "connection.json"
    config.write_text(json.dumps({"schema_version": "1.0", "connection": {
        "cwd": str(tmp_path), "commands": {"t3_workspace": [sys.executable, "-B", str(owner)]},
    }}), encoding="utf-8")
    command = [
        sys.executable, "-B", str(Path(receipt.__file__)), "--receipts-dir", str(tmp_path / "receipts"),
    ]
    options = ["run-live", "--run-id", "original", "--config", str(config)]

    def invoke(*args):
        return subprocess.run(
            [*command, *args], cwd=tmp_path, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=35, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    first = invoke(*options)
    original = json.loads(first.stdout)
    assert first.returncode != 0
    assert set(original["cases"]) == set(receipt.T3_CASES)
    assert all(row["outcome"] == "failed" for row in original["cases"].values())
    assert original == json.loads(invoke("get", "--run-id", "original").stdout)
    assert original == json.loads(invoke(*options).stdout)
    expected = [[operation, "original", case] for case in receipt.T3_CASES
                for operation in ("open", "close")]
    observed = [json.loads(row) for row in (tmp_path / "actions.jsonl").read_text().splitlines()]
    assert observed == expected
    assert not list(tmp_path.glob("original-*"))


def test_native_warnings_are_cold_readable_without_emitting_raw_streams(tmp_path, monkeypatch, capsys):
    import warnings

    def local_cases(report, **_):
        print("private stdout")
        print("private stderr", file=sys.stderr)
        warnings.warn("private warning body", ResourceWarning)
        _succeed(report)

    monkeypatch.setattr(receipt, "run_cases", local_cases)
    with warnings.catch_warnings():
        warnings.simplefilter("always", ResourceWarning)
        command = ["--receipts-dir", str(tmp_path / "receipt")]
        assert receipt.main([*command, "run-live", "--run-id", "synthetic-native"]) == 0
    first = capsys.readouterr()
    assert receipt.main([*command, "get", "--latest"]) == 0
    cold = capsys.readouterr()
    assert cold.out == first.out and cold.err == first.err == ""
    value = json.loads(cold.out)
    output = value["suite_output"]
    assert output["stdout_observed"] and output["stderr_observed"]
    warning, = output["warnings"]
    assert warning["type"] == "ResourceWarning" and warning["file"] == Path(__file__).name
    assert warning["line"] > 0
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


def test_unconfigured_workspace_is_blocked_without_guessing_a_sibling(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.setenv("RESEARCH_FEEDBACK_DIR", str(tmp_path / "feedback"))
    def no_home():
        raise RuntimeError("local account has no home directory")
    monkeypatch.setattr(Path, "home", staticmethod(no_home))
    config = tmp_path / "old.json"
    config.write_text(json.dumps({"schema_version": "1.0", "company_wiki_root": str(tmp_path)}))
    prefix = ["--receipts-dir", str(tmp_path / "receipt")]
    assert receipt.main([
        *prefix, "run-live", "--run-id", "without-port", "--config", str(config),
    ]) == 2
    first = json.loads(capsys.readouterr().out)
    assert first["state"] == "blocked"
    assert {case["reason"] for case in first["cases"].values()} == {"workspace_not_configured"}
    assert receipt.main([*prefix, "get", "--run-id", "without-port"]) == 0
    assert json.loads(capsys.readouterr().out) == first


def test_structured_native_events_reflect_cleanup_and_redact_raw_failure(tmp_path, monkeypatch):
    import ff_t3_native as native

    observed = {}

    def received(case, outcome, reason, detail):
        observed[case] = (outcome, reason, detail)

    def local_case(_workspace, _run, case):
        if case == "cn_annual":
            raise AssertionError("secret-cleanup-detail")
        if case == "us_annual":
            raise RuntimeError("secret-exception-detail")

    monkeypatch.setattr(native, "WorkspaceClient", lambda *args, **kwargs: object())
    monkeypatch.setattr(native, "probe_case", local_case)
    native.run_cases(received, config=tmp_path / "config", run_id="fixture")
    assert {case: facts[:2] for case, facts in observed.items()} == {
        "cn_annual": ("failed", "assertion_failed"),
        "hk_annual": ("passed", None),
        "us_annual": ("failed", "test_error"),
        "corrupt_original": ("passed", None),
    }
    assert observed["cn_annual"][2]["causes"][0]["type"] == "AssertionError"
    assert observed["us_annual"][2]["causes"][0]["type"] == "RuntimeError"
    assert "secret-" not in json.dumps(observed)


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
        cwd=tmp_path, timeout=20, stdin=subprocess.DEVNULL, capture_output=True, check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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


def test_native_short_probe_uses_explicit_jobs_dir(tmp_path):
    shutil.copytree(Path(receipt.__file__).parent, tmp_path / "scripts")
    entry = tmp_path / "scripts" / "fetch_filing.py"
    root = tmp_path / "isolated-jobs"
    completed = subprocess.run(
        [sys.executable, "-B", str(entry), "--jobs-dir", str(root)],
        input=b"invalid JSON", cwd=tmp_path, env=owner_child_environment(),
        capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["status"] == "request_error"
    records = list((root / "observations-direct-runs").glob("*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text(encoding="utf-8"))["outcome"]["exit_code"] == 2
    assert not (tmp_path / ".ff_jobs").exists()
