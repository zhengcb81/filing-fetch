"""F4 cold-reads one original scheduled slot by its public reference, without another tick."""

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from test_feedback_ordinary_failures import packets
from test_ff_job_facade import _CANDIDATE_HANDLE, _FETCH_REQUEST, _observation, _submit
from test_ff_job_feedback_lookup import _digest, _request, _snapshot

ROOT = Path(__file__).resolve().parents[1]
OWNER = "filing-fetch"
# Sanitized copies keep the native shape of the two historical slots and of their acquisition jobs.
FIRST = "sr-20261116T073000Z-1a2b3c4d5e"
LATER = "sr-20261123T073000Z-6f7e8d9c0a"
OTHER_ROUND = "sr-20261123T073000Z-0b1c2d3e4f"
RUNNING = "sr-20261130T073000Z-1122334455"
SKIPPED = "sr-20261130T073000Z-5566778899"
NEVER = "sr-20261130T073000Z-0000000000"
CORRUPT = "sr-20261130T073000Z-deadbeef00"
PLAIN, STARTED = "ffjob-000000000001", "ffjob-000000000002"
COUNTS = ("candidates", "reused", "downloaded", "read", "summarized", "skipped", "pending", "failed")
ZERO_COST = {
    "actual_or_forecast": "actual", "analysis_subject_id": None, "basis": "engine_zero_evidence",
    "currency": "USD", "fiscal_year": None, "period_end": None, "period_kind": None, "period_start": None,
    "scale": None, "scenario": None, "unit": "USD", "value": "0.00",
}


def _counts(**values):
    return dict.fromkeys(COUNTS, 0) | values


def _job(job_id, run_id, *, kind, started):
    return {
        "actions": [], "attempts": 1, "cancel_requested": False, "command_id": run_id,
        "cost": dict(ZERO_COST) if not started else None,
        "cost_state": "known" if not started else "unknown",
        "error": {"code": "upstream_error", "owner": OWNER, "retryable": True},
        "events": [
            {"at": "2026-11-21T14:17:48.863Z", "event": "submitted"},
            {"at": "2026-11-21T14:17:59.973Z", "detail": {"engine_status": None, "status": "failed"},
             "event": "run_finished"},
        ],
        "execution_count": 1, "idempotency_key": "sr-source-" + "0" * 64, "intent": "fetch_if_missing",
        "kind": kind, "owner_job_id": job_id, "owner_pid": None, "provider_phase_reached": started,
        "request": {"schema_version": "ff-transcript-request/1" if started else "2.0", "intent": "fetch_if_missing"},
        "request_hash": "0" * 64, "result": None, "schema_version": "ff-job/1",
        "spend_evidence": {"contract": "ff-filing-provider/1", "cost_usd": None, "download_events": 0,
                           "phase_reached": started, "provider_started": started, "usage_complete": True},
        "status": "failed", "status_known": True,
    }


def _slot(run_id, slot_id, *, counts, reasons, jobs=None, readings=None, state="partial", **extra):
    usage = {"metadata_bytes": 1965606, "metadata_requests": 4, "owner_cost_unknown": 0}
    for group, values in (("acquisition_jobs", jobs), ("reading_runs", readings)):
        if values is not None:
            usage[group] = values
            usage["owner_cost_unknown"] += sum(v.get("cost_state") == "unknown" for v in values.values())
    return {
        "counts": counts, "reason_codes": reasons, "roster_snapshot_id": "fixture-" + "0" * 57,
        "run_id": run_id, "slot_id": slot_id, "started_at": "2026-11-21T14:14:56Z", "state": state,
        "updated_at": "2026-11-21T14:14:56Z", "usage": usage, **extra,
    }


def _undispatched():
    """Partial; the only original call never reached the provider, so its zero is proven."""
    return _slot(
        FIRST, "weekly:2026-11-16", counts=_counts(candidates=1, failed=1), reasons=["upstream_error"],
        jobs={PLAIN: {"cost_state": "known", "cost_usd": "0.00"}},
    )


