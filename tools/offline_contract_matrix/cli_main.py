"""Offline manual FF -> ET -> CWP matrix. Exit 0 requires complete measured proof."""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run import Context, ProductionGuard, CASE_TIMEOUT, BATCH_DEADLINE  # noqa: E402
from runtime import Deadline, DeadlineExceeded, OwnedAttempt, run_process, guard_events  # noqa: E402
from matrix_cases import seed_all  # noqa: E402
from report import CaseResult, Dependency, build_report, emit, sha256_file  # noqa: E402
from matrix_outcome import source_ref  # noqa: E402
import oracle as oracle_mod  # noqa: E402


def _module_record(root: Path, relpath: str) -> dict[str, Any]:
    path = root / relpath
    return {"path":relpath, "file":str(path), "sha256":sha256_file(path) if path.is_file() else None}


def _dependency(repository: str, root: Path, modules: list[dict], *, env=None, deadline=None, cwd=None) -> Dependency:
    head = "unknown"
    try:
        proc = run_process(["git", "-C", str(root), "rev-parse", "HEAD"], env=env or {},
                           cwd=cwd or HERE, deadline=deadline or Deadline(5))
        if proc.returncode == 0:
            head = proc.stdout.decode("utf-8").strip()
    except Exception:
        pass
    return Dependency(repository=repository, root=str(root), head=head, modules=modules)


def _verify_binding(cwp_src: Path, et_root: Path, env: dict[str, str], *, deadline=None, cwd=None) -> dict:
    script = '''import json, hashlib, company_wiki, transcript_tool
def record(m):
    return {"file":m.__file__, "sha256":hashlib.sha256(open(m.__file__,"rb").read()).hexdigest()}
print(json.dumps({"company_wiki":record(company_wiki), "transcript_tool":record(transcript_tool)}))'''
    try:
        proc = run_process([sys.executable, "-B", "-c", script], env=env, cwd=cwd or HERE,
                           deadline=deadline or Deadline(30))
        data = json.loads(proc.stdout.decode("utf-8").strip().splitlines()[-1])
        expected = {"company_wiki":cwp_src / "company_wiki/__init__.py", "transcript_tool":et_root / "transcript_tool.py"}
        data["verified"] = proc.returncode == 0 and all(
            Path(data[k]["file"]).resolve() == v.resolve() and data[k]["sha256"] == sha256_file(v)
            for k, v in expected.items())
        return data
    except Exception as exc:
        return {"verified":False, "error":f"{type(exc).__name__}: {exc}"}


def _case_registry() -> list[tuple[str, Callable[[Context], CaseResult]]]:
    from case_specs import case_specs
    return [(spec.id, spec.execute) for spec in case_specs()]


