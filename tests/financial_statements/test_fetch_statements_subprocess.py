"""Neutral RED: real fetch_statements.py subprocess against a fake CWP CLI.

Mirrors the s3_fake_cwp pattern: a fake ``company_wiki.source_catalog.
financial_statements.cli`` module is installed as a temp package and selected
via PYTHONPATH; the real FF CLI process then runs end to end.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import pytest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2]

FAKE_CLI = '''
import json
import os
import sys

payload = json.loads(sys.stdin.read())
mode = os.environ.get("W19_FAKE_MODE", "ok")
if os.environ.get("W19_FAKE_CALLS"):
    with open(os.environ["W19_FAKE_CALLS"], "a", encoding="utf-8") as store:
        print(mode, file=store)
if payload.get("market") != "CN":
    print(json.dumps({"schema_version": "financial-statements-response/1",
                      "status": "request_error", "error": "unsupported market"},
                     ensure_ascii=False))
    raise SystemExit(2)
if mode.startswith("diagnostic_"):
    result = mode.removeprefix("diagnostic_")
    known = result not in ("unknown","legitimate")
    failed_table = {"statement_type":"balance_sheet","status":"unavailable","error_code":"provider_unavailable",
                    "coverage":{"terminal_reason":"provider_error"},"reports":[{"value":"private-artifact-sentinel"}]}
    if result == "legitimate":
        failed_table = {"statement_type":"balance_sheet","status":"not_found","coverage":{"terminal_reason":"no_data"}}
    if known:
        failed_table["usage"] = {"http_requests":1,"response_bytes":315,"cost_usd":"0.00"}
    body = {"schema_version":"financial-statements-response/1","status":"partial" if result in ("mixed","legitimate") else "unavailable",
            "statements":[failed_table]}
    if result in ("mixed","legitimate"):
        body["statements"].append({"statement_type":"income_statement","status":"complete"})
    if known:
        body["usage"] = dict(failed_table["usage"])
elif mode == "unavailable":
    body = {"schema_version": "financial-statements-response/1", "status": "unavailable"}
else:
    body = {
        "schema_version": "financial-statements-response/1",
        "status": "complete",
        "company_identity": {"canonical_name": "中微公司", "market": "CN",
                             "exchange": "SSE", "security_id": "688012"},
        "statements": [{"statement_type": st, "status": "complete",
                        "provider": "sina_finance",
                        "knowledge_mode": "current_snapshot",
                        "point_in_time_quality": "current_snapshot",
                        "coverage": {"observed_periods": 36, "pages": 4},
                        "usage": {"http_requests": 5, "response_bytes": 196351,
                                  "cost_usd": "0.00"},
                        "reports": []}
                       for st in payload["statements"]],
        "usage": {"http_requests": 5, "response_bytes": 196351, "cost_usd": "0.00"},
        "retrieved_at": "2026-10-25T13:00:00Z",
    }
sys.stdout.write(json.dumps(body, ensure_ascii=False))
'''


def _fake_package(tmp: Path) -> Path:
    package = tmp / "fake_pkgs" / "company_wiki" / "source_catalog" / "financial_statements"
    package.mkdir(parents=True)
    # Regular packages (explicit __init__.py at every level): namespace
    # portions are not reliably importable in this Windows/Miniconda setup.
    for parent in (
        tmp / "fake_pkgs" / "company_wiki",
        tmp / "fake_pkgs" / "company_wiki" / "source_catalog",
        package,
    ):
        (parent / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text(FAKE_CLI, encoding="utf-8")
    return tmp / "fake_pkgs"


def _wiki(tmp: Path) -> Path:
    root = tmp / "wiki"
    (root / "config").mkdir(parents=True)
    (root / "config" / "source_catalog.yaml").write_text(
        "schema_version: '1.0'\ncatalog_dir: '${PROJECT_ROOT}/.source_catalog'\n"
        "roots:\n  - root_id: company_raw\n    kind: company_raw\n    path: companies\n",
        encoding="utf-8",
    )
    (root / "companies").mkdir(exist_ok=True)
    launcher = tmp / "company_wiki.json"
    launcher.write_text(
        json.dumps(
            {"schema_version": "1.0", "company_wiki_root": str(root)}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    return launcher


REQUEST = {
    "schema_version": "financial-statements-request/1",
    "company_query": "中微公司",
    "market": "CN",
    "statements": ["income_statement"],
    "report_types": ["annual", "semi_annual", "q1", "q3"],
    "period_end_from": "2016-01-01",
    "period_end_to": "2026-06-30",
    "knowledge_mode": "current_snapshot",
    "as_of_date": "2026-10-25",
    "intent": "fetch_if_missing",
    "acquisition_limits": {
        "max_bytes": 8000000,
        "timeout_seconds": 60,
        "max_cost_usd": "0.00",
    },
}


def _run_cli(tmp_path: Path, request: dict, mode: str = "ok",
             request_file: bool = False) -> subprocess.CompletedProcess:
    fake_root = _fake_package(tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(fake_root) + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("RESEARCH_FEEDBACK_DIR", str(tmp_path / "ordinary-feedback"))
    env["PYTHONUTF8"] = "1"
    env["W19_FAKE_MODE"] = mode
    argv = [
        sys.executable, "-B", str(SKILL_ROOT / "scripts" / "fetch_statements.py"),
        "--config", str(_wiki(tmp_path)), "--timeout-seconds", "60",
    ]
    if request_file:
        path = tmp_path / "request.json"
        path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        argv += ["--request-file", str(path)]
        stdin = None
    else:
        stdin = json.dumps(request, ensure_ascii=False).encode("utf-8")
    proc = subprocess.run(
        argv, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(SKILL_ROOT), env=env, timeout=60,
    )
    return proc


class TestSubprocessFlow:
    def test_success_envelope_on_stdout(self, tmp_path):
        proc = _run_cli(tmp_path, REQUEST)
        assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
        payload = json.loads(proc.stdout.decode("utf-8"))
        assert payload["status"] == "complete"
        assert payload["statements"][0]["statement_type"] == "income_statement"

    def test_unavailable_status_is_still_exit_zero(self, tmp_path):
        proc = _run_cli(tmp_path, REQUEST, mode="unavailable")
        assert proc.returncode == 0
        payload = json.loads(proc.stdout.decode("utf-8"))
        assert payload["status"] == "unavailable"

    def test_request_file_mode(self, tmp_path):
        proc = _run_cli(tmp_path, REQUEST, request_file=True)
        assert proc.returncode == 0
        assert json.loads(proc.stdout.decode("utf-8"))["status"] == "complete"

    def test_invalid_market_request_exits_two(self, tmp_path):
        proc = _run_cli(tmp_path, dict(REQUEST, market="XX"))
        assert proc.returncode == 2
        payload = json.loads(proc.stdout.decode("utf-8"))
        assert payload["status"] == "request_error"

@pytest.mark.parametrize("mode", ["unavailable", "mixed", "unknown", "legitimate"])
def test_statement_diagnostics_recover_native_table_reason_usage_without_copying_reports(tmp_path, monkeypatch, mode):
    inbox = tmp_path / "isolated-feedback"
    monkeypatch.setenv("RESEARCH_FEEDBACK_DIR", str(inbox))
    request = {**REQUEST, "statements": ["balance_sheet","income_statement"]}
    proc = _run_cli(tmp_path, request, mode="diagnostic_"+mode)
    assert proc.returncode == 0
    raw = json.loads(proc.stdout)
    (marker,) = inbox.glob("*.ready")
    packet = [json.loads(line) for line in marker.with_suffix(".jsonl").read_bytes().splitlines()]
    by_check = {row["check_id"]:row for row in packet}
    table = by_check["statement-outcome/balance_sheet"]
    assert table["actual"] == raw["statements"][0]["status"]
    assert table["disposition"] == ("expected" if mode == "legitimate" else "deviation")
    assert by_check["provider-usage"]["actual"] == ("unknown" if mode in {"unknown","legitimate"} else "known")
    cold = subprocess.run([sys.executable, "-B", str(SKILL_ROOT / "scripts/ff_job_feedback.py"),
                           "get-diagnostic", table["details_ref"], "--observations-dir", str(inbox)],
                          cwd=tmp_path, capture_output=True, check=True)
    receipt = json.loads(cold.stdout)
    balance = next(item for item in receipt["statements"] if item["statement_type"] == "balance_sheet")
    assert balance["coverage"]["terminal_reason"] == ("no_data" if mode=="legitimate" else "provider_error")
    if mode != "legitimate":
        assert balance["error_code"] == "provider_unavailable" and table["issue_key"] == "provider_unavailable"
    if "usage" in raw:
        assert receipt["usage"] == balance["usage"] == raw["usage"]
    else:
        assert receipt["usage"] == {} and balance["usage"] == {}
    assert b"private-artifact-sentinel" not in cold.stdout
    assert "reports" not in balance
    if mode == "legitimate":
        assert all(r["disposition"] != "deviation" and "refusal_code" not in r for r in packet)


def test_durable_statement_result_replays_after_inbox_repair_without_refetch(tmp_path):
    jobs = tmp_path / "jobs"
    inbox = jobs / "observations"
    jobs.mkdir()
    inbox.write_text("temporarily unavailable")
    fake = _fake_package(tmp_path)
    config = _wiki(tmp_path)
    env = {key: value for key, value in os.environ.items() if not key.startswith("RESEARCH_FEEDBACK_")}
    calls = tmp_path / "fake-child.calls"
    env.update(PYTHONPATH=str(fake), PYTHONUTF8="1", W19_FAKE_MODE="diagnostic_mixed",
               W19_FAKE_CALLS=str(calls))
    argv = [sys.executable, "-B", str(SKILL_ROOT / "scripts/ff_job.py"), "--jobs-dir", str(jobs)]

    def job(*args, body=None):
        proc = subprocess.run([*argv, *args], input=json.dumps(body).encode() if body else None,
                              env=env, cwd=tmp_path, capture_output=True, timeout=15)
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        return json.loads(proc.stdout)

    submission = {"schema_version": "ff-job/1", "command_id": "table-mixed",
                  "kind": "statements.acquire", "idempotency_key": "table-mixed",
                  "request": {**REQUEST, "statements": ["balance_sheet", "income_statement"]}}
    owner_id = job("submit", body=submission)["owner_job_id"]
    argv_id = ["--owner-job-id", owner_id]
    ran = job("run", *argv_id, "--config", str(config))
    assert ran["engine_executed"] and ran["job"]["result"]["status"] == "partial"
    assert calls.read_text().splitlines() == ["diagnostic_mixed"]
    inbox.unlink()
    inbox.mkdir()
    assert job("get_status", *argv_id)["job"]["result"] == ran["job"]["result"]
    maintenance = [sys.executable, "-B", str(SKILL_ROOT / "scripts/ff_job_feedback.py"), "reoffer-job",
                   "--jobs-dir", str(jobs), *argv_id]
    subprocess.run(maintenance, env=env, cwd=tmp_path, capture_output=True, timeout=15, check=True)
    (ready,) = inbox.glob("*.ready")
    rows = [json.loads(line) for line in ready.with_suffix(".jsonl").read_bytes().splitlines()]
    by_check = {row["check_id"]: row for row in rows}
    assert by_check["job-outcome"]["actual"] == "succeeded"
    assert by_check["statement-outcome/balance_sheet"]["issue_key"] == "provider_unavailable"
    assert by_check["provider-usage"]["actual"] == "known"
    ref = by_check["statement-outcome/balance_sheet"]["details_ref"]
    cmd = [sys.executable, "-B", str(SKILL_ROOT / "scripts/ff_job_feedback.py"), "get-diagnostic",
           ref, "--observations-dir", str(inbox)]
    reply = subprocess.run(cmd, env=env, cwd=tmp_path, capture_output=True, check=True)
    assert json.loads(reply.stdout)["usage"] == {"http_requests": 1, "response_bytes": 315, "cost_usd": "0.00"}
    assert b"private-artifact-sentinel" not in reply.stdout
    ready.unlink()
    assert not job("run", *argv_id, "--config", str(config))["engine_executed"]
    job("get_status", *argv_id)
    subprocess.run(maintenance, env=env, cwd=tmp_path, capture_output=True, timeout=15, check=True)
    assert not list(inbox.glob("*.ready"))
    assert calls.read_text().splitlines() == ["diagnostic_mixed"]
