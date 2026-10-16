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
    """Call the scheduling owner the runner uses.

    ``cost=None`` exercises the SHIPPED path (the frozen static model), which is
    what the runner actually does. Pass ``cost`` explicitly to score a partition
    on the retained measured table.
    """
    import case_scheduling

    return case_scheduling.assign_groups(entries, workers=workers, cost=cost)


def _group_loads(groups, cost):
    return [round(sum(cost[cid] for _, (cid, _) in group), 4) for group in groups]


# ── 1. cost balance (scored on the FULL 41/41 retained table) ──────────────
#
# Honesty note: every assertion below is evaluated on the retained W07 table,
# which covers all 41 cases. An earlier version of this suite scored partitions
# on tables covering only the cases that actually RAN, pricing the NOT_RUN
# starvation tail at a constant fallback - which inflated the apparent gain from
# ~2% to ~20%. These tests deliberately use the full-coverage table so that
# cannot recur.


def test_measured_table_covers_the_full_41_case_registry():
    """Guard against a partial table silently pricing the tail at a constant."""
    entries = list(enumerate(_real_registry()))
    cost = _cost_model([cid for _, (cid, _) in entries])
    assert len(cost) == 41, "the scoring table must cover the full fixed denominator"
    assert len(REAL_COSTS) == 41
    assert set(cost) == {cid for _, (cid, _) in entries}


def test_balanced_partition_beats_position_round_robin_on_real_full_coverage():
    """The shipped static model must be a real, measurable improvement.

    Measured on the retained 41/41 table: legacy 75.5306s vs shipped 74.0080s,
    i.e. a 1.52s / 2.02% critical-path reduction against a 67.6663s optimum.
    The bar is deliberately modest because that is the honest size of the gain.
    """
    entries = list(enumerate(_real_registry()))
    cost = _cost_model([cid for _, (cid, _) in entries])
    legacy = [entries[i::2] for i in range(2)]
    balanced = _assign(entries, workers=2)          # shipped static model
    legacy_makespan = max(_group_loads(legacy, cost))
    new_makespan = max(_group_loads(balanced, cost))
    assert new_makespan < legacy_makespan, (
        f"the shipped partition {new_makespan:.4f}s must beat position "
        f"round-robin {legacy_makespan:.4f}s on the real full-coverage table"
    )
    assert legacy_makespan - new_makespan >= 1.0, (
        "the improvement must be at least a second to be worth shipping; got "
        f"{legacy_makespan - new_makespan:.4f}s"
    )


def test_position_round_robin_is_provably_imbalanced_on_real_costs():
    """Negative control, scored on the full table (not a local reimplementation).

    This is the defect A-node names: the old assignment's two groups differ by
    15.73s (26%) on measured data.
    """
    entries = list(enumerate(_real_registry()))
    cost = _cost_model([cid for _, (cid, _) in entries])
    legacy = [entries[i::2] for i in range(2)]
    loads = _group_loads(legacy, cost)
    total = sum(loads)
    assert loads[0] == pytest.approx(75.5306, abs=0.01)
    assert loads[1] == pytest.approx(59.8019, abs=0.01)
    assert max(loads) - min(loads) > total * 0.10, (
        f"position round-robin must show a >10% spread on real costs; got {loads}"
    )


def test_static_model_is_honestly_labelled_and_not_near_optimal():
    """The static model is a coarse proxy; the report must say so.

    Pinned as a fact so nobody later mistakes the 74.008s result for near
    optimality: the perfect-balance bound is 67.6663s and the shipped static
    model is several seconds above it.
    """
    from case_scheduling import balance_report, static_cost

    entries = list(enumerate(_real_registry()))
    frozen = static_cost(entries)
    groups = _assign(entries, workers=2)
    report = balance_report(groups, frozen, cost_source="static")
    assert report["cost_source"] == "static"
    assert "proxy" in report["cost_model"]
    cost = _cost_model([cid for _, (cid, _) in entries])
    real_makespan = max(_group_loads(groups, cost))
    bound = sum(cost.values()) / 2
    assert real_makespan > bound + 5.0, (
        "the static model must not be advertised as near-optimal: "
        f"makespan {real_makespan:.3f}s vs bound {bound:.3f}s"
    )
    assert real_makespan == pytest.approx(74.008, abs=0.01), (
        "the documented static-model result on the retained table must stay honest"
    )


