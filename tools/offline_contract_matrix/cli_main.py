"""Offline manual FF -> ET -> CWP matrix. Exit 0 requires complete measured proof."""
from __future__ import annotations
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run import (  # noqa: E402
    Context, ProductionGuard, CASE_TIMEOUT, BATCH_DEADLINE, PROOF_RESERVE_SECONDS,
)
from runtime import Deadline, DeadlineExceeded, OwnedAttempt, run_process, guard_events  # noqa: E402
from matrix_cases import seed_all  # noqa: E402
from measurement import (  # noqa: E402
    PhaseTimer, merge_launch_reports, launch_report, cache_stats,
)
from report import CaseResult, Dependency, build_report, emit, sha256_file  # noqa: E402
from matrix_outcome import source_ref  # noqa: E402
import oracle as oracle_mod  # noqa: E402

# Measured need (three timed full batches: 159.5/173.6/171.2s sequential) allows
# at most two concurrent workers; each group owns an independent Context/wiki/
# proxy/counters and a whole download->reuse case chain runs in one group.
WORKERS = 2


def _module_record(root: Path, relpath: str) -> dict[str, Any]:
    path = root / relpath
    return {"path":relpath, "file":str(path), "sha256":sha256_file(path) if path.is_file() else None}


class DependencyRecord(Dependency):
    """Dependency with truthful provenance fields.

    ``report.py`` is read-only tooling; the W07 provenance fields (git toplevel
    ownership vs the fixed manifest source commit) are attached here instead.
    """

    def __init__(self, repository: str, root: str, head: str, modules: list | None = None,
                 *, head_origin: str = "unknown", source_commit: str | None = None):
        super().__init__(repository=repository, root=root, head=head, modules=modules or [])
        self.head_origin = head_origin
        self.source_commit = source_commit

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["head_origin"] = self.head_origin
        data["source_commit"] = self.source_commit
        return data


def _manifest_source_commits(ff_root: Path) -> dict[str, str]:
    """Fixed source commits from this package's dependency manifest (reporting only)."""
    path = ff_root / ".planning" / "w07-ff-matrix-efficiency" / "input" / "dependency-manifest.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return {name: (row or {}).get("commit") for name, row in (data.get("dependencies") or {}).items()}


def _dependency(repository: str, root: Path, modules: list[dict], *, env=None, deadline=None,
                cwd=None, source_commit: str | None = None) -> Dependency:
    """Record git provenance truthfully.

    A code-only snapshot nested inside another worktree has no git identity of
    its own: ``git -C`` would walk up and report the PARENT worktree HEAD. Only
    report a HEAD when the git toplevel equals the supplied root; otherwise
    ``head`` stays unknown and the fixed manifest ``source_commit`` is the
    provenance record. This is report truthfulness, not a new identity gate.
    """
    head, origin = "unknown", "unknown"
    try:
        proc = run_process(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                           env=env or {}, cwd=cwd or HERE, deadline=deadline or Deadline(5))
        if proc.returncode == 0:
            toplevel = Path(proc.stdout.decode("utf-8").strip()).resolve()
            if toplevel == root.resolve():
                origin = "git_toplevel_match"
                head_proc = run_process(["git", "-C", str(root), "rev-parse", "HEAD"],
                                        env=env or {}, cwd=cwd or HERE, deadline=deadline or Deadline(5))
                head = head_proc.stdout.decode("utf-8").strip() if head_proc.returncode == 0 else "unknown"
            else:
                head, origin = "unknown", "unknown_nested_snapshot"
    except Exception:
        pass
    return DependencyRecord(repository=repository, root=str(root), head=head, modules=modules,
                            head_origin=origin, source_commit=source_commit)