def _unknown_cost():
    """Partial with one sub-item never settled; the started provider call's cost stays unknown."""
    return _slot(
        LATER, "weekly:2026-11-23",
        counts=_counts(candidates=2, failed=2, pending=1),
        reasons=["incremental_discover_unavailable", "discovery_failed:unsupported_sec_form",
                 "discovery_partial", "upstream_error"],
        jobs={PLAIN: {"cost_state": "known", "cost_usd": "0.00"}, STARTED: {"cost_state": "unknown"}},
    )


def _original_jobs():
    """Both jobs were created by the first slot; the later slot retried one and reused the other."""
    retried, reused = (_job(PLAIN, FIRST, kind="filing.acquire", started=False),
                       _job(STARTED, FIRST, kind="transcript.acquire", started=True))
    retried.update(attempts=3, execution_count=3, actions=[
        {"action": "retry", "at": "2026-11-23T20:01:55.095Z", "idempotency_key": f"{LATER}-retry-{PLAIN}"},
    ])
    return [retried, reused]


def _ledger(root, runs, jobs=(), *, current=None, last=None, corrupt=()):
    history = root / "scheduled" / "runs"
    (root / "jobs").mkdir(parents=True)
    history.mkdir(parents=True)
    for run in runs:
        (history / f"{run['run_id']}.json").write_text(json.dumps(run, indent=1), encoding="utf-8")
    for run_id in corrupt:
        (history / f"{run_id}.json").write_text('{"counts": ', encoding="utf-8")
    for job in jobs:
        (root / "jobs" / f"{job['owner_job_id']}.json").write_text(json.dumps(job, indent=1), encoding="utf-8")
    (root / "scheduled" / "state.json").write_text(json.dumps({
        "revision": 1, "settings": {}, "current": current, "last_run": last, "last_slot": None,
        "watermarks": {}, "pending": {},
    }), encoding="utf-8")


def _offered(run, root, tmp_path, monkeypatch, check_id):
    """One row the native publisher already offered for this slot, read from an isolated outbox."""
    from ff_job_feedback import _refresh_item, _refresh_summary

    out = tmp_path / "outbox"
    monkeypatch.setenv("RESEARCH_FEEDBACK_DIR", str(out))
    monkeypatch.delenv("RESEARCH_FEEDBACK_OUT", raising=False)
    assert _refresh_summary(run, root, None)
    for key in run.get("failures") or {}:
        _refresh_item(run, key, run["failures"][key], root, None)
    reference = f"ff-scheduled-refresh/1/{run['run_id']}"
    return next(row for row in packets(out)
                if row["check_id"] == check_id and row["evidence_ref"] == reference)


def _reconcile(root, observation, *, config=None):
    clean = {key: value for key, value in os.environ.items() if not key.startswith("RESEARCH_FEEDBACK_")}
    call = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", str(ROOT / "scripts/ff_job_feedback.py"), "reconcile",
         "--jobs-dir", str(root), "--timeout-seconds", "10",
         *(["--config", str(config)] if config else [])],
        input=json.dumps(_request(observation)), capture_output=True, text=True, encoding="utf-8",
        check=False, timeout=30, env=clean,
    )
    assert call.returncode == 0, (call.stdout, call.stderr)
    return json.loads(call.stdout)


def _attempts(snapshot):
    return sorted((name.name, json.loads(data)["attempts"]) for name, data in snapshot.items()
                  if name.parent.name == "jobs")


def _assert_untouched(root, before):
    after = _snapshot(root)
    assert after == before
    assert _attempts(after) == _attempts(before)
    assert not (root / "observations").exists()