def test_measured_costs_via_cost_of_hook_reach_near_optimal():
    """The supported hook for real measurements must actually work end-to-end."""
    from case_scheduling import static_cost

    entries = list(enumerate(_real_registry()))
    cost = _cost_model([cid for _, (cid, _) in entries])
    measured = static_cost(entries, cost_of=cost.get)
    assert measured == cost, "cost_of must take precedence over the static estimate"
    groups = _assign(entries, workers=2, cost=measured)
    makespan = max(_group_loads(groups, cost))
    bound = sum(cost.values()) / 2
    assert makespan <= bound * 1.01, (
        f"measured-cost scheduling must be near optimal; got {makespan:.4f}s "
        f"vs bound {bound:.4f}s"
    )



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


# ── 4b. the runner really uses the balanced assignment ─────────────────────
#
# This is the behavioural RED that the first version of this suite lacked: it
# drives the real cli_main.main and proves the grouping the RUNNER actually
# executes is cost-balanced, instead of re-testing a local reimplementation.
# On the pre-change runner cli_main made NO call to the scheduling owner at all,
# so this fails with "cli_main never consulted the scheduler".


def _spy_on_assignment(monkeypatch, recorder):
    """Record the runner's grouping decision WITHOUT importing the new module.

    Patching ``cli_main``'s own namespace keeps this a genuine behavioural RED:
    on the pre-change runner there is no such attribute, so the test fails on
    the missing DELEGATION (a real defect) rather than on a missing import.
    """
    import cli_main

    real = getattr(cli_main, "case_scheduling", None)

    class _Spy:
        def __init__(self, inner):
            self._inner = inner

        def assign_groups(self, entries, **kwargs):
            if self._inner is None:
                recorder.append({"groups": None, "kwargs": kwargs})
                raise AssertionError(
                    "cli_main never consulted a scheduling owner: the runner "
                    "partitions cases by position, not by cost")
            groups = self._inner.assign_groups(entries, **kwargs)
            recorder.append({"groups": groups, "kwargs": kwargs})
            return groups

        def balance_report(self, *a, **kw):
            return self._inner.balance_report(*a, **kw) if self._inner else {}

        def __getattr__(self, name):
            if self._inner is None:
                raise AttributeError(name)
            return getattr(self._inner, name)

    monkeypatch.setattr(cli_main, "case_scheduling", _Spy(real), raising=False)
    return real


def test_runner_delegates_grouping_to_the_cost_balanced_scheduler(tmp_path, monkeypatch):
    recorded = []
    _spy_on_assignment(monkeypatch, recorded)
    registry = _real_registry()
    _rc, _report, _ = _run_main(tmp_path, registry, [], clock=_Clock(), workers=2)

    assert recorded, (
        "cli_main never consulted the scheduling owner: the runner still "
        "partitions by position instead of by cost"
    )
    assert len(recorded) == 1, "exactly one scheduling decision per batch"
    call = recorded[0]
    assert call["kwargs"].get("workers") == 2
    groups = call["groups"]
    assert len(groups) == 2, "the runner must still use exactly two groups"

    # The grouping the runner actually executed must be the balanced one.
    cost = _cost_model([cid for cid, _ in registry])
    loads = _group_loads(groups, cost)
    legacy = [list(enumerate(registry))[i::2] for i in range(2)]
    legacy_makespan = max(_group_loads(legacy, cost))
    assert max(loads) < legacy_makespan, (
        f"the runner's real grouping {loads} did not beat position round-robin "
        f"({legacy_makespan:.4f}s)"
    )


def test_runner_reports_the_scheduling_decision_it_made(tmp_path, monkeypatch):
    recorded = []
    _spy_on_assignment(monkeypatch, recorded)
    registry = _real_registry()
    _rc, report, _ = _run_main(tmp_path, registry, [], clock=_Clock(), workers=2)
    scheduling = (report.get("scope") or {}).get("case_scheduling")
    assert scheduling, "the report must record the scheduling decision"
    for key in ("group_loads_seconds", "group_case_counts", "cost_source",
                "predicted_makespan_seconds", "perfect_balance_lower_bound_seconds"):
        assert key in scheduling, f"report scheduling record lacks {key}"
    assert scheduling["cost_source"] in {"static", "measured"}
    assert sorted(scheduling["group_case_counts"]) == sorted(len(g) for g in recorded[0]["groups"])


def test_runner_partition_covers_the_fixed_registry_exactly_once(tmp_path, monkeypatch):
    recorded = []
    _spy_on_assignment(monkeypatch, recorded)
    registry = _real_registry()
    _rc, _report, _ = _run_main(tmp_path, registry, [], clock=_Clock(), workers=2)
    flat = [cid for group in recorded[0]["groups"] for _pos, (cid, _r) in group]
    assert sorted(flat) == sorted(cid for cid, _ in registry)
    assert len(flat) == len(set(flat)), "a case was scheduled into two groups"



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


