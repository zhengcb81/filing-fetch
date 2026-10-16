"""Settle N1: does the layer model or the run-count model generalize better?

The re-auditor reproduced the layer model but got an INVERTED bootstrap result
from mine. My original numbers were prose-only (the script was deleted), which
is exactly the mistake I criticise elsewhere. This script is committed as the
receipt so the claim is reproducible either way.

Method: fix both partitions (the layer model's and the run-count model's), then
resample the per-case cost vector many times and score both partitions on the
SAME resample. Report the mean ratio and the head-to-head win rate.
"""
import json
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools" / "offline_contract_matrix"))
from case_specs import case_specs  # noqa: E402

W07 = ROOT / "docs/handoffs/w07-ff-matrix-efficiency/evidence/final-41-report.json"
OUT = ROOT / "docs/plans/du8-matrix-2026-10-16/receipts/cost-model-bootstrap.json"

TRIALS = 5000
SEED = 20261016


def lpt_bins(specs, weight):
    order = sorted(specs, key=lambda s: (-weight(s), s.id))
    bins = [[], []]
    loads = [0.0, 0.0]
    for s in order:
        i = 0 if loads[0] <= loads[1] else 1
        bins[i].append(s.id)
        loads[i] += weight(s)
    return bins


def makespan(bins, cost):
    return max(sum(cost[c] for c in b) for b in bins)


def main() -> int:
    specs = case_specs()
    ids = [s.id for s in specs]
    data = json.loads(W07.read_text(encoding="utf-8"))
    real = {c["id"]: c["actual"]["elapsed_seconds"] for c in data["cases"]}
    assert set(real) == set(ids), "need full 41/41 coverage"

    runcount_w = lambda s: 2.0 + 2.0 * max(0, len(s.runs) - 1)            # noqa: E731
    layer_base = {"real-3layer": 4.0, "ff+et": 4.0, "ff+cwp": 2.0, "ff-only": 0.5}
    layer_w = lambda s: layer_base.get(s.declared_layer, 2.0) + 2.0 * max(0, len(s.runs) - 1)  # noqa: E731

    legacy = [ids[i::2] for i in range(2)]
    bins_run = lpt_bins(specs, runcount_w)
    bins_layer = lpt_bins(specs, layer_w)
    bound = sum(real.values()) / 2

    def ratio(bins, cost):
        return makespan(bins, cost) / (sum(cost.values()) / 2)

    actual = {
        "legacy": round(ratio(legacy, real), 4),
        "runcount": round(ratio(bins_run, real), 4),
        "layer": round(ratio(bins_layer, real), 4),
    }

    # Distinct-value counts and plateau width (why the layer model is suspect).
    layer_vals = sorted({round(layer_w(s), 4) for s in specs})
    run_vals = sorted({round(runcount_w(s), 4) for s in specs})

    # Bootstrap: resample each case's cost within its own run-count stratum.
    rnd = random.Random(SEED)
    strata = {}
    for s in specs:
        strata.setdefault(len(s.runs), []).append(real[s.id])
    res = {"legacy": [], "runcount": [], "layer": []}
    for _ in range(TRIALS):
        boot = {s.id: rnd.choice(strata[len(s.runs)]) * rnd.uniform(0.9, 1.1) for s in specs}
        res["legacy"].append(ratio(legacy, boot))
        res["runcount"].append(ratio(bins_run, boot))
        res["layer"].append(ratio(bins_layer, boot))

    def wins(a, b):
        return round(sum(1 for x, y in zip(res[a], res[b]) if x < y) / TRIALS, 4)

    result = {
        "schema": "du8-cost-model-bootstrap/1",
        "purpose": (
            "Settle whether the layer cost model or the plain run-count model "
            "generalizes better, so the shipped-model choice rests on a "
            "reproducible measurement rather than prose."
        ),
        "source_table": str(W07),
        "coverage": {"measured": len(real), "required": len(ids)},
        "trials": TRIALS,
        "seed": SEED,
        "resampling": "per-case cost drawn from its own CaseSpec run-count stratum, times U(0.9,1.1)",
        "on_actual_table": actual,
        "bound_seconds": round(bound, 4),
        "distinct_model_values": {"runcount": run_vals, "layer": layer_vals},
        "bootstrap": {
            name: {
                "mean_ratio": round(statistics.mean(xs), 4),
                "median_ratio": round(sorted(xs)[TRIALS // 2], 4),
                "p90_ratio": round(sorted(xs)[int(TRIALS * 0.9)], 4),
                "worst_ratio": round(sorted(xs)[-1], 4),
            }
            for name, xs in res.items()
        },
        "head_to_head": {
            "runcount_beats_legacy": wins("runcount", "legacy"),
            "layer_beats_legacy": wins("layer", "legacy"),
            "runcount_beats_layer": wins("runcount", "layer"),
            "layer_beats_runcount": wins("layer", "runcount"),
            "runcount_worse_than_legacy": round(1 - wins("runcount", "legacy"), 4),
            "layer_worse_than_legacy": round(1 - wins("layer", "legacy"), 4),
        },
    }
    # State the conclusion the data actually supports.
    hl = result["head_to_head"]
    if hl["runcount_beats_legacy"] >= hl["layer_beats_legacy"]:
        result["conclusion"] = (
            "run-count generalizes at least as well as layer; ship run-count "
            "(also simpler and fully derivable from frozen inputs)"
        )
    else:
        result["conclusion"] = (
            "layer generalizes better under this resampling; the shipped "
            "run-count model is then a simplicity choice, NOT a robustness win"
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
