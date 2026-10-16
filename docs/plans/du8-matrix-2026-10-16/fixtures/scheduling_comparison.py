"""DU8 node B — load-normalized scheduling proof from the SAME measured batch.

The card forbids "fabricating time because the machine is slow" and forbids
re-running until something happens to be green. The honest way to show the
scheduling change is real, on a shared and saturated workstation, is a
*within-run* comparison: take one real full batch, read the measured per-case
seconds out of it, and evaluate BOTH partitions over that identical cost table.

The old partition is `entries[index::workers]` (what the runner used to do).
The new partition is `case_scheduling.assign_groups`, using ONLY the frozen
run-count cost model (no measured timings are fed back in), so the comparison
is not self-fulfilling.

Output: docs/plans/du8-matrix-2026-10-16/receipts/scheduling-comparison.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TOOLS = ROOT / "tools" / "offline_contract_matrix"
sys.path.insert(0, str(TOOLS))

from case_scheduling import assign_groups, static_cost, group_loads, balance_report  # noqa: E402
from case_specs import case_specs  # noqa: E402

OUT = ROOT / "docs" / "plans" / "du8-matrix-2026-10-16" / "receipts" / "scheduling-comparison.json"
BATCH = 180.0
RESERVE = 10.0
CASE_WINDOW = BATCH - RESERVE  # case work may only use this much of the batch


def _measured(report_path: Path) -> dict[str, float]:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return {c["id"]: (c.get("actual") or {}).get("elapsed_seconds")
            for c in data["cases"] if (c.get("actual") or {}).get("elapsed_seconds") is not None}


def _evaluate(groups, cost, window=CASE_WINDOW):
    """Predicted per-group finish time and cases that cannot fit the window."""
    loads = group_loads(groups, cost)
    makespan = max(loads) if loads else 0.0
    # Under a shared absolute window, a group whose accumulated work exceeds the
    # case window starves its own tail: those cases are the ones that go NOT_RUN.
    starved = {}
    for index, group in enumerate(groups):
        total = 0.0
        run_out = []
        for _pos, (cid, _runner) in group:
            total += cost.get(cid, 2.0)
            if total > window:
                run_out.append(cid)
        starved[f"g{index + 1}"] = run_out
    return {
        "group_loads_seconds": loads,
        "predicted_makespan_seconds": round(makespan, 4),
        "predicted_imbalance_seconds": round(makespan - (sum(loads) / len(loads)) if loads else 0.0, 4),
        "case_window_seconds": window,
        "cases_beyond_window": starved,
        "cases_beyond_window_total": sum(len(v) for v in starved.values()),
    }


def main() -> int:
    report_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if report_path is None or not report_path.is_file():
        candidates = sorted((ROOT / ".tmp" / "du8-c" / "out").glob("attempt-*/report.json"))
        if not candidates:
            print("no measured report found; pass one explicitly")
            return 2
        report_path = candidates[-1]

    measured = _measured(report_path)
    specs = case_specs()
    ids = [s.id for s in specs]

    # Cost tables. The FROZEN model is what the runner actually ships; the
    # measured table is only used to score both partitions on real data.
    entries = list(enumerate([(s.id, None) for s in specs]))
    frozen = static_cost(entries)
    real = {cid: measured.get(cid) for cid in ids if cid in measured}

    legacy = [entries[i::2] for i in range(2)]
    balanced = assign_groups(entries, workers=2, cost=frozen)

    result = {
        "schema": "du8-scheduling-comparison/1",
        "measured_report": str(report_path),
        "measured_cases": len(real),
        "measured_case_seconds": round(sum(real.values()), 4),
        "note": (
            "Both partitions are scored on the SAME measured per-case seconds taken "
            "from one real batch on this workstation. The new partition is produced "
            "by the shipped frozen run-count cost model only; no measured timing is "
            "fed back into the scheduler, so the comparison cannot be self-fulfilling."
        ),
        "frozen_cost_model": balance_report(balanced, frozen),
        "legacy_partition": {
            "rule": "entries[index::workers] (position round-robin)",
            "on_frozen_model": _evaluate(legacy, frozen),
            "on_measured_seconds": _evaluate(legacy, real),
        },
        "balanced_partition": {
            "rule": "case_scheduling.assign_groups (LPT on run-count cost)",
            "on_frozen_model": _evaluate(balanced, frozen),
            "on_measured_seconds": _evaluate(balanced, real),
            "groups": {f"g{i + 1}": [cid for _p, (cid, _r) in g] for i, g in enumerate(balanced)},
        },
    }
    lm = result["legacy_partition"]["on_measured_seconds"]["predicted_makespan_seconds"]
    bm = result["balanced_partition"]["on_measured_seconds"]["predicted_makespan_seconds"]
    result["measured_makespan_improvement_seconds"] = round(lm - bm, 4)
    result["measured_makespan_improvement_ratio"] = round(lm / bm, 4) if bm else None
    result["legacy_cases_beyond_window"] = result["legacy_partition"]["on_measured_seconds"]["cases_beyond_window_total"]
    result["balanced_cases_beyond_window"] = result["balanced_partition"]["on_measured_seconds"]["cases_beyond_window_total"]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items()
                      if k not in {"legacy_partition", "balanced_partition", "frozen_cost_model"}}, indent=2))
    print("\nlegacy  on measured:", json.dumps(result["legacy_partition"]["on_measured_seconds"]))
    print("balanced on measured:", json.dumps(
        {k: v for k, v in result["balanced_partition"]["on_measured_seconds"].items() if k != "groups"}))
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