def test_cost_model_claims_are_backed_by_committed_receipts():
    """No decisive cost-model claim may rest on prose alone.

    An earlier revision asserted a bootstrap result that no committed script
    reproduced, and that independent review inverted. Every claim about which
    cost model generalizes better must therefore point at a committed,
    re-runnable receipt.
    """
    plan = TOOLS.parents[1] / "docs" / "plans" / "du8-matrix-2026-10-16"
    fixtures = plan / "fixtures"
    receipts = plan / "receipts"
    assert (fixtures / "cost_model_bootstrap.py").is_file(), (
        "the bootstrap claim needs a committed, re-runnable script")
    assert (fixtures / "cost_model_bootstrap_sensitivity.py").is_file(), (
        "the scheme-dependence claim needs a committed, re-runnable script")
    for name in ("cost-model-bootstrap.json", "cost-model-bootstrap-sensitivity.json"):
        path = receipts / name
        assert path.is_file(), f"missing reproducible receipt: {name}"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("trials"), f"{name} must record its trial count"
    sensitivity = json.loads((receipts / "cost-model-bootstrap-sensitivity.json").read_text(encoding="utf-8"))
    assert len(sensitivity["schemes"]) >= 3, "the sensitivity receipt must show several schemes"
    # The two schemes must actually disagree, which is the whole point.
    per_scheme = [s["runcount_beats_layer"] for s in sensitivity["schemes"].values()]
    assert max(per_scheme) > 0.5 and min(per_scheme) < 0.5, (
        "the receipt must show the conclusion flipping between schemes; otherwise "
        "a single-scheme claim would be adequate and this guard is unnecessary")


def test_no_receipt_asserts_a_global_cost_model_conclusion():
    """Generated receipt strings must not resurrect the withdrawn claim.

    The bootstrap receipt is machine-generated, so its `conclusion` string is
    easy to overlook. It must scope itself to its own scheme and point at the
    sensitivity companion rather than asserting a general result.
    """
    receipts = (TOOLS.parents[1] / "docs" / "plans" / "du8-matrix-2026-10-16" / "receipts")
    bootstrap = json.loads((receipts / "cost-model-bootstrap.json").read_text(encoding="utf-8"))
    conclusion = bootstrap["conclusion"]
    assert "THIS resampling scheme" in conclusion, (
        "the generated conclusion must scope itself to one scheme")
    assert "sensitivity" in conclusion, (
        "the generated conclusion must point at the scheme-sensitivity receipt")
    assert "NOT for a claimed robustness advantage" in conclusion
    # And the withdrawn phrasing must be gone from every committed receipt.
    for path in receipts.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "generalizes at least as well" not in text, (
            f"{path.name} still carries the withdrawn robustness claim")


def test_ship_reason_is_simplicity_not_a_robustness_claim():
    """The shipped model's justification must not overclaim robustness."""
    module = (TOOLS / "case_scheduling.py").read_text(encoding="utf-8")
    assert "does NOT claim run-count" in module, (
        "the module must explicitly disclaim the refuted robustness claim")
    assert "SIMPLER" in module
    readme = (TOOLS / "README.md").read_text(encoding="utf-8")
    assert "不是「更稳健」" in readme or "不是\"更稳健\"" in readme, (
        "the README must state the ship reason is not superior robustness")


def test_full_coverage_comparison_receipt_is_the_real_one():
    """The committed comparison receipt must be full-coverage, not a refusal."""
    receipt = (TOOLS.parents[1] / "docs" / "plans" / "du8-matrix-2026-10-16"
               / "receipts" / "scheduling-comparison.json")
    data = json.loads(receipt.read_text(encoding="utf-8"))
    assert data["comparison_refused"] is False
    assert data["coverage"] == {"measured": 41, "required": 41, "missing": []}
    assert data["legacy_partition"]["makespan_seconds"] == pytest.approx(75.5306, abs=0.01)
    assert data["shipped_partition"]["makespan_seconds"] == pytest.approx(74.008, abs=0.01)
    assert data["perfect_balance_bound_seconds"] == pytest.approx(67.6663, abs=0.01)
    assert data["improvement_percent"] == pytest.approx(2.02, abs=0.01)


def test_refusal_sample_is_kept_separately_and_marks_itself_refused():
    """The refusal artifact must not be mistaken for the real comparison."""
    receipts = (TOOLS.parents[1] / "docs" / "plans" / "du8-matrix-2026-10-16" / "receipts")
    sample = receipts / "scheduling-comparison-refusal-sample.json"
    assert sample.is_file(), "keep a refusal sample under a distinct filename"
    data = json.loads(sample.read_text(encoding="utf-8"))
    assert data["comparison_refused"] is True
    assert "legacy_partition" not in data and "improvement_percent" not in data
