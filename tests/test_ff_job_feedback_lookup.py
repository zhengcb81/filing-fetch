"""F4 checks the original native job without starting another acquisition."""
from argparse import Namespace
import hashlib
import json
import os
from pathlib import Path
from stat import FILE_ATTRIBUTE_REPARSE_POINT
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import ff_job_feedback as feedback
from test_ff_job_facade import _CANDIDATE_HANDLE, _FETCH_REQUEST, _observation, _submit
from test_feedback_ordinary_failures import cli, packets
from test_selective_installation import _directory_link, _remove_directory_link
from ff_job_feedback import _lookup_job
from ff_job_runner import run_job
from ff_job_store import JobStore

ROOT = Path(__file__).resolve().parents[1]
OWNER = "filing-fetch"


def _digest(value):
    body = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("ascii")).hexdigest()


def _request(observation):
    row = {**observation, "origin_owner": OWNER}
    names = ("owner", "origin_owner", "run_id", "attempt_id", "step_id", "check_id")
    occurrence = _digest([row[name] for name in names])
    action = _digest(["reconcile", OWNER, occurrence])
    payload = {"occurrence_id": occurrence, "observation": row}
    return {
        "schema_version": "feedback-action/1", "owner": OWNER, "method": "lookup", "kind": "reconcile",
        "action_id": action, "request_digest": _digest([OWNER, "reconcile", action, payload]),
        "payload": payload,
    }


def _invoke(jobs, observation, *config):
    call = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", str(ROOT / "scripts/ff_job_feedback.py"),
         "reconcile", "--jobs-dir", str(jobs), *map(str, config)],
        input=json.dumps(_request(observation)), capture_output=True, text=True, encoding="utf-8", check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert call.returncode == 0, (call.stdout, call.stderr)
    return json.loads(call.stdout)


def _snapshot(jobs):
    return {path.relative_to(jobs): path.read_bytes() for path in jobs.rglob("*") if path.is_file()}


def _triage_request(observation):
    request = _request(observation)
    payload = request["payload"]
    action = _digest(["triage", OWNER, payload["occurrence_id"]])
    return {**request, "kind": "triage", "method": "submit", "action_id": action,
            "request_digest": _digest([OWNER, "triage", action, payload])}


