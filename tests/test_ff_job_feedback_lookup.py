"""F4 checks the original native job without starting another acquisition."""
from argparse import Namespace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from test_ff_job_facade import _CANDIDATE_HANDLE, _FETCH_REQUEST, _observation, _submit
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
    )
    assert call.returncode == 0, (call.stdout, call.stderr)
    return json.loads(call.stdout)


def _snapshot(jobs):
    return {path.relative_to(jobs): path.read_bytes() for path in jobs.rglob("*") if path.is_file()}


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
