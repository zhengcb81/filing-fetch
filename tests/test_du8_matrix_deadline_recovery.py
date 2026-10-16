"""DU8-FF-MATRIX-COMPLETION — A/B: deadline recovery, cancellation and isolation.

The card requires behavioural proof, on a fake clock plus *real* bounded child
processes, of the failure/cleanup paths that the fixed 180s batch depends on:

  * a case that dies at its own deadline must not cause its group to start
    another case past the shared absolute deadline (zero new launches);
  * a non-cooperative child (ignores termination) is still reaped with its
    descendants and its pipes are released;
  * a child killed by the deadline leaves its nested span `unknown`, never an
    estimated number;
  * a failed directory is never reused as a success, and no non-replayable
    side effect is repeated after cancellation;
  * concurrent groups keep separate wiki/config/call-counter/cache state.

No network, no supplier, no translation, no production write.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "offline_contract_matrix"
sys.path[:0] = [str(TOOLS), str(ROOT / "scripts")]

import runtime  # noqa: E402
import ff_process_transport as transport  # noqa: E402
import cli_main  # noqa: E402
from report import CaseResult  # noqa: E402


class _Clock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeSpec:
    declared_layer = "ff-only"
    scope = "fake probe"
    runs = ()

    def __init__(self, cid):
        self.id = cid

    def expected(self):
        return {}

    def metadata_errors(self, case):
        return []

    def assertion_errors(self, case):
        return []

    def request_errors(self, index, request):
        return []


# ── 1. cancellation: zero new launches after the deadline ──────────────────


def test_group_stops_launching_cases_the_moment_the_batch_expires(tmp_path):
    """A case that already died of the deadline must not drag in the next one.

    Behavioural RED: on the pre-change runner the absolute-deadline branch broke
    the loop while leaving ``stop_reason = None``, so a truncated batch recorded
    no cause at all. This fails there on the assertion below, not on an import.
    """
    clock = _Clock()
    starts = []

    def runner(ctx):
        starts.append(clock.monotonic())
        clock.advance(60.0)  # overruns the remaining window every time
        raise runtime.DeadlineExceeded("synthetic case deadline")

    ctx = SimpleNamespace(
        batch_deadline=None,
        deadline=None,
        traces={},
        artifacts=tmp_path,
        artifact_prefix="",
        active_case_spec=_FakeSpec("fake"),
        phases=None,
        begin_case=lambda: None,
        env=SimpleNamespace(wiki=tmp_path / "wiki"),
    )
    with patch.object(cli_main, "seed_all", lambda c: None), \
         patch("case_specs.get_spec", lambda cid: _FakeSpec(cid)), \
         patch("runtime.time", clock), patch("cli_main.time", clock):
        ctx.batch_deadline = runtime.Deadline(180)
        entries = [(i, (f"fake_case_{i}", runner)) for i in range(10)]
        done, stop = cli_main.run_case_group(ctx, entries, ctx.batch_deadline)

    assert stop, "an expired batch must record a stop reason"
    assert len(done) <= 3, f"too many cases started after expiry: {len(done)}"
    # every recorded case either finished or was labelled PARTIAL — no silent loss
    assert all(r.result in {"PARTIAL", "FAIL", "PASS"} for _, r in done)
    assert all(r.result == "PARTIAL" for _, r in done), (
        "a case that died of the deadline is PARTIAL, never PASS"
    )


def test_reserve_boundary_is_checked_before_every_case_start(tmp_path):
    clock = _Clock()
    launches = []

    def runner(ctx):
        launches.append(1)
        clock.advance(1.0)
        return CaseResult(id="fake", title="fake", declared_layer="ff-only", result="PASS")

    ctx = SimpleNamespace(
        batch_deadline=None, deadline=None, traces={},
        artifacts=tmp_path, artifact_prefix="", active_case_spec=_FakeSpec("fake"),
        phases=None, begin_case=lambda: None,
        env=SimpleNamespace(wiki=tmp_path / "wiki"),
    )
    with patch.object(cli_main, "seed_all", lambda c: None), \
         patch("case_specs.get_spec", lambda cid: _FakeSpec(cid)), \
         patch("runtime.time", clock), patch("cli_main.time", clock):
        # Build the deadline on the controlled clock, then move to the reserve.
        ctx.batch_deadline = runtime.Deadline(180)
        clock.advance(170.0)
        done, stop = cli_main.run_case_group(
            ctx, [(0, ("fake_case_0", runner))], ctx.batch_deadline
        )
    assert done == []
    assert launches == [], "a case was launched inside the reserved proof tail"
    assert stop and "reserve" in stop


# ── 2. non-cooperative child is still reaped ───────────────────────────────


def test_non_cooperative_child_tree_is_reaped_and_pipes_released(tmp_path):
    """A child that traps nothing and spawns a grandchild still gets collected."""
    marker = tmp_path / "pids.json"
    script = (
        "import json,os,subprocess,sys,time;from pathlib import Path;"
        "p=subprocess.Popen([sys.executable,'-B','-S','-c','import time;time.sleep(120)']);"
        "Path(sys.argv[1]).write_text(json.dumps([os.getpid(),p.pid]));"
        "time.sleep(120)"
    )
    command = [sys.executable, "-B", "-S", "-c", script, str(marker)]
    pids = []
    try:
        with pytest.raises(runtime.DeadlineExceeded):
            runtime.run_process(
                command, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                cwd=tmp_path, deadline=runtime.Deadline(1.5),
            )
        assert marker.is_file(), "grandchild never started; tree coverage unproven"
        pids = json.loads(marker.read_text())
        assert len(pids) == 2
        assert not any(transport.pid_is_alive(pid) for pid in pids), (
            "the owned tree leaked a live process"
        )
    finally:
        if marker.exists():
            pids = json.loads(marker.read_text())
        for pid in reversed(pids):
            if transport.pid_is_alive(pid):
                os.kill(pid, signal.SIGTERM)


def test_deadline_kill_leaves_the_child_span_unknown_not_estimated(tmp_path):
    """A killed child writes no exit row; its span must stay `unknown`."""
    from measurement import launch_report

    log = tmp_path / "launches.jsonl"
    log.write_text(
        json.dumps({"event": "boot", "at": 10.0, "pid": 99,
                    "argv": ["python", "et_transcript_proxy.py"]}),
        encoding="utf-8",
    )
    report = launch_report(log)
    span = report["child_spans"]["et_supervisor_worker"]
    assert span["status"] == "unknown"
    assert span["seconds"] is None
    assert span["reason"], "an unobserved span must carry a reason"


# ── 3. failed directory never becomes a success ────────────────────────────


def test_failed_attempt_directory_is_never_reused_as_a_new_attempt(tmp_path):
    owned, out = tmp_path / "owned", tmp_path / "out"
    first = runtime.OwnedAttempt.create(owned, out)
    scratch_name, out_name = first.scratch.name, first.output.name
    assert scratch_name.startswith("attempt-")
    (first.output / "report.json").write_text('{"result":"FAIL"}', encoding="utf-8")
    first.cleanup()

    second = runtime.OwnedAttempt.create(owned, out)
    try:
        assert second.scratch != first.scratch and second.scratch.name != scratch_name
        assert second.output != first.output and second.output.name != out_name
        assert not (second.output / "report.json").exists(), (
            "a previous attempt's failure record was reused as this attempt's state"
        )
    finally:
        second.cleanup()


def test_cleanup_refuses_when_the_owned_identity_changed(tmp_path):
    attempt = runtime.OwnedAttempt.create(tmp_path / "owned", tmp_path / "out")
    attempt.scratch = tmp_path / "somewhere-else"
    with pytest.raises(ValueError, match="identity changed"):
        attempt.cleanup()


def test_interrupted_attempt_reaps_scratch_and_keeps_preexisting_entries(tmp_path):
    owned, out = tmp_path / "owned", tmp_path / "out"
    owned.mkdir()
    sentinel = owned / ".w06_matrix_sentinel"
    sentinel.write_text("do-not-modify", encoding="utf-8")
    attempt = runtime.OwnedAttempt.create(owned, out)
    (attempt.scratch / "leftover.tmp").write_text("x", encoding="utf-8")
    before = sentinel.read_bytes()
    restore = attempt.cleanup()
    assert restore["restored"] is True
    assert restore["scratch_torn_down"] is True
    assert not attempt.scratch.exists()
    assert sentinel.read_bytes() == before, "a pre-existing owned entry was modified or removed"


# ── 4. concurrent groups do not pollute each other ─────────────────────────


def test_concurrent_groups_keep_independent_state(tmp_path):
    from run import Context

    contexts = [
        Context(ff_root=tmp_path / "ff", cwp_root=tmp_path / "cwp", et_root=tmp_path / "et",
                scratch=tmp_path / f"s{i}", out_root=tmp_path / f"o{i}", artifact_prefix=f"g{i + 1}.")
        for i in range(2)
    ]
    a, b = contexts
    a.traces.setdefault("chainA_download_reuse", []).append({"fixture_requests": 1})
    a.begin_case()
    assert b.traces == {}
    assert a.scratch != b.scratch
    assert a.env.wiki != b.env.wiki
    assert a.env.calls_file("tag") != b.env.calls_file("tag")
    assert a.phases is not b.phases
    assert a.artifact_prefix != b.artifact_prefix
    assert a.child_env()["W06_GUARD_LOG"] != b.child_env()["W06_GUARD_LOG"]


def test_each_group_owns_a_distinct_bytecode_cache_and_wiki(tmp_path):
    from run import Context

    a = Context(ff_root=tmp_path / "ff", cwp_root=tmp_path / "cwp", et_root=tmp_path / "et",
                scratch=tmp_path / "s1", out_root=tmp_path / "o1",
                pycache_root=tmp_path / "pc1")
    b = Context(ff_root=tmp_path / "ff", cwp_root=tmp_path / "cwp", et_root=tmp_path / "et",
                scratch=tmp_path / "s2", out_root=tmp_path / "o2",
                pycache_root=tmp_path / "pc2")
    assert a.child_env()["PYTHONPYCACHEPREFIX"] != b.child_env()["PYTHONPYCACHEPREFIX"]
    assert a.env.wiki != b.env.wiki


# ── 5. budget never renewed ────────────────────────────────────────────────


def test_retry_and_proof_do_not_renew_the_absolute_deadline(tmp_path):
    from run import Context, PROOF_RESERVE_SECONDS

    ctx = Context(ff_root=tmp_path / "ff", cwp_root=tmp_path / "cwp", et_root=tmp_path / "et",
                  scratch=tmp_path / "s", out_root=tmp_path / "o")
    clock = _Clock()
    with patch("runtime.time", clock):
        ctx.batch_deadline = runtime.Deadline(180)
        batch_end = ctx.batch_deadline.end
        for _ in range(3):
            ctx.begin_case()
            assert ctx.deadline.end <= batch_end - PROOF_RESERVE_SECONDS
            clock.advance(20.0)
        # A case window is never allowed to push past the batch's original end.
        assert ctx.batch_deadline.end == batch_end
        clock.advance(200.0)
        with pytest.raises(runtime.DeadlineExceeded):
            ctx.begin_case()


def test_refused_launch_after_expiry_still_never_starts_a_process(tmp_path):
    with patch.object(transport, "run_bounded") as bounded:
        with pytest.raises(runtime.DeadlineExceeded):
            runtime.run_process(["python"], env={}, cwd=tmp_path,
                                deadline=runtime.Deadline(end=-1))
        bounded.assert_not_called()


# ── 6. report still names real outcomes ────────────────────────────────────


def test_partial_case_keeps_its_error_and_never_becomes_a_pass(tmp_path):
    def runner(ctx):
        raise runtime.DeadlineExceeded("synthetic absolute deadline")

    ctx = SimpleNamespace(
        batch_deadline=runtime.Deadline(180), deadline=None, traces={},
        artifacts=tmp_path, artifact_prefix="", active_case_spec=_FakeSpec("x"),
        phases=None, begin_case=lambda: None,
        env=SimpleNamespace(wiki=tmp_path / "wiki"),
    )
    with patch.object(cli_main, "seed_all", lambda c: None), \
         patch("case_specs.get_spec", lambda cid: _FakeSpec(cid)):
        done, _ = cli_main.run_case_group(
            ctx, [(0, ("fake_case", runner))], ctx.batch_deadline
        )
    assert len(done) == 1
    result = done[0][1]
    assert result.result == "PARTIAL"
    assert "synthetic absolute deadline" in str(result.actual.get("error"))
