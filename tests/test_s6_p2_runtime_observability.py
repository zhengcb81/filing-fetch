"""Native P2 ingress, writer and diagnostic fault contracts."""

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread
import time

import pytest


pytestmark = [pytest.mark.e2e_offline, pytest.mark.regression]

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
TOKEN = "ghp_P2SynthToken012345678901234567890123"
PASSWORD = "p2-userinfo-secret"
BASIC = "dGVzdDpzZWNyZXRwMjEyMw=="
MIXED = f"Authorization:\n\tBasic {BASIC}\n\tmore-p2-secret"
URL = f"https://user:{PASSWORD}@example.invalid/"
OTHER_TOKENS = ("sk-P2Fixture0123456789", "tvly-P2Fixture0123456789", "AIzaP2Fixture0123456789")
JOB = "ffjob-0123456789ab"


def native(tmp_path, command, *, body="", **overrides):
    env = {key: value for key, value in os.environ.items() if not key.startswith("RESEARCH_FEEDBACK_")}
    return subprocess.run(
        [sys.executable, "-B", "-X", "utf8", *map(str, command)],
        input=body, text=True, encoding="utf-8", capture_output=True, timeout=25,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        cwd=tmp_path, env={**env, **overrides},
    )


def cli(tmp_path, name, args, **env):
    return native(tmp_path, [SCRIPTS / (name + ".py"), *args], **env)


def rows(root, name="runtime-errors.jsonl"):
    path = root / "logs" / name
    return [json.loads(line) for line in path.read_bytes().splitlines()]


@pytest.mark.parametrize(("name", "args", "local_only"), [
    ("fetch_filing", ["--" + TOKEN], False),
    ("fetch_statements", ["--" + TOKEN], False),
    ("ff_job", ["--" + TOKEN], False),
    ("ff_scheduled_refresh", ["--" + TOKEN], False),
    ("ff_scheduled_windows", ["--" + TOKEN], False),
    ("ff_t3_receipt", ["--" + TOKEN], True),
    ("ff_job_feedback", ["get-diagnostic", TOKEN], True),
    ("ff_job_feedback", ["get-direct-run", "--run-id", TOKEN], True),
    ("ff_job_feedback", ["get-report", TOKEN], True),
])
def test_cli_argument_failure_is_a_single_safe_owner_occurrence(tmp_path, name, args, local_only):
    root = tmp_path / "outbox"
    result = cli(tmp_path, name, args, RESEARCH_FEEDBACK_DIR=str(root),
                 RESEARCH_FEEDBACK_RUN_ID="p2-original", RESEARCH_FEEDBACK_ATTEMPT_ID="attempt-7")
    assert result.returncode == 2 and result.stdout == ""
    assert "usage:" in result.stderr and TOKEN not in result.stderr
    record, = rows(root)
    assert (record["run_id"], record["attempt_id"]) == ("p2-original", "attempt-7")
    assert record["code_version"] and len(record["input_ref"]) == 64
    assert any(check["actual"] == "argument_error" for check in record["checks"])
    assert record["diagnostic"]["causes"][0]["type"] == "SystemExit"
    assert any(frame["file"] == name + ".py" for frame in record["diagnostic"]["causes"][0]["frames"])
    assert TOKEN not in repr(record)
    assert bool(list(root.glob("*.ready"))) is not local_only


def test_late_control_refusal_survives_two_unwritable_native_locations(tmp_path):
    primary, secondary = (tmp_path / name for name in ("primary", "secondary"))
    for path in (primary, secondary):
        path.write_bytes(b"unmodified")
    args = ["get-diagnostic", TOKEN, "--jobs-dir", secondary]
    result = cli(tmp_path, "ff_job_feedback", args, RESEARCH_FEEDBACK_DIR=str(primary),
                 RESEARCH_FEEDBACK_RUN_ID="original-control", RESEARCH_FEEDBACK_ATTEMPT_ID="attempt-7")
    assert result.returncode == 2 and result.stdout == ""
    assert "invalid diagnostic reference" in result.stderr
    alarms = [line for line in result.stderr.splitlines() if line.startswith("warning: filing-fetch ")]
    alarm, = alarms
    assert "original-control" in alarm and "attempt-7" in alarm
    assert TOKEN not in result.stderr and str(tmp_path) not in alarm
    assert all(path.read_bytes() == b"unmodified" for path in (primary, secondary))


