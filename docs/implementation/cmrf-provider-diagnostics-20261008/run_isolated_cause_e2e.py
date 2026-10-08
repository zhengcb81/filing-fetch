"""Concentrated R6-FF-CAUSE E2E — manual big node, fully offline.

Real company-wiki CLI (imported read-only from the canonical checkout via
PYTHONPATH) + the real FF public CLI, driven against an ISOLATED temporary
wiki with a fake CN ``json_command_v1`` provider that logs start/HTTP/usage.

Scenarios
  A  broken acquisition config  -> real CWP CLI emits its structured taxonomy
     error on stderr -> FF public CLI surfaces error_code=fatal and the safe
     upstream_cause; the fake provider log must show NO provider start.
  B  fake provider typed failure -> CWP re-serializes the adapter failure
     through the 6-code taxonomy (adapter machine codes/usage dropped at the
     CLI boundary — findings G2) -> FF keeps fatal + honest provider_started/
     usage_complete nulls; the fake provider log PROVES it started, which may
     only appear in this test report, never in production output.
  C  legal fetch_if_missing import through the bounded fake provider, then a
     reuse_only pass whose SourceRef is byte-verified (sha256 + size) against
     the canonical file, with download_events=0 and no provider invocation.

No real market/model/network calls. All state lives in one temp directory
(keep with --keep); nothing writes the production source_catalog.yaml or any
canonical checkout file. Report JSON is written next to this script.

Usage:
    python run_isolated_cause_e2e.py \
        [--cwp-src C:/Users/郑曾波/Projects/company-wiki/src] [--keep]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
FF_ROOT = HERE.parents[2]
FF_CLI = FF_ROOT / "scripts" / "fetch_filing.py"
DEFAULT_CWP_SRC = Path("C:/Users/郑曾波/Projects/company-wiki/src")

PDF_BODY = b"%PDF-1.7\nbyd fy2024 annual report bytes for offline R6-FF-CAUSE E2E " * 30
PDF_SHA = hashlib.sha256(PDF_BODY).hexdigest()

_CN_SNAPSHOT = {
    "schema_version": "1.0",
    "market": "CN",
    "retrieved_at": "2026-10-08T00:00:00Z",
    "sources": ["isolated-e2e-seed"],
    "record_count": 1,
    "records": [
        {
            "schema_version": "1.0",
            "canonical_name": "比亚迪股份有限公司",
            "market": "CN",
            "exchange": "SZSE",
            "ticker": "002594",
            "security_id": "002594",
            "aliases": ["比亚迪", "BYD"],
            "active": True,
            "source_name": "isolated-e2e-seed",
            "source_url": "https://example.invalid/seed",
            "source_record_id": "urn:isolated-e2e:CN:002594",
            "identifiers": {},
        }
    ],
}

# Fake CN provider (json_command_v1). Three behaviors selected by argv[1]:
#   ok          - discover returns the BYD FY2024 annual; fetch stages the PDF
#                 and reports bounded usage (response_bytes / cost_usd).
#   typed_error - logs start/HTTP, then emits the structured adapter 1.0
#                 failure JSON on stderr and exits 1 (never writes bytes).
# The log records one JSON line per provider START and per HTTP attempt with
# usage, so the report can cross-check what FF could and could not know.
_FAKE_PROVIDER = r'''
import argparse, hashlib, json, sys
from pathlib import Path

behavior = sys.argv[1]
log_path = Path(sys.argv[2])
parser = argparse.ArgumentParser()
parser.add_argument("action", choices=("discover", "fetch"))
parser.add_argument("--staging-dir")
args = parser.parse_args(sys.argv[3:])
payload = json.loads(sys.stdin.read())

def log(event, **fields):
    entry = {"event": event, "action": args.action, **fields}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

identity = {"name": "stockinfo-cninfo", "version": "1.1.0"}
ANN_ID = "1222881496"
TITLE = "比亚迪股份有限公司2024年年度报告"
DETAIL_URL = "https://www.cninfo.com.cn/new/disclosure/detail?stockCode=002594&announcementId=1222881496"
TRANSPORT_URL = "https://static.cninfo.com.cn/finalpage/2025-03-25/1222881496.PDF"
BODY = b"%PDF-1.7\nbyd fy2024 annual report bytes for offline R6-FF-CAUSE E2E " * 30

log("provider_started", behavior=behavior, budget=payload.get("acquisition_budget"))

if behavior == "typed_error":
    log("http_attempt", url=TRANSPORT_URL, status=503)
    log("usage", response_bytes=0, cost_usd="0.00", complete=False)
    failure = {
        "schema_version": "1.0",
        "status": "failed",
        "adapter": identity,
        "error": {
            "code": "upstream_unavailable",
            "type": "CninfoApiError",
            "message": "simulated upstream 503 for offline E2E",
            "retryable": True,
            "acquisition_usage": {"response_bytes": 0, "cost_usd": "0.00"},
            "acquisition_usage_complete": True,
        },
    }
    sys.stderr.write(json.dumps(failure, ensure_ascii=False) + "\n")
    sys.exit(1)

if args.action == "discover":
    log("http_attempt", url=DETAIL_URL, status=200)
    usage = {"schema_version": "1.0", "response_bytes": 2048, "cost_usd": "0.00"}
    log("usage", response_bytes=2048, cost_usd="0.00", complete=True)
    response = {
        "schema_version": "1.0",
        "status": "ok",
        "adapter": identity,
        "acquisition_usage": usage,
        "candidates": [{
            "candidate_id": "cninfo:" + ANN_ID,
            "provider": "cninfo",
            "provider_document_id": ANN_ID,
            "identity_method": "announcement_id",
            "market": "CN",
            "entity": "002594",
            "title": TITLE,
            "source_url": DETAIL_URL,
            "document_kind": "annual_report",
            "form_type": "annual_report",
            "filing_date": "2025-03-24",
            "fiscal_year": 2024,
            "fiscal_period": "FY",
            "language": "zh-CN",
            "amended": False,
            "transport_url": TRANSPORT_URL,
        }],
    }
else:
    raw = json.loads(payload["adapter_payload_json"])
    log("http_attempt", url=raw["transport_url"], status=200)
    staging_dir = Path(args.staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    filename = "byd_fy2024_annual.pdf"
    part = staging_dir / (filename + ".part")
    part.write_bytes(BODY)
    final = staging_dir / filename
    if final.exists():
        final.unlink()
    part.replace(final)
    usage = {"schema_version": "1.0", "response_bytes": len(BODY), "cost_usd": "0.00"}
    log("usage", response_bytes=len(BODY), cost_usd="0.00", complete=True)
    response = {
        "schema_version": "1.0",
        "status": "ok",
        "adapter": identity,
        "acquisition_usage": usage,
        "receipt": {
            "candidate_id": raw["candidate_id"],
            "provider": raw["provider"],
            "provider_document_id": raw["provider_document_id"],
            "source_url": raw["source_url"],
            "staged_path": str(final),
            "content_sha256": hashlib.sha256(BODY).hexdigest(),
            "byte_size": len(BODY),
            "mime_type": "application/pdf",
            "retrieved_at": "2026-10-08T08:00:00Z",
            "http_status": 200,
            "adapter_name": identity["name"],
            "adapter_version": identity["version"],
            "etag": None,
            "last_modified": None,
        },
    }
sys.stdout.write(json.dumps(response, ensure_ascii=False))
'''


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _catalog_yaml() -> str:
    return (
        "schema_version: '1.0'\n"
        "catalog_dir: .source_catalog\n"
        "roots:\n"
        "  - root_id: company_raw\n"
        "    path: companies\n"
        "    kind: company_raw\n"
        "    priority: 10\n"
        "    read_only: false\n"
    )


def _acquisition_yaml(adapter_py: Path, *, broken: bool) -> str:
    if broken:
        # Deterministic AcquisitionConfigError inside the REAL CWP CLI.
        return "schema_version: '1.1'\nstaging_root: staging\ntimeout_seconds: 60\n"
    return (
        "schema_version: '1.1'\n"
        "staging_root: staging\n"
        "timeout_seconds: 60\n"
        "adapters:\n"
        "  cn:\n"
        "    name: stockinfo-cninfo\n"
        "    version: 1.1.0\n"
        f"    interface: json_command_v1\n"
        f"    project_root: \"{adapter_py.parent.as_posix()}\"\n"
        "    config_root: null\n"
        f"    command: [\"${{PYTHON_EXECUTABLE}}\", \"{adapter_py.as_posix()}\"]\n"
        "    supports_acquisition_budget: true\n"
        "  hk:\n"
        "    name: dayu-hk\n"
        "    version: 1.0.0\n"
        "    interface: dayu_cli_v1\n"
        f"    project_root: \"{adapter_py.parent.as_posix()}\"\n"
        f"    config_root: \"{adapter_py.parent.as_posix()}\"\n"
        f"    command: [\"${{PYTHON_EXECUTABLE}}\", \"{adapter_py.as_posix()}\"]\n"
        "  us:\n"
        "    name: dayu-us\n"
        "    version: 1.0.0\n"
        "    interface: dayu_cli_v1\n"
        f"    project_root: \"{adapter_py.parent.as_posix()}\"\n"
        f"    config_root: \"{adapter_py.parent.as_posix()}\"\n"
        f"    command: [\"${{PYTHON_EXECUTABLE}}\", \"{adapter_py.as_posix()}\"]\n"
    )


def _build_wiki(base: Path, adapter_py: Path, *, broken: bool) -> Path:
    wiki = base / "wiki"
    _write(wiki / "config" / "source_catalog.yaml", _catalog_yaml())
    _write(
        wiki / "config" / "source_acquisition.yaml",
        _acquisition_yaml(adapter_py, broken=broken),
    )
    _write(
        wiki / ".source_catalog" / "security_master" / "cn.json",
        json.dumps(_CN_SNAPSHOT, ensure_ascii=False, indent=2),
    )
    (wiki / "companies").mkdir(parents=True, exist_ok=True)
    _write(base / "ff-config.json", json.dumps({
        "schema_version": "1.0",
        "company_wiki_root": str(wiki),
    }))
    return wiki


def _request(intent: str) -> dict:
    request = {
        "schema_version": "2.0",
        "company_query": "比亚迪",
        "market": "CN",
        "document_kind": "annual_report",
        "mode": "exact",
        "fiscal_year": 2024,
        "as_of_date": "2026-10-08",
        "filing_intent": intent,
    }
    if intent == "fetch_if_missing":
        # reuse_only forbids acquisition_limits (only fetch_if_missing binds
        # provider ceilings).
        request["acquisition_limits"] = {
            "max_bytes": 10_000_000,
            "timeout_seconds": 60,
            "max_cost_usd": "0",
        }
    return request


def _run_ff(base: Path, request: dict, env: dict) -> tuple[int, dict, str]:
    request_file = base / "request.json"
    request_file.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable, str(FF_CLI),
            "--request-file", str(request_file),
            "--config", str(base / "ff-config.json"),
            "--timeout-seconds", "120",
        ],
        capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(base),
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"_raw_stdout": proc.stdout[:2000]}
    return proc.returncode, payload, proc.stderr


def _provider_log(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _events(log: list[dict], event: str) -> list[dict]:
    return [entry for entry in log if entry.get("event") == event]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwp-src", type=Path, default=DEFAULT_CWP_SRC)
    parser.add_argument("--keep", action="store_true", help="keep the temp root")
    args = parser.parse_args()
    cwp_src = args.cwp_src.resolve(strict=True)
    if not (cwp_src / "company_wiki" / "source_catalog" / "cli.py").is_file():
        print(f"error: company_wiki package not found under {cwp_src}", file=sys.stderr)
        return 2

    env = dict(os.environ)
    env["PYTHONPATH"] = str(cwp_src) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUTF8"] = "1"

    report: dict = {
        "schema_version": "cmrf-ff-cause-e2e/1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cwp_src": str(cwp_src),
        "ff_cli": str(FF_CLI),
        "scenarios": {},
    }
    failures: list[str] = []

    def check(scenario: str, name: str, condition: bool, detail: str = "") -> None:
        status = "PASS" if condition else "FAIL"
        report["scenarios"].setdefault(scenario, {"checks": []})["checks"].append(
            {"name": name, "status": status, "detail": detail}
        )
        if not condition:
            failures.append(f"{scenario}/{name}: {detail}")

    base = Path(tempfile.mkdtemp(prefix="cmrf-ff-cause-e2e-"))
    try:
        adapter_dir = base / "adapter"
        adapter_dir.mkdir(parents=True)
        adapter_py = adapter_dir / "fake_cn_provider.py"
        adapter_py.write_text(_FAKE_PROVIDER, encoding="utf-8")
        provider_log = adapter_dir / "provider.jsonl"

        # -- Scenario A: broken acquisition config through the REAL CWP CLI --
        wiki_a = _build_wiki(base / "a", adapter_py, broken=True)
        base_a = base / "a"
        # ff-config.json points at the scenario wiki.
        _write(base_a / "ff-config.json", json.dumps({
            "schema_version": "1.0", "company_wiki_root": str(wiki_a),
        }))
        rc, out, err = _run_ff(base_a, _request("fetch_if_missing"), env)
        log_a = _provider_log(provider_log)
        check("A_broken_config", "ff_exits_2", rc == 2, f"rc={rc}")
        filing = out.get("filing", {})
        cause = filing.get("upstream_cause")
        check("A_broken_config", "v2_fatal_status", out.get("status") == "fatal", str(out.get("status")))
        check("A_broken_config", "cause_present_fatal", bool(cause) and cause.get("code") in ("fatal", "unknown"), json.dumps(cause))
        check(
            "A_broken_config", "honest_nulls",
            bool(cause) and cause.get("provider_started") is None and cause.get("usage_complete") is None,
            json.dumps(cause),
        )
        check("A_broken_config", "provider_never_started", not _events(log_a, "provider_started"),
              f"{len(_events(log_a, 'provider_started'))} start events")
        check("A_broken_config", "no_secret_stderr_leak", "FMP_API_KEY" not in json.dumps(out) and "api_key" not in json.dumps(out))
        report["scenarios"]["A_broken_config"]["ff_response"] = out
        report["scenarios"]["A_broken_config"]["provider_log_lines"] = len(log_a)

        # -- Scenario B: fake provider typed failure through the REAL CWP CLI --
        provider_log.unlink(missing_ok=True)
        # B reuses the OK-shaped acquisition config but the provider behaves
        # per its first CLI arg; a second fake script selects typed_error.
        adapter_b = adapter_dir / "fake_cn_provider_error.py"
        adapter_b.write_text(_FAKE_PROVIDER, encoding="utf-8")
        wiki_b = _build_wiki(base / "b", adapter_b, broken=False)
        # point the cn adapter command at the typed_error behavior via wrapper
        wrapper = adapter_dir / "run_error_behavior.py"
        wrapper.write_text(
            "import runpy, sys\n"
            f"sys.argv = [sys.argv[0], 'typed_error', r'{provider_log.as_posix()}'] + sys.argv[1:]\n"
            f"runpy.run_path(r'{adapter_b.as_posix()}', run_name='__main__')\n",
            encoding="utf-8",
        )
        acq = (wiki_b / "config" / "source_acquisition.yaml").read_text(encoding="utf-8")
        acq = acq.replace(f'"{adapter_b.as_posix()}"', f'"{wrapper.as_posix()}"')
        (wiki_b / "config" / "source_acquisition.yaml").write_text(acq, encoding="utf-8")
        base_b = base / "b"
        _write(base_b / "ff-config.json", json.dumps({
            "schema_version": "1.0", "company_wiki_root": str(wiki_b),
        }))
        rc, out, err = _run_ff(base_b, _request("fetch_if_missing"), env)
        log_b = _provider_log(provider_log)
        cause = out.get("filing", {}).get("upstream_cause")
        check("B_typed_provider_failure", "ff_exits_2", rc == 2, f"rc={rc}")
        check("B_typed_provider_failure", "v2_fatal_status", out.get("status") == "fatal", str(out.get("status")))
        check("B_typed_provider_failure", "cause_code_fatal_or_unknown",
              bool(cause) and cause.get("code") in ("fatal", "unknown"), json.dumps(cause))
        check("B_typed_provider_failure", "honest_nulls_despite_real_start",
              bool(cause) and cause.get("provider_started") is None and cause.get("usage_complete") is None,
              json.dumps(cause))
        starts = _events(log_b, "provider_started")
        https = _events(log_b, "http_attempt")
        check("B_typed_provider_failure", "provider_actually_started", len(starts) >= 1,
              f"{len(starts)} start events (test-report evidence only)")
        check("B_typed_provider_failure", "http_attempted", len(https) >= 1, f"{len(https)} http events")
        check("B_typed_provider_failure", "adapter_code_not_leaked",
              "upstream_unavailable" not in json.dumps(out) and "CninfoApiError" not in json.dumps(out))
        report["scenarios"]["B_typed_provider_failure"]["ff_response"] = out
        report["scenarios"]["B_typed_provider_failure"]["provider_log"] = log_b
        report["scenarios"]["B_typed_provider_failure"]["note"] = (
            "provider_started/usage_complete stay null in FF output because CWP's "
            "public stderr taxonomy carries no such fields (findings G1/G2); the "
            "fake provider's own log proves it started - recorded here only."
        )

        # -- Scenario C1: legal import via the bounded fake provider --
        provider_log.unlink(missing_ok=True)
        adapter_c = adapter_dir / "fake_cn_provider_ok.py"
        adapter_c.write_text(_FAKE_PROVIDER, encoding="utf-8")
        wiki_c = _build_wiki(base / "c", adapter_c, broken=False)
        base_c = base / "c"
        _write(base_c / "ff-config.json", json.dumps({
            "schema_version": "1.0", "company_wiki_root": str(wiki_c),
        }))
        wrapper_ok = adapter_dir / "run_ok_behavior.py"
        wrapper_ok.write_text(
            "import runpy, sys\n"
            f"sys.argv = [sys.argv[0], 'ok', r'{provider_log.as_posix()}'] + sys.argv[1:]\n"
            f"runpy.run_path(r'{adapter_c.as_posix()}', run_name='__main__')\n",
            encoding="utf-8",
        )
        acq = (wiki_c / "config" / "source_acquisition.yaml").read_text(encoding="utf-8")
        acq = acq.replace(f'"{adapter_c.as_posix()}"', f'"{wrapper_ok.as_posix()}"')
        (wiki_c / "config" / "source_acquisition.yaml").write_text(acq, encoding="utf-8")

        rc1, out1, err1 = _run_ff(base_c, _request("fetch_if_missing"), env)
        log_c1 = _provider_log(provider_log)
        check("C1_legal_import", "ff_exits_0", rc1 == 0, f"rc={rc1} err={err1[-400:]}")
        check("C1_legal_import", "source_candidate", out1.get("status") == "source_candidate", str(out1.get("status")))
        check("C1_legal_import", "one_download_event",
              out1.get("downloads") == 1 and out1.get("filing", {}).get("download_events") == 1,
              f"downloads={out1.get('downloads')} events={out1.get('filing', {}).get('download_events')}")
        check("C1_legal_import", "no_cause_on_success", "upstream_cause" not in json.dumps(out1))
        check("C1_legal_import", "provider_fetch_200",
              any(e.get("status") == 200 for e in _events(log_c1, "http_attempt")))
        report["scenarios"]["C1_legal_import"]["ff_response"] = out1

        # -- Scenario C2: legal reuse, SourceRef strong byte verification --
        log_lines_before = len(log_c1)
        rc2, out2, err2 = _run_ff(base_c, _request("reuse_only"), env)
        log_c2 = _provider_log(provider_log)
        ref = out2.get("filing", {}).get("source_ref") or {}
        canonical_hits = [
            path for path in (wiki_c / "companies").rglob("*.pdf")
            if hashlib.sha256(path.read_bytes()).hexdigest() == PDF_SHA
        ]
        check("C2_legal_reuse", "ff_exits_0", rc2 == 0, f"rc={rc2} err={err2[-400:]}")
        check("C2_legal_reuse", "source_candidate_reuse",
              out2.get("status") == "source_candidate"
              and out2.get("filing", {}).get("resolution_outcome") == "reused_existing",
              str(out2.get("filing", {}).get("resolution_outcome")))
        check("C2_legal_reuse", "zero_download_trace",
              out2.get("downloads") == 0 and out2.get("filing", {}).get("download_events") == 0,
              f"downloads={out2.get('downloads')} events={out2.get('filing', {}).get('download_events')}")
        check("C2_legal_reuse", "no_provider_invocation", len(log_c2) == log_lines_before,
              f"{len(log_c2)} vs {log_lines_before} provider log lines")
        check("C2_legal_reuse", "source_ref_bytes_verified",
              ref.get("content_sha256") == PDF_SHA and bool(canonical_hits),
              f"ref={ref.get('content_sha256', '')[:12]} canonical={len(canonical_hits)}")
        if canonical_hits and ref.get("content_sha256") == PDF_SHA:
            size_ok = canonical_hits[0].stat().st_size == ref.get("byte_size")
            check("C2_legal_reuse", "source_ref_size_verified", size_ok,
                  f"{canonical_hits[0].stat().st_size} vs {ref.get('byte_size')}")
        check("C2_legal_reuse", "no_physical_fields",
              not any(k in json.dumps(ref).lower() for k in ("path", "location", "bundle", "root:")))
        report["scenarios"]["C2_legal_reuse"]["ff_response"] = out2

        report["tmp_root"] = str(base)
        report["retained"] = bool(args.keep)
        report["result"] = "PASS" if not failures else "FAIL"
        report["failures"] = failures
        report_path = HERE / "isolated_cause_e2e_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"result": report["result"], "failures": failures,
                          "report": str(report_path)}, ensure_ascii=False, indent=2))
        return 0 if not failures else 1
    finally:
        if args.keep:
            print(f"[keep] temp root retained: {base}")
        else:
            shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
