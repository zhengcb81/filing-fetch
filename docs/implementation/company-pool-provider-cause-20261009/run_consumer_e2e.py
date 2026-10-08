"""One offline milestone: actual FF CLI -> actual CWP CLI -> bounded fake provider.

CWP source must be an explicit completed producer worktree. Existing production
raw/config are never loaded or written. All fixture state is in a short owned
TEMP root and removed at exit; only the small proof report is retained here.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile

HERE = Path(__file__).resolve().parent
FF_ROOT = HERE.parents[2]
OLD_HELPER = HERE.parent / "cmrf-provider-diagnostics-20261008/run_isolated_cause_e2e.py"
spec = importlib.util.spec_from_file_location("ff_existing_offline_fixture", OLD_HELPER)
fixture = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(fixture)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwp-src", type=Path, required=True)
    args = parser.parse_args()
    source = args.cwp_src.resolve(strict=True)
    assert (source / "company_wiki/source_catalog/acquisition_failure.py").is_file()
    env = dict(os.environ, PYTHONPATH=str(source), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    report = dict(schema_version="ff-operation-cause-e2e/1", paid_calls=0, checks=[], scenarios={})
    def check(name, actual, expected):
        report["checks"].append(dict(check=name, actual=actual, expected=expected,
                                     status="PASS" if actual == expected else "FAIL"))
    parent = Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix="ffcause-") as temporary:
        base = Path(temporary).resolve()
        assert base.parent == parent
        adapter = base / "p.py"
        # Existing public fixture, corrected to the published usage/1 shape.
        code = fixture._FAKE_PROVIDER.replace(
            '"acquisition_usage": {"response_bytes": 0, "cost_usd": "0.00"}',
            '"acquisition_usage": {"schema_version": "1.0", "response_bytes": 0, "cost_usd": "0.00"}')
        adapter.write_text(code, encoding="utf-8", newline="\n")
        logs = base / "provider.jsonl"
        def wiki(name, behavior):
            wrapper = base / (name + ".py")
            behavior_expr = "'typed_error' if 'fetch' in sys.argv else 'ok'" if behavior == "fetch_error" else repr(behavior)
            wrapper.write_text("import runpy,sys\n"
                               + "behavior=" + behavior_expr + "\n"
                               + f"sys.argv=[sys.argv[0],behavior,{str(logs)!r}]+sys.argv[1:]\n"
                               + f"runpy.run_path({str(adapter)!r},run_name='__main__')\n",
                               encoding="utf-8", newline="\n")
            root = fixture._build_wiki(base / name, wrapper, broken=False)
            return root, base / name
        # Discovery uses 2048 bytes, then fetch fails with complete final usage0.
        root, case = wiki("f", "fetch_error")
        rc, out, err = fixture._run_ff(case, fixture._request("fetch_if_missing"), env)
        report["scenarios"]["fetch_failure"] = out
        cause = out.get("filing", {}).get("upstream_cause", {})
        check("fetch_failure_exit", rc, 2)
        check("fetch_failure_generic_unchanged", out.get("status"), "fatal")
        check("fetch_failure_specific", cause.get("code"), "upstream_unavailable")
        check("fetch_failure_started", cause.get("provider_started"), True)
        check("fetch_failure_complete", cause.get("usage_complete"), True)
        check("fetch_failure_fixed_six_keys", sorted(cause), sorted([
            "schema_version", "operation", "code", "provider_started", "usage_complete", "retry_scope"]))
        check("ff_ensure_not_retried", out.get("calls"), 2)
        # Existing CWP _stage_with_retry owns three fully accounted fetch tries.
        check("cwp_existing_three_fetch_attempts", len(fixture._events(fixture._provider_log(logs), "provider_started")), 4)
        check("failed_has_no_raw", len(list((root / "companies").rglob("*.pdf"))), 0)
        logs.unlink(missing_ok=True)
        # latest_as_of catches discovery failure as an honest diagnosed GAP.
        _, case = wiki("g", "typed_error")
        request = fixture._request("fetch_if_missing")
        request["mode"] = "latest_as_of"
        request.pop("fiscal_year", None)
        rc, out, err = fixture._run_ff(case, request, env)
        report["scenarios"]["failure_gap"] = out
        cause = out.get("filing", {}).get("upstream_cause", {})
        check("failure_gap_status_preserved", out.get("status"), "gap")
        check("failure_gap_specific", cause.get("code"), "upstream_unavailable")
        check("failure_gap_started", cause.get("provider_started"), True)
        check("failure_gap_complete", cause.get("usage_complete"), True)
        check("failure_gap_zero_downloads", out.get("downloads"), 0)
        check("failure_gap_not_retried", len(fixture._events(fixture._provider_log(logs), "provider_started")), 1)
        check("public_no_secret_or_physical_path", any(token in json.dumps(out) for token in (
            str(base), "simulated upstream 503", "CninfoApiError", "api_key=")), False)
        logs.unlink(missing_ok=True)
        # Successful immutable import followed by reuse: no new diagnostics/download.
        root, case = wiki("s", "ok")
        rc, out, err = fixture._run_ff(case, fixture._request("fetch_if_missing"), env)
        report["scenarios"]["success"] = out
        check("success_exit", rc, 0)
        check("success_downloads", out.get("downloads"), 1)
        check("success_no_failure_cause", "upstream_cause" in out.get("filing", {}), False)
        before = fixture._provider_log(logs)
        rc, out, err = fixture._run_ff(case, fixture._request("reuse_only"), env)
        report["scenarios"]["reuse"] = out
        check("reuse_exit", rc, 0)
        check("reuse_downloads", out.get("downloads"), 0)
        check("reuse_no_provider_call", fixture._provider_log(logs), before)
        ref = out.get("filing", {}).get("source_ref", {})
        check("reuse_original_sha", ref.get("content_sha256"), fixture.PDF_SHA)
        originals = list((root / "companies").rglob("*.pdf"))
        check("raw_single_original", len(originals), 1)
        check("raw_unchanged", hashlib.sha256(originals[0].read_bytes()).hexdigest() if originals else None, fixture.PDF_SHA)
    report["temporary_root_restored"] = not base.exists()
    report["failures"] = [item["check"] for item in report["checks"] if item["status"] != "PASS"]
    report["result"] = "PASS" if not report["failures"] and report["temporary_root_restored"] else "FAIL"
    report["runtime_sha256"] = {name: hashlib.sha256((FF_ROOT / "scripts" / name).read_bytes()).hexdigest()
        for name in ("ff_provider_cause.py", "ff_process_transport.py", "fetch_filing.py", "ff_v2_envelope.py")}
    output = HERE / "consumer_e2e_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps(dict(result=report["result"], checks=len(report["checks"]),
                         failures=report["failures"], restored=report["temporary_root_restored"], report=str(output)), ensure_ascii=False))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
