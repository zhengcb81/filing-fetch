"""W20 interruption/recovery handlers for the offline contract matrix.

Every case here drives the REAL public FF CLI as a child process, the REAL ET
supervisor/worker chain through the test-proxy and the REAL CWP
ensure/import/query services. Interruptions are injected only at boundaries
the harness owns:

* killing the FF child process tree (via FF's own ``ff_process_tree`` job
  semantics) at an externally observable moment — a worker GET in flight, the
  canonical transcript original appearing, or the supplier response having
  returned; or
* reshaping the ET result/usage stream inside the test proxy (see
  ``et_transcript_proxy`` scenarios).

No product failpoint exists. Recovery is observed only through CWP's public
query/import path; the harness never builds a second state store.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from run import Context, CASE_TIMEOUT  # noqa: E402
from report import CaseResult, sha256_file  # noqa: E402
from fixture_builder import CN, HK, Identity  # noqa: E402
import ff_process_tree  # noqa: E402  (FF's own owned-tree semantics, read-only)

POLL_SECONDS = 0.02
KILL_WAIT_SECONDS = 10.0

_ACCEPTED = {"reused", "unknown_publication"}


# ── filesystem observability (cheap, owned scratch only) ───────────────────


def _transcript_sidecars(ctx: Context, entity: str = "Apple Inc.") -> list[Path]:
    directory = ctx.env.wiki / "companies" / entity / "raw" / "investor_relations" / "transcripts"
    return sorted(directory.glob("*.source.json")) if directory.is_dir() else []


def _filing_originals(ctx: Context, identity: Identity, kind_dir: str) -> list[Path]:
    directory = ctx.env.wiki / "companies" / identity.entity / "raw" / kind_dir
    if not directory.is_dir():
        return []
    return [p for p in sorted(directory.iterdir())
            if p.is_file() and not p.name.endswith(".source.json")]


def _adapter_rows(ctx: Context, tag: str, action: str) -> int:
    return sum(1 for row in ctx.adapter_records()
               if row.get("receipt_tag") == tag and row.get("action") == action)


# ── bounded FF launcher with optional interruption ─────────────────────────


def _active_spec(ctx: Context, case_id: str):
    spec = getattr(ctx, "active_case_spec", None)
    if spec is not None and spec.id == case_id:
        return spec
    import case_registry
    spec = case_registry.resolve_spec(case_id)
    if spec is None:
        raise ValueError(f"unknown supplemental case id: {case_id}")
    return spec


def _run_state(ctx: Context, *, scenario: str, calls_tag: str, content_utf8: str,
               call_date: str = "2025-12-01", response_bytes: int = 512,
               provider_scenario: str = "serve") -> tuple[Path, Path]:
    """Write one run-private proxy/adapter state file plus its calls file.

    A private state file per run (referenced through the child's own
    ``W06_MATRIX_STATE``) keeps concurrent children's provider counters and ET
    receipts race-free without touching any shared runner state.
    """
    calls_file = ctx.env.calls_file(calls_tag)
    state = {
        "scenario": scenario,
        "provider_scenario": provider_scenario,
        "content_utf8": content_utf8,
        "call_date": call_date,
        "response_bytes": response_bytes,
        "calls_file": str(calls_file),
        "et_temp_root": str(ctx.env.et_temp_root()),
        "receipts_dir": str(ctx.artifacts),
        "receipt_tag": calls_tag,
    }
    path = ctx.env.proxy_state / f"state.{calls_tag}.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return path, calls_file


def launch_ff_run(ctx: Context, *, case_id: str, run_label: str, request: dict[str, Any],
                  timeout: int = CASE_TIMEOUT, kill_when: Callable[[], bool] | None = None,
                  run_index: int | None = None) -> dict[str, Any]:
    """Run the real FF CLI once; optionally kill the whole owned tree.

    The trace mirrors ``Context.run_ff`` so the oracle's bound-evidence checks
    (request/response/fixture bytes, ET receipts, expected original sha) apply
    unchanged; ``killed``/``kill_reason`` record a harness-injected
    interruption of this run.
    """
    spec = _active_spec(ctx, case_id)
    index = run_index if run_index is not None else len(ctx.traces.get(case_id, []))
    state_path = ctx.env.proxy_state / f"state.{case_id}.{run_label}.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    calls = Path(state["calls_file"]) if state.get("calls_file") else None
    errors = spec.request_errors(index, request) + spec.fixture_errors(index, state, True)
    if errors:
        raise ValueError("case input contract drift: " + "; ".join(errors))
    request = spec.runs[index].request()
    prefix = getattr(ctx, "artifact_prefix", "")
    fixture_path = ctx.artifacts / f"{prefix}{case_id}.{run_label}.fixture.json"
    fixture_path.write_text(json.dumps({"state": state, "with_fmp_key": True},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
    req_path = ctx.artifacts / f"{prefix}{case_id}.{run_label}.request.json"
    req_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    stdout_path = ctx.artifacts / f"{prefix}{case_id}.{run_label}.stdout.bin"
    stderr_path = ctx.artifacts / f"{prefix}{case_id}.{run_label}.stderr.bin"
    et_before = ctx.fixture_requests(calls) if calls else 0
    adapters_before = len(ctx.adapter_records())
    env = dict(ctx.child_env())
    env["W06_MATRIX_STATE"] = str(state_path)
    cmd = [sys.executable, str(ctx.ff_root / "scripts" / "fetch_filing.py"),
           "--config", str(ctx.env.ff_config), "--timeout-seconds", str(timeout)]
    ctx.phases.count_launch("ff_cli")
    killed, kill_reason = False, None
    proc = None
    job = None
    popen_kwargs: dict[str, Any] = {}
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True
    with req_path.open("rb") as stdin_file, \
            stdout_path.open("wb") as out_file, stderr_path.open("wb") as err_file:
        proc = subprocess.Popen(cmd, stdin=stdin_file, stdout=out_file, stderr=err_file,
                                env=env, cwd=str(ctx.scratch), **popen_kwargs)
        if os.name == "nt":
            job = ff_process_tree.assign_windows_job(proc)
        deadline_end = ctx.deadline.case(timeout).end
        try:
            while True:
                if proc.poll() is not None:
                    break
                if kill_when is not None and kill_when():
                    _terminate_tree(proc, job)
                    killed, kill_reason = True, "harness interruption at observed boundary"
                    break
                if time.monotonic() >= deadline_end:
                    _terminate_tree(proc, job)
                    killed, kill_reason = True, "case deadline bound reached"
                    break
                time.sleep(POLL_SECONDS)
            try:
                proc.wait(timeout=KILL_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                _terminate_tree(proc, job)
                proc.wait(timeout=KILL_WAIT_SECONDS)
        finally:
            if job is not None:
                job.close()
    stdout = stdout_path.read_bytes()
    stderr_bytes = stderr_path.read_bytes()
    try:
        response = json.loads(stdout.decode("utf-8", errors="replace"))
    except ValueError:
        response = {"_unparsed_stdout": stdout.decode("utf-8", errors="replace")[:2000]}
    resp_path = ctx.artifacts / f"{prefix}{case_id}.{run_label}.response.json"
    resp_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    stderr_txt_path = ctx.artifacts / f"{prefix}{case_id}.{run_label}.stderr.txt"
    stderr_txt_path.write_text(stderr_text, encoding="utf-8")
    trace: dict[str, Any] = {
        "exit_code": proc.returncode,
        "response": response,
        "stderr": stderr_text,
        "request_ref": req_path.name,
        "response_ref": resp_path.name,
        "stderr_ref": stderr_txt_path.name,
        "et_fixture_requests": (ctx.fixture_requests(calls) if calls else 0) - et_before,
        "adapter_fixture_requests": len(ctx.adapter_records()) - adapters_before,
        "receipt_tag": state.get("receipt_tag"),
        "fixture_scenario": state.get("scenario"),
        "fixture_ref": fixture_path.name,
        "fixture_sha256": sha256_file(fixture_path),
        "expected_original_content_sha256": (
            hashlib.sha256(state.get("content_utf8", "").encode("utf-8")).hexdigest()
            if state.get("content_utf8") else None),
        "request_sha256": sha256_file(req_path),
        "response_sha256": sha256_file(resp_path),
        "killed": killed,
        "kill_reason": kill_reason,
        "adapter_fetch_requests": _adapter_rows(ctx, state.get("receipt_tag") or "", "fetch"),
    }
    # adapter_fetch_requests counts this run's own tag rows; for shared-tag
    # sequential runs the tag is unique per run label, so the count is exact.
    for kind in ("result", "usage"):
        receipt = ctx.artifacts / f"{state.get('receipt_tag')}.{kind}.json"
        if receipt.is_file():
            trace[f"et_{kind}_receipt"] = {"file": receipt.name, "sha256": sha256_file(receipt)}
    trace["fixture_requests"] = trace["et_fixture_requests"] + trace["adapter_fixture_requests"]
    if run_index is None:
        ctx.traces.setdefault(case_id, []).append(trace)
    else:
        traces = ctx.traces.setdefault(case_id, [])
        while len(traces) <= run_index:
            traces.append({})
        traces[run_index] = trace
    return trace


def _terminate_tree(proc: subprocess.Popen, job) -> None:
    if os.name == "nt":
        if job is not None:
            job.terminate()
    else:
        ff_process_tree.kill_owned_group(proc.pid)


def _prepare_run(ctx: Context, case_id: str, run_label: str, scenario: str, content: str,
                 index: int, *, call_date: str = "2025-12-01",
                 provider_scenario: str = "serve") -> dict[str, Any]:
    """Write the run-private state and launch the FF child without a kill."""
    spec = _active_spec(ctx, case_id)
    tag = f"{case_id}.{run_label}"
    state_path, _calls = _run_state(ctx, scenario=scenario, calls_tag=tag,
                                    content_utf8=content, call_date=call_date,
                                    provider_scenario=provider_scenario)
    request = spec.runs[index].request()
    return {"case_id": case_id, "run_label": run_label, "request": request,
            "state_path": state_path, "scenario": scenario, "content": content,
            "index": index, "provider_scenario": provider_scenario}


def _execute(ctx: Context, prepared: dict[str, Any], *,
             kill_when: Callable[[], bool] | None = None,
             timeout: int = CASE_TIMEOUT) -> dict[str, Any]:
    return launch_ff_run(ctx, case_id=prepared["case_id"], run_label=prepared["run_label"],
                         request=prepared["request"], timeout=timeout,
                         kill_when=kill_when, run_index=prepared["index"])


def _result(ctx: Context, cid: str, title: str, actual: dict[str, Any]) -> CaseResult:
    spec = _active_spec(ctx, cid)
    actual["runs"] = ctx.traces.get(cid, [])
    result = CaseResult(id=cid, title=title, declared_layer=spec.declared_layer,
                        observed_layer="w20 fault/recovery chain (real FF CLI + "
                                       "test-proxy boundary + real CWP import)",
                        result="NOT_RUN", scope=spec.scope, expected=spec.expected(),
                        actual=actual)
    errors = spec.assertion_errors(result.to_dict())
    result.result = "PASS" if not errors else "FAIL"
    result.diagnostics.extend(errors or ["all supplemental assertions observed"])
    return result


# ── transcript-side cases ──────────────────────────────────────────────────


def case_call_kill_before_durable(ctx: Context) -> CaseResult:
    cid = "w20_call_kill_before_durable"
    content = "Synthetic W20 pre-durable interrupt transcript FY2034 Q1."
    p1 = _prepare_run(ctx, cid, "run1", "stall", content, 0)
    calls = Path(json.loads(p1["state_path"].read_text(encoding="utf-8"))["calls_file"])
    run1 = _execute(ctx, p1, kill_when=lambda: ctx.fixture_requests(calls) >= 1)
    durable_at_kill = bool(_transcript_sidecars(ctx))
    p2 = _prepare_run(ctx, cid, "run2", "success", content, 1)
    _execute(ctx, p2)
    p3 = _prepare_run(ctx, cid, "run3", "success", content, 2)
    _execute(ctx, p3)
    return _result(ctx, cid, "FF tree killed while the provider GET is in flight; "
                             "recovery re-acquires once then reuses", {
        "durable_at_kill": durable_at_kill,
        "kill_reason": run1.get("kill_reason"),
    })


def case_call_kill_after_import(ctx: Context) -> CaseResult:
    cid = "w20_call_kill_after_import"
    content = "Synthetic W20 durable-interrupt transcript FY2034 Q2."
    p1 = _prepare_run(ctx, cid, "run1", "success", content, 0)
    run1 = _execute(ctx, p1, kill_when=lambda: bool(_transcript_sidecars(ctx)))
    sidecars_at_kill = _transcript_sidecars(ctx)
    p2 = _prepare_run(ctx, cid, "run2", "success", content, 1)
    run2 = _execute(ctx, p2)
    t2 = (run2.get("response") or {}).get("transcript") or {}
    branch = ("durable_at_kill"
              if t2.get("status") in _ACCEPTED and run2.get("et_fixture_requests") == 0
              else "not_durable_at_kill")
    p3 = _prepare_run(ctx, cid, "run3", "success", content, 2)
    _execute(ctx, p3)
    return _result(ctx, cid, "FF tree killed when the canonical original appears; "
                             "the durable-at-kill branch is read from recovery", {
        "recovery_branch": branch,
        "sidecars_at_kill": len(sidecars_at_kill),
        "kill_reason": run1.get("kill_reason"),
    })


def case_et_fault(ctx: Context) -> CaseResult:
    """Shared handler for the two pure ET-stream fault cases."""
    spec = getattr(ctx, "active_case_spec", None)
    if spec is None or spec.id not in {"w20_call_et_truncated", "w20_call_et_exit_nonzero"}:
        raise ValueError("case_et_fault requires its own active case spec")
    cid = spec.id
    scenario = spec.runs[0].fixture().get("scenario") or "success"
    content = spec.runs[0].fixture().get("content_utf8") or ""
    return _et_fault_case(ctx, cid, scenario, content)


def _et_fault_case(ctx: Context, cid: str, scenario: str, content: str) -> CaseResult:
    p1 = _prepare_run(ctx, cid, "run1", scenario, content, 0)
    _execute(ctx, p1)
    durable_after_fault = bool(_transcript_sidecars(ctx))
    p2 = _prepare_run(ctx, cid, "run2", "success", content, 1)
    _execute(ctx, p2)
    return _result(ctx, cid, f"ET {scenario} at the test-proxy boundary; named failure, "
                             "one recovery download (nothing durable survived the fault, "
                             "so there is nothing to reuse)", {
        "durable_after_fault": durable_after_fault,
    })


def case_hash_lie(ctx: Context) -> CaseResult:
    cid = "w20_call_hash_lie"
    content = "Synthetic W20 hash-lie transcript FY2035 Q1."
    p1 = _prepare_run(ctx, cid, "run1", "hash_lie", content, 0)
    _execute(ctx, p1)
    durable_after_fault = bool(_transcript_sidecars(ctx))
    p2 = _prepare_run(ctx, cid, "run2", "success", content, 1)
    run2 = _execute(ctx, p2)
    t2 = (run2.get("response") or {}).get("transcript") or {}
    branch = ("not_durable_at_rejection"
              if t2.get("status") == "downloaded" else "durable_despite_rejection")
    p3 = _prepare_run(ctx, cid, "run3", "success", content, 2)
    _execute(ctx, p3)
    return _result(ctx, cid, "ET claims a payload sha that differs from the bytes; "
                             "named rejection, honest recovery", {
        "durable_after_fault": durable_after_fault,
        "recovery_branch": branch,
    })


def case_receipt_binding(ctx: Context) -> CaseResult:
    cid = "w20_call_receipt_binding"
    stale = "Synthetic W20 stale-receipt transcript FY2035 Q2."
    truncated = "Synthetic W20 truncated-receipt transcript FY2035 Q3."
    p1 = _prepare_run(ctx, cid, "run1", "stale_usage", stale, 0)
    _execute(ctx, p1)
    p2 = _prepare_run(ctx, cid, "run2", "truncated_usage", truncated, 1)
    _execute(ctx, p2)
    p3 = _prepare_run(ctx, cid, "run3", "stale_usage", stale, 2)
    _execute(ctx, p3)
    return _result(ctx, cid, "stale/truncated usage receipts stay unknown; the call "
                             "is preserved and the replay reuses", {})


def case_concurrent_same(ctx: Context) -> CaseResult:
    cid = "w20_call_concurrent_same"
    content = "Synthetic W20 concurrent transcript FY2035 Q4."
    pa = _prepare_run(ctx, cid, "run1a", "success", content, 0)
    pb = _prepare_run(ctx, cid, "run1b", "success", content, 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(_execute, ctx, pa)
        future_b = pool.submit(_execute, ctx, pb)
        future_a.result()
        future_b.result()
    p3 = _prepare_run(ctx, cid, "run2", "success", content, 2)
    _execute(ctx, p3)
    return _result(ctx, cid, "two concurrent identical requests; one durable source, "
                             "honest answers, zero-request replay", {})


# ── filing-side cases ──────────────────────────────────────────────────────


def case_filing_kill_recovery(ctx: Context) -> CaseResult:
    cid = "w20_filing_kill_recovery"
    p1 = _prepare_run(ctx, cid, "run1", "success", "", 0)
    tag = f"{cid}.run1"
    run1 = _execute(ctx, p1, kill_when=lambda: _adapter_rows(ctx, tag, "fetch") >= 1)
    durable_at_kill = bool(_filing_originals(ctx, CN, "prospectus"))
    p2 = _prepare_run(ctx, cid, "run2", "success", "", 1)
    _execute(ctx, p2)
    p3 = _prepare_run(ctx, cid, "run3", "success", "", 2)
    _execute(ctx, p3)
    return _result(ctx, cid, "FF tree killed after the supplier response returns but "
                             "before the import is durable; recovery fetches once", {
        "durable_at_kill": durable_at_kill,
        "kill_reason": run1.get("kill_reason"),
    })


def case_filing_concurrent_cross_company(ctx: Context) -> CaseResult:
    cid = "w20_filing_concurrent_cross_company"
    pcn = _prepare_run(ctx, cid, "run1a", "success", "", 0)
    phk = _prepare_run(ctx, cid, "run1b", "success", "", 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_cn = pool.submit(_execute, ctx, pcn)
        future_hk = pool.submit(_execute, ctx, phk)
        future_cn.result()
        future_hk.result()
    pcn2 = _prepare_run(ctx, cid, "run2", "success", "", 2)
    _execute(ctx, pcn2)
    phk2 = _prepare_run(ctx, cid, "run3", "success", "", 3)
    _execute(ctx, phk2)
    counts = {"cn": len(_filing_originals(ctx, CN, "financial_reports/annual")),
              "hk": len(_filing_originals(ctx, HK, "financial_reports/annual"))}
    return _result(ctx, cid, "concurrent CN/HK same-year annual reports stay "
                             "company-bound; later requests reuse", {
        "cross_company_source_counts": counts,
    })
