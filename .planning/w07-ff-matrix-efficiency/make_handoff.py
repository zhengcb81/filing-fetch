"""Generate docs/handoffs/w07-ff-matrix-efficiency/handoff.json (run once)."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


inputs = json.load(open(ROOT / ".planning/w07-ff-matrix-efficiency/INPUTS.json", encoding="utf-8"))
changed = [
    ("tools/offline_contract_matrix/runtime.py",
     "measured launch log; MAX_PATH-safe short-path bytecode cache; child reaping on any error"),
    ("tools/offline_contract_matrix/run.py",
     "proof reserve inside unchanged 30/180 budget; single-helper seed batch; ff_cli timing; per-group artifact prefix; env reuse"),
    ("tools/offline_contract_matrix/cli_main.py",
     "phase timing + launch accounting; truthful dependency provenance; cache-warming binding probe; 2 isolated worker groups; final-proof scheduling"),
    ("tools/offline_contract_matrix/measurement.py",
     "new PhaseTimer/launch_report/merge/cache_stats helpers"),
    ("tools/offline_contract_matrix/seed_batch.py",
     "new bounded single-process sequential real CWP ensure writer"),
    ("tools/offline_contract_matrix/matrix_cases.py",
     "seed_all only; all other handler ASTs byte-equal to case-handler-baseline.json"),
    ("tests/test_w07_matrix_efficiency.py",
     "new W07 focused suite: 18 tests (scheduling REDs, measurement contract, isolation)"),
]
changed_rows = [{"path": p, "purpose": why, "sha256": sha(ROOT / p), "bytes": (ROOT / p).stat().st_size}
                for p, why in changed]

readonly_rows = [{"path": r["path"], "sha256": r["sha256"], "verified": True} for r in inputs["readonly_code"]]
for rel in ("input/case-handler-baseline.json", "input/dependency-manifest.json"):
    readonly_rows.append({
        "path": ".planning/w07-ff-matrix-efficiency/" + rel,
        "sha256": sha(ROOT / (".planning/w07-ff-matrix-efficiency/" + rel)),
        "verified": True,
    })
et_commit = "d0ac42c60dcca992db78860b8469cfed3dd527e5"
et_root = ROOT / ".planning/w07-ff-matrix-efficiency/input/runtime/et"
for rel in ("tests/__init__.py", "tests/test_retrieval_runtime.py", "tests/test_transcript_api.py"):
    readonly_rows.append({
        "path": "input-repair et@" + et_commit + "/" + rel,
        "sha256": sha(et_root / rel),
        "verified": True,
        "note": "rebuilt via git archive at the manifest-fixed commit (card-authorized); blob-identical",
    })

persist = sum(p.stat().st_size for p in (ROOT / "docs/handoffs/w07-ff-matrix-efficiency").rglob("*") if p.is_file())
handoff = {
    "schema": "w07-lane-handoff/1",
    "lane": "W07-FF-PERF",
    "status": "COMPLETE",
    "repository": "C:\\Users\\\u90d1\u66fe\u6ce2\\Projects\\filing-fetch",
    "workdir": "C:\\Users\\\u90d1\u66fe\u6ce2\\Projects\\_harness_worktrees\\w07\\ff-matrix-efficiency",
    "branch": "codex/w07-ff-matrix-efficiency",
    "base_commit": "2d380a054c658ce3b5f0763523e49a0ab34acf78",
    "implementation_commit": "b20a714",
    "changed_files": changed_rows,
    "readonly_inputs": readonly_rows,
    "interfaces": [
        {"name": "tools/offline_contract_matrix/run.py CLI (4 required args)",
         "compatibility": "before/after identical; optional --workers 1..2 added (default 2)"},
        {"name": "report schema ff-et-cwp-offline-matrix/1",
         "compatibility": "additive only: scope.phase_timing/launch_accounting/bytecode_cache/workers, dependency head_origin/source_commit; case/oracle fields unchanged"},
        {"name": "CaseSpec/RunSpec/oracle.py/matrix_outcome.py/source_proofs.py",
         "compatibility": "unchanged (manifest-locked read-only)"},
        {"name": "Context (run.py)",
         "compatibility": "constructor kwargs backward compatible; new optional artifact_prefix/pycache_root; request/response/expectation semantics unchanged"},
        {"name": "seed helper tools/offline_contract_matrix/seed_batch.py",
         "compatibility": "new internal helper; per-request receipt shape documented in warm-seed-receipts.*.json"},
    ],
    "tests": [
        {"node": "A", "command": "python -B -m pytest -q tests/test_w07_matrix_efficiency.py",
         "exit_code": 1, "counts": {"failed": 13, "passed": 1}, "seconds": 1.21,
         "evidence": "RED record: seed_all 10 launches; leaked child; nested-git misreport; starved proof; missing phase timing"},
        {"node": "B", "command": "python -B -m pytest -q tests/test_w07_matrix_efficiency.py",
         "exit_code": 0, "counts": {"passed": 18}, "seconds": 0.81,
         "evidence": "final focused suite"},
        {"node": "B", "command": "python -B -m pytest -q tests/test_w06_contract_matrix.py tests/test_w06_matrix_runtime.py tests/test_w06_case_authority.py",
         "exit_code": 0, "counts": {"passed": 195}, "seconds": 5.88,
         "evidence": "existing matrix runtime/seed/case-authority expectations unchanged"},
        {"node": "C", "command": "python -B tools/offline_contract_matrix/run.py --cwp-project .planning/w07-ff-matrix-efficiency/input/runtime/cwp --et-project .planning/w07-ff-matrix-efficiency/input/runtime/et --owned-root .tmp/w07-a6 --out-root .tmp/w07-b6",
         "exit_code": 0,
         "counts": {"PASS": 41, "FAIL": 0, "PARTIAL": 0, "NOT_RUN": 0, "oracle_findings": 0,
                    "fresh_proofs_verified": 26},
         "seconds": 90.29, "evidence": "evidence/final-41-report.json"},
    ],
    "issues": [
        {"root_cause": "PYTHONPYCACHEPREFIX mirror paths exceeded Windows MAX_PATH (260): CPython silently skipped producer .pyc writes and every FF->CWP/ET child recompiled the full trees (compile() x122 per launch, 274-char cache path not written)",
         "evidence": "evidence/timing-before-after.json; evidence/first-run-failure-report.json scope.bytecode_cache",
         "scope": "all ~270 multi-layer child launches",
         "resolution": "fixed: short attempt-sibling cache root + 8.3 short code roots + cache-warming binding probe; measured max_pyc_path_len 252, company_wiki_pyc 98 (all imported modules)"},
        {"root_cause": "seed_all launched 10 independent CWP CLI ensures (full interpreter+import each)",
         "evidence": "A-node RED: 10 warm_seed launches",
         "scope": "batch preparation",
         "resolution": "fixed: one bounded seed_batch helper sequentially calling the same real ensure service; per-request request/response/receipt/source-ref/count records kept"},
        {"root_cause": "case work could consume the whole 180s batch deadline so the mandatory final fresh source proof never launched (0 attempts) and oracle downgraded PASS to PARTIAL",
         "evidence": "card failure records 2PASS/31PARTIAL/8NOT_RUN and 1PASS/27PARTIAL/13NOT_RUN; A-node starvation RED",
         "scope": "batch tail + all proof-dependent cases",
         "resolution": "fixed: case window capped at batch.end-10s reserve; 30s/case and 180s/batch values/starts unchanged; proof runs after all changes"},
        {"root_cause": "run_process leaked the child on non-timeout transport errors",
         "evidence": "A-node RED (killed=False)",
         "scope": "any unexpected error path",
         "resolution": "fixed: any exception kills/reaps the process tree"},
        {"root_cause": "dependency record reported the parent FF worktree HEAD for nested gitless code-only snapshots",
         "evidence": "A-node nested-gitless counterexample",
         "scope": "cwp/et dependency rows",
         "resolution": "fixed: HEAD only when git toplevel == root; otherwise unknown + manifest source commit kept separate from module binding"},
        {"root_cause": "prepared input/runtime/et lacked the tests/test_retrieval_runtime.py private launcher seam the harness ET proxy imports (manifest listed only 19 top-level modules)",
         "evidence": "ModuleNotFoundError probe; dependency-manifest files list",
         "scope": "chain A / all ff+et cases",
         "resolution": "fixed as card-authorized rebuild: 3 files exported via git cat-file blob at fixed commit d0ac42c6 (blob-identical); recorded in readonly_inputs"},
        {"root_cause": "workstation load swings single-process cost 2-3x (ff_hit 1.55s vs 5.43s), so sequential full batches landed 159.5-173.6s (only one of three inside budget)",
         "evidence": "evidence/timing-before-after.json; interim runs .tmp/w07-b2..b5",
         "scope": "whole batch variance",
         "resolution": "mitigated: cache warm-up plus 2 isolated worker groups (measured necessary); final run 90.29s leaves ~90s headroom. Residual: sustained-load hosts should read scope.phase_timing"},
    ],
    "cleanup": {
        "baseline": "owned roots .tmp/w07-a6 (absent) and .tmp/w07-b6 (absent) recorded before run",
        "final": ".tmp/w07-b6/attempt-b316b130a9fc43e8a1ec2a5c0c51e2ac (retained report/restore/proofs); .tmp/w07-a6 restored absent",
        "restored": True,
        "nonowned_preserved": True,
        "detail": "restore.json: scratch_torn_down + bytecode_cache_torn_down + production_metadata_unchanged all true",
    },
    "cost": {"real_provider_calls": 0, "real_llm_calls": 0, "dollars": 0,
             "synthetic_fixture_requests": 42,
             "synthetic_scope": "fixture provider boundary only; producer unknown usage stays null"},
    "space": {"persist_bytes": persist, "scratch_peak_bytes": None},
    "source_truth_verified": False,
    "economic_reasonableness": "not_evaluated",
    "residuals": [
        "cache mirror paths reach 252 chars (limit 260): deeper modules could still skip caching on longer installs",
        "sustained host load inflates per-process cost 2-3x; scope.phase_timing/launch_accounting identify the slowest phase if a rerun overruns",
        "FF/ET production fixes and mainline release remain ROOT scope",
    ],
    "root_next_action": "receive/integrate",
}
out = ROOT / "docs/handoffs/w07-ff-matrix-efficiency/handoff.json"
out.write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding="utf-8")
(ROOT / ".planning/w07-ff-matrix-efficiency/changed_files.json").write_text(
    json.dumps(changed_rows, indent=2), encoding="utf-8")
print("handoff.json written; persist bytes:", persist, "readonly entries:", len(readonly_rows))