def test_unhandled_cli_error_retains_original_type_without_reflecting_exception_message(tmp_path):
    root = tmp_path / "outbox"
    program = """
import sys
sys.path.insert(0, sys.argv[1])
from ff_runtime_feedback import observed_cli, cli_exit

@observed_cli("isolated-resolver")
def execute(argv, *, diagnostics):
    raise FileNotFoundError(sys.argv[2])

raise SystemExit(cli_exit(execute))
"""
    result = native(tmp_path, ["-c", program, SCRIPTS, MIXED + "\n" + URL + "\n" + TOKEN + " " + " ".join(OTHER_TOKENS)],
                    RESEARCH_FEEDBACK_DIR=str(root), RESEARCH_FEEDBACK_RUN_ID="raw-exception")
    assert result.returncode == 1 and result.stdout == ""
    assert "Traceback" in result.stderr and "FileNotFoundError" in result.stderr
    assert all(secret not in result.stderr for secret in (TOKEN, BASIC, PASSWORD, "more-p2-secret", *OTHER_TOKENS))
    record, = rows(root)
    assert record["run_id"] == "raw-exception"
    assert record["diagnostic"]["causes"][0]["type"] == "FileNotFoundError"


def test_healthy_missing_control_result_does_not_create_feedback(tmp_path):
    root, state = (tmp_path / name for name in ("outbox", "state"))
    ref = "ff-diagnostic/1/feedback-" + "a" * 32
    result = cli(tmp_path, "ff_job_feedback", ["get-diagnostic", ref, "--jobs-dir", state],
                 RESEARCH_FEEDBACK_DIR=str(root))
    assert (result.returncode, json.loads(result.stdout), result.stderr) == (1, {"status": "unavailable"}, "")
    assert not root.exists() and not state.exists()


def test_job_owner_rotates_once_under_two_real_writers_and_redacts_at_write(tmp_path):
    root = tmp_path / "state"
    log = root / "logs" / (JOB + ".log")
    log.parent.mkdir(parents=True)
    before = json.dumps({"fixture": "x" * (2 * 1024 * 1024)}).encode("ascii") + b"\n"
    log.write_bytes(before)
    program = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ff_job_store import JobStore
