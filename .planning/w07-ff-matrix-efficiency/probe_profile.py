"""Profile CWP ensure CLI and FF CLI child processes (diagnosis only)."""
from __future__ import annotations
import json
import pstats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "offline_contract_matrix"))

from runtime import Deadline, OwnedAttempt, run_process  # noqa: E402
from fixture_builder import CN  # noqa: E402
from run import Context, _mk_filing_request  # noqa: E402


def show(prof_path, label, n=20):
    st = pstats.Stats(str(prof_path))
    import io
    buf = io.StringIO()
    st.stream = buf
    st.sort_stats("cumulative").print_stats(n)
    print(f"===== {label} =====")
    print(buf.getvalue())


def main():
    cwp = ROOT / ".planning/w07-ff-matrix-efficiency/input/runtime/cwp"
    et = ROOT / ".planning/w07-ff-matrix-efficiency/input/runtime/et"
    scratch_parent = ROOT / ".tmp" / "w07-prof"
    out_parent = ROOT / ".tmp" / "w07-prof-out"
    attempt = OwnedAttempt.create(scratch_parent, out_parent,
                                  (cwp / "src", et, ROOT / "config", ROOT / "scripts"))
    try:
        ctx = Context(ff_root=ROOT, cwp_root=cwp, et_root=et,
                      scratch=attempt.scratch, out_root=attempt.output,
                      deadline=Deadline(600))
        ctx.write_state(scenario="success", calls_file=ctx.env.calls_file("probe_ensure"),
                        receipt_tag="probe_ensure")
        # ---- CWP ensure CLI under cProfile ----
        wrap = attempt.scratch / "ensure_wrap.py"
        wrap.write_text("from company_wiki.source_catalog.cli import main\nraise SystemExit(main())\n",
                        encoding="utf-8")
        prof1 = attempt.scratch / "ensure.prof"
        cmd = [sys.executable, "-B", "-m", "cProfile", "-o", str(prof1),
               str(wrap),
               "--config", str(ctx.env.wiki / "config/source_catalog.yaml"), "ensure",
               "--entity", CN.canonical_name, "--market", CN.market, "--security-id", CN.security_id,
               "--document-kind", "annual_report", "--fiscal-year", "2024", "--fiscal-period", "FY",
               "--as-of-date", "2026-12-31", "--source-ref-v2", "--allow-download",
               "--acquisition-config", str(ctx.env.wiki / "config/source_acquisition.yaml"),
               "--max-download-bytes", "2000000", "--max-download-seconds", "10",
               "--max-download-cost-usd", "0"]
        t0 = time.monotonic()
        proc = run_process(cmd, env=ctx.child_env(), cwd=ctx.scratch, deadline=Deadline(120))
        print("ensure seconds:", round(time.monotonic() - t0, 3), "exit:", proc.returncode)
        show(prof1, "CWP ensure CLI", 22)

        # ---- FF local hit under cProfile ----
        ctx.scan()
        req = _mk_filing_request(CN, document_kind="annual_report", fiscal_year=2024,
                                 fiscal_period="FY", intent="reuse_only")
        prof2 = attempt.scratch / "ff.prof"
        t0 = time.monotonic()
        proc = run_process(
            [sys.executable, "-B", "-m", "cProfile", "-o", str(prof2),
             str(ROOT / "scripts" / "fetch_filing.py"),
             "--config", str(ctx.env.ff_config), "--timeout-seconds", "30"],
            input=json.dumps(req, ensure_ascii=False).encode("utf-8"),
            env=ctx.child_env(), cwd=ctx.scratch, deadline=Deadline(120))
        print("ff seconds:", round(time.monotonic() - t0, 3), "exit:", proc.returncode)
        show(prof2, "FF fetch_filing local hit", 25)
    finally:
        print("restore:", attempt.cleanup())


if __name__ == "__main__":
    main()
