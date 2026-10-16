"""W07-FF-PERF focused suite: measured phase timing + batch scheduling defects.

Tool-level only: controlled clocks and small fake processes, never a real
cross-repo run. The suite must prove, before the efficiency work is trusted:

  * phase timing is measured, complete and never guesses an unobserved phase;
  * seed_all converges the 10 warm CWP ensures into ONE bounded helper process
    while leaving one request/response/receipt/source-ref/count record each;
  * the mandatory final fresh source proof is never starved by case work and
    runs after every case within the unchanged 30s/case + 180s/batch budget;
  * run_process never leaks a child when an unexpected error escapes;
  * dependency records distinguish a real git HEAD from a nested gitless
    code-only snapshot (source commit comes from the dependency manifest).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "offline_contract_matrix"
sys.path.insert(0, str(TOOLS))

import runtime  # noqa: E402
from report import Dependency  # noqa: E402


class _Clock:
    """Monotonic stand-in shared by cli_main / runtime / measurement patches."""

    def __init__(self, start: float = 1000.0):
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ── phase timing contract ──────────────────────────────────────────────────


def test_phase_timer_measures_spans_and_never_exceeds_total():
    from measurement import PhaseTimer

    clock = _Clock()
    timer = PhaseTimer(clock=clock.monotonic)
    with timer.span("binding"):
        clock.advance(1.5)
    with timer.span("seed"):
        clock.advance(2.0)
    with timer.span("seed"):
        clock.advance(0.5)
    with timer.span("total"):
        clock.advance(0.25)
    snapshot = timer.snapshot()
    assert snapshot["binding"]["seconds"] == pytest.approx(1.5)
    assert snapshot["binding"]["status"] == "measured"
    assert snapshot["seed"]["seconds"] == pytest.approx(2.5)
    assert snapshot["seed"]["spans"] == 2
    assert snapshot["total"]["seconds"] == pytest.approx(0.25)


def test_unknown_phase_is_null_never_estimated():
    from measurement import PhaseTimer, REQUIRED_PHASES

    timer = PhaseTimer(clock=_Clock().monotonic)
    timer.mark_unknown("et_supervisor_worker", "nested child wall time unobserved")
    snapshot = timer.snapshot()
    phase = snapshot["et_supervisor_worker"]
    assert phase["status"] == "unknown"
    assert phase["seconds"] is None  # never a guessed number
    assert phase["reason"]
    for name in REQUIRED_PHASES:
        assert name in snapshot or name == "total"


def test_launch_log_aggregates_counts_spans_and_killed_unknown(tmp_path):
    from measurement import launch_report

    log = tmp_path / "launches.jsonl"
    rows = [
        {"event": "boot", "at": 100.0, "pid": 1, "argv": ["python", "et_transcript_proxy.py"]},
        {"event": "exit", "at": 101.5, "pid": 1, "argv": ["python", "et_transcript_proxy.py"]},
        {"event": "boot", "at": 100.2, "pid": 2, "argv": ["python", "fixture_provider_adapter.py"]},
        {"event": "exit", "at": 100.9, "pid": 2, "argv": ["python", "fixture_provider_adapter.py"]},
        {"event": "boot", "at": 102.0, "pid": 3, "argv": ["python", "et_transcript_proxy.py"]},
        # killed child: no exit row -> its span must stay unknown, not estimated
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    report = launch_report(log)
    assert report["launches"]["by_kind"]["et_proxy"] == 2
    assert report["launches"]["by_kind"]["fixture_adapter"] == 1
    et = report["child_spans"]["et_supervisor_worker"]
    assert et["status"] == "measured"
    assert et["seconds"] == pytest.approx(1.5)
    assert et["unknown_spans"] == 1
    fixture = report["child_spans"]["fixture"]
    assert fixture["seconds"] == pytest.approx(0.7)


# ── seed consolidation ─────────────────────────────────────────────────────


class _SeedProbe:
    """Records how seed_all drives the Context acquisition interface."""

    def __init__(self, tmp_path):
        from types import SimpleNamespace

        self.artifacts = tmp_path / "artifacts"
        self.artifacts.mkdir()
        self.env = SimpleNamespace(
            calls_file=lambda tag: tmp_path / "calls" / f"{tag}.jsonl",
            seed_original=lambda *a, **k: tmp_path / "seeded.bin",
        )
        self.warm_seed_calls = []
        self.batch_calls = []
        self.scans = 0
        self.seed_receipts = []

    def warm_seed(self, identity, kind, year, period):
        self.warm_seed_calls.append((identity.market, kind, year, period))
        return {"response_ref": "unused", "exit_code": 0}

    def warm_seed_batch(self, seeds):
        self.batch_calls.append(list(seeds))
        rows = []
        for i, (identity, kind, year, period) in enumerate(seeds):
            tag = f"seed_{identity.market.lower()}_{kind}_{year}_{period}"
            rows.append({
                "tag": tag,
                "request_argv": ["ensure"],
                "exit_code": 0,
                "response": {"status": "ok"},
                "response_ref": f"{tag}.response.json",
                "response_sha256": "0" * 64,
                "source_ref": {"document_id": f"doc-{i}"},
                "counts": {"adapter_invocations": 2, "fixture_requests": 0},
            })
        return rows

    def scan(self):
        self.scans += 1


def test_seed_all_converges_ten_warm_ensures_into_one_helper_process(tmp_path):
    import matrix_cases

    ctx = _SeedProbe(tmp_path)
    matrix_cases.seed_all(ctx)
    assert ctx.warm_seed_calls == [], "seed_all must not launch one CLI per warm ensure"
    assert len(ctx.batch_calls) == 1, "seed_all must issue exactly one bounded helper batch"
    (seeds,) = ctx.batch_calls
    assert len(seeds) == 10
    assert ctx.scans == 1
    receipts = json.loads((ctx.artifacts / "warm-seed-receipts.json").read_text(encoding="utf-8"))
    assert len(receipts) == 10
    for row in receipts:
        for key in ("tag", "request_argv", "response_ref", "response_sha256", "source_ref", "counts", "exit_code"):
            assert key in row, f"per-seed {key} record missing"
    assert len({row["tag"] for row in receipts}) == 10


def test_seed_batch_helper_records_each_request_response_receipt_and_count(tmp_path):
    from seed_batch import run_batch

    served = []
    state_file = tmp_path / "state.json"
    calls = tmp_path / "calls.jsonl"
    calls.write_text("", encoding="utf-8")

    def fake_service(argv):
        served.append(list(argv))
        with calls.open("a", encoding="utf-8") as fh:
            fh.write('{"op":"get"}\n')
        return 0, json.dumps({"status": "ok", "tag": argv[0]}), ""

    payload = {
        "artifacts": str(tmp_path / "artifacts"),
        "requests": [
            {
                "tag": f"seed_t{i}",
                "state_file": str(state_file),
                "state": {"scenario": "success", "calls_file": str(calls)},
                "argv": [f"req-{i}"],
            }
            for i in range(3)
        ],
    }
    summary = run_batch(payload, invoke=fake_service)
    assert summary["helper_processes"] == 1
    assert len(served) == 3
    assert len(summary["requests"]) == 3
    for index, row in enumerate(summary["requests"]):
        assert row["tag"] == f"seed_t{index}"
        assert row["response"]["status"] == "ok"
        assert (tmp_path / "artifacts" / row["response_ref"]).is_file()
        assert row["response_sha256"]
        assert row["counts"]["fixture_requests"] >= 1
        assert row["exit_code"] == 0


# ── final fresh proof cannot be starved ────────────────────────────────────


class _FakeSpec:
    declared_layer = "ff-only"
    scope = "fake scheduling probe"
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


def _slow_case_factory(clock, launches, advance=5.0):
    """Emulates run_ff enforcement: a case is killed at its own deadline."""

    def runner(ctx):
        from report import CaseResult

        launches.append(["CASE"])
        window = ctx.deadline.end - clock.monotonic()
        step = min(advance, window)
        clock.advance(step)
        if clock.monotonic() >= ctx.deadline.end:
            from runtime import DeadlineExceeded

            raise DeadlineExceeded("synthetic case hit its deadline")
        return CaseResult(id="fake_case", title="fake", declared_layer="ff-only", result="PASS")

    return runner


def _run_main_with_clock(tmp_path, clock, registry, launches, *, workers=1):
    """Drive cli_main.main with a controlled clock and recorded child launches."""
    import cli_main

    def fake_run_process(command, *, env, cwd, deadline, input=None):
        deadline.remaining()  # same pre-launch rejection the real runtime enforces
        launches.append([str(part) for part in command])
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"schema_version": "w07-fresh-source-proofs/1", "proofs": {}, "catalog_snapshot": []}
            ).encode("utf-8"),
            stderr=b"",
        )

    def fake_dependency(repository, root, modules, **kwargs):
        return Dependency(repository=repository, root=str(root), head="unknown", modules=[])

    clock_patches = [patch("cli_main.time", clock), patch("runtime.time", clock), patch("measurement.time", clock)] if clock is not None else []
    with patch.object(cli_main, "run_process", fake_run_process), patch.object(
        cli_main, "_verify_binding", return_value={"verified": True}
    ), patch.object(cli_main, "_dependency", fake_dependency), patch.object(
        cli_main, "_module_record", return_value={}
    ), patch.object(cli_main, "seed_all", lambda ctx: None), patch.object(
        cli_main, "_case_registry", return_value=registry
    ), patch("case_specs.get_spec", lambda cid: _FakeSpec(cid)):
        for p in clock_patches:
            p.start()
        try:
            rc = cli_main.main(
                [
                    "--cwp-project",
                    str(tmp_path / "cwp"),
                    "--et-project",
                    str(tmp_path / "et"),
                    "--owned-root",
                    str(tmp_path / "owned"),
                    "--out-root",
                    str(tmp_path / "out"),
                    "--workers",
                    str(workers),
                ]
            )
        finally:
            for p in clock_patches:
                p.stop()
    reports = sorted((tmp_path / "out").glob("*/report.json"))
    report = json.loads(reports[-1].read_text(encoding="utf-8")) if reports else None
    return rc, report, launches


def test_final_proof_runs_after_all_cases_and_keeps_its_reserve(tmp_path):
    clock = _Clock()
    launches = []
    registry = [(f"fake_case_{i}", _slow_case_factory(clock, launches)) for i in range(40)]
    rc, report, recorded = _run_main_with_clock(tmp_path, clock, registry, launches)
    proof_positions = [
        i for i, c in enumerate(launches) if any("source_proofs" in str(part) for part in c)
    ]
    case_positions = [i for i, c in enumerate(launches) if c and c[0] == "CASE"]
    assert proof_positions, (
        "final fresh source proof was starved: case work consumed the whole "
        "batch deadline and the mandatory proof never launched"
    )
    assert case_positions, "no case work recorded"
    assert max(case_positions) < min(proof_positions), (
        "fresh source proof must run after all case work"
    )
    assert report["scope"]["batch_elapsed_seconds"] <= 180


def test_report_contains_measured_phase_timing_and_launch_accounting(tmp_path):
    clock = _Clock()
    launches = []
    registry = [("fake_case_0", _slow_case_factory(clock, launches, advance=1.0))]
    _, report, _ = _run_main_with_clock(tmp_path, clock, registry, launches)
    timing = report["scope"].get("phase_timing")
    assert timing, "report lacks measured phase timing"
    for phase in ("binding", "seed", "ff_cli", "et_supervisor_worker", "fixture",
                  "fresh_source_proof", "cleanup", "total"):
        assert phase in timing, f"phase {phase} missing from phase timing"
        entry = timing[phase]
        assert entry["status"] in {"measured", "unknown"}
        if entry["status"] == "measured":
            assert isinstance(entry["seconds"], (int, float)) and entry["seconds"] >= 0
        else:
            assert entry["seconds"] is None and entry.get("reason")
    accounting = report["scope"].get("launch_accounting")
    assert accounting, "report lacks launch accounting"
    assert accounting["launches"]["parent_launch_total"] >= 1


def test_case_crash_still_records_cleanup_and_restores_scratch(tmp_path):
    clock = _Clock()
    launches = []

    def crashing(ctx):
        raise RuntimeError("synthetic case crash")

    registry = [("fake_case_0", crashing)]
    rc, report, _ = _run_main_with_clock(tmp_path, clock, registry, launches)
    assert rc != 0
    assert report["restore"]["restored"] is True
    assert report["scope"]["phase_timing"]["cleanup"]["status"] == "measured"
    assert report["scope"]["phase_timing"]["total"]["status"] == "measured"


# ── process/dependency truthfulness ────────────────────────────────────────


def test_run_process_reaps_child_when_communicate_raises_other_error(tmp_path):
    # communicate was matrix's former private implementation. Inject at the
    # shared transport's real lifetime boundary and verify actual cleanup.
    import os
    import threading
    transport = runtime.process_transport
    captured = []

    def broken_lifetime(proc, job, state, deadline):
        captured.append(proc)
        raise RuntimeError("synthetic communicate failure")

    with patch.object(transport, "_await_lifetime", broken_lifetime):
        with pytest.raises(RuntimeError, match="synthetic communicate failure"):
            runtime.run_process(
                [sys.executable, "-B", "-S", "-c", "import threading;threading.Event().wait()"],
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), cwd=tmp_path,
                deadline=runtime.Deadline(5),
            )
    assert len(captured) == 1
    assert captured[0].poll() is not None, "child process leaked after unexpected transport error"
    assert captured[0].stdout is not None and captured[0].stderr is not None
    assert all(
        pipe.closed
        for pipe in (captured[0].stdin, captured[0].stdout, captured[0].stderr)
        if pipe is not None
    )
    assert not [t for t in threading.enumerate() if t.name.startswith("ff-process")]



def test_expired_deadline_still_refuses_launch_after_reserve_change(tmp_path):
    with patch.object(runtime.subprocess, "Popen") as launch:
        with pytest.raises(runtime.DeadlineExceeded):
            runtime.run_process(["python"], env={}, cwd=tmp_path, deadline=runtime.Deadline(end=-1))
        launch.assert_not_called()


def test_nested_gitless_snapshot_reports_unknown_head_and_manifest_source_commit(tmp_path):
    import cli_main

    nested = tmp_path / "ff-worktree" / ".planning" / "pkg" / "input" / "runtime" / "et"
    nested.mkdir(parents=True)
    parent_top = tmp_path / "ff-worktree"

    def fake_run_process(command, *, env, cwd, deadline, input=None):
        if "--show-toplevel" in command:
            return SimpleNamespace(returncode=0, stdout=str(parent_top).encode("utf-8"), stderr=b"")
        return SimpleNamespace(returncode=0, stdout=b"2d380a054c658ce3b5f0763523e49a0ab34acf78\n", stderr=b"")

    with patch.object(cli_main, "run_process", fake_run_process):
        dep = cli_main._dependency(
            "et", nested, [], source_commit="d0ac42c60dcca992db78860b8469cfed3dd527e5"
        )
    data = dep.to_dict()
    assert data["head"] in {"unknown", None}, (
        "a nested gitless code-only snapshot must not inherit the parent worktree HEAD"
    )
    assert data["source_commit"] == "d0ac42c60dcca992db78860b8469cfed3dd527e5"
    assert data["source_commit"] != data["head"]
    assert data["head_origin"] == "unknown_nested_snapshot"


def test_git_toplevel_match_reports_real_head(tmp_path):
    import cli_main

    root = tmp_path / "repo"
    root.mkdir()

    def fake_run_process(command, *, env, cwd, deadline, input=None):
        if "--show-toplevel" in command:
            return SimpleNamespace(returncode=0, stdout=str(root).encode("utf-8"), stderr=b"")
        return SimpleNamespace(returncode=0, stdout=b"abc123\n", stderr=b"")

    with patch.object(cli_main, "run_process", fake_run_process):
        dep = cli_main._dependency("ff", root, [], source_commit=None)
    data = dep.to_dict()
    assert data["head"] == "abc123"
    assert data["head_origin"] == "git_toplevel_match"


def test_bytecode_cache_root_avoids_max_path_and_is_owned(tmp_path):
    """The multi-layer recompile common cause: mirrored cache paths must fit.

    ``PYTHONPYCACHEPREFIX`` mirrors full source paths under the prefix; when the
    prefix nests under the attempt scratch those mirror paths exceed Windows
    MAX_PATH (260) and Python silently stops caching the producer tree, which
    recompiles company_wiki/ET on every single child launch.
    """
    import importlib.util

    from runtime import OwnedAttempt

    owned = tmp_path / "w07-abcd1234"
    attempt = OwnedAttempt.create(owned, tmp_path / "out")
    try:
        assert attempt.cache == owned / "pc", "cache root must be the short sibling of the attempt dir"
        assert attempt.cache.parent == attempt.scratch.parent

        anchor = str(tmp_path.anchor)
        deep_source = anchor + "/".join(["producer"] * 3) + "/company_wiki/automation/narrative.py"

        def mirrored_len(prefix: Path, source: str) -> int:
            old = sys.pycache_prefix
            sys.pycache_prefix = str(prefix)
            try:
                return len(importlib.util.cache_from_source(source))
            finally:
                sys.pycache_prefix = old

        # Pad the source so the nested placement provably overflows while the
        # short owned root stays under the limit (length-invariant).
        pad = max(0, 260 - mirrored_len(attempt.cache, deep_source) + 4)
        padded = anchor + "p" * pad + "/company_wiki/automation/narrative.py"
        short_case = mirrored_len(attempt.cache, padded)
        nested_case = mirrored_len(attempt.scratch / "pycache", padded)
        assert short_case < 260, "short cache root must keep mirrored pyc paths under MAX_PATH"
        assert nested_case >= 260, "nested scratch cache placement is exactly the silent-drop defect"

        (attempt.cache / "marker.cpython-313.pyc").write_bytes(b"\x00")
        restore = attempt.cleanup()
        assert restore["bytecode_cache_torn_down"] is True
        assert restore["restored"] is True
        assert not attempt.cache.exists()
    finally:
        if attempt.scratch.exists():
            attempt.cleanup()


def test_preexisting_cache_dir_is_not_deleted_by_cleanup(tmp_path):
    from runtime import OwnedAttempt

    owned = tmp_path / "w07-11112222"
    owned.mkdir()
    cache = owned / "pc"
    cache.mkdir()
    (cache / "other.pyc").write_bytes(b"\x00")
    attempt = OwnedAttempt.create(owned, tmp_path / "out")
    assert attempt.cache_created is True
    assert attempt.cache != cache, "pre-existing cache must never be used for new writes"
    restore = attempt.cleanup()
    assert cache.exists() and (cache / "other.pyc").is_file(), "non-owned cache must be preserved"
    assert restore["restored"] is True


# ── budget/ownership invariants under the new scheduling ───────────────────


def test_case_deadline_never_extends_into_batch_or_proof_reserve(tmp_path):
    from run import Context, CASE_TIMEOUT, PROOF_RESERVE_SECONDS

    ctx = Context(
        ff_root=tmp_path / "ff",
        cwp_root=tmp_path / "cwp",
        et_root=tmp_path / "et",
        scratch=tmp_path / "scratch",
        out_root=tmp_path / "output",
    )
    clock = _Clock()
    with patch("runtime.time", clock):
        ctx.batch_deadline = runtime.Deadline(180)
        batch_end = ctx.batch_deadline.end
        ctx.begin_case()
        assert ctx.deadline.end <= batch_end - PROOF_RESERVE_SECONDS
        assert ctx.deadline.end <= clock.monotonic() + CASE_TIMEOUT
        clock.advance(200)
        with pytest.raises(runtime.DeadlineExceeded):
            ctx.begin_case()


def test_multiple_owned_contexts_keep_separate_state(tmp_path):
    from run import Context

    contexts = [
        Context(
            ff_root=tmp_path / "ff",
            cwp_root=tmp_path / "cwp",
            et_root=tmp_path / "et",
            scratch=tmp_path / f"scratch{i}",
            out_root=tmp_path / f"output{i}",
        )
        for i in range(2)
    ]
    first, second = contexts
    first.traces.setdefault("chainA_download_reuse", []).append({"fixture_requests": 1})
    assert second.traces == {}
    assert first.scratch != second.scratch
    assert first.env.wiki != second.env.wiki
    assert first.phases is not second.phases


def test_two_worker_groups_keep_independent_wikis_and_merge_proof_evidence(tmp_path):
    from report import CaseResult as _CR

    launches = []

    def instant_pass(cid):
        def runner(ctx):
            return _CR(id=cid, title="fake", declared_layer="ff-only", result="PASS")

        return runner

    registry = [(f"fake_case_{i}", instant_pass(f"fake_case_{i}")) for i in range(4)]
    rc, report, _ = _run_main_with_clock(tmp_path, None, registry, launches, workers=2)
    assert report["scope"]["workers"] == 2
    assert report["restore"]["restored"] is True
    outcomes = {c["id"]: c["result"] for c in report["cases"]}
    for i in range(4):
        assert outcomes[f"fake_case_{i}"] != "NOT_RUN", "every case must belong to a group"
    proof_launches = [c for c in launches if any("source_proofs" in str(part) for part in c)]
    assert len(proof_launches) == 2, "one final fresh proof per owned wiki, after joining"
    assert "catalog_snapshot" in report["source_proofs"]
    artifacts = sorted((tmp_path / "out").glob("*/artifacts"))
    assert artifacts, "retained evidence dir missing"
    names = {p.name for p in artifacts[0].iterdir()}
    assert "g1.fresh-source-proofs.json" in names and "g2.fresh-source-proofs.json" in names


def test_worker_group_runs_seeded_wiki_and_cases_in_own_context(tmp_path):
    from run import Context
    import cli_main

    seeded = []

    def fake_seed(ctx):
        seeded.append(ctx.env.wiki)

    def instant_pass(ctx):
        from report import CaseResult as _CR

        return _CR(id="fake", title="fake", declared_layer="ff-only", result="PASS")

    ctx = Context(
        ff_root=tmp_path / "ff",
        cwp_root=tmp_path / "cwp",
        et_root=tmp_path / "et",
        scratch=tmp_path / "scratch",
        out_root=tmp_path / "output",
        artifact_prefix="g1.",
    )
    with patch.object(cli_main, "seed_all", fake_seed), patch("case_specs.get_spec", lambda cid: _FakeSpec(cid)):
        done, stop = cli_main.run_case_group(ctx, [(0, ("fake_case", instant_pass))], ctx.batch_deadline)
    assert seeded == [ctx.env.wiki]
    assert stop is None and len(done) == 1
    assert done[0][1].result == "PASS"