def _fresh_proofs(ctx: Context) -> dict:
    refs = []
    for traces in ctx.traces.values():
        for trace in traces:
            for key in ("filing", "transcript"):
                ref = source_ref((trace.get("response", {}).get(key) or {}).get("source_ref"))
                if ref:
                    refs.append(ref)
    proc = run_process([sys.executable, "-B", str(HERE / "source_proofs.py")],
                       input=json.dumps({"wiki":str(ctx.env.wiki), "refs":refs}).encode("utf-8"),
                       env=ctx.child_env(), cwd=ctx.scratch, deadline=ctx.batch_deadline)
    path = ctx.artifacts / "fresh-source-proofs.json"
    path.write_bytes(proc.stdout)
    (ctx.artifacts / "fresh-source-proofs.stderr.txt").write_bytes(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"fresh verified reader failed: {proc.stderr.decode('utf-8', errors='replace')[:1000]}")
    return json.loads(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="w06-offline-contract-matrix")
    for name in ("cwp-project", "et-project", "owned-root", "out-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    start = time.monotonic()
    deadline = Deadline(BATCH_DEADLINE)
    ff_root, cwp_root, et_root = HERE.parent.parent, args.cwp_project.resolve(), args.et_project.resolve()
    guard = ProductionGuard(ff_root, cwp_root, et_root)
    protected = tuple(root / child for root in (ff_root, cwp_root, et_root) for child in ("config", "companies", "src", "scripts", "transcripts"))
    attempt = OwnedAttempt.create(args.owned_root, args.out_root, protected)
    results, binding, proofs, deps, events = [], {"verified":False}, {}, [], []
    registry = _case_registry()
    ctx = None
    error = None
    try:
        ctx = Context(ff_root=ff_root, cwp_root=cwp_root, et_root=et_root,
                      scratch=attempt.scratch, out_root=attempt.output, deadline=deadline)
        env = ctx.child_env()
        binding = _verify_binding(cwp_root / "src", et_root, env, deadline=deadline, cwd=attempt.scratch)
        if not binding.get("verified"):
            raise RuntimeError("producer code binding is unverified")
        for repo, root, modules in (
            ("ff", ff_root, ["scripts/fetch_filing.py", "scripts/transcript_tool_transport.py", "scripts/transcript_companion.py"]),
            ("cwp", cwp_root, ["src/company_wiki/source_catalog/source_reader.py", "src/company_wiki/source_catalog/service.py", "src/company_wiki/source_catalog/config.py"]),
            ("et", et_root, ["transcript_tool.py", "transcript_api.py", "retrieval_runtime.py"]),
        ):
            deps.append(_dependency(repo, root, [_module_record(root, p) for p in modules], env=env, deadline=deadline, cwd=attempt.scratch))
        seed_all(ctx)
        for cid, runner in registry:
            case_start = time.monotonic()
            try:
                ctx.begin_case()
                from case_specs import get_spec
                ctx.active_case_spec = get_spec(cid)
                result = runner(ctx)
                errors = ctx.active_case_spec.metadata_errors(result.to_dict())
                if errors:
                    raise ValueError("case runner contract drift: " + "; ".join(errors))
            except DeadlineExceeded as exc:
                result = CaseResult(id=cid, title=cid, declared_layer="unknown", result="PARTIAL", actual={"error":str(exc)})
            except Exception as exc:
                result = CaseResult(id=cid, title=cid, declared_layer="unknown", result="FAIL", actual={"error":f"{type(exc).__name__}: {exc}"})
            from case_specs import get_spec
            spec = get_spec(cid)
            result.declared_layer, result.scope, result.expected = spec.declared_layer, spec.scope, spec.expected()
            elapsed = time.monotonic() - case_start
            result.actual["elapsed_seconds"] = round(elapsed, 4)
            result.actual["runs"] = ctx.traces.get(cid, [])
            traces = result.actual["runs"]
            result.provider_counters["fixture_requests"] = sum(t["fixture_requests"] for t in traces)
            if result.expected.get("run_twice"):
                result.provider_counters["run2_fixture_requests"] = traces[1]["fixture_requests"] if len(traces) >= 2 else None
            if elapsed > CASE_TIMEOUT:
                result.result = "PARTIAL"
                result.diagnostics.append("absolute case deadline exceeded; no PASS")
            results.append(result)
            if time.monotonic() >= deadline.end:
                break
        proofs = _fresh_proofs(ctx)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if ctx is not None:
            events = guard_events(attempt.scratch)
            (attempt.output / "guard-events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
        after = guard.snapshot()
        restore = attempt.cleanup()
        restore["production_metadata_unchanged"] = guard.unchanged(after)
        restore["restored"] &= restore["production_metadata_unchanged"]
    observed = {r.id for r in results}
    for cid, _ in registry:
        if cid not in observed:
            from case_specs import get_spec
            spec = get_spec(cid)
            results.append(CaseResult(id=cid, title=cid, declared_layer=spec.declared_layer, scope=spec.scope, expected=spec.expected(), result="NOT_RUN", diagnostics=[error or "batch deadline exhausted"]))
    elapsed = time.monotonic() - start
    cost = {"real_provider_calls":0 if events and not any(e["op"] == "network_denied" for e in events) else None,
            "paid_usd":0 if events else None, "unknown_charge":None,
            "fixture_requests":sum(r.provider_counters.get("fixture_requests", 0) for r in results if isinstance(r.provider_counters.get("fixture_requests"), int)),
            "fixture_counter_scope":"observed local fixture GETs only; producer unknown usage stays null"}
    scope = {"batch_elapsed_seconds":round(elapsed, 4), "case_limit_seconds":CASE_TIMEOUT,
             "network_guard_boots":sum(e["op"] == "guard_boot" for e in events),
             "network_attempts_denied":sum(e["op"] == "network_denied" for e in events),
             "translation_attempts":sum(e["op"] == "translation_attempt" for e in events),
             "provider_boundary":"fixture response only; real supplier reachability/coverage is not proven",
             "error":error, "production_baseline_scope":"stat only; no real key/config bytes read or hashed"}
    report = build_report(dependencies=deps, cases=results, cost=cost, scope=scope, restore=restore)
    report.update({"code_binding":binding, "required_cases":[c for c, _ in registry],
                   "evidence_root":str(attempt.output / "artifacts"), "source_proofs":proofs})
    findings = oracle_mod.audit(report)
    # Unmeasured downstream evidence cannot leave a base predicate labelled PASS.
    missing = {f.case_id for f in findings if f.vector in {"source_bytes_not_verified", "missing_bound_evidence", "invalid_bound_evidence"}}
    for case in report["cases"]:
        if case["id"] in missing and case["result"] == "PASS":
            case["result"] = "PARTIAL"
            case["diagnostics"].append("fresh byte/evidence verification did not close; base predicate alone is insufficient")
    by_id = {c["id"]:c["result"] for c in report["cases"]}
    for result in results:
        result.result = by_id[result.id]
    report["oracle"] = {"pass":not findings, "findings":[f.to_dict() for f in findings]}
    emit(report, attempt.output / "report.json")
    (attempt.output / "restore.json").write_text(json.dumps(restore, indent=2), encoding="utf-8")
    counts = {kind:sum(r.result == kind for r in results) for kind in ("PASS", "FAIL", "PARTIAL", "NOT_RUN")}
    print(f"cases: {counts}; seconds={elapsed:.2f}; oracle findings={len(findings)}")
    print(f"report: {attempt.output / 'report.json'}")
    return 0 if results and all(r.result == "PASS" for r in results) and not findings and not error else 1


if __name__ == "__main__":
    raise SystemExit(main())
