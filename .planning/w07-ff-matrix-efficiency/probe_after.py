"""W07 after-fix smoke: real batch seed + one local hit + one ET chain + proofs."""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "offline_contract_matrix"))

from runtime import Deadline, OwnedAttempt  # noqa: E402
from fixture_builder import CN, US  # noqa: E402
from run import Context, _mk_filing_request, _companion  # noqa: E402
from measurement import merge_launch_accounting  # noqa: E402
from matrix_outcome import source_ref  # noqa: E402


def main():
    cwp = ROOT / ".planning/w07-ff-matrix-efficiency/input/runtime/cwp"
    et = ROOT / ".planning/w07-ff-matrix-efficiency/input/runtime/et"
    attempt = OwnedAttempt.create(ROOT / ".tmp" / "w07-smoke", ROOT / ".tmp" / "w07-smoke-out",
                                  (cwp / "src", et, ROOT / "config", ROOT / "scripts"))
    try:
        ctx = Context(ff_root=ROOT, cwp_root=cwp, et_root=et,
                      scratch=attempt.scratch, out_root=attempt.output, deadline=Deadline(300))
        t0 = time.monotonic()
        receipts = ctx.warm_seed_batch([(CN, "annual_report", 2024, "FY"), (US, "annual_report", 2024, "FY")])
        print("seed_batch(2 seeds) seconds:", round(time.monotonic() - t0, 3))
        for row in receipts:
            print("  ", row["tag"], row["exit_code"], (row["response"] or {}).get("status"),
                  bool(row["source_ref"]), row["counts"])

        t0 = time.monotonic()
        ctx.scan()
        print("scan seconds:", round(time.monotonic() - t0, 3))

        from case_specs import get_spec
        ctx.begin_case()
        ctx.active_case_spec = get_spec("fin_cn_annual_hit")
        req = _mk_filing_request(CN, document_kind="annual_report", fiscal_year=2024,
                                 fiscal_period="FY", intent="reuse_only")
        t0 = time.monotonic()
        run1 = ctx.run_ff(req, case_id="fin_cn_annual_hit")
        print("ff_local_hit seconds:", round(time.monotonic() - t0, 3),
              "status:", run1["response"].get("status"))

        ctx.begin_case()
        ctx.active_case_spec = get_spec("chainA_download_reuse")
        ctx.write_state(scenario="success", calls_file=ctx.env.calls_file("smoke_chain"),
                        receipt_tag="smoke_chain",
                        content_utf8="Synthetic original-language AAPL FY2025 Q1 earnings call transcript.")
        req2 = _mk_filing_request(US, document_kind="annual_report", fiscal_year=2025,
                                  fiscal_period="FY", intent="reuse_only",
                                  companion=_companion(2025, 1, "fetch_if_missing"))
        t0 = time.monotonic()
        run2 = ctx.run_ff(req2, case_id="chainA_download_reuse", run_label="smoke")
        print("ff_et_companion seconds:", round(time.monotonic() - t0, 3),
              "transcript:", json.dumps((run2["response"].get("transcript") or {}).get("status")))
        t = run2["response"].get("transcript") or {}
        print("  source_ref:", bool(source_ref(t.get("source_ref"))),
              "et_receipt:", run2.get("et_usage_receipt") is not None,
              "fixture_requests:", run2.get("fixture_requests"))

        accounting = merge_launch_accounting(ctx.phases, attempt.scratch / "launches.jsonl")
        print("phases:", json.dumps(ctx.phases.snapshot(), ensure_ascii=False))
        print("launches:", json.dumps(accounting["launches"], ensure_ascii=False))
    finally:
        print("restore:", attempt.cleanup())


if __name__ == "__main__":
    main()
