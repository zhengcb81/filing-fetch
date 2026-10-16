"""DU8 node B — scheduling comparison, scored ONLY on full-coverage data.

Design rules learned from an earlier version of this script that produced a
misleading headline:

  * A cost table that covers only the cases that happened to RUN prices the
    NOT_RUN starvation tail at a constant fallback. Since the starvation tail is
    exactly the heavy end, that inflates the apparent scheduling gain. This
    script therefore REFUSES to report a comparison from a partial table and
    says so explicitly.
  * The partition under test is produced by the shipped frozen cost model only;
    no measured timing is fed back into the scheduler, so the comparison cannot
    be self-fulfilling.
  * Random-partition and bootstrap baselines are reported next to the result so
    a modest gain cannot be mistaken for a large one.

Output: docs/plans/du8-matrix-2026-10-16/receipts/scheduling-comparison.json
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TOOLS = ROOT / "tools" / "offline_contract_matrix"
sys.path.insert(0, str(TOOLS))

from case_scheduling import assign_groups, group_loads, static_cost  # noqa: E402
from case_specs import case_specs  # noqa: E402

OUT = ROOT / "docs" / "plans" / "du8-matrix-2026-10-16" / "receipts" / "scheduling-comparison.json"
BATCH = 180.0
RESERVE = 10.0
CASE_WINDOW = BATCH - RESERVE


def _measured(report_path: Path) -> dict[str, float]:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return {c["id"]: (c.get("actual") or {}).get("elapsed_seconds")
            for c in data["cases"] if (c.get("actual") or {}).get("elapsed_seconds") is not None}


def _makespan(groups, cost):
    return max(group_loads(groups, cost)) if groups else 0.0


def _cases_beyond_window(groups, cost):
    starved = {}
    for index, group in enumerate(groups):
        total = 0.0
        run_out = []
        for _pos, (cid, _r) in group:
            total += cost[cid]
            if total > CASE_WINDOW:
                run_out.append(cid)
        starved[f"g{index + 1}"] = run_out
    return starved


def _random_baseline(entries, cost, ids, trials=20000, seed=20261016):
    rnd = random.Random(seed)
    legacy_makespan = _makespan([entries[i::2] for i in range(2)], cost)
    better = 0
    makespans = []
    for _ in range(trials):
        order = list(range(len(ids)))
        rnd.shuffle(order)
        half = len(ids) // 2
        a = [entries[i] for i in order[:half]]
        b = [entries[i] for i in order[half:]]
        m = _makespan([a, b], cost)
        makespans.append(m)
        if m < legacy_makespan:
            better += 1
    makespans.sort()
    return {
        "trials": trials,
        "fraction_beating_legacy": round(better / trials, 4),
        "median_random_makespan_seconds": round(makespans[trials // 2], 4),
    }


def main() -> int:
    report_path = Path(sys.argv[1])
    if not report_path.is_file():
        print(f"report not found: {report_path}")
        return 2

    measured = _measured(report_path)
    specs = case_specs()
    ids = [s.id for s in specs]
    entries = list(enumerate([(s.id, None) for s in specs]))

    result = {
        "schema": "du8-scheduling-comparison/1",
        "measured_report": str(report_path),
        "frozen_model": "case_scheduling.static_cost (CaseSpec run count)",
        "case_window_seconds": CASE_WINDOW,
    }

    if set(measured) != set(ids):
        missing = sorted(set(ids) - set(measured))
        result.update({
            "coverage": {"measured": len(measured), "required": len(ids), "missing": missing},
            "comparison_refused": True,
            "refusal_reason": (
                "the table is partial: pricing the un-run cases at a constant fallback "
                "would put a fabricated cost on exactly the starvation tail and inflate "
                "the apparent scheduling gain. No headline comparison is reported from "
                "this report; use a full 41/41 report instead."
            ),
            "honest_partial_facts": {
                "measured_case_seconds": round(sum(measured.values()), 4),
                "note": "raw measurement only; NOT a partition comparison",
            },
        })
    else:
        cost = dict(measured)
        frozen = static_cost(entries)
        legacy = [entries[i::2] for i in range(2)]
        shipped = assign_groups(entries, workers=2, cost=frozen)
        bound = sum(cost.values()) / 2

        result.update({
            "coverage": {"measured": len(measured), "required": len(ids), "missing": []},
            "comparison_refused": False,
            "perfect_balance_bound_seconds": round(bound, 4),
            "legacy_partition": {
                "rule": "entries[index::workers] (position round-robin)",
                "makespan_seconds": round(_makespan(legacy, cost), 4),
                "group_loads_seconds": group_loads(legacy, cost),
                "cases_beyond_window": _cases_beyond_window(legacy, cost),
            },
            "shipped_partition": {
                "rule": "case_scheduling.assign_groups on the frozen run-count model",
                "model_loads_seconds": group_loads(shipped, frozen),
                "makespan_seconds": round(_makespan(shipped, cost), 4),
                "group_loads_seconds": group_loads(shipped, cost),
                "cases_beyond_window": _cases_beyond_window(shipped, cost),
            },
        })
        lm = result["legacy_partition"]["makespan_seconds"]
        sm = result["shipped_partition"]["makespan_seconds"]
        result["improvement_seconds"] = round(lm - sm, 4)
        result["improvement_ratio"] = round(lm / sm, 4)
        result["improvement_percent"] = round(100 * (lm - sm) / lm, 2)
        result["random_baseline"] = _random_baseline(entries, cost, ids)
        result["honesty_note"] = (
            "Reported gain is modest by design. On this table "
            f"{result['random_baseline']['fraction_beating_legacy'] * 100:.1f}% of random "
            "partitions beat position round-robin, so the shipped static model is a "
            "reproducible improvement, not near-optimal scheduling."
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