def _verify_binding(cwp_src: Path, et_root: Path, env: dict[str, str], *, deadline=None, cwd=None) -> dict:
    # The extra imports warm the shared bytecode cache for every hot producer
    # entry point in ONE process before the worker groups start, so concurrent
    # groups never double-compile the same trees (W07 measurement).
    script = '''import json, hashlib, company_wiki, transcript_tool
import company_wiki.source_catalog.cli, company_wiki.source_catalog.source_query_cli
import tests.test_retrieval_runtime, tests.test_transcript_api
def record(m):
    return {"file":m.__file__, "sha256":hashlib.sha256(open(m.__file__,"rb").read()).hexdigest()}
print(json.dumps({"company_wiki":record(company_wiki), "transcript_tool":record(transcript_tool)}))'''
    try:
        proc = run_process([sys.executable, "-c", script], env=env, cwd=cwd or HERE,
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
    proc = run_process([sys.executable, str(HERE / "source_proofs.py")],
                       input=json.dumps({"wiki":str(ctx.env.wiki), "refs":refs}).encode("utf-8"),
                       env=ctx.child_env(), cwd=ctx.scratch, deadline=ctx.batch_deadline)
    prefix = getattr(ctx, "artifact_prefix", "")
    path = ctx.artifacts / f"{prefix}fresh-source-proofs.json"
    path.write_bytes(proc.stdout)
    (ctx.artifacts / f"{prefix}fresh-source-proofs.stderr.txt").write_bytes(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"fresh verified reader failed: {proc.stderr.decode('utf-8', errors='replace')[:1000]}")
    return json.loads(proc.stdout)


def _merge_source_proofs(target: dict, part: dict, group: str) -> None:
    """Retain every owned wiki proof; a later group cannot hide an earlier failure.

    Legacy oracle consumes a flat document-ID map. Its projection is conservative
    for collisions: every group's proof must verify and agree on the byte/version
    facts. Full unmodified worker proof records remain available alongside it.
    """
    groups = target.setdefault("worker_groups", {})
    if group in groups:
        raise ValueError(f"duplicate worker proof group: {group}")
    groups[group] = part
    merged = target.setdefault("proofs", {})
    for key, row in (part.get("proofs") or {}).items():
        previous = merged.get(key)
        if previous is None:
            merged[key] = dict(row)
        else:
            facts = ("content_sha256", "byte_size", "source_versions",
                     "physical_originals", "document_kind", "original_language_content_sha256")
            agrees = all(previous.get(f) == row.get(f) for f in facts)
            combined = dict(previous)
            combined["verified"] = previous.get("verified") is True and row.get("verified") is True and agrees
            combined["worker_collision"] = True
            if not combined["verified"]:
                combined["error"] = "worker proof collision includes a failed or incompatible verification"
            merged[key] = combined
    target.setdefault("catalog_snapshot", []).extend(part.get("catalog_snapshot") or [])


def run_case_group(ctx: Context, entries: list[tuple[int, tuple[str, Callable]]],
                   deadline: Deadline) -> tuple[list[tuple[int, CaseResult]], str | None]:
    """One concurrent worker group: own wiki/seeds/proxy/counters.

    The absolute batch deadline is shared and never reset; every download ->
    reuse case chain stays whole inside one group; the final fresh source proof
    runs only after all groups joined (by the caller).
    """
    from case_specs import get_spec

    done: list[tuple[int, CaseResult]] = []
    stop_reason = None
    phases = getattr(ctx, "phases", None)
    if phases is not None:
        with phases.span("seed"):
            seed_all(ctx)
    else:
        seed_all(ctx)
    for pos, (cid, runner) in entries:
        # The final fresh source proof is mandatory: case work may not spend
        # the reserved tail of the unchanged single batch deadline.
        if time.monotonic() >= deadline.end - PROOF_RESERVE_SECONDS:
            stop_reason = (
                f"final-proof reserve preserved ({PROOF_RESERVE_SECONDS}s of the single "
                "batch deadline); remaining cases kept NOT_RUN instead of starving the proof")
            break
        case_start = time.monotonic()
        try:
            ctx.begin_case()
            ctx.active_case_spec = get_spec(cid)
            result = runner(ctx)
            errors = ctx.active_case_spec.metadata_errors(result.to_dict())
            if errors:
                raise ValueError("case runner contract drift: " + "; ".join(errors))
        except DeadlineExceeded as exc:
            result = CaseResult(id=cid, title=cid, declared_layer="unknown", result="PARTIAL", actual={"error":str(exc)})
        except Exception as exc:
            result = CaseResult(id=cid, title=cid, declared_layer="unknown", result="FAIL", actual={"error":f"{type(exc).__name__}: {exc}"})
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
        done.append((pos, result))
        if time.monotonic() >= deadline.end:
            break
    return done, stop_reason


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="w06-offline-contract-matrix")
    for name in ("cwp-project", "et-project", "owned-root", "out-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=range(1, WORKERS + 1), default=WORKERS,
                        help="concurrent worker groups (each owns an independent wiki/proxy)")
    args = parser.parse_args(argv)
    workers = args.workers
    start = time.monotonic()
    deadline = Deadline(BATCH_DEADLINE)
    ff_root, cwp_root, et_root = HERE.parent.parent, args.cwp_project.resolve(), args.et_project.resolve()
    guard = ProductionGuard(ff_root, cwp_root, et_root)
    protected = tuple(root / child for root in (ff_root, cwp_root, et_root) for child in ("config", "companies", "src", "scripts", "transcripts"))
    attempt = OwnedAttempt.create(args.owned_root, args.out_root, protected)
    results, binding, proofs, deps, events = [], {"verified":False}, {"proofs": {}, "catalog_snapshot": []}, [], []
    registry = []
    ctxs = []
    error = None
    stop_reason = None
    timer = PhaseTimer()
    cache_info = {"pyc_files": 0, "company_wiki_pyc": 0, "max_pyc_path_len": None}
    accounting = {"launches": {"total_boot": 0, "total_exit": 0, "by_kind": {},
                               "parent_calls": {}, "parent_launch_total": 0},
                  "child_spans": {}}
    try:
        registry = _case_registry()
        env = None
        for index in range(workers):
            ctxs.append(Context(ff_root=ff_root, cwp_root=cwp_root, et_root=et_root,
                                scratch=attempt.scratch / f"g{index + 1}",
                                out_root=attempt.output, deadline=deadline,
                                artifact_prefix=f"g{index + 1}.",
                                pycache_root=attempt.cache))
        env = ctxs[0].child_env()
        timer.count_launch("binding_probe")
        with timer.span("binding"):
            binding = _verify_binding(cwp_root / "src", et_root, env, deadline=deadline, cwd=ctxs[0].scratch)
        if not binding.get("verified"):
            raise RuntimeError("producer code binding is unverified")
        source_commits = _manifest_source_commits(ff_root)
        for repo, root, modules in (
            ("ff", ff_root, ["scripts/fetch_filing.py", "scripts/transcript_tool_transport.py", "scripts/transcript_companion.py"]),
            ("cwp", cwp_root, ["src/company_wiki/source_catalog/source_reader.py", "src/company_wiki/source_catalog/service.py", "src/company_wiki/source_catalog/config.py"]),
            ("et", et_root, ["transcript_tool.py", "transcript_api.py", "retrieval_runtime.py"]),
        ):
            timer.count_launch("git")
            deps.append(_dependency(repo, root, [_module_record(root, p) for p in modules], env=env,
                                    deadline=deadline, cwd=ctxs[0].scratch,
                                    source_commit=source_commits.get(repo)))
        # Independent worker groups: each seeds its own wiki and runs a disjoint
        # slice of the fixed case registry under the one shared deadline.
        entries = list(enumerate(registry))
        groups = [entries[index::workers] for index in range(workers)]
        done_by_pos: dict[int, CaseResult] = {}
        stops = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run_case_group, ctxs[index], groups[index], deadline)
                       for index in range(workers)]
            for future in futures:
                done, group_stop = future.result()
                done_by_pos.update(dict(done))
                if group_stop:
                    stops.append(group_stop)
        results = [done_by_pos[pos] for pos in sorted(done_by_pos)]
        stop_reason = "; ".join(dict.fromkeys(stops)) or None
        # The mandatory final fresh source proof runs AFTER all groups joined and
        # after every change, once per owned wiki, merged into one proof record.
        timer.count_launch("fresh_source_proof", workers)
        with timer.span("fresh_source_proof"):
            for index, ctx in enumerate(ctxs):
                part = _fresh_proofs(ctx)
                _merge_source_proofs(proofs, part, f"g{index + 1}")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            for ctx in ctxs:
                phases = getattr(ctx, "phases", None)
                if phases is not None:
                    timer.merge(phases)
            cache_info = cache_stats(attempt.cache)
            accounting = merge_launch_reports(
                [launch_report(attempt.scratch / f"g{index + 1}" / "launches.jsonl")
                 for index in range(workers)])
            parent_calls = timer.launch_counts()
            accounting["launches"]["parent_calls"] = parent_calls
            accounting["launches"]["parent_launch_total"] = sum(parent_calls.values())
            for phase, entry in accounting["child_spans"].items():
                if entry.get("status") == "measured":
                    timer.record(phase, entry["seconds"])
                else:
                    timer.mark_unknown(phase, entry.get("reason") or "nested child span unobserved")
            events = []
            for index in range(workers):
                events.extend(guard_events(attempt.scratch / f"g{index + 1}"))
            (attempt.output / "guard-events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")
        finally:
            with timer.span("cleanup"):
                after = guard.snapshot()
                restore = attempt.cleanup()
                restore["production_metadata_unchanged"] = guard.unchanged(after)
                restore["restored"] &= restore["production_metadata_unchanged"]
    observed = {r.id for r in results}
    for cid, _ in registry:
        if cid not in observed:
            from case_specs import get_spec
            spec = get_spec(cid)
            results.append(CaseResult(id=cid, title=cid, declared_layer=spec.declared_layer, scope=spec.scope, expected=spec.expected(), result="NOT_RUN", diagnostics=[error or stop_reason or "batch deadline exhausted"]))
    elapsed = time.monotonic() - start
    timer.record("total", elapsed)
    cost = {"real_provider_calls":0 if events and not any(e["op"] == "network_denied" for e in events) else None,
            "paid_usd":0 if events else None, "unknown_charge":None,
            "fixture_requests":sum(r.provider_counters.get("fixture_requests", 0) for r in results if isinstance(r.provider_counters.get("fixture_requests"), int)),
            "fixture_counter_scope":"observed local fixture GETs only; producer unknown usage stays null"}
    scope = {"batch_elapsed_seconds":round(elapsed, 4), "case_limit_seconds":CASE_TIMEOUT,
             "batch_deadline_seconds":BATCH_DEADLINE, "final_proof_reserve_seconds":PROOF_RESERVE_SECONDS,
             "workers":workers, "worker_isolation":"independent Context/wiki/proxy/counters per group; download->reuse chains stay within one group",
             "network_guard_boots":sum(e["op"] == "guard_boot" for e in events),
             "network_attempts_denied":sum(e["op"] == "network_denied" for e in events),
             "translation_attempts":sum(e["op"] == "translation_attempt" for e in events),
             "provider_boundary":"fixture response only; real supplier reachability/coverage is not proven",
             "phase_timing":timer.snapshot(), "launch_accounting":accounting,
             "bytecode_cache":cache_info,
             "stop_reason":stop_reason,
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
