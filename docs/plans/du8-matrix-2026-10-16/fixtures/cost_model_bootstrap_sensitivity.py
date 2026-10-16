"""N1 sensitivity: does the conclusion depend on the resampling scheme?

The re-auditor inverted my bootstrap result. My committed script resamples each
case's cost from its own run-count stratum (times U(0.9,1.1)). The auditor
applied +-40% / +-20% noise to the fixed partitions and got layer winning.

Both are defensible resampling models of "the batch runs on a different machine
load". This script runs several schemes side by side and reports the
win rates, so the shipped-model decision can be read off the range rather than
from one hand-picked scheme.
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
OUT = ROOT / "docs/plans/du8-matrix-2026-10-16/receipts/cost-model-bootstrap-sensitivity.json"
TRIALS = 5000


def main() -> int:
    specs = case_specs()
    ids = [s.id for s in specs]
    data = json.loads(W07.read_text(encoding="utf-8"))
    real = {c["id"]: c["actual"]["elapsed_seconds"] for c in data["cases"]}

    rc_w = lambda s: 2.0 + 2.0 * max(0, len(s.runs) - 1)  # noqa: E731
    lb = {"real-3layer": 4.0, "ff+et": 4.0, "ff+cwp": 2.0, "ff-only": 0.5}
    ly_w = lambda s: lb.get(s.declared_layer, 2.0) + 2.0 * max(0, len(s.runs) - 1)  # noqa: E731

    def bins_for(w):
        order = sorted(specs, key=lambda s: (-w(s), s.id))
        grouped = [[], []]
        load = [0.0, 0.0]
        for s in order:
            i = 0 if load[0] <= load[1] else 1
            grouped[i].append(s.id)
            load[i] += w(s)
        return grouped

    legacy = [ids[i::2] for i in range(2)]
    b_run, b_layer = bins_for(rc_w), bins_for(ly_w)

    def ratio(b, c):
        return max(sum(c[x] for x in g) for g in b) / (sum(c.values()) / 2)

    strata = {}
    for s in specs:
        strata.setdefault(len(s.runs), []).append(real[s.id])

    schemes = {}
    for noise in (0.10, 0.20, 0.40):
        rnd = random.Random(20261016)
        r = {"legacy": [], "runcount": [], "layer": []}
        for _ in range(TRIALS):
            boot = {s.id: real[s.id] * rnd.uniform(1 - noise, 1 + noise) for s in specs}
            for k, b in (("legacy", legacy), ("runcount", b_run), ("layer", b_layer)):
                r[k].append(ratio(b, boot))
        schemes[f"proportional_noise_pm{int(noise*100)}pct"] = r

    # my committed scheme: within-run-count-stratum resample
    rnd = random.Random(20261016)
    r = {"legacy": [], "runcount": [], "layer": []}
    for _ in range(TRIALS):
        boot = {s.id: rnd.choice(strata[len(s.runs)]) * rnd.uniform(0.9, 1.1) for s in specs}
        for k, b in (("legacy", legacy), ("runcount", b_run), ("layer", b_layer)):
            r[k].append(ratio(b, boot))
    schemes["stratified_resample_x_0.9_1.1"] = r

    out = {"schema": "du8-cost-model-bootstrap-sensitivity/1", "trials": TRIALS, "schemes": {}}
    for name, r in schemes.items():
        def wins(a, b):
            return round(sum(1 for x, y in zip(r[a], r[b]) if x < y) / TRIALS, 4)
        out["schemes"][name] = {
            "mean_ratio": {k: round(statistics.mean(v), 4) for k, v in r.items()},
            "runcount_beats_legacy": wins("runcount", "legacy"),
            "layer_beats_legacy": wins("layer", "legacy"),
            "runcount_beats_layer": wins("runcount", "layer"),
        }
    out["on_actual_table"] = {
        "legacy": round(ratio(legacy, real), 4),
        "runcount": round(ratio(b_run, real), 4),
        "layer": round(ratio(b_layer, real), 4),
    }
    # The honest reading: does run-count beat layer in EVERY scheme?
    every = all(s["runcount_beats_layer"] >= 0.5 for s in out["schemes"].values())
    out["conclusion"] = (
        "run-count is at least as robust as layer under every resampling scheme tested"
        if every else
        "the two models trade places depending on the resampling scheme: run-count wins "
        "under stratified resampling, layer wins under proportional noise. The shipped "
        "choice therefore rests on SIMPLICITY and frozen-input derivability, not on a "
        "generalization advantage."
    )
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
