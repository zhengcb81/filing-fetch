"""Native feedback at the same public entry points used by direct and scheduled callers."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def cli(tmp, script, args=(), body="", **env):
    clean = {key: value for key, value in os.environ.items() if not key.startswith("RESEARCH_FEEDBACK_")}
    return subprocess.run(
        [sys.executable, "-B", "-X", "utf8", str(SCRIPTS / (script + ".py")), *map(str, args)],
        input=body,
        text=True,
        encoding="utf-8",
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        cwd=tmp,
        timeout=20,
        env={**clean, **env},
    )


def packets(directory):
    rows = []
    for signal in directory.glob("*.ready"):
        assert re.fullmatch(r"feedback-[a-f0-9]{32}", signal.stem)
        mark = json.loads(signal.read_text(encoding="utf-8"))
        packet = [
            json.loads(line) for line in signal.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert all(
            all(row[k] == mark[k] for k in ("owner", "run_id", "attempt_id", "step_id")) for row in packet
        )
        rows += packet
    return rows


def runtime_rows(directory):
    log = directory / "logs" / "runtime-errors.jsonl"
    return [json.loads(line) for line in log.read_bytes().splitlines()]


@pytest.mark.parametrize(("script", "args", "body", "code", "reason"), [
    ("ff_job", ("--jobs-dir", "state", "submit"), "[]", 2, "request_error"),
    ("ff_job_feedback", ("reconcile", "--jobs-dir", "state"), "{", 1, "reconcile_failed"),
    ("ff_t3_receipt", ("--receipts-dir", "bad-receipts", "get", "--latest"), "", 1, "receipt_io_failed"),
])
def test_public_cli_failure_lands_native_rotating_diagnostic_without_wire_noise(
    tmp_path, script, args, body, code, reason,
):
    blocked = tmp_path / "bad-receipts"
    blocked.write_text("test-private-path-marker", encoding="utf-8")
    state = tmp_path / "state"
    observed = tmp_path / "override"
    isolate = {"RESEARCH_FEEDBACK_DIR": str(observed)} if script == "ff_t3_receipt" else {}
    result = cli(tmp_path, script, args, body, **isolate,
                 RESEARCH_FEEDBACK_RUN_ID="original-run", RESEARCH_FEEDBACK_ATTEMPT_ID="original-attempt")
    assert result.returncode == code and result.stderr == ""
    envelope = json.loads(result.stdout)
    if script == "ff_job_feedback":
        assert envelope == {"error": "JSONDecodeError"}
        assert not list(observed.glob("*.ready"))  # The F4 control plane must not send itself work.
    elif script == "ff_t3_receipt":
        assert envelope["reason"] == reason and envelope["state"] == "unknown"
        assert blocked.read_text(encoding="utf-8") == "test-private-path-marker"
    else:
        assert envelope["error"]["code"] == reason
    row, = runtime_rows(observed if script == "ff_t3_receipt" else state)
    assert (row["run_id"], row["attempt_id"]) == ("original-run", "original-attempt")
    assert row["schema_version"] == "ff-runtime-log/1" and row["level"] == "warning"
    assert any(check["actual"] == reason for check in row["checks"])
    assert row["diagnostic"]["causes"][0]["type"]
    assert str(tmp_path) not in json.dumps(row) and "test-private-path-marker" not in json.dumps(row)


def test_runtime_log_fallback_keeps_the_original_job_json_and_stderr(tmp_path):
    first = cli(tmp_path, "ff_job", ["--jobs-dir", "control", "submit"], "[]")
    jobs = tmp_path / "jobs"
    blocked = tmp_path / "backup-outbox"
    blocked.write_bytes(b"untouched")
    failed_log = cli(tmp_path, "ff_job", ["--jobs-dir", jobs, "submit"], "[]",
                     RESEARCH_FEEDBACK_DIR=str(blocked), RESEARCH_FEEDBACK_RUN_ID="runtime-fallback")
    assert (failed_log.returncode, failed_log.stdout, failed_log.stderr) == (2, first.stdout, "")
    assert blocked.read_bytes() == b"untouched"
    record, = runtime_rows(jobs)
    assert record["run_id"] == "runtime-fallback"


@pytest.mark.parametrize("script", ["ff_job_feedback", "ff_t3_receipt"])
def test_control_cli_argument_refusal_uses_local_log_only(tmp_path, script):
    outbox = tmp_path / "outbox"
    result = cli(tmp_path, script, ["--private-marker"], "", RESEARCH_FEEDBACK_DIR=str(outbox),
                 RESEARCH_FEEDBACK_RUN_ID="rejected-argument")

    assert result.returncode == 2 and result.stdout == "" and "usage:" in result.stderr
    assert not list(outbox.glob("*.ready"))
    entry, = runtime_rows(outbox)
    assert entry["run_id"] == "rejected-argument" and entry["checks"][0]["actual"] == "argument_error"
    assert "private-marker" not in str(entry)


def test_unwritable_native_log_has_no_wire_effect(tmp_path):
    first = cli(tmp_path, "ff_job", ["--jobs-dir", "control", "submit"], "[]")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    blocked = jobs / "logs"
    blocked.write_bytes(b"untouched")

    result = cli(tmp_path, "ff_job", ["--jobs-dir", jobs, "submit"], "[]")

    assert (result.returncode, result.stdout, result.stderr) == (2, first.stdout, "")
    assert blocked.read_bytes() == b"untouched"
    assert any(row["actual"] == "request_error" for row in packets(jobs / "observations"))


def test_two_real_cli_processes_share_one_safe_rotation(tmp_path):
    jobs = tmp_path / "shared"
    logs = jobs / "logs"
    logs.mkdir(parents=True)
    log = logs / "runtime-errors.jsonl"
    before = json.dumps({"fixture": "x" * (2 * 1024 * 1024)}).encode("ascii") + b"\n"
    log.write_bytes(before)

    def fail(run_id):
        return cli(tmp_path, "ff_job", ["--jobs-dir", jobs, "submit"], "[]",
                   RESEARCH_FEEDBACK_RUN_ID=run_id)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(fail, ("shared-a", "shared-b")))
    assert all(result.returncode == 2 and result.stderr == "" for result in results)
    assert {row["run_id"] for row in runtime_rows(jobs)} == {"shared-a", "shared-b"}
    assert len(runtime_rows(jobs)) == 2
    assert log.with_name(log.name + ".1").read_bytes() == before


def test_torn_runtime_log_keeps_next_occurrence_independent(tmp_path):
    jobs = tmp_path / "shared"
    log = jobs / "logs" / "runtime-errors.jsonl"
    log.parent.mkdir(parents=True)
    log.write_bytes(b'{"interrupted":')

    result = cli(tmp_path, "ff_job", ["--jobs-dir", jobs, "submit"], "[]",
                 RESEARCH_FEEDBACK_RUN_ID="next-occurrence")

    assert result.returncode == 2 and result.stderr == ""
    fragment, row = log.read_bytes().splitlines()
    assert fragment == b'{"interrupted":'
    assert json.loads(row)["run_id"] == "next-occurrence"


@pytest.mark.parametrize(
    ("script", "args", "body", "code", "cause"),
    [
        ("fetch_filing", ["--timeout-seconds", "0"], "", "invalid_timeout", None),
        ("fetch_filing", ["--unused-flag-secret-sentinel"], "", "argument_error", "SystemExit"),
        ("fetch_filing", [], "{", "request_error", "JSONDecodeError"),
        ("fetch_statements", [], "{", "request_error", "JSONDecodeError"),
        ("ff_job", ["submit"], "[]", "request_error", "FFJobError"),
        ("ff_job", ["get_status", "--owner-job-id", "ffjob-000000000000"], "", "request_error", "FFJobError"),
        ("ff_scheduled_refresh", ["configure", "--request-stdin"], "[]", "request_error", "ValueError"),
    ],
)
def test_normal_failed_entrypoint_is_cold_recoverable(tmp_path, script, args, body, code, cause):
    out = tmp_path / "state" / "observations"
    env = {}
    if script in ("ff_job", "ff_scheduled_refresh"):
        args = ["--jobs-dir", tmp_path / "state", *args]
    else:
        env["RESEARCH_FEEDBACK_DIR"] = str(out)
    result = cli(tmp_path, script, args, body, **env)
    assert result.returncode == 2
    failures = [row for row in packets(out) if row["disposition"] == "deviation"]
    assert len(failures) == 1 and code in failures[0]["actual"]
    details = list(out.glob("*.cause.json"))
    assert len(details) == 1
    text = details[0].read_text(encoding="utf8")
    assert "secret-sentinel" not in text
    assert failures[0]["details_ref"].endswith(details[0].stem.split(".")[0])
    cold = cli(
        tmp_path, "ff_job_feedback", ["get-diagnostic", failures[0]["details_ref"], "--observations-dir", out]
    )
    assert cold.returncode == 0 and json.loads(cold.stdout) == json.loads(text)
    if cause:
        assert cause in text


@pytest.mark.parametrize(("args", "reason", "no_dispatch"), [
    (("get_status", "--owner-job-id", "foreign-id"), "request_error", True),
    (("allowed_actions", "--owner-job-id", "ffjob-000000000000"), "request_error", True),
    (("list_jobs",), "fatal", True),
    (("run", "--owner-job-id", "foreign-id"), "request_error", False),
    (("act", "--owner-job-id", "foreign-id", "--action", "retry", "--idempotency-key", "fixture"),
     "request_error", False),
])
def test_job_failure_reports_only_proven_no_dispatch(tmp_path, args, reason, no_dispatch):
    jobs = tmp_path / "state"
    corrupt_job = jobs / "jobs" / "ffjob-000000000000.json"
    if args[0] == "list_jobs":
        corrupt_job.parent.mkdir(parents=True)
        corrupt_job.write_text('{"error":{"unexpected":true}}', encoding="utf-8")

    result = cli(tmp_path, "ff_job", ["--jobs-dir", jobs, *args])
    envelope = json.loads(result.stdout)
    assert result.returncode == 2 and result.stderr == ""
    assert envelope["command"] == args[0] and envelope["error"]["code"] == reason
    original = packets(jobs / "observations")
    checks = {row["check_id"]: row["actual"] for row in original}
    assert checks == (
        {"execution-outcome": reason, "provider-start": "not_started", "provider-usage": "not_applicable"}
        if no_dispatch else {"execution-outcome": reason}
    )
    assert len({(row["run_id"], row["attempt_id"], row["step_id"], row["evidence_ref"])
                for row in original}) == 1
    logged, = runtime_rows(jobs)
    assert {check["check_id"]: check["actual"] for check in logged["checks"]} == checks
    assert logged["diagnostic"]["causes"][0]["type"] == "FFJobError"
    if args[0] == "list_jobs":
        assert corrupt_job.read_text(encoding="utf-8") == '{"error":{"unexpected":true}}'


def test_bare_pytest_isolates_inherited_feedback(tmp_path, tmp_path_factory):
    directory = Path(os.environ["RESEARCH_FEEDBACK_DIR"])
    assert directory.parent == tmp_path_factory.getbasetemp()
    assert directory != tmp_path
    assert not any(
        name in os.environ
        for name in ("RESEARCH_FEEDBACK_OUT", "RESEARCH_FEEDBACK_RUN_ID", "RESEARCH_FEEDBACK_ATTEMPT_ID")
    )
    state = tmp_path / "state"
    output = cli(
        tmp_path, "ff_job", ["--jobs-dir", state, "get_status", "--owner-job-id", "foreign-id"],
        RESEARCH_FEEDBACK_DIR=str(directory),
    )
    assert output.returncode == 2
    assert any(row["check_id"] == "execution-outcome" for row in packets(directory))
    logged, = runtime_rows(directory)
    assert logged["event"] == "get_status"
    assert not state.exists()


def test_broken_explicit_transport_retains_native_failure_without_new_work(tmp_path):
    jobs = tmp_path / "jobs"
    invalid_target = tmp_path / "directory-not-a-file"
    invalid_target.mkdir()
    p = cli(
        tmp_path, "ff_job", ["--jobs-dir", jobs, "submit"], "[]", RESEARCH_FEEDBACK_OUT=str(invalid_target)
    )
    assert p.returncode == 2 and json.loads(p.stdout)["error"]["code"] == "request_error"
    assert p.stderr == ""
    assert len([r for r in packets(jobs / "observations") if r["disposition"] == "deviation"]) == 1
    assert not (jobs / "jobs").exists()


def test_unavailable_feedback_outboxes_warn_without_changing_job_protocol(tmp_path):
    jobs = tmp_path / "jobs"
    args = ["--jobs-dir", jobs, "submit"]
    baseline = cli(tmp_path, "ff_job", ["--jobs-dir", tmp_path / "control", "submit"], "[]")
    blocked = tmp_path / "unavailable-private-path"
    blocked.write_bytes(b"untouchable")
    # Block all three channels without changing the original request.
    jobs.mkdir()
    original = jobs / "observations"
    original.write_bytes(b"untouchable owner root")
    failed = cli(tmp_path, "ff_job", args, "[]", RESEARCH_FEEDBACK_DIR=str(blocked),
                 RESEARCH_FEEDBACK_OUT=str(blocked / "sidecar"))

    assert failed.returncode == baseline.returncode == 2
    assert failed.stdout == baseline.stdout
    notice, = failed.stderr.splitlines()
    assert "filing-fetch" in notice and "feedback" in notice
    assert re.search(r"\([A-Za-z]+Error\)$", notice)
    assert str(blocked) not in notice and "unavailable-private-path" not in notice
    assert not (jobs / "jobs").exists()


def test_native_config_failure_and_usage_read_same_owner_attempt_without_replay(tmp_path):
    jobs = tmp_path / "jobs"

    def job(*args, body=""):
        p = cli(tmp_path, "ff_job", ["--jobs-dir", jobs, *args], body)
        assert p.returncode == 0, (p.stdout, p.stderr)
        return json.loads(p.stdout)

    request = {
        "schema_version": "2.0",
        "company_query": "Test Fixture",
        "document_kind": "annual_report",
        "fiscal_year": 2025,
        "as_of_date": "2026-07-18",
        "filing_intent": "reuse_only",
        "mode": "exact",
    }
    body = {
        "schema_version": "ff-job/1",
        "command_id": "diag",
        "kind": "filing.acquire",
        "idempotency_key": "diag",
        "request": request,
    }
    jid = job("submit", body=json.dumps(body))["owner_job_id"]
    run_args = ("run", "--owner-job-id", jid, "--config", str(tmp_path / "missing-owner.json"))
    job(*run_args)
    first = packets(jobs / "observations")
    second = job(*run_args)
    cached = job("get_status", "--owner-job-id", jid)["job"]
    assert cached["execution_count"] == 1 and not second["engine_executed"]
    assert cached["error"]["code"] == "config_error"
    assert packets(jobs / "observations") == first
    rows = {r["check_id"]: r for r in first}
    assert rows["job-outcome"]["actual"] == "failed" and rows["job-outcome"]["disposition"] == "deviation"
    assert rows["job-outcome"]["issue_key"] == "config_error"
    assert rows["job-usage"]["actual"] == "not_applicable"
    assert all(r["evidence_ref"].endswith(jid) for r in first)


def test_failed_job_and_unknown_cost_remain_two_independent_observations(tmp_path, monkeypatch):
    from ff_job_feedback import publish_job_observation

    monkeypatch.setenv("RESEARCH_FEEDBACK_DIR", str(tmp_path))
    monkeypatch.delenv("RESEARCH_FEEDBACK_OUT", raising=False)
    record = {
        "owner_job_id": "ffjob-000000000000",
        "attempts": 1,
        "status": "unknown",
        "status_known": False,
        "cost_state": "unknown",
        "error": {"code": "upstream_error"},
    }
    publish_job_observation(record, started=False)
    rows = {r["check_id"]: r for r in packets(tmp_path)}
    assert rows["job-outcome"]["actual"] == "unknown"
    assert (
        rows["job-failure"]["actual"] == "upstream_error"
        and rows["job-failure"]["disposition"] == "deviation"
    )
    assert rows["job-usage"]["actual"] == "unknown" and rows["job-usage"]["disposition"] == "unknown"


def test_typed_budget_refusal_is_visible_without_mislabeling_unknown_provider_cost(tmp_path):
    from ff_short_feedback import observation_rows
    from test_feedback_observation import _identity
    from ff_provider_cause import validated_acquisition_failure

    receipt = {
        "schema_version": "acquisition-failure/1",
        "code": "cost_budget_exceeded",
        "retryable": False,
        "provider_started": False,
        "usage_complete": True,
        "usage_scope": "operation",
        "acquisition_usage": {"schema_version": "1.0", "response_bytes": 0, "cost_usd": "0.00"},
    }
    assert validated_acquisition_failure(receipt) is not None
    output = {"schema_version": "2.0", "status": "upstream_error", "filing": {"acquisition_failure": receipt}}
    rows = observation_rows(
        output=output,
        error=None,
        stats={"calls": 1},
        request={"filing_intent": "fetch_if_missing"},
        allow_download=True,
        identity=_identity(),
    )
    check = next(row for row in rows if row["check_id"] == "request-outcome")
    assert check["refusal_code"] == "cost_budget_exceeded" and check["disposition"] == "expected"


@pytest.mark.parametrize("blocked_at_run", [False, True], ids=["ordinary", "recover-outbox"])
def test_public_schedule_mixed_document_results_have_individual_cold_references(tmp_path, blocked_at_run):
    from test_scheduled_refresh import configure_body
    from test_scheduled_refresh_public_e2e import _PUBLIC_OWNER

    owner = tmp_path / "provider"
    owner.mkdir()
    fixture = owner / "office.py"
    fixture.write_text(
        _PUBLIC_OWNER.replace(
            '"state": "read",',
            '"state": ("read" if ref["document_id"].endswith("HK") else "failed"), '
            '"reason_codes": ([] if ref["document_id"].endswith("HK") else ["parse_failed"]),',
        ),
        encoding="utf8",
    )

    def put(path, data):
        path.write_text(json.dumps(data), encoding="utf8")

    config = tmp_path / "connection.json"
    put(
        config,
        {
            "schema_version": "1.0",
            "connection": {
                "cwd": str(owner),
                "commands": {
                    "incremental_discover": [sys.executable, "-B", str(fixture), "discover"],
                    "incremental_read": [sys.executable, "-B", str(fixture), "read"],
                },
            },
        },
    )
    put(
        tmp_path / "scheduled_refresh.json",
        {"schema_version": "ff-scheduled-refresh-deployment/1", "pinned_rosters": "members.json"},
    )
    put(
        tmp_path / "members.json",
        {
            "rosters": {
                "primary": {
                    "snapshot_id": "f4-mixed",
                    "items": [
                        {"entity_id": "issuer-" + m, "listing_id": "listing-" + m, "market": m, "ticker": t}
                        for m, t in (("CN", "600001"), ("HK", "01234"), ("US", "TEST"))
                    ],
                }
            }
        },
    )
    jobs = tmp_path / "state"

    def refresh(*args, body="", **labels):
        p = cli(tmp_path, "ff_scheduled_refresh", ["--jobs-dir", jobs, "--config", config, *args], body, **labels)
        assert p.returncode == 0, (p.stdout, p.stderr)
        return json.loads(p.stdout)

    refresh(
        "configure",
        "--request-stdin",
        body=json.dumps(
            configure_body(
                roster={"mode": "pinned", "roster_ref": "primary"},
                transcripts_enabled=False,
                backlog_enabled=False,
            )
        ),
    )
    inbox = jobs / "observations"
    if blocked_at_run:
        inbox.write_text("this fixture temporarily occupies the owner outbox", encoding="utf8")
    refresh("tick", RESEARCH_FEEDBACK_RUN_ID="original-run", RESEARCH_FEEDBACK_ATTEMPT_ID="original-attempt")
    original = refresh("runs")["items"][0]
    calls_at_finish = (owner / "calls.jsonl").read_bytes()
    if blocked_at_run:
        assert not packets(inbox)
        inbox.unlink()
        refresh("status")
        assert not inbox.exists()
        flush = cli(tmp_path, "ff_job_feedback", ["flush-observations", "--jobs-dir", jobs])
        assert flush.returncode == 0, (flush.stdout, flush.stderr)
    assert original["state"] == "partial" and original["counts"]["failed"] == 2
    assert len(original["failures"]) == 2
    native = packets(jobs / "observations")
    failures = [r for r in native if r["check_id"] == "refresh-item-outcome"]
    assert len(failures) == 2 and len({r["step_id"] for r in failures}) == 2
    assert all(r["actual"] == "parse_failed" for r in failures)
    assert {(r["run_id"], r["attempt_id"]) for r in native} == {("original-run", "original-attempt")}
    assert all(r["evidence_ref"].endswith(original["run_id"]) for r in failures)
    assert any(r["check_id"] == "refresh-usage" and r["actual"] == "unknown" for r in native)
    n = (owner / "calls.jsonl").read_bytes()
    refresh("tick")
    assert (owner / "calls.jsonl").read_bytes() == n
    assert packets(jobs / "observations") == native
    assert (owner / "calls.jsonl").read_bytes() == calls_at_finish
    for marker in inbox.glob("*.ready"):
        marker.unlink()
    for command in ("status", "runs", "tick", "status", "runs", "tick"):
        refresh(command)
    assert not list(inbox.glob("*.ready"))
    assert (owner / "calls.jsonl").read_bytes() == calls_at_finish


def test_killed_native_job_is_recovered_by_cold_status_without_another_execution(tmp_path):
    import time
    from test_ff_job_cross_process import _submit_body

    jobs = tmp_path / "jobs"
    body = _submit_body(key="lost-before-provider", command_id="lost-before-provider")
    p = cli(tmp_path, "ff_job", ["--jobs-dir", jobs, "submit"], json.dumps(body))
    assert p.returncode == 0
    jid = json.loads(p.stdout)["owner_job_id"]
    signal = tmp_path / "entered"
    worker = """