@pytest.mark.parametrize(
    ("run", "expected", "items"),
    [
        pytest.param(_undispatched(), {"status": "known", "job_status": "failed", "cost_state": "known"}, [
            {"kind": "acquisition_job", "id": PLAIN, "dispatch": "original", "job_status": "failed",
             "cost_state": "known", "recorded_usage": {
                 "provider_started": False, "usage_complete": True, "download_events": 0}}],
            id="partial-undispatched-zero"),
        pytest.param(_unknown_cost(), {"status": "cost_unknown", "job_status": "unconfirmed",
                                       "cost_state": "unknown"}, [
            {"kind": "acquisition_job", "id": PLAIN, "dispatch": "retry", "job_status": "failed",
             "cost_state": "known", "recorded_usage": {
                 "provider_started": False, "usage_complete": True, "download_events": 0}},
            {"kind": "acquisition_job", "id": STARTED, "dispatch": "reused", "job_status": "failed",
             "cost_state": "unknown", "recorded_usage": {
                 "provider_started": True, "usage_complete": True, "download_events": 0}}],
            id="partial-pending-unknown-cost"),
    ],
)
def test_original_slot_is_cold_read_twice_without_new_work(tmp_path, monkeypatch, run, expected, items):
    root = tmp_path / "state"
    _ledger(root, [run], _original_jobs())
    observation = _offered(run, root, tmp_path, monkeypatch, "refresh-usage")
    recorder = tmp_path / "owner-was-called"
    config = tmp_path / "owner.json"
    config.write_text(json.dumps({"schema_version": "1.0", "connection": {
        "cwd": str(tmp_path), "commands": {"catalog": [
            sys.executable, "-c", "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('called')",
            str(recorder)]},
    }}), encoding="utf-8")
    before = _snapshot(root)
    assert [attempts for _, attempts in _attempts(before)] == [3, 1]

    first = _reconcile(root, observation, config=config)
    second = _reconcile(root, observation)

    assert first["state"] == "done" and first == second
    result = first["result"]
    assert {key: result[key] for key in expected} == expected
    assert result["evidence_ref"] == observation["evidence_ref"] == f"ff-scheduled-refresh/1/{run['run_id']}"
    assert result["native_attempt"] == observation["attempt_id"] == "scheduled"
    assert result["native_status"] == "partial" and result["counts"] == run["counts"]
    assert result["reason_codes"] == run["reason_codes"] and result["items"] == items
    assert "item" not in result
    # A successful read exit is never a business success for a partial slot.
    assert result["job_status"] != "succeeded"
    _assert_untouched(root, before)
    assert not recorder.exists()


def test_missing_other_round_running_skip_and_corrupt_records_do_not_shadow_each_other(tmp_path, monkeypatch):
    undispatched, unknown = _undispatched(), _unknown_cost()
    other = _slot(OTHER_ROUND, "weekly:2026-11-23", counts=_counts(candidates=1, failed=1),
                  reasons=["upstream_error"], jobs={STARTED: {"cost_state": "unknown"}})
    # Failures are offered while the slot is still active; nothing final exists for it yet.
    running = _slot(RUNNING, "weekly:2026-11-30", counts=_counts(failed=1), reasons=["owner_timeout"],
                    state="reading", feedback_identity={"run_id": "root-run", "attempt_id": "try-1"},
                    failures={_digest(["acquisition", "x", "owner_timeout"]): {
                        "schema_version": "ff-failure-detail/1", "reason": "owner_timeout", "causes": [],
                        "stage": "acquisition", "reference_hash": _digest("sr-source-x")}})
    skipped = _slot(SKIPPED, "weekly:2026-11-30", counts=_counts(reused=2, skipped=2),
                    reasons=["reading_skipped_by_owner"], state="completed",
                    readings={"sr-read-fixture": {"cost_state": "not_applicable"}})
    root = tmp_path / "state"
    _ledger(root, [undispatched, unknown, other, skipped], _original_jobs(), current=running, last=skipped,
            corrupt=(CORRUPT,))

    def row(run, check_id="refresh-usage"):
        return _offered(run, root, tmp_path, monkeypatch, check_id)

    reference = f"ff-scheduled-refresh/1/{NEVER}"
    before = _snapshot(root)
    answers = {
        "no-original-slot": _reconcile(root, dict(row(undispatched), evidence_ref=reference)),
        "cadence-id-is-not-a-run": _reconcile(
            root, dict(row(undispatched), evidence_ref="ff-scheduled-refresh/1/weekly:2026-11-16")),
        "other-round-of-same-period": _reconcile(root, row(other)),
        "same-period-original": _reconcile(root, row(unknown)),
        "other-round-step-under-original-reference": _reconcile(
            root, {**row(other), "step_id": LATER, "evidence_ref": f"ff-scheduled-refresh/1/{LATER}"}),
        "still-running": _reconcile(root, row(running, "refresh-item-outcome")),
        "legitimate-skip": _reconcile(root, row(skipped)),
        "corrupt-record": _reconcile(
            root, dict(row(undispatched), evidence_ref=f"ff-scheduled-refresh/1/{CORRUPT}")),
        "healthy-neighbour": _reconcile(root, row(undispatched)),
    }

    unknown_answer = {"state": "unknown"}
    assert [answers[name] for name in ("no-original-slot", "cadence-id-is-not-a-run",
                                       "other-round-step-under-original-reference", "corrupt-record")] == (
        [unknown_answer] * 4)
    assert answers["other-round-of-same-period"]["result"]["evidence_ref"].endswith(OTHER_ROUND)
    original = answers["same-period-original"]["result"]
    assert original["evidence_ref"].endswith(LATER)
    assert {k: original[k] for k in ("status", "job_status", "cost_state")} == {
        "status": "cost_unknown", "job_status": "unconfirmed", "cost_state": "unknown"}
    assert answers["still-running"] == {"state": "pending"}
    settled = answers["legitimate-skip"]["result"]
    assert (settled["status"], settled["job_status"], settled["cost_state"]) == (
        "known", "succeeded", "not_applicable")
    assert settled["counts"]["skipped"] == 2
    assert answers["healthy-neighbour"]["result"]["job_status"] == "failed"
    # Nine questions: four share only "unknown"; the five other answers stay pairwise distinct.
    assert len({json.dumps(a, sort_keys=True) for a in answers.values()}) == 6
    _assert_untouched(root, before)
    absent = tmp_path / "never-created"
    assert _reconcile(absent, row(undispatched)) == unknown_answer and not absent.exists()


