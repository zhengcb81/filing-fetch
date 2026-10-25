"""Neutral RED: real fetch_statements.py subprocess against a fake CWP CLI.

Mirrors the s3_fake_cwp pattern: a fake ``company_wiki.source_catalog.
financial_statements.cli`` module is installed as a temp package and selected
via PYTHONPATH; the real FF CLI process then runs end to end.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[2]

FAKE_CLI = '''
import json
import os
import sys

payload = json.loads(sys.stdin.read())
mode = os.environ.get("W19_FAKE_MODE", "ok")
if payload.get("market") != "CN":
    print(json.dumps({"schema_version": "financial-statements-response/1",
                      "status": "request_error", "error": "unsupported market"},
                     ensure_ascii=False))
    raise SystemExit(2)
if mode == "unavailable":
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
    (package / "__init__.py").write_text("", encoding="utf-8")
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
    return subprocess.run(
        argv, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(SKILL_ROOT), env=env, timeout=60,
    )


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