def _triage_cli(reports, *args, request=None, lose_reply=False):
    program = ROOT / "scripts/ff_job_feedback.py"
    if lose_reply:
        # Interrupt the owner after the receipt is committed and before its stdout reply.
        interrupted = (
            "import builtins,os,runpy,sys\n"
            "sys.argv = sys.argv[1:]\n"
            "sys.path.insert(0, sys.argv[0].rsplit(os.sep, 1)[0])\n"
            "builtins.print = lambda *args, **kwargs: os._exit(73)\n"
            "runpy.run_path(sys.argv[0], run_name='__main__')"
        )
        command = ["-c", interrupted, str(program)]
    else:
        command = [str(program)]
    return subprocess.run(
        [sys.executable, "-B", "-X", "utf8", *command, "--reports-dir", str(reports), *map(str, args)],
        input=None if request is None else json.dumps(request), capture_output=True, text=True,
        encoding="utf-8", check=False, timeout=20, env=os.environ.copy(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@pytest.mark.parametrize("historical", [False, True])
def test_triage_cold_reads_the_owner_decision_after_losing_the_reply(tmp_path, historical):
    jobs = tmp_path / "jobs"
    reports = tmp_path / "reports"
    original = cli(tmp_path, "ff_job", ["--jobs-dir", jobs, "get_status", "--owner-job-id", "foreign-id"])
    assert original.returncode == 2
    outbox = jobs / "observations"
    observations = packets(outbox)
    row = next(row for row in observations if row["check_id"] == "execution-outcome")
    if historical:
        packet, = outbox.glob("*.jsonl")
        packet.write_text(json.dumps(row) + "\n", encoding="utf-8")
    before = _snapshot(jobs)
    request = _triage_request(row)
    action = request["action_id"]

    absent = _triage_cli(reports, "get-triage", action)
    assert absent.returncode == 1 and not reports.exists()
    run = _triage_cli(reports, "triage", "--jobs-dir", jobs, request=request, lose_reply=True)
    assert run.returncode == 73 and run.stdout == run.stderr == ""
    cold = _triage_cli(reports, "get-triage", action)
    receipt = json.loads(cold.stdout)["receipt"]
    assert cold.returncode == 0 and receipt["request"] == request
    result = receipt["result"]
    assert result["decision"] == "needs_evidence" and result["evidence_ref"] == row["evidence_ref"]
    assert result["issue_ref"] == f"ff-triage/1/{action}"
    assert {"original_caller", "original_request"} <= set(result["missing_evidence"])
    assert result["facts"] == {
        "operation": "get_status", "outcome": "request_error", "diagnostic_ref": row["details_ref"],
        "invocation_usage": {"provider_started": None if historical else False,
                             "cost_state": "unknown" if historical else "not_applicable"},
        "target_job_cost_state": "unknown",
    }
    assert _snapshot(jobs) == before
    report = _triage_cli(reports, "get-report", action)
    assert report.returncode == 1
    saved = _snapshot(reports)
    assert len(saved) == 1

    # A durable triage decision survives the disappearance of the original log in this fixture.
    repeat = _triage_cli(reports, "triage", "--jobs-dir", tmp_path / "absent-owner", request=request)
    assert repeat.returncode == 0 and json.loads(repeat.stdout) == {"result": result}
    conflicting = _triage_request({**row, "actual": "other_failure"})
    refused = _triage_cli(reports, "triage", "--jobs-dir", jobs, request=conflicting)
    assert refused.returncode != 0 and _snapshot(reports) == saved


def test_triage_refuses_a_wrong_attempt_and_a_forged_native_reason(tmp_path):
    jobs = tmp_path / "jobs"
    reports = tmp_path / "reports"
    original = cli(tmp_path, "ff_job", ["--jobs-dir", jobs, "get_status", "--owner-job-id", "foreign-id"])
    assert original.returncode == 2
    row = next(row for row in packets(jobs / "observations") if row["check_id"] == "execution-outcome")
    for changes in ({"attempt_id": "another"}, {"actual": "other_failure"}):
        forged = _triage_request({**row, **changes})
        refused = _triage_cli(reports, "triage", "--jobs-dir", jobs, request=forged)
        assert refused.returncode == 1 and json.loads(refused.stdout) == {"error": "original_evidence_unavailable"}
        assert not reports.exists()


@pytest.mark.parametrize("linked", [False, True])
def test_triage_uses_the_selected_reports_root_even_with_an_old_subdirectory(tmp_path, linked):
    jobs = tmp_path / "jobs"
    reports = tmp_path / "reports"
    outside = tmp_path / "outside"
    reports.mkdir()
    old = reports / "triage"
    if linked:
        outside.mkdir()
        _directory_link(old, outside)
    else:
        old.mkdir()
    try:
        attempt = cli(tmp_path, "ff_job", ["--jobs-dir", jobs, "get_status", "--owner-job-id", "foreign-id"])
        assert attempt.returncode == 2
        row = next(row for row in packets(jobs / "observations") if row["check_id"] == "execution-outcome")
        request = _triage_request(row)
        accepted = _triage_cli(reports, "triage", "--jobs-dir", jobs, request=request)
        assert accepted.returncode == 0
        assert not list(old.iterdir())
        assert (reports / f"triage-{request['action_id']}.json").is_file()
        cold = _triage_cli(reports, "get-triage", request["action_id"])
        assert cold.returncode == 0 and json.loads(cold.stdout)["receipt"]["request"] == request
    finally:
        if linked:
            _remove_directory_link(old)


@pytest.mark.parametrize("linked", [
    False, pytest.param(True, marks=[
        pytest.mark.posix_only,
        pytest.mark.skipif(sys.platform == "win32", reason="requires a POSIX file symlink"),
    ]),
])
def test_triage_preserves_only_a_regular_receipt_that_wins_creation(tmp_path, monkeypatch, linked):
    reports = tmp_path / "reports"
    reports.mkdir()
    outside = tmp_path / "other.json"
    row = {
        "schema_version": "feedback-observation/1", "owner": OWNER, "run_id": "run", "attempt_id": "attempt",
        "step_id": "get_status/operation", "check_id": "execution-outcome", "expected": "completed",
        "actual": "request_error", "evidence_ref": "ff-cli/1/operation",
    }
    request = _triage_request(row)
    expected = reports / f"triage-{request['action_id']}.json"
    args = Namespace(reports_dir=reports, jobs_dir=[tmp_path / "jobs"], observations_dir=None)
    monkeypatch.setattr(feedback, "_triage_original", lambda *_: {"missing_evidence": ["second_writer"]})
    write_once = feedback._write_receipt_once
    final = {}

    def competing_writer(path, content):
        assert path == expected
        first = json.loads(content)
        first["result"]["missing_evidence"] = ["first_writer"]
        final.update(first)
        data = json.dumps(first).encode("utf-8")
        if linked:
            outside.write_bytes(data)
            try:
                path.symlink_to(outside)
            except NotImplementedError:
                pytest.skip("filesystem does not implement file symlinks")
        else:
            path.write_bytes(data)
        assert write_once(path, content) is False
        return False

    monkeypatch.setattr(feedback, "_write_receipt_once", competing_writer)
    if linked:
        try:
            with pytest.raises(ValueError, match="regular file"):
                feedback._record_triage(args, request)
            assert expected.is_symlink() and json.loads(outside.read_bytes()) == final
        finally:
            expected.unlink(missing_ok=True)
    else:
        assert feedback._record_triage(args, request) == final["result"]
        assert json.loads(expected.read_bytes()) == final


def test_triage_rejects_an_open_descriptor_from_a_different_inode(tmp_path, monkeypatch):
    path = tmp_path / "triage-original.json"
    other = tmp_path / "other.json"
    path.write_bytes(b"{}")
    other.write_bytes(b"{}")
    monkeypatch.setattr(os, "fstat", lambda _: other.stat())
    with pytest.raises(ValueError, match="changed before reading"):
        feedback._read_triage(path)


def test_triage_rejects_a_reparse_leaf_even_with_a_regular_mode(tmp_path, monkeypatch):
    path = tmp_path / "triage-original.json"
    path.write_bytes(b"{}")
    ordinary_mode = path.lstat().st_mode
    lstat = Path.lstat

    def reparse_candidate(candidate):
        if candidate.name == path.name:
            return SimpleNamespace(st_mode=ordinary_mode, st_file_attributes=FILE_ATTRIBUTE_REPARSE_POINT)
        return lstat(candidate)

    monkeypatch.setattr(Path, "lstat", reparse_candidate)
    with pytest.raises(ValueError, match="regular file"):
        feedback._read_triage(path)


@pytest.mark.parametrize("scope", ["request", "payload", "observation", "observation_value"])
def test_triage_does_not_retain_fields_outside_the_durable_action_contract(tmp_path, scope):
    jobs = tmp_path / "jobs"
    reports = tmp_path / "reports"
    original = cli(tmp_path, "ff_job", ["--jobs-dir", jobs, "get_status", "--owner-job-id", "foreign-id"])
    assert original.returncode == 2
    row = next(row for row in packets(jobs / "observations") if row["check_id"] == "execution-outcome")
    row.update(parent_step_id="fixture-parent", original_occurrence_id="fixture-origin",
               refusal_code="fixture_refusal", terminal_check_id="fixture-terminal")
    valid = _triage_request(row)
    request = json.loads(json.dumps(valid))
    payload = request["payload"]
    marker = "fixture-private-field"
    if scope == "observation_value":
        payload["observation"]["issue_key"] = {"uncontracted_field": marker}
    else:
        fields = {"request": request, "payload": payload, "observation": payload["observation"]}
        fields[scope]["uncontracted_field"] = marker
    action_id = request["action_id"]
    request["request_digest"] = _digest([OWNER, "triage", action_id, payload])

    rejected = _triage_cli(reports, "triage", "--jobs-dir", jobs, request=request)
    assert rejected.returncode == 1 and not reports.exists()
    assert marker not in rejected.stdout + rejected.stderr

    accepted = _triage_cli(reports, "triage", "--jobs-dir", jobs, request=valid)
    assert accepted.returncode == 0
    lookup = _triage_cli(reports, "get-triage", action_id)
    assert lookup.returncode == 0 and json.loads(lookup.stdout)["receipt"]["request"] == valid

    receipt_path = reports / f"triage-{action_id}.json"
    receipt_path.write_text(json.dumps({"request": request, **json.loads(accepted.stdout)}), encoding="utf-8")
    rejected_lookup = _triage_cli(reports, "get-triage", action_id)
    assert rejected_lookup.returncode == 1 and marker not in rejected_lookup.stdout + rejected_lookup.stderr


def test_report_keeps_version_bound_replay_receipts_separate_from_triage(tmp_path):
    reports = tmp_path / "reports"
    request = {"schema_version": "feedback-action/1", "owner": OWNER, "method": "submit", "kind": "report"}
    scope = ["occurrence", OWNER, "owner/issue", "fixed-version"]
    for verdict in ("needs_evidence", "verified"):
        action = _digest(["report", OWNER, *scope, verdict])
        payload = {
            "occurrence_id": scope[0], "original_occurrence_id": scope[0], "origin_owner": OWNER,
            "issue_ref": scope[2], "fixed_version": scope[3], "verdict": verdict, "evidence_ref": "replay/receipt",
        }
        submit = {**request, "action_id": action, "payload": payload,
                  "request_digest": _digest([OWNER, "report", action, payload])}
        response = _triage_cli(reports, "report", request=submit)
        if verdict == "needs_evidence":
            assert response.returncode == 1 and not reports.exists()
        else:
            assert response.returncode == 0 and json.loads(response.stdout) == {"result": {"recorded": True}}
            saved = _snapshot(reports)
            assert _triage_cli(reports, "report", request=submit).returncode == 0
            cold = _triage_cli(reports, "get-report", action)
            assert cold.returncode == 0 and json.loads(cold.stdout) == {"report": submit}
            assert _triage_cli(reports, "get-triage", action).returncode == 1
            assert _snapshot(reports) == saved


@pytest.mark.parametrize("provider_fee", ["0.35", None])
def test_native_result_and_original_usage_are_read_without_configuration(tmp_path, monkeypatch, provider_fee):
    jobs = tmp_path / "jobs"
    store = JobStore(jobs)
    sidecar = tmp_path / "native.jsonl"
    monkeypatch.setenv("RESEARCH_FEEDBACK_OUT", str(sidecar))
    monkeypatch.setenv("RESEARCH_FEEDBACK_RUN_ID", "original-run")
    monkeypatch.setenv("RESEARCH_FEEDBACK_ATTEMPT_ID", "original-attempt")
    job, _ = _submit(store, kind="filing.acquire", request=_FETCH_REQUEST)
    envelope = {
        "status": "source_candidate",
        "source_ref": _CANDIDATE_HANDLE["source_ref"],
        "acquisition_observation": _observation(provider_started=True, usage_complete=True, cost_usd=provider_fee),
    }
    with patch("ff_job_runner._run_filing_engine", return_value=(envelope, {"calls": 2, "downloads": 1})):
        landed, executed = run_job(store, job["owner_job_id"], config_path=None, timeout_seconds=120)
    assert executed and landed["status"] == "succeeded"
    observation = json.loads(sidecar.read_text(encoding="utf-8").splitlines()[-1])
    saved = _snapshot(jobs)

    first = _invoke(jobs, observation)
    assert first == _invoke(jobs, observation)
    assert first["state"] == "done"
    result = first["result"]
    assert result["owner_job_id"] == job["owner_job_id"]
    assert result["native_attempt"] == result["execution_count"] == 1
    assert result["evidence_ref"] == observation["evidence_ref"]
    assert result["job_status"] == "succeeded"
    assert result["recorded_usage"] == {
        "provider_started": True, "usage_complete": True, "download_events": 1,
    }
    assert result["new_provider_requests"] == result["new_downloads"] == 0
    assert result["new_cost_usd"] == "0.00"
    if provider_fee is None:
        assert result["status"] == "cost_unknown"
        assert result["cost_state"] == "unknown" and result["cost"] is None
    else:
        assert result["status"] == "known"
        assert result["cost_state"] == "known" and result["cost"]["value"] == provider_fee
    assert store.load(job["owner_job_id"])["request"]["acquisition_limits"] == _FETCH_REQUEST["acquisition_limits"]
    assert _snapshot(jobs) == saved


def test_missing_job_and_attempt_mismatch_never_start_recovery(tmp_path):
    missing = tmp_path / "missing"
    bogus = "ffjob-123456abcdef"
    observation = {
        "schema_version": "feedback-observation/1", "owner": OWNER, "run_id": "original-run",
        "attempt_id": "original-attempt", "step_id": f"{bogus}/1", "check_id": "action-started",
        "expected": "started", "actual": "started", "terminal_check_id": "job-outcome",
        "evidence_ref": f"ff-job/1/{bogus}",
    }
    assert _invoke(missing, observation)["state"] == "unknown"
    assert not missing.exists()

    jobs = tmp_path / "jobs"
    store = JobStore(jobs)
    job, _ = _submit(store, kind="filing.acquire", request=_FETCH_REQUEST)
    saved = _snapshot(jobs)
    old = dict(observation, evidence_ref=f"ff-job/1/{job['owner_job_id']}",
               step_id=f"{job['owner_job_id']}/2")
    assert _invoke(jobs, old, "--config", tmp_path / "missing-config.json")["state"] == "unknown"
    assert _snapshot(jobs) == saved


def test_configured_lookup_is_pure_before_explicit_read_only_reconciliation(tmp_path):
    from ff_job_runner import reconcile

    jobs = tmp_path / "jobs"
    store = JobStore(jobs)
    job, _ = _submit(store, kind="filing.acquire", request=_FETCH_REQUEST)
    job_id = job["owner_job_id"]
    job = store.mutate(job_id, lambda record: dict(
        record, status="unknown", status_known=False, attempts=1, cost_state="unknown",
    ))
    row = {
        "schema_version": "feedback-observation/1", "owner": OWNER, "run_id": job_id,
        "attempt_id": "preserved-attempt", "step_id": f"{job_id}/1", "check_id": "action-started",
        "expected": "started", "actual": "started", "terminal_check_id": "job-outcome",
        "evidence_ref": f"ff-job/1/{job_id}",
    }
    request = _request(row)
    readonly = Namespace(jobs_dir=jobs, config=None, timeout_seconds=10.0)
    configured = Namespace(jobs_dir=jobs, config=tmp_path / "lookup-only.json", timeout_seconds=10.0)
    before = _snapshot(jobs)
    with patch("ff_job_runner._reconcile_query", return_value=("succeeded", None, {})) as query:
        assert _lookup_job(readonly, request) == {"state": "unknown"}
        assert _lookup_job(configured, request) == {"state": "unknown"}
        query.assert_not_called()
        assert _snapshot(jobs) == before
        reconcile(store, job_id, idempotency_key="explicit-reconcile", config_path=configured.config,
                  timeout_seconds=10.0, expected_attempt=1)
        first = _lookup_job(configured, request)
        assert first == _lookup_job(configured, request)
        query.assert_called_once_with(
            "filing.acquire", job["request"], owner_job_id=job_id, config_path=configured.config,
            timeout_seconds=10.0,
        )
    result = first["result"]
    assert result["job_status"] == "succeeded" and result["cost_state"] == "unknown"
    assert result["native_attempt"] == 1 and result["execution_count"] == 0
    after = store.load(job_id)
    assert after["owner_job_id"] == job_id and after["attempts"] == 1
    assert after["spend_evidence"] == job["spend_evidence"]
    assert after["request"]["acquisition_limits"] == _FETCH_REQUEST["acquisition_limits"]
    assert [action["action"] for action in after["actions"]] == ["reconcile"]
