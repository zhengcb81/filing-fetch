"""Pure cost-balanced case scheduling for the offline contract matrix.

Why this module exists (DU8-FF-MATRIX-COMPLETION, node A): the runner used
``entries[index::workers]`` — a *position* round-robin. Position carries no
cost information, and the fixed 41-case registry is heterogeneous (cheap
single-run local hits vs the real-3layer ``chainA_download_reuse`` and the
multi-run fetch/retry chains). On the retained W07 full 41/41 cost table that
produced group loads of 75.5306s and 59.8019s: a 15.73s (26%) imbalance that
became the single critical path and starved the tail of the 180s budget.

This owner is deliberately **pure**: no clock, no process, no environment, no
I/O, no randomness. Callers supply the case entries and a cost estimate; the
function returns the group assignment. That keeps the planner trivially
testable under a fake clock and incapable of widening concurrency by itself.

HONESTY ABOUT THE COST MODEL (measured, not asserted)
-----------------------------------------------------
Two cost sources are supported, and their real-world strength differs a lot.
Both were scored on the retained W07 41/41 measured table (perfect-balance bound
= total/2 = 67.6663s; legacy position round-robin = 75.5306s; critical-path
ratio = makespan / bound, so 1.0 is perfect):

* ``measured`` — the caller supplies per-case seconds (e.g. a prior run's
  ``actual.elapsed_seconds``) through ``cost_of``. Ratio 1.0000: LPT on real
  costs reaches the bound.
* ``static`` (default) — derived only from the frozen case authority (run
  count). Ratio 1.0937 on the real table: a 1.52s / 2.02% critical-path gain
  over legacy, and 69% of random 20/21 partitions beat it.

So the static model is shipped as a **safe, reproducible, modest** improvement -
NOT as near-optimal scheduling. A higher-scoring per-layer variant was
not selected because the simpler model is easier to derive (see RUN_WEIGHT_SECONDS). Callers holding real
measurements should pass them via ``cost_of``; the runner exposes the hook but
does not use it implicitly, so a batch never depends on a prior run's timing.

Determinism: the longest-processing-time-first greedy runs over a total order
of (cost descending, case id ascending), and ties between equal group loads
break toward the lower group index. The same case set therefore always yields
the same partition, independent of input order.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

# Static fallback for a case the caller supplied no measurement for. Chosen at
# the cheap single-run local-hit order of magnitude so an unknown case can never
# dominate the schedule.
DEFAULT_COST_SECONDS = 2.0

# Static model: a fixed base plus a weight per FF chain, because a ``CaseSpec``
# with N runs starts N full download->reuse chains inside ONE group.
#
# A richer model (per-declared-layer base) was tried and rejected. It scores
# better on the retained W07 41/41 table (67.723s, ratio 1.0008, against a
# 67.666s bound) but that number is not trustworthy: it carries only 4 distinct
# values across 41 cases and its optimal weight region is a narrow plateau.
#
# The robustness comparison is genuinely SCHEME-DEPENDENT and is recorded in
# fixtures/cost_model_bootstrap.py, cost_model_bootstrap_sensitivity.py and
# receipts/cost-model-bootstrap*.json. Under stratified resampling of the W07
# costs the plain run-count model wins (mean ratio 1.0498, beats legacy in 70.2%
# of draws vs the layer model's 1.0598 / 64.2%). Under proportional noise the
# LAYER model wins decisively (at +-20% it beats legacy in 100% of draws and
# beats run-count in 99.96%). So this module does NOT claim run-count
# generalizes better.
#
# Run-count is shipped because it is SIMPLER, has transparent provenance, is
# fully derivable from the frozen case authority, and is a demonstrated (if
# modest) improvement on real full-coverage data - not because it is more
# robust. A reader who wants the better-fitting static model should use the
# layer weights recorded in the bootstrap fixtures.
RUN_WEIGHT_SECONDS = 2.0


def static_cost(entries: Sequence[tuple[int, tuple[str, Any]]],
                cost_of: Callable[[str], float] | None = None) -> dict[str, float]:
    """Cost estimate per case id, using a caller measurement when available.

    ``cost_of`` is the supported hook for real measurements (the report's own
    ``actual.elapsed_seconds`` from an earlier run). Return ``None`` from it for
    cases without a measurement and the frozen static estimate is used instead.
    """
    from case_registry import resolve_spec

    model: dict[str, float] = {}
    for _pos, (cid, _runner) in entries:
        if cost_of is not None:
            value = cost_of(cid)
            if value is not None:
                model[cid] = float(value)
                continue
        spec = resolve_spec(cid)
        runs = len(getattr(spec, "runs", ()) or ())
        model[cid] = DEFAULT_COST_SECONDS + RUN_WEIGHT_SECONDS * max(0, runs - 1)
    return model


def assign_groups(entries: Iterable[tuple[int, tuple[str, Any]]], *,
                  workers: int, cost: dict[str, float] | None = None,
                  cost_of: Callable[[str], float] | None = None
                  ) -> list[list[tuple[int, tuple[str, Any]]]]:
    """Partition the fixed case entries into ``workers`` cost-balanced groups.

    Guarantees relied on by the runner and its tests:

    * every *entry* lands in exactly one group;
    * at most ``workers`` groups are produced - the planner never raises
      concurrency to balance load;
    * the result depends only on the *set* of entries, not their order;
    * the greedy always charges the currently lightest group, so the heaviest
      case is never stacked on top of an already heavier group.

    Grouping is per entry, so a whole download->reuse case chain stays in one
    group as long as the caller passes each case exactly once. The runner does
    that by construction (``enumerate(registry)``), and the suite asserts the
    exactly-once property on the real registry. The planner does NOT dedupe:
    the same case id supplied twice would be scheduled twice, which is a caller
    error rather than a scheduler guarantee.

    A group can be empty when there are fewer entries than workers. Equal
    positive costs are distributed across groups; they do not stack in one.
    """
    entries = list(entries)
    if workers < 1:
        raise ValueError("workers must be at least one")
    model = dict(cost) if cost is not None else static_cost(entries, cost_of)

    # Total order: cost descending, then id ascending for determinism.
    ordered = sorted(
        entries,
        key=lambda item: (-model.get(item[1][0], DEFAULT_COST_SECONDS), item[1][0]),
    )
    groups: list[list[tuple[int, tuple[str, Any]]]] = [[] for _ in range(workers)]
    loads = [0.0] * workers
    for item in ordered:
        target = 0
        for index in range(1, workers):
            if loads[index] < loads[target]:
                target = index
        groups[target].append(item)
        loads[target] += model.get(item[1][0], DEFAULT_COST_SECONDS)
    return groups


def group_loads(groups: Sequence[Sequence[tuple[int, tuple[str, Any]]]],
                cost: dict[str, float]) -> list[float]:
    """Predicted seconds per group; reporting helper, never a gate."""
    return [round(sum(cost.get(cid, DEFAULT_COST_SECONDS) for _pos, (cid, _r) in group), 4)
            for group in groups]


def balance_report(groups: Sequence[Sequence[tuple[int, tuple[str, Any]]]],
                   cost: dict[str, float], *, cost_source: str = "static") -> dict[str, Any]:
    """Summary of a partition for the report and the handoff.

    ``cost_source`` records which model produced the numbers so a reader can
    never mistake a static prediction for a measurement.
    """
    loads = group_loads(groups, cost)
    makespan = max(loads) if loads else 0.0
    total = sum(loads)
    lower_bound = total / len(loads) if loads else 0.0
    return {
        "group_loads_seconds": loads,
        "group_case_counts": [len(group) for group in groups],
        "predicted_makespan_seconds": round(makespan, 4),
        "perfect_balance_lower_bound_seconds": round(lower_bound, 4),
        "imbalance_seconds": round(makespan - lower_bound, 4),
        "cost_source": cost_source,
        "cost_model": (
            "measured per-case seconds supplied via cost_of" if cost_source == "measured"
            else "frozen static estimate from CaseSpec run count; a coarse proxy, "
                 "measured at 74.008s vs legacy 75.531s and vs the 67.666s "
                 "perfect-balance bound on the retained W07 41/41 table"
        ),
    }