store = JobStore(Path(sys.argv[2]), initialize=False)
store.append_log(sys.argv[3], {"event": sys.argv[4], "detail": {"messages": sys.argv[5:]}})
"""

    def write(event):
        return native(tmp_path, ["-c", program, SCRIPTS, root, JOB, event, MIXED, URL, TOKEN, *OTHER_TOKENS])

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, ("started", "finished")))
    assert all((result.returncode, result.stdout, result.stderr) == (0, "", "") for result in results)
    saved = rows(root, JOB + ".log")
    assert {record["event"] for record in saved} == {"started", "finished"} and len(saved) == 2
    assert all(secret not in repr(saved) for secret in (TOKEN, BASIC, PASSWORD, "more-p2-secret", *OTHER_TOKENS))
    assert log.with_name(log.name + ".1").read_bytes() == before


def test_statement_child_failure_recovers_typed_tail_and_original_post(tmp_path):
    class AcceptedThenTruncated(BaseHTTPRequestHandler):
        def do_POST(self):
            self.server.posts.append(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Length", "80")
            self.end_headers()
            self.wfile.write(b"only a fragment")

        def log_message(self, *_args):
            return

    provider = ThreadingHTTPServer(("127.0.0.1", 0), AcceptedThenTruncated)
    provider.posts = []
    thread = Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    child = tmp_path / "statement_owner.py"
    child.write_text(
        "import json, sys, urllib.request\n"
        "if sys.platform == 'win32': assert not __import__('ctypes').windll.kernel32.GetConsoleWindow()\n"
        "class ProviderStreamError(Exception): pass\n"
        "request = json.load(sys.stdin)\n"
        "try:\n"
        "    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(urllib.request.Request(sys.argv[1], data=b'test'), timeout=4) as answer:\n"
        "        answer.read()\n"
        "except Exception as error:\n"
        "    raise ProviderStreamError(sys.argv[2]) from error\n",
        encoding="utf-8",
    )
    config = tmp_path / "connection.json"
    config.write_text(json.dumps({
        "schema_version": "1.0", "connection": {"cwd": str(tmp_path), "commands": {
            "financial_statements": [sys.executable, "-B", str(child),
                                      f"http://127.0.0.1:{provider.server_port}/", MIXED + "\n" + URL + "\n" + TOKEN + " " + " ".join(OTHER_TOKENS)],
        }},
    }), encoding="utf-8")
    root = tmp_path / "outbox"
    options = {"RESEARCH_FEEDBACK_DIR": str(root), "RESEARCH_FEEDBACK_RUN_ID": "stream-original",
               "RESEARCH_FEEDBACK_ATTEMPT_ID": "once"}
    request = {
        "schema_version": "financial-statements-request/1",
        "company_query": "Synthetic Ltd", "market": "CN", "statements": ["income_statement"],
        "knowledge_mode": "current_snapshot", "intent": "fetch_if_missing",
        "acquisition_limits": {"max_bytes": 1024, "timeout_seconds": 10, "max_cost_usd": "0.00"},
    }
    try:
        result = cli(tmp_path, "fetch_statements", ["--config", config], body=json.dumps(request), **options)
        assert (result.returncode, result.stderr) == (2, "")
        reply = json.loads(result.stdout)
        assert reply["status"] == "upstream_error"
        record, = rows(root)
        assert record["run_id"] == "stream-original" and record["attempt_id"] == "once"
        assert len(record["code_version"]) == 64 and len(record["input_ref"]) == 64
        detail = record["diagnostic"]
        assert {cause["type"] for cause in detail["causes"]} >= {"FilingFetchError", "ChildFailed"}
        assert detail["child_process"]["exception_type"] == "ProviderStreamError"
        assert detail["child_process"]["last_frame"] == {"file": child.name, "line": 9}
        assert all(secret not in repr(record) + result.stdout for secret in (TOKEN, BASIC, PASSWORD, "more-p2-secret", *OTHER_TOKENS))

        recovered = cli(tmp_path, "ff_job_feedback", [
            "get-statement-run", record["evidence_ref"], "--observations-dir", root,
        ], **options)
        assert recovered.returncode == 0 and recovered.stderr == ""
        original = json.loads(recovered.stdout)["result"]
        assert original["evidence_ref"] == record["evidence_ref"] and original["cost_state"] == "unknown"
        packet_rows = [json.loads(line) for packet in root.glob("*.jsonl") for line in packet.read_bytes().splitlines()]
        terminal = next(item for item in packet_rows if item["check_id"] == "execution-outcome")
        details = cli(tmp_path, "ff_job_feedback", [
            "get-diagnostic", terminal["details_ref"], "--observations-dir", root,
        ], **options)
        assert details.returncode == 0 and details.stderr == ""
        assert json.loads(details.stdout)["child_process"] == detail["child_process"]

        def digest(value):
            payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
            return hashlib.sha256(payload).hexdigest()

        owner = terminal["owner"]
        observation = dict(terminal, origin_owner=owner)
        fields = ("owner", "origin_owner", "run_id", "attempt_id", "step_id", "check_id")
        occurrence = digest([observation[name] for name in fields])
        action_id = digest(["reconcile", owner, occurrence])
        payload = {"observation": observation, "occurrence_id": occurrence}
        action = {
            "schema_version": "feedback-action/1", "owner": owner, "kind": "reconcile", "method": "lookup",
            "action_id": action_id, "payload": payload,
            "request_digest": digest([owner, "reconcile", action_id, payload]),
        }
        reply = cli(tmp_path, "ff_job_feedback", [
            "reconcile", "--jobs-dir", tmp_path / "state", "--observations-dir", root,
        ], body=json.dumps(action), **options)
        assert (reply.returncode, reply.stderr) == (0, "")
        receipt = json.loads(reply.stdout)["result"]
        assert receipt["trace"] == original and receipt["cost_state"] == "unknown"
        assert receipt["new_provider_requests"] == receipt["new_downloads"] == 0
        assert receipt["new_cost_usd"] == "0.00" and provider.posts == [b"test"]
    finally:
        provider.shutdown()
        thread.join(5)
        provider.server_close()


def test_native_cli_killed_while_waiting_for_request_never_dispatches(tmp_path):
    from test_ff_runtime_lifecycle import _feedback_request

    root = tmp_path / "outbox"
    options = {"RESEARCH_FEEDBACK_DIR": str(root), "RESEARCH_FEEDBACK_RUN_ID": "pre-dispatch",
               "RESEARCH_FEEDBACK_ATTEMPT_ID": "once"}
    counter = tmp_path / "command-started"
    child = tmp_path / "statement_owner.py"
    child.write_text("from pathlib import Path\nimport sys\nPath(sys.argv[1]).touch()\n", encoding="utf-8")
    config = tmp_path / "connection.json"
    config.write_text(json.dumps({
        "schema_version": "1.0", "connection": {"cwd": str(tmp_path), "commands": {
            "financial_statements": [sys.executable, "-B", str(child), str(counter)],
        }},
    }), encoding="utf-8")
    command = [sys.executable, "-B", "-X", "utf8", SCRIPTS / "fetch_statements.py", "--config", config]
    environment = {key: value for key, value in os.environ.items() if not key.startswith("RESEARCH_FEEDBACK_")}
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=tmp_path,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env={**environment, **options},
    )
    try:
        deadline = time.monotonic() + 12
        while not list(root.glob("*.ready")) and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.025)
        signal, = root.glob("*.ready")
        start, = [json.loads(line) for line in signal.with_suffix(".jsonl").read_bytes().splitlines()]
        assert start["check_id"] == "action-started"
        assert (start["run_id"], start["attempt_id"]) == ("pre-dispatch", "once")
        assert process.poll() is None and not counter.exists()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=8)

    def cold_read():
        reply = cli(tmp_path, "ff_job_feedback", [
            "reconcile", "--jobs-dir", tmp_path / "state", "--observations-dir", root,
        ], body=json.dumps(_feedback_request(start)), **options)
        assert (reply.returncode, reply.stderr) == (0, "")
        return json.loads(reply.stdout)["result"]

    receipt = cold_read()
    assert cold_read() == receipt and not counter.exists()
    assert receipt["evidence_ref"] == start["evidence_ref"] and receipt["job_status"] == "interrupted"
    assert receipt["cost_state"] == "unknown"
    assert [step["phase"] for step in receipt["trace"]["steps"]] == ["started"]
    assert receipt["new_provider_requests"] == receipt["new_downloads"] == 0
    assert receipt["new_cost_usd"] == "0.00"


@pytest.mark.windows_only
@pytest.mark.skipif(os.name != "nt", reason="Windows no-delete sharing is required")
def test_windows_locked_rotation_preserves_old_generation_and_falls_back(tmp_path):
    root, fallback = (tmp_path / name for name in ("primary", "fallback"))
    log = root / "logs" / "runtime-errors.jsonl"
    log.parent.mkdir(parents=True)
    backup = log.with_name(log.name + ".1")
    old = b"previous owner generation\n"
    current = json.dumps({"fixture": "x" * (2 * 1024 * 1024)}).encode("ascii") + b"\n"
    backup.write_bytes(old)
    log.write_bytes(current)
    with backup.open("rb") as locked:
        result = cli(tmp_path, "ff_job", ["--jobs-dir", fallback, "submit"], body="[]",
                     RESEARCH_FEEDBACK_DIR=str(root), RESEARCH_FEEDBACK_RUN_ID="locked-rotation")
        assert (result.returncode, result.stderr) == (2, "")
        assert json.loads(result.stdout)["status"] == "request_error"
        assert locked.read() == old and log.read_bytes() == current
    entry, = rows(fallback)
    assert entry["run_id"] == "locked-rotation"


def test_native_log_loss_is_announced_even_while_outbox_is_writable(tmp_path):
    outbox, jobs = (tmp_path / name for name in ("outbox", "jobs"))
    for root in (outbox, jobs):
        root.mkdir()
        (root / "logs").write_bytes(b"occupied")
    result = cli(tmp_path, "ff_job", ["--jobs-dir", jobs, "submit"], body="[]",
                 RESEARCH_FEEDBACK_DIR=str(outbox), RESEARCH_FEEDBACK_RUN_ID="ordinary-log-loss",
                 RESEARCH_FEEDBACK_ATTEMPT_ID="attempt-6")
    assert result.returncode == 2 and json.loads(result.stdout)["status"] == "request_error"
    assert len(list(outbox.glob("*.ready"))) == 1
    notice, = result.stderr.splitlines()
    assert "runtime log unavailable" in notice
    assert "run_id=ordinary-log-loss" in notice and "attempt_id=attempt-6" in notice
    assert str(tmp_path) not in notice
    assert all((root / "logs").read_bytes() == b"occupied" for root in (outbox, jobs))


@pytest.mark.parametrize("metadata", [
    {"diagnostic_execution": "outdated"},
    {"diagnostic_execution": {"owner": "fake-owner", "event": "fake-event", "input_ref": "sk-fixture-disk-label"}},
    {"feedback_identity": "outdated"},
])
def test_corrupt_job_metadata_never_changes_durable_cancel(tmp_path, metadata):
    from test_ff_job_cross_process import _submit_body

    jobs = tmp_path / "jobs"
    args = ["--jobs-dir", jobs]
    root = tmp_path / "outbox"
    environment = {"RESEARCH_FEEDBACK_DIR": str(root)}
    submission = cli(tmp_path, "ff_job", [*args, "submit"], body=json.dumps(
        _submit_body(key="native-metadata", command_id="metadata-fixture")
    ), **environment)
    assert submission.returncode == 0
    jid = json.loads(submission.stdout)["owner_job_id"]
    path = jobs / "jobs" / (jid + ".json")
    before = json.loads(path.read_bytes())
    path.write_text(json.dumps({**before, **metadata}), encoding="utf-8")
    action = [*args, "act", "--owner-job-id", jid, "--action", "cancel", "--idempotency-key", "cancel-fixture"]
    result = cli(tmp_path, "ff_job", action, **environment)
    assert (result.returncode, result.stderr) == (0, "")
    view = json.loads(result.stdout)
    assert view["job"]["status"] == "cancelled"
    latest = cli(tmp_path, "ff_job", [*args, "get_status", "--owner-job-id", jid], **environment)
    assert latest.returncode == 0 and json.loads(latest.stdout)["job"] == view["job"]
    replay = cli(tmp_path, "ff_job", action, **environment)
    assert replay.returncode == 0 and json.loads(replay.stdout)["idempotent_replay"] is True
    record = json.loads(path.read_bytes())
    assert (record["attempts"], record["execution_count"]) == (0, 0)
    audit, = rows(jobs, jid + ".log")
    assert audit["run_id"] == jid and audit["event"] == "cancelled"
    assert all(mark not in repr(audit) for mark in ("fake-owner", "fake-event", "sk-fixture-disk-label"))


@pytest.mark.parametrize("legacy_unredacted", [False, True])
def test_original_caller_coordinates_survive_public_identity_redaction(tmp_path, legacy_unredacted):
    from test_ff_runtime_lifecycle import Case, REQUEST

    run_id, attempt = "sk-fixture-run-label", "trial-one"
    case = Case(tmp_path, "ok")
    case.env.update(RESEARCH_FEEDBACK_RUN_ID=run_id, RESEARCH_FEEDBACK_ATTEMPT_ID=attempt)
    completed = case.invoke("fetch_statements.py", "--config", str(case.config), body=REQUEST)
    assert completed.returncode == 0
    path, = (tmp_path / "in-direct-runs").glob("*.json")
    original = json.loads(path.read_bytes())
    opaque = original["run_id"]
    assert opaque != run_id
    if legacy_unredacted:
        path.write_text(json.dumps({**original, "run_id": run_id}), encoding="utf-8")

    args = ["--jobs-dir", str(case.jobs)]
    by_reference = case.invoke("ff_job_feedback.py", "get-statement-run", original["evidence_ref"], *args)
    for name in (run_id, opaque):
        by_coordinates = case.invoke("ff_job_feedback.py", "get-statement-run", "--run-id", name,
                                     "--attempt-id", attempt, *args)
        assert (by_coordinates.returncode, by_coordinates.stderr) == (0, b"")
        assert json.loads(by_coordinates.stdout) == json.loads(by_reference.stdout)
        assert json.loads(by_coordinates.stdout)["result"]["run_id"] == opaque
        assert run_id.encode() not in by_coordinates.stdout
    assert case.count() == 1


def test_fault_and_cold_read_support_literal_hash_percent_and_long_owner_path(tmp_path):
    from ff_persistence import owner_io_path

    root = tmp_path / "native#%path"
    for segment in ("a", "b", "c", "d"):
        root /= segment * 62
    assert len(str(root)) > 260 and "#%" in str(root)
    owner_io_path(root).mkdir(parents=True)
    result = cli(tmp_path, "ff_job", ["--jobs-dir", root, "submit"], body="[]",
                 RESEARCH_FEEDBACK_RUN_ID="literal-path-original", RESEARCH_FEEDBACK_ATTEMPT_ID="once")
    assert (result.returncode, result.stderr) == (2, "")
    assert json.loads(result.stdout)["status"] == "request_error"
    marks = owner_io_path(root / "observations")
    packet, = marks.glob("*.jsonl")
    failure = next(row for row in map(json.loads, packet.read_bytes().splitlines())
                   if row["check_id"] == "execution-outcome")
    readback = cli(tmp_path, "ff_job_feedback", [
        "get-diagnostic", failure["details_ref"], "--jobs-dir", root,
    ])
    assert readback.returncode == 0 and readback.stderr == ""
    detail = json.loads(readback.stdout)
    assert detail["run_id"] == failure["run_id"] == "literal-path-original"
    assert detail["causes"][0]["type"] == "FFJobError"


def test_short_filing_killed_after_loopback_dispatch_recovers_original_without_resend(tmp_path):
    from test_feedback_observation import Harness, _v2_request
    from test_ff_runtime_lifecycle import _feedback_request

    accepted = Event()
    release = Event()
    calls = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(self.rfile.read(int(self.headers["Content-Length"])))
            accepted.set()
            release.wait(10)

        def log_message(self, *_args):
            return

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    server = Thread(target=provider.serve_forever, daemon=True)
    server.start()
    harness = Harness(tmp_path, scenario="download")
    wrapper = tmp_path / "fixture_provider.py"
    wrapper.write_text(
        "import runpy, sys, urllib.request\n"
        "url = sys.argv.pop(1)\n"
        "fixture = sys.argv.pop(1)\n"
        "if 'ensure' in sys.argv and '--allow-download' in sys.argv:\n"
        "    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))\n"
        "    opener.open(urllib.request.Request(url, data=b'one-fixture-request'), timeout=8).read()\n"
        "sys.argv[0] = fixture\n"
        "runpy.run_path(fixture, run_name='__main__')\n",
        encoding="utf-8",
    )
    config = json.loads(harness.config.read_bytes())
    config["connection"]["commands"]["catalog"] = [
        sys.executable, "-B", str(wrapper), f"http://127.0.0.1:{provider.server_port}/",
        str(harness.service), "catalog",
    ]
    harness.config.write_text(json.dumps(config), encoding="utf-8")
    root = Path(harness.env["RESEARCH_FEEDBACK_DIR"])
    process = subprocess.Popen(
        [sys.executable, "-B", "-X", "utf8", str(SCRIPTS / "fetch_filing.py"), "--config", str(harness.config)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=harness.empty_cwd,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env={**harness.env, "RESEARCH_FEEDBACK_RUN_ID": "filing-original", "RESEARCH_FEEDBACK_ATTEMPT_ID": "once"},
    )
    try:
        assert process.stdin is not None
        body = json.dumps(_v2_request("fetch_if_missing")).encode("utf-8")
        process.stdin.write(body)
        process.stdin.close()
        process.stdin = None
        assert accepted.wait(12), "the public CLI did not reach the loopback provider"
        marker, = root.glob("*.ready")
        start, = map(json.loads, marker.with_suffix(".jsonl").read_bytes().splitlines())
        assert start["check_id"] == "action-started"
        assert (start["run_id"], start["attempt_id"]) == ("filing-original", "once")
        assert process.poll() is None
        process.kill()
        process.communicate(timeout=8)

        for _ in range(2):
            reply = cli(tmp_path, "ff_job_feedback", [
                "reconcile", "--jobs-dir", tmp_path / "jobs", "--observations-dir", root,
            ], body=json.dumps(_feedback_request(start)), RESEARCH_FEEDBACK_DIR=str(root))
            assert (reply.returncode, reply.stderr) == (0, "")
            outcome = json.loads(reply.stdout)["result"]
            assert outcome["evidence_ref"] == start["evidence_ref"]
            assert outcome["job_status"] == "interrupted" and outcome["cost_state"] == "unknown"
            assert outcome["new_provider_requests"] == outcome["new_downloads"] == 0
            assert outcome["new_cost_usd"] == "0.00"
            assert outcome["trace"]["request_sha256"] == hashlib.sha256(body).hexdigest()
            assert outcome["trace"]["external_effect"] == "possible"
        assert calls == [b"one-fixture-request"]
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=8)
        release.set()
        provider.shutdown()
        server.join(5)
        provider.server_close()


def test_original_job_reconcile_accepts_legacy_and_safe_coordinates_without_new_work(tmp_path):
    from test_ff_runtime_lifecycle import Case, _feedback_request

    raw = "sk-fixture-job-label"
    case = Case(tmp_path, "ok")
    case.env.update(RESEARCH_FEEDBACK_RUN_ID=raw, RESEARCH_FEEDBACK_ATTEMPT_ID="original-attempt")
    jid = case.submit()
    original = case.run_job(jid)
    assert original.returncode == 0 and json.loads(original.stdout)["job"]["status"] == "succeeded"
    path = case.jobs / "jobs" / (jid + ".json")
    record = json.loads(path.read_bytes())
    safe = record["feedback_identity"]["run_id"]
    assert safe != raw
    record["feedback_identity"]["run_id"] = raw
    path.write_text(json.dumps(record), encoding="utf-8")
    packets = [json.loads(line) for packet in case.inbox.glob("*.jsonl") for line in packet.read_bytes().splitlines()]
    terminal = next(row for row in packets if row["check_id"] == "job-outcome")
    answers = []
    for label in (safe, raw):
        result = case.invoke("ff_job_feedback.py", "reconcile", "--jobs-dir", str(case.jobs),
                             body=_feedback_request(dict(terminal, run_id=label)))
        assert (result.returncode, result.stderr) == (0, b"")
        assert raw.encode() not in result.stdout
        answers.append(json.loads(result.stdout))
    assert answers[0] == answers[1] and answers[0]["state"] == "done"
    result = answers[0]["result"]
    assert result["owner_job_id"] == jid and result["native_attempt"] == 1
    assert result["execution_count"] == 1 and result["new_provider_requests"] == result["new_downloads"] == 0
    assert result["new_cost_usd"] == "0.00" and case.count() == 1
