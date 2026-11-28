"""Subprocess controls for the job, diagnostics and statements lifecycle boundaries."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
REQUEST = {
    "schema_version": "financial-statements-request/1",
    "company_query": "synthetic company",
    "market": "CN",
    "statements": ["balance_sheet", "income_statement"],
    "knowledge_mode": "current_snapshot",
    "intent": "fetch_if_missing",
    "acquisition_limits": {"max_bytes": 100000, "timeout_seconds": 15, "max_cost_usd": "0.00"},
}
FAKE_STATEMENTS = r'''
import json
import pathlib
import sys
import time

root = pathlib.Path(sys.argv[1])
mode = sys.argv[2]
request = json.load(sys.stdin)
lookup = request["intent"] == "reuse_only"
if lookup:
    assert "acquisition_limits" not in request
else:
    assert request["acquisition_limits"]["max_bytes"] == 100000
with (root / "calls").open("a", encoding="utf-8") as calls:
    print("lookup" if lookup else mode, file=calls, flush=True)
if mode == "block_terminal_log":
    log, = (root / "jobs" / "logs").glob("ffjob-*.log")
    log.rename(log.with_suffix(".previous"))
    log.mkdir()
elif mode == "park" and not lookup:
    # The target has consumed the request but has no outcome yet.
    time.sleep(4)
elif mode == "hold":
    while not (root / "release").is_file():
        time.sleep(0.01)
usage = dict(http_requests=1, response_bytes=315, cost_usd="0.00")
bad = mode == "partial"
tables = [
    dict(statement_type="balance_sheet", status="unavailable", error_code="provider_unavailable",
         coverage=dict(terminal_reason="provider_error")) if bad else
    dict(statement_type="balance_sheet", status="complete"),
    dict(statement_type="income_statement", status="complete",
         reports=[dict(value="private-statement-fixture")]),
]
print(json.dumps(dict(schema_version="financial-statements-response/1",
                      status="partial" if bad else "complete", statements=tables, usage=usage)))
'''


class Case:
    def __init__(self, tmp_path, mode):
        self.root = tmp_path
        self.scripts = SCRIPTS
        self.jobs = tmp_path / "jobs"
        self.inbox = tmp_path / "in"
        self.config = tmp_path / "config.json"
        self.calls = tmp_path / "calls"
        child = tmp_path / "statements.py"
        child.write_text(FAKE_STATEMENTS, encoding="utf-8")
        self.config.write_text(json.dumps({
            "schema_version": "1.0",
            "connection": {
                "cwd": str(tmp_path),
                "commands": {"financial_statements": [sys.executable, "-B", str(child), str(tmp_path), mode]},
            },
        }), encoding="utf-8")
        self.env = {name: value for name, value in os.environ.items()
                    if not name.startswith("RESEARCH_FEEDBACK_")}
        self.env.update(RESEARCH_FEEDBACK_DIR=str(self.inbox), PYTHONUTF8="1")

    def argv(self, script, *args):
        return [sys.executable, "-B", str(self.scripts / script), *args]

    def invoke(self, script, *args, body=None):
        return subprocess.run(
            self.argv(script, *args), input=json.dumps(body).encode("utf-8") if body is not None else None,
            env=self.env, cwd=self.root, capture_output=True, timeout=15, creationflags=NO_WINDOW,
        )

    def job(self, *args, body=None):
        return self.invoke("ff_job.py", "--jobs-dir", str(self.jobs), *args, body=body)

    def submit(self):
        done = self.job("submit", body={
            "schema_version": "ff-job/1", "kind": "statements.acquire",
            "idempotency_key": "fixture-only", "command_id": "fixture-only", "request": REQUEST,
        })
        assert done.returncode == 0, (done.stdout, done.stderr)
        return json.loads(done.stdout)["owner_job_id"]

    def run_job(self, jid):
        return self.job("run", "--owner-job-id", jid, "--config", str(self.config), "--timeout-seconds", "10")

    def get_job(self, jid):
        done = self.job("get_status", "--owner-job-id", jid)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)["job"]

    def diagnostic(self, reference):
        return self.invoke("ff_job_feedback.py", "get-diagnostic", reference,
                           "--observations-dir", str(self.inbox), "--jobs-dir", str(self.jobs))

    def reoffer(self, jid):
        return self.invoke("ff_job_feedback.py", "reoffer-job", "--jobs-dir", str(self.jobs), "--owner-job-id", jid)

    def flush(self, jobs=None):
        return self.invoke("ff_job_feedback.py", "flush-observations", "--jobs-dir", str(jobs or self.jobs))

    def count(self):
        return len(self.calls.read_bytes().splitlines()) if self.calls.exists() else 0

    def wait_for_dispatch(self, child):
        deadline = time.monotonic() + 7
        while self.count() == 0 and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.025)
        assert self.count() == 1


def _feedback_request(observation):
    def digest(value):
        raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("ascii")).hexdigest()

    owner = observation["owner"]
    row = dict(observation, origin_owner=owner)
    fields = ("owner", "origin_owner", "run_id", "attempt_id", "step_id", "check_id")
    occurrence = digest([row[name] for name in fields])
    action_id = digest(["reconcile", owner, occurrence])
    payload = {"observation": row, "occurrence_id": occurrence}
    return {
        "schema_version": "feedback-action/1", "owner": owner, "kind": "reconcile", "method": "lookup",
        "action_id": action_id, "payload": payload,
        "request_digest": digest([owner, "reconcile", action_id, payload]),
    }


@pytest.mark.parametrize("mode", ["ok", "block_terminal_log", "block_start_log"])
def test_job_log_unavailable_keeps_original_terminal_and_execution_evidence(tmp_path, mode):
    case = Case(tmp_path, mode)
    if mode == "block_start_log":
        case.jobs.mkdir()
        (case.jobs / "logs").write_text("optional sink unavailable", encoding="utf-8")
    jid = case.submit()
    result = case.run_job(jid)
    assert result.returncode == 0, (result.stdout, result.stderr)
    view = json.loads(result.stdout)["job"]
    assert view["status"] == "succeeded"
    assert view["result"]["status"] == "complete"
    assert view["result"]["usage"]["http_requests"] == 1
    assert view["cost_state"] == "known"
    assert view["attempts"] == view["execution_count"] == 1
    if mode != "ok":
        assert ("job log " + jid).encode() in result.stderr
        log = case.inbox / "logs" / "runtime-errors.jsonl"
        assert any(json.loads(line)["run_id"] == jid for line in log.read_bytes().splitlines())
    assert case.get_job(jid)["result"] == case.get_job(jid)["result"] == view["result"]
    assert case.count() == 1


@pytest.mark.parametrize("all_roots", [False, True])
def test_detail_failure_uses_readable_copy_or_leaves_original_recoverable(tmp_path, all_roots):
    case = Case(tmp_path, "partial")
    jid = case.submit()
    key = json.dumps(["filing-fetch", jid, "1", jid + "/1", "complete"], separators=(",", ":"))
    packet = "feedback-" + uuid.uuid5(uuid.NAMESPACE_URL, key).hex
    fallback = case.jobs / "observations"
    blocked = [case.inbox / (packet + ".cause.json")]
    if all_roots:
        blocked.append(fallback / (packet + ".cause.json"))
    for path in blocked:
        path.mkdir(parents=True)
    done = case.run_job(jid)
    assert done.returncode == 0, (done.stdout, done.stderr)
    terminal = json.loads(done.stdout)["job"]
    assert terminal["status"] == "succeeded" and terminal["result"]["status"] == "partial"
    if all_roots:
        assert not any((root / (packet + ".sent")).exists() for root in (case.inbox, fallback))
        assert case.diagnostic("ff-diagnostic/1/" + packet).returncode == 1
        for path in blocked:
            path.rmdir()
        assert case.get_job(jid)["result"] == terminal["result"]
        assert case.reoffer(jid).returncode == 0
    for _ in range(2):
        details = case.diagnostic("ff-diagnostic/1/" + packet)
        assert details.returncode == 0, (details.stdout, details.stderr)
        assert json.loads(details.stdout)["usage"] == {
            "http_requests": 1, "response_bytes": 315, "cost_usd": "0.00",
        }
    assert case.get_job(jid)["cost_state"] == terminal["cost_state"] == "known"
    assert case.count() == 1


def test_reconcile_state_is_durable_before_optional_log(tmp_path):
    case = Case(tmp_path, "park")
    jid = case.submit()
    args = ("--owner-job-id", jid, "--config", str(case.config), "--timeout-seconds", "10")
    child = subprocess.Popen(
        case.argv("ff_job.py", "--jobs-dir", str(case.jobs), "run", *args),
        env=case.env, cwd=case.root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW,
    )
    try:
        case.wait_for_dispatch(child)
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)

    initial = case.get_job(jid)
    assert initial["status"] == initial["cost_state"] == "unknown"
    log = case.jobs / "logs" / (jid + ".log")
    log.rename(log.with_suffix(".previous"))
    log.mkdir()
    action = ("act", "--action", "reconcile", "--idempotency-key", "original-check", *args)
    for _ in range(2):
        output = case.job(*action)
        assert output.returncode == 0, (output.stdout, output.stderr)
        view = json.loads(output.stdout)["job"]
        assert view["status"] == "succeeded" and view["cost_state"] == "unknown"
        assert view["derived_by"] == "reconcile_read_only"
    assert case.get_job(jid)["result"] == view["result"]
    assert case.calls.read_text().splitlines() == ["park", "lookup"]


@pytest.mark.parametrize("mode", ["ok", "park"])
def test_statements_direct_cold_read_reaches_same_attempt_without_work(tmp_path, mode):
    case = Case(tmp_path, mode)
    case.env.update(RESEARCH_FEEDBACK_RUN_ID="original-cli-run", RESEARCH_FEEDBACK_ATTEMPT_ID="original-attempt")
    argv = case.argv("fetch_statements.py", "--config", str(case.config), "--timeout-seconds", "10")
    child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=case.env, cwd=case.root, creationflags=NO_WINDOW)
    try:
        assert child.stdin
        request_bytes = json.dumps(REQUEST).encode("utf-8")
        child.stdin.write(request_bytes)
        child.stdin.close()
        child.stdin = None
        if mode == "park":
            case.wait_for_dispatch(child)
            child.kill()
        stdout, stderr = child.communicate(timeout=10)
        if mode == "ok":
            assert child.returncode == 0, (stdout, stderr)
            assert json.loads(stdout)["status"] == "complete"
        else:
            assert child.returncode != 0 and not stdout
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)

    markers = sorted(case.inbox.glob("*.ready"))
    assert len(markers) == 1
    rows = [json.loads(line) for line in markers[0].with_suffix(".jsonl").read_bytes().splitlines()]
    start = next(row for row in rows if row["check_id"] == "action-started")
    assert start["run_id"] == "original-cli-run" and start["attempt_id"] == "original-attempt"
    for _ in range(2):
        cold = case.invoke("ff_job_feedback.py", "get-statement-run", start["evidence_ref"],
                           "--jobs-dir", str(case.jobs))
        assert cold.returncode == 0, (cold.stdout, cold.stderr)
        native = json.loads(cold.stdout)
        result = native["result"]
        assert result["run_id"] == start["run_id"] and result["attempt_id"] == start["attempt_id"]
        assert result["request_sha256"] == hashlib.sha256(request_bytes).hexdigest()
        assert result["implementation_version"].startswith("sha256-")
        phases = [step["phase"] for step in result["steps"]]
        assert phases[:3] == ["started", "request_read", "dispatching"]
        assert result["external_effect"] == ("response_received" if mode == "ok" else "possible")
        assert result["cost_state"] == ("known" if mode == "ok" else "unknown")
        assert native["state"] == ("done" if mode == "ok" else "unknown")
        assert b"private-statement-fixture" not in cold.stdout
        recovered = case.invoke("ff_job_feedback.py", "reconcile", "--jobs-dir", str(case.jobs),
                                body=_feedback_request(start))
        assert recovered.returncode == 0, recovered.stderr
        receipt = json.loads(recovered.stdout)
        assert receipt["state"] == "done"
        assert receipt["result"]["trace"] == result
        assert receipt["result"]["job_status"] == ("succeeded" if mode == "ok" else "interrupted")
        assert receipt["result"]["new_provider_requests"] == 0
    mismatch = case.invoke("ff_job_feedback.py", "reconcile", "--jobs-dir", str(case.jobs),
                           body=_feedback_request(dict(start, attempt_id="another-attempt")))
    assert mismatch.returncode == 0 and json.loads(mismatch.stdout) == {"state": "unknown"}
    assert case.count() == 1


def test_statements_pre_dispatch_rejection_proves_no_request_and_preserves_protocol(tmp_path):
    case = Case(tmp_path, "ok")
    proc = case.invoke("fetch_statements.py", "--config", str(case.config), body=dict(REQUEST, market="bad"))
    assert proc.returncode == 2 and json.loads(proc.stdout)["status"] == "request_error"
    marker, = case.inbox.glob("*.ready")
    start = json.loads(marker.with_suffix(".jsonl").read_bytes().splitlines()[0])
    data = case.invoke("ff_job_feedback.py", "get-statement-run", start["evidence_ref"],
                       "--jobs-dir", str(case.jobs))
    result = json.loads(data.stdout)["result"]
    assert result["external_effect"] == "not_started" and result["cost_state"] == "not_applicable"
    assert result["outcome"]["diagnostic"]["causes"][0]["type"] == "FilingFetchError"
    assert case.count() == 0


def test_status_is_read_only_when_original_job_observations_need_repair(tmp_path):
    case = Case(tmp_path, "partial")
    jid = case.submit()
    result = case.run_job(jid)
    assert result.returncode == 0, result.stderr
    for output in case.inbox.glob("feedback-*"):
        output.unlink()
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert case.get_job(jid)["result"]["status"] == "partial"
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before

    for _ in range(2):
        recovered = case.reoffer(jid)
        assert recovered.returncode == 0, recovered.stderr
    marker, = case.inbox.glob("*.ready")
    rows = [json.loads(line) for line in marker.with_suffix(".jsonl").read_bytes().splitlines()]
    assert {row["run_id"] for row in rows} == {jid}
    assert case.count() == 1


def test_short_filing_cold_run_has_original_input_and_version(tmp_path):
    case = Case(tmp_path, "ok")
    case.env.update(RESEARCH_FEEDBACK_RUN_ID="short-original", RESEARCH_FEEDBACK_ATTEMPT_ID="short-attempt")
    request = {
        "schema_version": "2.0", "mode": "exact", "company_query": "Sample plc",
        "market": "CN", "document_kind": "annual_report", "fiscal_year": 2024, "as_of_date": "2025-08-01",
        "filing_intent": "unsupported-intent",
    }
    result = case.invoke("fetch_filing.py", "--config", str(case.config), body=request)
    assert result.returncode == 2 and json.loads(result.stdout)["status"] == "request_error"
    cold = case.invoke("ff_job_feedback.py", "get-direct-run", "--run-id", "short-original",
                       "--attempt-id", "short-attempt", "--jobs-dir", str(case.jobs))
    assert cold.returncode == 0, cold.stderr
    reply = json.loads(cold.stdout)
    trace = reply["result"]
    assert reply["state"] == "done" and trace["implementation_version"].startswith("sha256-")
    assert trace["evidence_ref"].startswith("ff-short/1/")
    assert trace["input"]["request"] == request
    assert trace["request_sha256"] == hashlib.sha256(json.dumps(request).encode()).hexdigest()
    assert trace["outcome"]["diagnostic"]["reason"].startswith("request_error")
    assert trace["external_effect"] == "not_started" and trace["cost_state"] == "not_applicable"
    assert case.count() == 0


def test_direct_statement_delivery_reoffered_from_receipt_without_repeat(tmp_path):
    from ff_persistence import owner_io_path

    case = Case(tmp_path, "hold")
    # Scope the fallback native directory to this owner fixture.
    case.scripts = tmp_path / "scripts"
    shutil.copytree(SCRIPTS, case.scripts, ignore=shutil.ignore_patterns("__pycache__"))
    argv = case.argv("fetch_statements.py", "--config", str(case.config), "--timeout-seconds", "20")
    child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=case.env, cwd=tmp_path, creationflags=NO_WINDOW)
    try:
        assert child.stdin
        child.stdin.write(json.dumps(REQUEST).encode())
        child.stdin.close()
        child.stdin = None
        case.wait_for_dispatch(child)
        marker, = case.inbox.glob("*.ready")
        start = json.loads(marker.with_suffix(".jsonl").read_bytes().splitlines()[0])
        keys = ("owner", "run_id", "attempt_id", "step_id")
        key = json.dumps([*[start[field] for field in keys], "complete"], separators=(",", ":"))
        packet = "feedback-" + uuid.uuid5(uuid.NAMESPACE_URL, key).hex
        blocked = [
            owner_io_path(root / (packet + ".cause.json"))
            for root in (case.inbox, tmp_path / ".ff_jobs" / "observations")
        ]
        for path in blocked:
            path.mkdir(parents=True)
        (tmp_path / "release").touch()
        stdout, stderr = child.communicate(timeout=25)
        assert child.returncode == 0 and json.loads(stdout)["status"] == "complete"
        assert b"feedback detail unavailable" in stderr
        assert not (case.inbox / (packet + ".jsonl")).exists()
        for path in blocked:
            path.rmdir()
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)

    def original():
        reply = case.invoke("ff_job_feedback.py", "reconcile", "--jobs-dir", str(case.jobs),
                            body=_feedback_request(start))
        assert reply.returncode == 0, reply.stderr
        return json.loads(reply.stdout)

    receipt = original()
    assert receipt["state"] == "done"
    published = case.inbox / (packet + ".jsonl")
    assert not published.exists()  # Lookup cannot perform maintenance.
    assert case.flush().returncode == 0
    ready = published.with_suffix(".ready")
    native = published.read_bytes()
    assert ready.is_file() and case.diagnostic("ff-diagnostic/1/" + packet).returncode == 0
    published.unlink()  # Only the offered packet is lost before the confirmation.
    assert published.with_suffix(".sent").is_file()
    assert original() == receipt and not published.exists()
    assert case.flush().returncode == 0 and published.read_bytes() == native
    ready.unlink()  # The legacy consumer removes ready once its database commits.
    assert original() == receipt and case.flush().returncode == 0 and not ready.exists()
    assert case.count() == 1


def test_direct_trace_survives_two_unavailable_outboxes(tmp_path):
    case = Case(tmp_path, "ok")
    case.scripts = tmp_path / "scripts"
    shutil.copytree(SCRIPTS, case.scripts, ignore=shutil.ignore_patterns("__pycache__"))
    case.env.update(RESEARCH_FEEDBACK_RUN_ID="held-by-caller", RESEARCH_FEEDBACK_ATTEMPT_ID="original")
    case.inbox.write_text("occupied", encoding="utf-8")
    native = tmp_path / ".ff_jobs" / "observations"
    native.parent.mkdir()
    native.write_text("occupied", encoding="utf-8")
    run = case.invoke("fetch_statements.py", "--config", str(case.config), body=REQUEST)
    assert run.returncode == 0 and json.loads(run.stdout)["status"] == "complete"
    cold = case.invoke("ff_job_feedback.py", "get-statement-run", "--run-id", "held-by-caller",
                       "--attempt-id", "original", "--jobs-dir", str(case.jobs))
    assert cold.returncode == 0, cold.stderr
    trace = json.loads(cold.stdout)
    assert trace["state"] == "done" and trace["result"]["outcome"]["usage"]["http_requests"] == 1
    assert case.inbox.read_text(encoding="utf-8") == "occupied"
    case.inbox.unlink()
    native.unlink()
    for _ in range(2):
        repaired = case.flush(tmp_path / ".ff_jobs")
        assert repaired.returncode == 0, (repaired.stdout, repaired.stderr)
    marker, = case.inbox.glob("*.ready")
    rows = [json.loads(line) for line in marker.with_suffix(".jsonl").read_bytes().splitlines()]
    assert {row["run_id"] for row in rows} == {"held-by-caller"}
    assert {"action-started", "execution-outcome"} <= {row["check_id"] for row in rows}
    assert sum(row["check_id"] == "action-started" for row in rows) == 1
    assert rows[0]["attempt_id"] == "original"
    assert case.count() == 1


def test_flush_recovers_original_job_when_both_outboxes_hid_success(tmp_path):
    case = Case(tmp_path, "ok")
    case.env.update(RESEARCH_FEEDBACK_RUN_ID="job-original", RESEARCH_FEEDBACK_ATTEMPT_ID="job-attempt")
    case.jobs.mkdir()
    native = case.jobs / "observations"
    for root in (native, case.inbox):
        root.write_text("outbox occupied", encoding="utf-8")
    jid = case.submit()
    ran = case.run_job(jid)
    assert ran.returncode == 0, (ran.stdout, ran.stderr)
    original = json.loads(ran.stdout)["job"]
    assert original["status"] == "succeeded" and original["cost_state"] == "known"
    for root in (native, case.inbox):
        root.unlink()
    assert case.get_job(jid) == original and not case.inbox.exists()
    for _ in range(2):
        flushed = case.flush()
        assert flushed.returncode == 0, (flushed.stdout, flushed.stderr)
    marker, = case.inbox.glob("*.ready")
    rows = [json.loads(line) for line in marker.with_suffix(".jsonl").read_bytes().splitlines()]
    assert {row["check_id"] for row in rows} == {"action-started", "job-outcome", "job-usage"}
    assert {row["run_id"] for row in rows} == {"job-original"}
    assert {row["attempt_id"] for row in rows} == {"job-attempt"}
    assert case.get_job(jid) == original
    assert case.count() == 1


def test_flush_recovers_unoffered_start_after_hard_stop_without_inventing_outcome(tmp_path):
    case = Case(tmp_path, "park")
    case.scripts = tmp_path / "scripts"
    shutil.copytree(SCRIPTS, case.scripts, ignore=shutil.ignore_patterns("__pycache__"))
    jobs = tmp_path / ".ff_jobs"
    jobs.mkdir()
    native = jobs / "observations"
    for root in (native, case.inbox):
        root.write_text("occupied", encoding="utf-8")
    case.env.update(RESEARCH_FEEDBACK_RUN_ID="interrupted-run", RESEARCH_FEEDBACK_ATTEMPT_ID="dispatch-attempt")
    child = subprocess.Popen(
        case.argv("fetch_statements.py", "--config", str(case.config), "--timeout-seconds", "12"),
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=case.env, cwd=tmp_path,
        creationflags=NO_WINDOW,
    )
    try:
        assert child.stdin is not None
        child.stdin.write(json.dumps(REQUEST).encode())
        child.stdin.close()
        case.wait_for_dispatch(child)
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=12)
    for root in (native, case.inbox):
        root.unlink()
    for _ in range(2):
        repaired = case.flush(jobs)
        assert repaired.returncode == 0, (repaired.stdout, repaired.stderr)
    marker, = case.inbox.glob("*.ready")
    rows = [json.loads(line) for line in marker.with_suffix(".jsonl").read_bytes().splitlines()]
    row, = rows
    assert (row["check_id"], row["run_id"], row["attempt_id"]) == (
        "action-started", "interrupted-run", "dispatch-attempt",
    )
    status = case.invoke("ff_job_feedback.py", "reconcile", "--jobs-dir", str(jobs), body=_feedback_request(row))
    assert status.returncode == 0, status.stderr
    receipt = json.loads(status.stdout)["result"]
    assert receipt["job_status"] == "interrupted" and receipt["cost_state"] == "unknown"
    assert receipt["trace"]["outcome"] is None and receipt["new_provider_requests"] == 0
    assert case.count() == 1


def test_public_run_and_attempt_find_redacted_replay_scope(tmp_path):
    case = Case(tmp_path, "ok")
    case.env.update(RESEARCH_FEEDBACK_RUN_ID="caller-run", RESEARCH_FEEDBACK_ATTEMPT_ID="caller-attempt")
    request = dict(REQUEST, continuation="credential-shape-not-for-logs", period_end_from="2020-01-01")
    result = case.invoke("fetch_statements.py", "--config", str(case.config), body=request)
    assert result.returncode == 0, result.stderr
    data = case.invoke("ff_job_feedback.py", "get-statement-run", "--run-id", "caller-run",
                       "--attempt-id", "caller-attempt", "--jobs-dir", str(case.jobs))
    assert data.returncode == 0, data.stderr
    assert b"credential-shape-not-for-logs" not in data.stdout
    trace = json.loads(data.stdout)["result"]
    assert trace["run_id"] == "caller-run" and trace["attempt_id"] == "caller-attempt"
    assert trace["input"]["request"]["company_query"] == REQUEST["company_query"]
    assert trace["input"]["request"]["period_end_from"] == request["period_end_from"]
    assert trace["input"]["request"]["acquisition_limits"] == REQUEST["acquisition_limits"]
    assert "continuation" not in trace["input"]["request"]
    assert "continuation" in trace["input"]["withheld"]
    assert case.count() == 1
