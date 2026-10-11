"""CLI orchestration for the offline FF↔ET↔CWP contract matrix.

Entry: ``python -B tools/offline_contract_matrix/run.py --cwp-project ... --et-project ...
--owned-root ... --out-root ...``. This module builds the isolated scratch,
records the pre-run baseline and sentinel, verifies the code binding (actual
module __file__/SHA), runs the coverage matrix, writes the
``ff-et-cwp-offline-matrix/1`` report, runs the failure-vector oracle, and
restores the sentinel/baseline.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from run import (  # noqa: E402
    Context, ProductionGuard,
    CASE_TIMEOUT, SENTINEL_NAME, SENTINEL_CONTENT,
)
from matrix_cases import (  # noqa: E402
    case_chain_a, case_fin_local_hit, case_fin_fetch, case_nonperiod,
    case_call_fy_only, case_call_past_cutoff, case_call_wrong_quarter,
    case_err_request, case_err_402, case_err_missing_creds, case_err_unknown_usage,
    seed_all,
)
from report import CaseResult, Dependency, build_report, emit, sha256_file  # noqa: E402
from fixture_builder import CN, US, HK  # noqa: E402
import oracle as oracle_mod  # noqa: E402


def _git_head(root: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=15)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _module_record(root: Path, relpath: str) -> dict[str, Any]:
    path = root / relpath
    try:
        return {"path": relpath, "file": str(path), "sha256": sha256_file(path)}
    except OSError:
        return {"path": relpath, "file": str(path), "sha256": None}


def _verify_binding(cwp_src: Path, et_root: Path, env: dict[str, str]) -> dict[str, Any]:
    """Child-import the supplied modules and confirm they resolve inside the
    supplied code roots (record the actual __file__ + SHA)."""
    script = (
        "import sys, json, hashlib, os;\n"
        "sys.path.insert(0, sys.argv[1]);\n"
        "import company_wiki, transcript_tool;\n"
        "def h(p):\n"
        "    return hashlib.sha256(open(p,'rb').read()).hexdigest()\n"
        "print(json.dumps({'company_wiki_file': company_wiki.__file__,\n"
        "                  'company_wiki_sha256': h(company_wiki.__file__),\n"
        "                  'transcript_tool_file': transcript_tool.__file__,\n"
        "                  'transcript_tool_sha256': h(transcript_tool.__file__)}))"
    )
    import os as _os
    child_env = dict(_os.environ)
    child_env["PYTHONPATH"] = str(cwp_src) + _os.pathsep + str(et_root)
    try:
        out = subprocess.run([sys.executable, "-B", "-c", script, str(et_root)],
                             capture_output=True, text=True, env=child_env, timeout=30,
                             cwd=str(et_root))
        data = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        return {"verified": False, "error": f"{type(exc).__name__}: {exc}"}
    cw_file = data.get("company_wiki_file") or ""
    tt_file = data.get("transcript_tool_file") or ""
    verified = (
        str(Path(cw_file).resolve()).startswith(str(cwp_src.resolve()))
        and str(Path(tt_file).resolve()).startswith(str(et_root.resolve()))
    )
    data["verified"] = verified
    return data


def _dependency(repository: str, root: Path, modules: list[dict[str, Any]]) -> Dependency:
    return Dependency(repository=repository, root=str(root), head=_git_head(root), modules=modules)


def _case_registry() -> list[tuple[str, Callable[[Context], CaseResult]]]:
    return [
        ("chainA_download_reuse", case_chain_a),
        ("fin_cn_annual_hit", lambda c: case_fin_local_hit(c, CN, "annual_report", 2024, "FY", "fin_cn_annual_hit")),
        ("fin_hk_semi_hit", lambda c: case_fin_local_hit(c, HK, "semi_annual_report", 2024, "S1", "fin_hk_semi_hit")),
        ("fin_us_quarterly_hit", lambda c: case_fin_local_hit(c, US, "quarterly_report", 2024, "Q1", "fin_us_quarterly_hit")),
        ("fin_hk_annual_fetch", lambda c: case_fin_fetch(c, HK, "annual_report", 2026, "fin_hk_annual_fetch")),
        ("nonperiod_prospectus", lambda c: case_nonperiod(c, US, "prospectus", "nonperiod_prospectus")),
        ("nonperiod_equity_offering", lambda c: case_nonperiod(c, US, "equity_offering_prospectus", "nonperiod_equity_offering")),
        ("nonperiod_convertible_bond", lambda c: case_nonperiod(c, US, "convertible_bond_prospectus", "nonperiod_convertible_bond")),
        ("nonperiod_investor_relations", lambda c: case_nonperiod(c, HK, "investor_relations", "nonperiod_investor_relations")),
        ("call_fy_only_no_q", case_call_fy_only),
        ("call_past_cutoff", case_call_past_cutoff),
        ("call_wrong_quarter", case_call_wrong_quarter),
        ("err_request_error", case_err_request),
        ("err_402_entitlement", case_err_402),
        ("err_missing_creds", case_err_missing_creds),
        ("err_unknown_usage", case_err_unknown_usage),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="w06-offline-contract-matrix")
    parser.add_argument("--cwp-project", type=Path, required=True)
    parser.add_argument("--et-project", type=Path, required=True)
    parser.add_argument("--owned-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    args = parser.parse_args(argv)

    ff_root = HERE.parent.parent          # tools/offline_contract_matrix -> worktree root
    cwp_root = args.cwp_project.resolve()
    et_root = args.et_project.resolve()
    owned_root = args.owned_root.resolve()
    out_root = args.out_root.resolve()
    owned_root.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)

    # Pre-placed sentinel + production baseline before any work.
    sentinel = owned_root / SENTINEL_NAME
    sentinel.write_bytes(SENTINEL_CONTENT)
    guard = ProductionGuard(ff_root, cwp_root, et_root)

    scratch = owned_root / "scratch"
    if scratch.exists():
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)

    ctx = Context(ff_root=ff_root, cwp_root=cwp_root, et_root=et_root,
                  scratch=scratch, out_root=out_root)
    binding = _verify_binding(cwp_root / "src", et_root, ctx.child_env())

    start = time.monotonic()
    results: list[CaseResult] = []
    seed_all(ctx)
    for case_id, runner in _case_registry():
        case_start = time.monotonic()
        try:
            result = runner(ctx)
        except Exception as exc:  # noqa: BLE001 — keep partial, never crash the batch
            result = CaseResult(
                id=case_id, title=case_id, declared_layer="unknown",
                observed_layer="error", result="FAIL",
                scope="case raised", actual={"error": f"{type(exc).__name__}: {exc}"},
                diagnostics=[f"case raised {type(exc).__name__}: {exc}"],
            )
        elapsed = time.monotonic() - case_start
        result.diagnostics.append(f"elapsed_seconds={elapsed:.2f}")
        if elapsed > CASE_TIMEOUT:
            result.diagnostics.append(f"WARN case exceeded {CASE_TIMEOUT}s budget")
        results.append(result)
    batch_elapsed = time.monotonic() - start

    # Restore checks: production bytes unchanged + sentinel intact.
    after = guard.snapshot()
    baseline_unchanged = guard.unchanged(after)
    sentinel_ok = sentinel.is_file() and sentinel.read_bytes() == SENTINEL_CONTENT
    # Tear down scratch (owned), keep report + artifacts.
    scratch_restored = True
    try:
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)
        scratch_restored = not scratch.exists()
    except Exception:  # noqa: BLE001
        scratch_restored = False
    restore = {
        "baseline_unchanged": baseline_unchanged,
        "sentinel_intact": sentinel_ok,
        "scratch_torn_down": scratch_restored,
        "restored": bool(baseline_unchanged and sentinel_ok and scratch_restored),
    }

    # Cost ledger: real charge is 0; fixture requests listed separately.
    fixture_total = sum((r.provider_counters.get("fixture_requests") or 0) for r in results)
    cost = {
        "real_provider_calls": 0, "paid_usd": 0, "unknown_charge": None,
        "fixture_requests": fixture_total,
        "note": "fixture requests are offline synthetic and excluded from the real-cost ledger",
    }
    scope = {
        "network": "all real HTTP refused; only in-process fixture responses",
        "downloads": "synthetic valid PDF/HTML/TXT originals, metadata marked synthetic",
        "translation": "0 (TranslatorFactory never constructed)",
        "caveat": "offline synthetic run proves contract wiring only; it does not prove "
                  "external reachability, real supplier completeness, or economic quality",
        "batch_elapsed_seconds": round(batch_elapsed, 2),
    }

    deps = [
        _dependency("ff", ff_root, [
            _module_record(ff_root, "scripts/fetch_filing.py"),
            _module_record(ff_root, "scripts/transcript_tool_transport.py"),
            _module_record(ff_root, "scripts/transcript_companion.py"),
        ]),
        _dependency("cwp", cwp_root, [
            _module_record(cwp_root, "src/company_wiki/source_catalog/source_reader.py"),
            _module_record(cwp_root, "src/company_wiki/source_catalog/service.py"),
            _module_record(cwp_root, "src/company_wiki/source_catalog/config.py"),
        ]),
        _dependency("et", et_root, [
            _module_record(et_root, "transcript_tool.py"),
            _module_record(et_root, "transcript_api.py"),
            _module_record(et_root, "retrieval_runtime.py"),
        ]),
    ]

    report = build_report(dependencies=deps, cases=results, cost=cost,
                          scope=scope, restore=restore)
    report["code_binding"] = binding

    findings = oracle_mod.audit(report)
    report["oracle"] = {"findings": [f.to_dict() for f in findings],
                        "pass": oracle_mod.passes(findings)}

    emit(report, out_root / "report.json")
    (out_root / "restore.json").write_text(json.dumps(restore, indent=2), encoding="utf-8")

    # Concise console summary.
    counts = {"PASS": 0, "FAIL": 0, "NOT_RUN": 0}
    for r in results:
        counts[r.result] = counts.get(r.result, 0) + 1
    print(f"cases: {counts}  batch_elapsed={batch_elapsed:.1f}s")
    print(f"oracle: {'PASS' if not findings else 'FAIL'} findings={len(findings)}")
    for f in findings:
        print(f"  [{f.vector}] {f.case_id}: {f.detail}")
    print(f"report: {out_root / 'report.json'}")
    # Exit non-zero if the oracle flags any failure vector or any case FAILED.
    hard_fail = bool(findings) or counts.get("FAIL", 0) > 0
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