import pathlib,sys
sys.path.insert(0,sys.argv.pop(1))
marker=pathlib.Path(sys.argv.pop(1))
import ff_job, ff_job_runner
def parked(*args, **kwargs):
    marker.write_text("1", encoding="ascii")
    sys.stdin.buffer.read(1)
    raise RuntimeError("test process should have terminated first")
ff_job_runner._run_filing_engine = parked
raise SystemExit(ff_job.main())
"""
    env = {k: v for k, v in os.environ.items() if not k.startswith("RESEARCH_FEEDBACK_")}
    env.update(RESEARCH_FEEDBACK_RUN_ID="one-original", RESEARCH_FEEDBACK_ATTEMPT_ID="frozen-attempt")
    live = subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-c",
            worker,
            str(SCRIPTS),
            str(signal),
            "--jobs-dir",
            str(jobs),
            "run",
            "--owner-job-id",
            jid,
        ],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 15
        while not signal.exists() and live.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert signal.is_file()
        assert any(r["check_id"] == "action-started" for r in packets(jobs / "observations"))
    finally:
        live.kill()
        live.communicate(timeout=8)
    for _ in range(2):
        cold = cli(tmp_path, "ff_job", ["--jobs-dir", jobs, "get_status", "--owner-job-id", jid])
        job = json.loads(cold.stdout)["job"]
        assert job["status"] == "unknown" and job["execution_count"] == 0 and job["attempts"] == 1
    assert not any(r["check_id"] == "job-failure" for r in packets(jobs / "observations"))
    offered = cli(tmp_path, "ff_job_feedback", ["reoffer-job", "--jobs-dir", jobs, "--owner-job-id", jid])
    assert offered.returncode == 0
    rows = packets(jobs / "observations")
    failure = next(r for r in rows if r["check_id"] == "job-failure")
    assert (failure["actual"], failure["run_id"], failure["attempt_id"]) == (
        "run_lost",
        "one-original",
        "frozen-attempt",
    )
    assert failure["disposition"] == "deviation" and signal.read_text() == "1"


@pytest.mark.windows_only


@pytest.mark.skipif(sys.platform != "win32", reason="requires the native Windows process or scheduler")
@pytest.mark.parametrize("use_directory", [False, True], ids=["missing", "directory"])
def test_login_launcher_reports_missing_interpreter_without_registering_a_task(tmp_path, use_directory):
    jobs = tmp_path / "jobs"
    interpreter = tmp_path / "invalid-interpreter.exe"
    if use_directory:
        interpreter.mkdir()
    result = cli(
        tmp_path,
        "ff_scheduled_windows",
        ["run", "--jobs-dir", jobs, "--python", interpreter],
    )
    assert result.returncode != 0
    rows = packets(jobs / "observations")
    assert len(rows) == 1 and rows[0]["actual"] == "task_launch_failed"
    assert not (jobs / "scheduled").exists()


def test_external_owners_never_inherit_filing_fetch_delivery_paths(tmp_path, monkeypatch):
    from ff_company_wiki_connection import connection_environment
    from ff_runtime_feedback import owner_child_environment

    private = (
        "RESEARCH_FEEDBACK_OUT",
        "RESEARCH_FEEDBACK_DIR",
        "RESEARCH_FEEDBACK_RUN_ID",
        "RESEARCH_FEEDBACK_ATTEMPT_ID",
    )
    for name in private:
        monkeypatch.setenv(name, "only-the-parent")
    assert all(
        name not in child
        for child in (connection_environment(tmp_path), owner_child_environment())
        for name in private
    )
    assert all(os.environ[name] == "only-the-parent" for name in private)


def test_unavailable_transport_is_repaired_from_existing_native_job_on_cold_read(tmp_path):
    from test_ff_job_cross_process import _submit_body

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    native = jobs / "observations"
    native.write_text("occupied", encoding="utf8")
    broken = tmp_path / "bad-out"
    broken.mkdir()
    p = cli(
        tmp_path,
        "ff_job",
        ["--jobs-dir", jobs, "submit"],
        json.dumps(_submit_body(key="redelivery", command_id="redelivery")),
    )
    jid = json.loads(p.stdout)["owner_job_id"]
    p = cli(
        tmp_path,
        "ff_job",
        ["--jobs-dir", jobs, "run", "--owner-job-id", jid, "--config", tmp_path / "absent"],
        RESEARCH_FEEDBACK_OUT=str(broken),
    )
    job = json.loads(p.stdout)["job"]
    assert job["status"] == "failed" and job["execution_count"] == 1
    native.unlink()  # Remove only the obstruction created by this fixture.
    args = ["--jobs-dir", jobs, "get_status", "--owner-job-id", jid]
    assert json.loads(cli(tmp_path, "ff_job", args).stdout)["job"] == job
    maintenance = ["reoffer-job", "--jobs-dir", jobs, "--owner-job-id", jid]
    assert cli(tmp_path, "ff_job_feedback", maintenance).returncode == 0
    rows = packets(native)
    assert any(r["issue_key"] == "config_error" for r in rows if "issue_key" in r)
    signals = list(native.glob("*.ready"))
    for signal in signals:
        signal.unlink()  # consumer ACK
    assert json.loads(cli(tmp_path, "ff_job", args).stdout)["job"] == job
    assert cli(tmp_path, "ff_job_feedback", maintenance).returncode == 0
    assert not list(native.glob("*.ready"))

def test_multiple_outstanding_slots_survive_restart_and_replay_independently(tmp_path, monkeypatch):
    from datetime import timedelta
    from ff_refresh_owners import Deployment
    from ff_refresh_runner import run_tick
    from ff_refresh_store import RefreshStore
    from test_refresh_runner import Owners, TIME, _settings

    jobs = tmp_path / "jobs"
    store = RefreshStore(jobs)
    owners = Owners()
    owners.partial = True
    store.configure(_settings(reading_level="off"), None)
    out = jobs / "observations"
    out.write_text("synthetic publication outage", encoding="utf8")
    snapshot_ids = set()
    for day in range(2):
        monkeypatch.setenv("RESEARCH_FEEDBACK_DIR", str(out))
        monkeypatch.setenv("RESEARCH_FEEDBACK_RUN_ID", f"original-day-{day}")
        run_tick(store, owners, Deployment(), now=TIME+timedelta(days=day))
        snapshot_ids.add(store.load()["last_run"]["run_id"])
    assert set(store.load()["feedback_pending"]) == snapshot_ids and len(snapshot_ids) == 2
    out.unlink()
    p = cli(tmp_path, "ff_scheduled_refresh", ["--jobs-dir", jobs, "status"])
    assert p.returncode == 0 and set(store.load()["feedback_pending"]) == snapshot_ids
    assert not out.exists()
    p = cli(tmp_path, "ff_job_feedback", ["flush-observations", "--jobs-dir", jobs])
    assert p.returncode == 0 and store.load()["feedback_pending"] == []
    recovered = [r for r in packets(out) if r["check_id"] == "refresh-item-outcome"]
    assert {r["run_id"] for r in recovered} == {"original-day-0","original-day-1"}
    assert {r["evidence_ref"].split("/")[-1] for r in recovered} == snapshot_ids
    for marker in out.glob("*.ready"):
        marker.unlink()
    for command in ("status","runs"):
        assert cli(tmp_path, "ff_scheduled_refresh", ["--jobs-dir",jobs,command]).returncode == 0
    assert cli(tmp_path, "ff_job_feedback", ["flush-observations", "--jobs-dir", jobs]).returncode == 0
    assert not list(out.glob("*.ready"))
