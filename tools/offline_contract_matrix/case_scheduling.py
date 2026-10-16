"""Pure cost-balanced case scheduling for the offline contract matrix.

Why this module exists (DU8-FF-MATRIX-COMPLETION, node A): the runner used
``entries[index::workers]`` — a *position* round-robin. Position carries no
cost information, and the fixed 41-case registry is heavily heterogeneous
(1-run local hits ~1.5s vs the real-3layer ``chainA_download_reuse`` ~10.6s
and the 2-run ``request_after_failure_retry`` ~8.3s). Measured on the retained
W07 full batch this produced group loads of 75.53s and 59.80s: a 15.7s (26%)
imbalance that became the critical path and, at the 180s batch budget, pushed
the tail cases into the reserved proof window.

This owner is deliberately **pure**: no clock, no process, no environment, no
I/O, no randomness. Callers supply the case entries and a cost estimate; the
function returns the group assignment. That keeps the planner trivially
testable under a fake clock and incapable of widening concurrency by itself.

Determinism: the longest-processing-time-first greedy is applied over a total
order that is (cost descending, case id ascending), and ties between group
loads are broken by the lower group index. The same set of cases therefore
always yields the same partition, independent of input order.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

# Default cost estimate for a case the cost model does not know. Chosen as the
# cheap single-run local-hit order of magnitude so an unknown case can never
# dominate the schedule; the real per-case timings replace it as soon as the
# measurement exists.
DEFAULT_COST_SECONDS = 2.0

# Relative weight of one FF child launch inside a case. A `CaseSpec` with N
# runs starts N full download->reuse chains inside ONE group, so the run count
# is the strongest static predictor of case cost available before measurement.
RUN_WEIGHT_SECONDS = 2.0


def static_cost(entries: Sequence[tuple[int, tuple[str, Any]]],
                cost_of: Callable[[str], float] | None = None) -> dict[str, float]:
    """Cost estimate per case id from the fixed CaseSpec shape.

    ``cost_of`` lets the caller supply measured per-case seconds (the report's
    own ``actual.elapsed_seconds``). Without it the estimate is the run count,
    which is a property of the frozen case authority rather than of a run.
    """
    from case_specs import get_spec

    model: dict[str, float] = {}
    for _pos, (cid, _runner) in entries:
        if cost_of is not None:
            value = cost_of(cid)
            if value is not None:
                model[cid] = float(value)
                continue
        spec = get_spec(cid)
        runs = len(getattr(spec, "runs", ()) or ())
        model[cid] = DEFAULT_COST_SECONDS + RUN_WEIGHT_SECONDS * max(0, runs - 1)
    return model


def assign_groups(entries: Iterable[tuple[int, tuple[str, Any]]], *,
                  workers: int, cost: dict[str, float] | None = None) -> list[list[tuple[int, tuple[str, Any]]]]:
    """Partition the fixed case entries into ``workers`` cost-balanced groups.

    Guarantees relied on by the runner and its tests:

    * every entry lands in exactly one group;
    * a whole case chain stays inside one group (grouping is by case id, and a
      case id owns exactly one entry);
    * at most ``workers`` groups are produced — the planner never raises
      concurrency to balance load;
    * the result depends only on the *set* of entries, not their order;
    * group 0 receives the heaviest case, and the greedy then always charges
      the currently lightest group, so the heaviest case is never stacked on
      top of an already heavier group.
    """
    entries = list(entries)
    if workers < 1:
        raise ValueError("workers must be at least one")
    model = dict(cost) if cost is not None else static_cost(entries)

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
                   cost: dict[str, float]) -> dict[str, Any]:
    """Measured-shape summary of a partition for the report and the handoff."""
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
        "cost_model": "measured per-case seconds where available, else CaseSpec run-count weight",
    }
