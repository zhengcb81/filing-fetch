"""ROOT DU8 acceptance: coverage honesty, attempt ownership and observed cleanup."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools/offline_contract_matrix"
sys.path[:0] = [str(TOOLS), str(ROOT / "scripts")]
import extended_cases  # noqa: E402
from case_specs import get_spec  # noqa: E402
import runtime  # noqa: E402


def recovery():
    path = ROOT / "docs/plans/du8-matrix-2026-10-16/fixtures/interruption_recovery_e2e.py"
    spec = importlib.util.spec_from_file_location("root_du8_recovery", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def negative(tmp_path, count, *, reason="provider_deadline", case_id="call_hard_timeout"):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / f"{case_id}.result.json").write_text(
        json.dumps({"status": "provider_unavailable", "reason": reason}), encoding="utf8"
    )
    et = tmp_path / "et"
    et.mkdir(exist_ok=True)
    ctx = SimpleNamespace(
        artifacts=artifacts,
        env=SimpleNamespace(calls_file=lambda tag: tmp_path / "calls", et_temp_root=lambda: et),
        write_state=lambda **kw: None,
        run_ff=lambda *a, **kw: {
            "response": {"transcript": {"status": "provider_unavailable", "reason": reason}},
            "request_ref": "request",
            "response_ref": "response",
        },
        fixture_requests=lambda path: count,
    )
    return extended_cases.transcript_negative(
        ctx, "stall", case_id, {"provider_deadline"}, seconds=1
    )


def test_pre_get_deadline_is_partial_coverage_not_broken_boundary_or_inflight_pass(tmp_path):
    result = negative(tmp_path, 0)
    assert result.result == "PARTIAL"
    assert result.actual["deadline_coverage"] == {
        "absolute_boundary": "PASS",
        "inflight_stall": "NOT_RUN",
        "observed_gets": 0,
    }
    assert "GET" in " ".join(result.diagnostics)


def test_observed_get_deadline_keeps_original_full_pass_and_authority(tmp_path):
    result = negative(tmp_path, 1)
    assert result.result == "PASS"
    assert result.actual["deadline_coverage"]["inflight_stall"] == "PASS"
    # A relabelled zero-GET row still fails the unchanged independent authority.
    spec = get_spec("call_hard_timeout")
    row = result.to_dict()
    row["actual"]["runs"] = [
        {
            "response": {
                "transcript": {"status": "provider_unavailable", "reason": "provider_deadline"}
            },
            "et_fixture_requests": 0,
        }
    ]
    assert spec.assertion_errors(row)


@pytest.mark.parametrize("count,reason", [(0, "other"), (2, "provider_deadline")])
def test_wrong_reason_or_duplicate_gets_are_not_valid_deadline_coverage(tmp_path, count, reason):
    assert negative(tmp_path, count, reason=reason).result == "FAIL"


def test_other_negative_case_still_requires_one_attempt(tmp_path):
    assert negative(tmp_path, 0, case_id="call_wrong_symbol").result == "FAIL"


def test_recovery_only_selects_its_unique_new_attempt(tmp_path):
    mod = recovery()
    old = tmp_path / "attempt-old"
    old.mkdir()
    assert mod._new_attempt(tmp_path, {"attempt-old"}) is None
    fresh = tmp_path / "attempt-fresh"
    fresh.mkdir()
    assert mod._new_attempt(tmp_path, {"attempt-old"}) == fresh
    (tmp_path / "attempt-other").mkdir()
    assert mod._new_attempt(tmp_path, {"attempt-old"}) is None


def test_old_or_preparation_artifacts_cannot_prove_case_entry(tmp_path):
    mod = recovery()
    output = tmp_path / "output"
    (output / "artifacts").mkdir(parents=True)
    (output / "artifacts" / "warm-seed-receipts.json").write_text("[]")
    assert mod._case_entry(output, tmp_path / "scratch") is None


def test_case_marker_binds_request_fixture_get_to_same_owned_attempt(tmp_path):
    mod = recovery()
    output, scratch, calls, fixture = _observed_fixture(tmp_path)
    observations = {}
    assert mod._case_entry(output, scratch, observations=observations) is None
    calls.write_text('{"op":"get"}\n')
    marker = mod._case_entry(output, scratch, observations=observations)
    assert marker["case_id"] == "call_hard_timeout" and marker["observed_gets"] == 1
    assert marker["request_sha256"] and marker["fixture_sha256"] and marker["calls_sha256"]
    foreign = tmp_path / "foreign.jsonl"
    foreign.write_text('{"op":"get"}\n')
    fixture.write_text(json.dumps({"state": {"calls_file": str(foreign)}}))
    assert mod._case_entry(output, scratch, observations=observations) is None


def test_cleanup_observation_failure_is_unknown_never_empty_success(tmp_path):
    mod = recovery()
    state = SimpleNamespace(chunks={"stdout": [], "stderr": []})
    proc = SimpleNamespace(returncode=None)
    with patch.object(
        mod.transport, "_cleanup", side_effect=OSError("synthetic unavailable owner")
    ):
        observed = mod._finish_owned(proc, None, state)
    assert observed["status"] == "unknown" and observed["tree_reaped"] is None


def test_real_bounded_stall_is_entered_and_owned_tree_reaped(tmp_path):
    mod = recovery()
    marker = tmp_path / "entered.json"
    command = [
        sys.executable,
        "-B",
        "-S",
        "-c",
        "import json,os,subprocess,sys,time;from pathlib import Path;"
        'child=subprocess.Popen([sys.executable,"-B","-S","-c","import time;time.sleep(60)"]);'
        'Path(sys.argv[1]).write_text(json.dumps({"op":"get","pids":[os.getpid(),child.pid]}));'
        "time.sleep(60)",
        str(marker),
    ]
    # Test fixture has its own finite ceiling; no 30s/180s product budget changes.
    receipt = mod._interrupt_owned(
        command,
        cwd=tmp_path,
        env=mod._safe_env(),
        observe=lambda: json.loads(marker.read_text()) if marker.exists() else None,
        seconds=5,
    )
    assert receipt["case_entry"]["op"] == "get"
    assert receipt["cleanup"]["status"] == "observed" and receipt["cleanup"]["tree_reaped"] is True
    assert receipt["interrupted"] is True
    assert not any(mod.transport.pid_is_alive(pid) for pid in receipt["case_entry"]["pids"])


def test_absolute_wait_is_not_renewed_after_slow_spawn(tmp_path):
    mod = recovery()
    now = [100.0]
    proc = SimpleNamespace(returncode=1, poll=lambda: None)
    state = SimpleNamespace(start=lambda *a: None, chunks={"stdout": [], "stderr": []})
    observed = []

    def spawn(*a):
        now[0] += 2.0
        return proc, None

    with (
        patch.object(mod.time, "monotonic", side_effect=lambda: now[0]),
        patch.object(mod.transport, "_spawn", side_effect=spawn),
        patch.object(mod.transport, "_IOState", return_value=state),
        patch.object(
            mod, "_finish_owned", return_value={"status": "observed", "tree_reaped": True}
        ),
    ):
        result = mod._interrupt_owned(
            ["fake"], cwd=tmp_path, env={}, observe=lambda: observed.append(1), seconds=1
        )
    assert observed == [] and result["case_entry"] is None and result["interrupted"] is False


def test_original_limits_and_fixed_request_authority_stay_unchanged():
    import cli_main

    assert (
        cli_main.WORKERS,
        cli_main.CASE_TIMEOUT,
        cli_main.BATCH_DEADLINE,
        cli_main.PROOF_RESERVE_SECONDS,
    ) == (2, 30, 180, 10)
    assert (
        get_spec("call_hard_timeout")
        .runs[0]
        .request()["companion_transcript"]["acquisition_limits"]["timeout_seconds"]
        == 1
    )
    with patch("runtime.time.monotonic", return_value=20.0):
        deadline = runtime.Deadline(1)
    with patch("runtime.time.monotonic", return_value=21.1):
        with pytest.raises(runtime.DeadlineExceeded):
            deadline.remaining()


def _observed_fixture(tmp_path):
    output = tmp_path / "output"
    artifacts = output / "artifacts"
    artifacts.mkdir(parents=True)
    scratch = tmp_path / "scratch"
    calls = scratch / "g1/proxy/calls/current.jsonl"
    calls.parent.mkdir(parents=True)
    state = {"calls_file": str(calls), "receipt_tag": "call_hard_timeout"}
    (calls.parent.parent / "state.json").write_text(json.dumps(state))
    (artifacts / "call_hard_timeout.run1.request.json").write_text("{}")
    fixture = artifacts / "call_hard_timeout.run1.fixture.json"
    fixture.write_text(json.dumps({"state": state}))
    return output, scratch, calls, fixture


def test_first_seen_positive_get_is_not_new_observed_work(tmp_path):
    mod = recovery()
    output, scratch, calls, _ = _observed_fixture(tmp_path)
    calls.write_text('{"op":"get"}\n')
    observations = {}
    # Exercise old observer behavior as well: its lack of a new keyword is not
    # the defect. A positive cumulative GET on first observation is the defect.
    import inspect

    kwargs = (
        {"observations": observations}
        if "observations" in inspect.signature(mod._case_entry).parameters
        else {}
    )
    assert mod._case_entry(output, scratch, **kwargs) is None
    assert mod._case_entry(output, scratch, **kwargs) is None


def test_only_current_request_zero_then_new_get_is_observed(tmp_path):
    mod = recovery()
    output, scratch, calls, _ = _observed_fixture(tmp_path)
    observations = {}
    assert mod._case_entry(output, scratch, observations=observations) is None
    calls.write_text('{"op":"get"}\n')
    marker = mod._case_entry(output, scratch, observations=observations)
    assert marker["observed_gets"] == 1 and marker["prior_observed_gets"] == 0
    assert mod._case_entry(output, scratch, observations=observations) is None


def test_partial_log_or_changed_active_state_never_seeds_fake_zero(tmp_path):
    mod = recovery()
    output, scratch, calls, _ = _observed_fixture(tmp_path)
    calls.write_text('{"op":')
    observations = {}
    assert mod._case_entry(output, scratch, observations=observations) is None
    calls.write_text('{"op":"get"}\n')
    assert mod._case_entry(output, scratch, observations=observations) is None
    calls.write_text("")
    mod._case_entry(output, scratch, observations=observations)
    calls.write_text('{"op":"get"}\n')
    (calls.parent.parent / "state.json").write_text('{"receipt_tag":"different-case"}')
    assert mod._case_entry(output, scratch, observations=observations) is None


@pytest.mark.parametrize("change", ["response", "fixture", "rollback"])
def test_changed_or_completed_request_never_reuses_a_zero_baseline(tmp_path, change):
    mod = recovery()
    output, scratch, calls, fixture = _observed_fixture(tmp_path)
    observations = {}
    assert mod._case_entry(output, scratch, observations=observations) is None
    if change == "response":
        (output / "artifacts/call_hard_timeout.run1.response.json").write_text("{}")
    elif change == "fixture":
        data = json.loads(fixture.read_text())
        data["extra"] = "changed"
        fixture.write_text(json.dumps(data))
    else:
        calls.write_text('{"op":"get"}\n')
        assert mod._case_entry(output, scratch, observations=observations)
        calls.write_text("")
        assert mod._case_entry(output, scratch, observations=observations) is None
    calls.write_text('{"op":"get"}\n')
    assert mod._case_entry(output, scratch, observations=observations) is None


def test_rebuilt_markdown_is_utf8_and_exact_original_bytes_are_archived():
    import hashlib

    plan = ROOT / "docs/plans/du8-matrix-2026-10-16"
    archive = json.loads((plan / "root-original-corrupt-markdown.json").read_text(encoding="utf8"))
    for name, record in archive.items():
        (plan / name).read_bytes().decode("utf8", errors="strict")
        original = bytes.fromhex(record["hex"])
        assert len(original) == record["original_bytes"]
        assert hashlib.sha256(original).hexdigest() == record["original_sha256"]
        with pytest.raises(UnicodeDecodeError):
            original.decode("utf8", errors="strict")
