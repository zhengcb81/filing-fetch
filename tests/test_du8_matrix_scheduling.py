"""DU8-FF-MATRIX-COMPLETION — A-node RED: fair scheduling and deadline recovery.

Tool-level only: controlled clocks and small fake processes, never a real
cross-repo run, never network, never a supplier. The suite freezes the
*independent expectation* for the fixed 41-case batch before the scheduling
change is trusted:

  1. the two worker groups must be **cost balanced** (position round-robin is
     not a cost model: measured on the retained W07 full batch it produced
     g1=75.53s vs g2=59.80s, a 15.7s / 26% imbalance on the critical path);
  2. the assignment must be **independent of input order** (reversing the
     registry yields the same partition of the same cases);
  3. a whole download->reuse case chain must never straddle two groups;
  4. the scheduler must **never enlarge concurrency** (<= WORKERS, <= 2);
  5. once the shared absolute deadline is reached, **zero new launches** may
     happen; a case that already failed must not have its group start another
     case past the reserve;
  6. per-case and batch limits are unchanged (30s / 180s / 10s reserve), the
     deadline start is never moved and `remaining` is never renewed.

These tests are written against behavior, not implementation names: they read
the group assignment produced by the public scheduler seam.
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
    def __init__(self, start: float = 1000.0):
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeSpec:
    declared_layer = "ff-only"
    scope = "fake scheduling probe"
    runs = ()

    def __init__(self, cid, *, cost: float = 1.0, runs: int = 1):
        self.id = cid
        self.cost = cost
        self.runs = tuple(SimpleNamespace() for _ in range(runs))

    def expected(self):
        return {}

    def metadata_errors(self, case):
        return []

    def assertion_errors(self, case):
        return []

    def request_errors(self, index, request):
        return []


# ── the measured cost table from the retained real full batch ──────────────
# docs/handoffs/w07-ff-matrix-efficiency/evidence/final-41-report.json
# actual.elapsed_seconds, in the fixed registry order of case_specs().
REAL_COSTS = (
    10.6064, 1.9432, 2.1158, 1.8699, 2.2179, 1.9516, 1.9538, 2.2823, 1.7773,
    2.2093, 4.6718, 5.3261, 4.2892, 4.6051, 3.8190, 4.8945, 3.8662, 3.9547,
    3.8321, 2.3510, 2.2720, 2.2644, 2.2742, 1.5018, 3.7044, 3.2684, 0.1531,
    3.3492, 2.3101, 3.5014, 3.0711, 2.5425, 3.4579, 3.6499, 3.6912, 3.9348,
    8.2695, 2.0848, 2.3905, 2.3170, 4.7871,
)

# Independent hand anchor: the two-run / real-3layer chains are the expensive
# ones. This is a property of the fixed CaseSpec, not of a run.
TWO_RUN_IDS = frozenset({
    "chainA_download_reuse", "fin_cn_annual_fetch", "fin_cn_semi_fetch",
    "fin_cn_quarterly_fetch", "fin_hk_annual_fetch", "fin_hk_semi_fetch",
    "fin_hk_quarterly_fetch", "fin_us_annual_fetch", "fin_us_semi_fetch",
    "fin_us_quarterly_fetch", "request_after_failure_retry",
})


def _real_registry():
    from case_specs import case_specs

    return [(s.id, None) for s in case_specs()]


def _cost_model(ids):
    """Map case id -> the retained measured seconds (unknown ids: cheap)."""
    real = _real_registry()
    table = {cid: REAL_COSTS[i] for i, (cid, _) in enumerate(real) if i < len(REAL_COSTS)}
    return {cid: table.get(cid, 1.0) for cid in ids}


# ── the public scheduler seam ──────────────────────────────────────────────


def _assign(entries, *, workers=2, cost=None):
    """Call the scheduling owner the runner uses, with an explicit cost model."""
    import case_scheduling

    ids = [cid for _, (cid, _) in entries]
    model = cost if cost is not None else _cost_model(ids)
    return case_scheduling.assign_groups(entries, workers=workers, cost=cost or model)


def _group_loads(groups, cost):
    return [round(sum(cost[cid] for _, (cid, _) in group), 4) for group in groups]


# ── 1. cost balance ────────────────────────────────────────────────────────


def test_real_41_registry_is_cost_balanced_across_two_groups():
    entries = list(enumerate(_real_registry()))
    cost = _cost_model([cid for _, (cid, _) in entries])
    groups = _assign(entries, workers=2, cost=cost)
    assert len(groups) == 2, "the fixed batch still uses exactly two worker groups"
    loads = _group_loads(groups, cost)
    total = sum(loads)
    makespan = max(loads)
    # Lower bound is total/workers; the optimal partition on this cost table is
    # 67.67s per group. Require the scheduler to stay within 6% of the optimum,
    # which the old position round-robin (75.53/59.80) fails by a wide margin.
    assert makespan <= total / 2 * 1.06, (
        f"group loads {loads} are imbalanced: critical path {makespan:.2f}s vs "
        f"optimal {total / 2:.2f}s (old round-robin measured 75.53/59.80)"
    )
    assert abs(loads[0] - loads[1]) <= total * 0.06, (
        f"unbalanced critical path: {loads}"
    )


def test_position_round_robin_would_fail_the_same_balance_bar():
    """Negative control: the old assignment is provably not cost balanced."""
    entries = list(enumerate(_real_registry()))
    cost = _cost_model([cid for _, (cid, _) in entries])
    legacy = [entries[i::2] for i in range(2)]
    loads = _group_loads(legacy, cost)
    total = sum(loads)
    assert max(loads) > total / 2 * 1.06, (
        "the retained cost table must show the old round-robin as imbalanced; "
        f"got {loads}"
    )
    # And it reproduces the measured real split (75.53 / 59.80).
    assert loads[0] == pytest.approx(75.5306, abs=0.01)
    assert loads[1] == pytest.approx(59.8019, abs=0.01)


# ── 2. order independence ──────────────────────────────────────────────────


def test_assignment_is_independent_of_input_order():
    entries = list(enumerate(_real_registry()))
    ids = [cid for _, (cid, _) in entries]
    cost = _cost_model(ids)
    forward = _assign(entries, workers=2, cost=cost)
    reversed_entries = list(reversed(entries))
    backward = _assign(reversed_entries, workers=2, cost=cost)

    def sets(groups):
        return sorted(sorted(cid for _, (cid, _) in g) for g in groups)

    assert sets(forward) == sets(backward), (
        "the same case set must partition identically regardless of input order"
    )


def test_every_case_is_assigned_exactly_once():
    entries = list(enumerate(_real_registry()))
    groups = _assign(entries, workers=2)
    flat = [cid for g in groups for _, (cid, _) in g]
    assert sorted(flat) == sorted(cid for _, (cid, _) in entries)
    assert len(flat) == len(set(flat))


# ── 3. chain integrity ─────────────────────────────────────────────────────


def test_two_run_chains_are_never_split_across_groups():
    entries = list(enumerate(_real_registry()))
    groups = _assign(entries, workers=2)
    owner = {}
    for index, group in enumerate(groups):
        for _, (cid, _) in group:
            assert cid not in owner, f"{cid} assigned to two groups"
            owner[cid] = index
    for cid in TWO_RUN_IDS:
        assert cid in owner, f"two-run chain {cid} lost from the schedule"


def test_chainA_stays_whole_and_is_placed_by_cost_not_by_position():
    """chainA is the single most expensive case and must not head group 1 by luck.

    Independent expectation: the scheduler must *compensate* for the heaviest
    case rather than stack it. The right invariant is therefore near-equal
    load, not a strict ordering: at the optimum the two groups differ by
    ~0.003s, so the heavy case's group may legitimately be a hair heavier.
    The old position round-robin fails this by putting chainA alone in a group
    that then also collects the other heavy chains (75.53 vs 59.80).
    """
    entries = list(enumerate(_real_registry()))
    cost = _cost_model([cid for _, (cid, _) in entries])
    groups = _assign(entries, workers=2, cost=cost)
    placement = {cid: i for i, g in enumerate(groups) for _, (cid, _) in g}
    assert placement["chainA_download_reuse"] in (0, 1)
    loads = _group_loads(groups, cost)
    total = sum(loads)
    heavy_group = placement["chainA_download_reuse"]
    other = 1 - heavy_group
    # The heavy-case group may not be materially heavier than the optimum.
    assert loads[heavy_group] - total / 2 <= total * 0.01, (
        f"the group owning the heaviest case is {loads[heavy_group] - total / 2:.3f}s "
        f"above the perfect-balance bound; loads={loads}"
    )
    assert loads[heavy_group] <= loads[other] + total * 0.01, (
        "the group receiving the heaviest case must not also carry a materially "
        f"larger load: {loads}"
    )


# ── 4. concurrency never grows ─────────────────────────────────────────────


def test_scheduler_never_invents_more_groups_than_workers():
    import cli_main

    entries = list(enumerate(_real_registry()))
    for workers in (1, 2):
        groups = _assign(entries, workers=workers)
        assert len(groups) == workers
    assert cli_main.WORKERS == 2, "the measured concurrency ceiling stays at two"


def test_workers_beyond_ceiling_are_refused_by_the_cli():
    import cli_main

    with pytest.raises(SystemExit):
        cli_main.main([
            "--cwp-project", "x", "--et-project", "y",
            "--owned-root", "z", "--out-root", "w", "--workers", "3",
        ])


# ── 5. deadline recovery: zero new launches past the reserve ───────────────


def _run_main(tmp_path, registry, launches, *, clock=None, workers=2, specs=None):
    import cli_main

    specs = specs or {}

    def fake_run_process(command, *, env, cwd, deadline, input=None):
        deadline.remaining()
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

    patches = [
        patch.object(cli_main, "run_process", fake_run_process),
        patch.object(cli_main, "_verify_binding", return_value={"verified": True}),
        patch.object(cli_main, "_dependency", fake_dependency),
        patch.object(cli_main, "_module_record", return_value={}),
        patch.object(cli_main, "seed_all", lambda ctx: None),
        patch.object(cli_main, "_case_registry", return_value=registry),
        patch("case_specs.get_spec", lambda cid: specs.get(cid) or _FakeSpec(cid)),
    ]
    if clock is not None:
        patches += [patch("cli_main.time", clock), patch("runtime.time", clock),
                    patch("measurement.time", clock)]
    for p in patches:
        p.start()
    try:
        rc = cli_main.main([
            "--cwp-project", str(tmp_path / "cwp"),
            "--et-project", str(tmp_path / "et"),
            "--owned-root", str(tmp_path / "owned"),
            "--out-root", str(tmp_path / "out"),
            "--workers", str(workers),
        ])
    finally:
        for p in patches:
            p.stop()
    reports = sorted((tmp_path / "out").glob("*/report.json"))
    report = json.loads(reports[-1].read_text(encoding="utf-8")) if reports else None
    return rc, report, launches


@pytest.mark.parametrize("workers", [1, 2])
def test_no_case_launch_happens_after_the_proof_reserve_is_reached(tmp_path, workers):
    """A group that overruns must stop starting cases; the proof keeps its tail."""
    from run import BATCH_DEADLINE, PROOF_RESERVE_SECONDS

    clock = _Clock()
    launches = []

    def runner_factory(cid):
        def runner(ctx):
            from report import CaseResult

            launches.append(["CASE", cid])
            clock.advance(25.0)
            return CaseResult(id=cid, title=cid, declared_layer="ff-only", result="PASS")

        return runner

    registry = [(f"fake_case_{i}", runner_factory(f"fake_case_{i}")) for i in range(12)]
    specs = {cid: _FakeSpec(cid) for cid, _ in registry}
    rc, report, _ = _run_main(tmp_path, registry, launches, clock=clock, workers=workers, specs=specs)

    case_launches = [(i, c[1]) for i, c in enumerate(launches) if c and c[0] == "CASE"]
    assert case_launches, "no case work ran"
    assert len(case_launches) < len(registry), "the batch was expected to run out of budget"

    # Every launch must have started strictly before the reserve boundary.
    reserve_start = BATCH_DEADLINE - PROOF_RESERVE_SECONDS
    assert len(case_launches) * 25.0 <= reserve_start + 25.0, (
        "a case started after the proof reserve: " f"{len(case_launches)} cases x 25s"
    )
    # And the mandatory proof still launched.
    proof_positions = [i for i, c in enumerate(launches)
                       if any("source_proofs" in str(p) for p in c)]
    assert proof_positions, "the final fresh source proof was starved"
    assert max(i for i, _ in case_launches) < min(proof_positions)
    assert report["scope"]["stop_reason"], "a truncated batch must record why"
    assert report["scope"]["stop_reason"] != ""


def test_not_run_cases_are_named_and_keep_their_real_denominator(tmp_path):
    clock = _Clock()
    launches = []

    def runner_factory(cid):
        def runner(ctx):
            from report import CaseResult

            launches.append(["CASE", cid])
            clock.advance(40.0)
            return CaseResult(id=cid, title=cid, declared_layer="ff-only", result="PASS")

        return runner

    registry = [(f"fake_case_{i}", runner_factory(f"fake_case_{i}")) for i in range(10)]
    specs = {cid: _FakeSpec(cid) for cid, _ in registry}
    _rc, report, _ = _run_main(tmp_path, registry, launches, clock=clock, workers=1, specs=specs)
    ids = [c["id"] for c in report["cases"]]
    assert sorted(ids) == sorted(cid for cid, _ in registry), (
        "the denominator must stay the full fixed registry; NOT_RUN cases are named"
    )
    assert any(c["result"] == "NOT_RUN" for c in report["cases"])
    for case in report["cases"]:
        if case["result"] == "NOT_RUN":
            assert case["diagnostics"], "a NOT_RUN case must carry a real reason"


# ── 6. budgets unchanged ───────────────────────────────────────────────────


def test_fixed_limits_are_untouched_by_the_scheduling_owner():
    import run
    import cli_main

    assert run.CASE_TIMEOUT == 30
    assert run.BATCH_DEADLINE == 180
    assert run.PROOF_RESERVE_SECONDS == 10.0
    assert cli_main.WORKERS == 2


def test_case_window_still_never_extends_into_the_reserve(tmp_path):
    from run import Context, CASE_TIMEOUT, PROOF_RESERVE_SECONDS

    ctx = Context(
        ff_root=tmp_path / "ff", cwp_root=tmp_path / "cwp", et_root=tmp_path / "et",
        scratch=tmp_path / "scratch", out_root=tmp_path / "output",
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


def test_scheduling_owner_is_pure_and_reads_no_clock_or_process():
    """A pure planner: no subprocess, no time, no filesystem side effect."""
    source = (TOOLS / "case_scheduling.py").read_text(encoding="utf-8")
    for forbidden in ("subprocess", "time.monotonic", "os.environ", "socket", "threading"):
        assert forbidden not in source, f"the scheduler must stay a pure planner: {forbidden}"
