"""W07-FF-PERF small-sample timing probe (diagnosis only, not the E2E run)."""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "offline_contract_matrix"))

from runtime import Deadline, OwnedAttempt, run_process, synthetic_env  # noqa: E402
from fixture_builder import ScratchEnvironment, CN, US  # noqa: E402
from run import Context, _mk_filing_request, _companion  # noqa: E402

TIMES = {}


def timed(name, fn, reps=1):
    out = []
    for _ in range(reps):
        t0 = time.monotonic()
        val = fn()
        out.append(time.monotonic() - t0)
    TIMES[name] = out
    print(f"{name}: {[round(x, 3) for x in out]}")
    return val


def main():
    cwp = ROOT / ".planning/w07-ff-matrix-efficiency/input/runtime/cwp"
    et = ROOT / ".planning/w07-ff-matrix-efficiency/input/runtime/et"
    scratch_parent = ROOT / ".tmp" / "w07-probe"
    out_parent = ROOT / ".tmp" / "w07-probe-out"
    attempt = OwnedAttempt.create(scratch_parent, out_parent,
                                  (cwp / "src", et, ROOT / "config", ROOT / "scripts"))
    try:
        ctx = Context(ff_root=ROOT, cwp_root=cwp, et_root=et,
                      scratch=attempt.scratch, out_root=attempt.output,
                      deadline=Deadline(600))
        env = ctx.child_env()

        # 1) bare interpreter startup
        timed("bare_python_startup", lambda: run_process(
            [sys.executable, "-B", "-c", "pass"], env=env, cwd=attempt.scratch,
            deadline=Deadline(60)), reps=3)

        # 2) interpreter + company_wiki import (what every CWP CLI launch pays)
        timed("python_import_company_wiki", lambda: run_process(
            [sys.executable, "-B", "-c", "import company_wiki"],
            env=env, cwd=attempt.scratch, deadline=Deadline(60)), reps=3)

        # 3) interpreter + fetch_filing.py import (what every FF CLI launch pays)
        timed("python_import_fetch_filing", lambda: run_process(
            [sys.executable, "-B", "-c",
             "import importlib.util,sys; spec=importlib.util.spec_from_file_location('ff', r'%s'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)" % str(ROOT / "scripts" / "fetch_filing.py").replace("\\", "/")],
            env=env, cwd=attempt.scratch, deadline=Deadline(60)), reps=1)

        # 4) one warm_seed ensure (real CWP CLI incl. fixture adapter subprocess)
        timed("warm_seed_ensure", lambda: ctx.warm_seed(CN, "annual_report", 2024, "FY"), reps=1)
        timed("warm_seed_ensure_2", lambda: ctx.warm_seed(CN, "semi_annual_report", 2024, "S1"), reps=1)

        # 5) one scan
        timed("scan", lambda: ctx.scan(), reps=1)

        # 6) FF local hit (reuse_only against seeded 2024 FY)
        ctx.begin_case()
        from case_specs import get_spec
        ctx.active_case_spec = get_spec("fin_cn_annual_hit")
        req = _mk_filing_request(CN, document_kind="annual_report", fiscal_year=2024,
                                 fiscal_period="FY", intent="reuse_only")
        timed("ff_local_hit", lambda: ctx.run_ff(req, case_id="fin_cn_annual_hit"), reps=1)

        # 7) FF + ET companion chain (one run of chainA-like request)
        ctx.active_case_spec = get_spec("chainA_download_reuse")
        ctx.write_state(scenario="success", calls_file=ctx.env.calls_file("probe_chain"),
                        receipt_tag="probe_chain",
                        content_utf8="Synthetic original-language AAPL FY2025 Q1 earnings call transcript.")
        req2 = _mk_filing_request(US, document_kind="annual_report", fiscal_year=2025,
                                  fiscal_period="FY", intent="reuse_only",
                                  companion=_companion(2025, 1, "fetch_if_missing"))
        timed("ff_et_companion_run", lambda: ctx.run_ff(req2, case_id="chainA_download_reuse",
                                                        run_label="probe"), reps=1)

        print(json.dumps(TIMES, indent=2))
    finally:
        restore = attempt.cleanup()
        print("restore:", restore)


if __name__ == "__main__":
    main()