def test_unbound_attempts_and_unmapped_items_stay_unknown(tmp_path, monkeypatch):
    run = _undispatched()
    root = tmp_path / "state"
    _ledger(root, [run], _original_jobs())
    summary = _offered(run, root, tmp_path, monkeypatch, "refresh-outcome")
    before = _snapshot(root)

    # Historical receipts never stored the mapping of each failure; it cannot be reconstructed.
    unbound = [dict(summary, attempt_id="another-attempt"), dict(summary, run_id="another-run"),
               dict(summary, step_id=LATER), dict(summary, step_id=f"{FIRST}/{_digest(['item'])}",
                                                  check_id="refresh-item-outcome")]
    assert [_reconcile(root, observation) for observation in unbound] == [{"state": "unknown"}] * 4
    _assert_untouched(root, before)

    foreign = tmp_path / "foreign-command"
    _ledger(foreign, [run], [{**_job(PLAIN, "dashboard-request", kind="filing.acquire", started=False)}])
    result = _reconcile(foreign, summary)["result"]
    assert (result["status"], result["cost_state"]) == ("cost_unknown", "unknown")
    assert result["items"] == [{"kind": "acquisition_job", "id": PLAIN, "dispatch": "unbound", "cost_state": None}]
    missing = tmp_path / "missing-job"
    _ledger(missing, [run])
    assert _reconcile(missing, summary)["result"] == {
        **result, "items": result["items"]}


def test_recorded_item_failure_is_bound_to_its_original_attempt_and_reason(tmp_path, monkeypatch):
    key = _digest(["reading", "reference", "parse_failed"])
    run = _slot(
        LATER, "weekly:2026-11-23", counts=_counts(candidates=1, failed=1), reasons=["parse_failed"],
        readings={"sr-read-fixture": {"cost_state": "known", "cost_usd": "0.00"}},
        feedback_identity={"run_id": "root-run", "attempt_id": "try-2"},
        failures={key: {"schema_version": "ff-failure-detail/1", "reason": "parse_failed",
                        "causes": [{"relation": "raised", "type": "OwnerUnavailable", "frames": []}],
                        "stage": "reading", "reference_hash": _digest("item")}},
    )
    root = tmp_path / "state"
    _ledger(root, [run])
    outcome = _offered(run, root, tmp_path, monkeypatch, "refresh-item-outcome")
    before = _snapshot(root)

    reply = _reconcile(root, outcome)
    result = reply["result"]
    assert reply["state"] == "done"
    assert (result["status"], result["job_status"], result["cost_state"]) == ("known", "failed", "known")
    assert result["native_attempt"] == "try-2" and result["item"] == {
        "key": key, "reason": "parse_failed", "stage": "reading"}
    assert result["items"] == [{"kind": "reading_run", "id": "sr-read-fixture", "cost_state": "known"}]
    assert _reconcile(root, dict(outcome, attempt_id="scheduled")) == {"state": "unknown"}
    _assert_untouched(root, before)


def test_unfinished_dispatch_or_stale_zero_cannot_settle_a_slot(tmp_path, monkeypatch):
    interrupted = _slot(LATER, "weekly:2026-11-23", counts=_counts(candidates=1, failed=1),
                        reasons=["upstream_error"], jobs={PLAIN: {"cost_state": "known", "cost_usd": "0.00"}},
                        active_action={"stage": "acquisition", "reference": "sr-source-x", "admitted_at": "x"})
    root = tmp_path / "state"
    _ledger(root, [interrupted], [_job(PLAIN, LATER, kind="filing.acquire", started=False)])
    observation = _offered(interrupted, root, tmp_path, monkeypatch, "refresh-outcome")
    assert _reconcile(root, observation)["result"]["job_status"] == "unconfirmed"

    stale = tmp_path / "stale"
    undispatched = _undispatched()
    _ledger(stale, [undispatched], [{**_job(PLAIN, FIRST, kind="filing.acquire", started=False),
                                     "cost": None, "cost_state": "unknown"}])
    result = _reconcile(stale, _offered(undispatched, stale, tmp_path, monkeypatch, "refresh-usage"))["result"]
    assert (result["status"], result["cost_state"], result["items"][0]["cost_state"]) == (
        "cost_unknown", "unknown", "unknown")


def test_ff_job_reference_keeps_its_established_lookup_beside_slot_records(tmp_path, monkeypatch):
    from ff_job_runner import run_job
    from ff_job_store import JobStore

    jobs = tmp_path / "state"
    store = JobStore(jobs)
    sidecar = tmp_path / "native.jsonl"
    monkeypatch.setenv("RESEARCH_FEEDBACK_OUT", str(sidecar))
    job, _ = _submit(store, kind="filing.acquire", request=_FETCH_REQUEST)
    envelope = {"status": "source_candidate", "source_ref": _CANDIDATE_HANDLE["source_ref"],
                "acquisition_observation": _observation(provider_started=True, usage_complete=True,
                                                        cost_usd="0.35")}
    with patch("ff_job_runner._run_filing_engine", return_value=(envelope, {"calls": 2, "downloads": 1})):
        landed, executed = run_job(store, job["owner_job_id"], config_path=None, timeout_seconds=120)
    assert executed and landed["status"] == "succeeded"
    observation = json.loads(sidecar.read_text(encoding="utf-8").splitlines()[-1])
    plain = _reconcile(jobs, observation)
    (jobs / "scheduled").mkdir()
    (jobs / "scheduled" / "state.json").write_text("{", encoding="utf-8")
    before = _snapshot(jobs)

    reply = _reconcile(jobs, observation)

    assert reply == plain == {"state": "done", "result": {
        "status": "known", "job_status": "succeeded", "cost_state": "known",
        "cost": landed["cost"], "evidence_ref": f"ff-job/1/{job['owner_job_id']}",
        "owner_job_id": job["owner_job_id"], "native_attempt": 1, "execution_count": 1,
        "recorded_usage": {"provider_started": True, "usage_complete": True, "download_events": 1},
        "new_provider_requests": 0, "new_downloads": 0, "new_cost_usd": "0.00",
    }}
    assert "native_status" not in reply["result"] and "items" not in reply["result"]
    _assert_untouched(jobs, before)
