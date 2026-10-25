"""Neutral RED: FF fetch_statements thin client contract (stubbed transport)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import ff_financial_statements  # noqa: E402
from filing_contracts import FilingFetchError  # noqa: E402

ENVELOPE = {
    "schema_version": "financial-statements-response/1",
    "status": "complete",
    "company_identity": {
        "canonical_name": "中微公司",
        "market": "CN",
        "exchange": "SSE",
        "security_id": "688012",
    },
    "statements": [
        {
            "statement_type": "income_statement",
            "status": "complete",
            "provider": "sina_finance",
            "knowledge_mode": "current_snapshot",
            "point_in_time_quality": "current_snapshot",
            "coverage": {"observed_periods": 36, "pages": 4},
            "usage": {"http_requests": 5, "response_bytes": 196351, "cost_usd": "0.00"},
            "reports": [],
        }
    ],
    "usage": {"http_requests": 5, "response_bytes": 196351, "cost_usd": "0.00"},
    "retrieved_at": "2026-10-25T13:00:00Z",
}

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


def _wiki_root(tmp_path: Path) -> Path:
    root = tmp_path / "wiki"
    (root / "config").mkdir(parents=True)
    (root / "config" / "source_catalog.yaml").write_text(
        "schema_version: '1.0'\ncatalog_dir: '${PROJECT_ROOT}/.source_catalog'\n"
        "roots:\n  - root_id: company_raw\n    kind: company_raw\n    path: companies\n",
        encoding="utf-8",
    )
    (root / "companies").mkdir(exist_ok=True)
    launcher = tmp_path / "company_wiki.json"
    launcher.write_text(
        json.dumps(
            {"schema_version": "1.0", "company_wiki_root": str(root)}, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    return launcher


def _completed(stdout: dict, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=json.dumps(stdout, ensure_ascii=False).encode("utf-8"),
        stderr=b"",
    )


class TestThinClientContract:
    def test_command_targets_cwp_financial_statements_cli(self, tmp_path):
        config = _wiki_root(tmp_path)
        captured: dict = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return _completed(ENVELOPE)

        with patch.object(ff_financial_statements, "_run_bounded_json", side_effect=fake_run):
            envelope = ff_financial_statements.fetch_statements(
                config_path=config, request=REQUEST, timeout_seconds=60
            )
        assert envelope["status"] == "complete"
        command = captured["command"]
        assert command[:4] == [
            sys.executable, "-m",
            "company_wiki.source_catalog.financial_statements.cli",
        ]
        assert "--wiki-root" in command
        wiki = Path(command[command.index("--wiki-root") + 1])
        assert (wiki / "config" / "source_catalog.yaml").is_file()

    def test_request_travels_on_stdin_and_response_passthrough(self, tmp_path):
        config = _wiki_root(tmp_path)
        with patch.object(
            ff_financial_statements,
            "_run_bounded_json",
            return_value=(
                json.dumps(ENVELOPE, ensure_ascii=False).encode("utf-8"),
                b"",
                0,
            ),
        ) as mock_run:
            envelope = ff_financial_statements.fetch_statements(
                config_path=config, request=REQUEST, timeout_seconds=60
            )
        sent = mock_run.call_args.kwargs.get("input_bytes")
        assert json.loads(sent.decode("utf-8")) == REQUEST
        assert envelope["schema_version"] == "financial-statements-response/1"

    def test_invalid_request_raises_request_error(self, tmp_path):
        config = _wiki_root(tmp_path)
        with pytest.raises(FilingFetchError) as excinfo:
            ff_financial_statements.fetch_statements(
                config_path=config,
                request=dict(REQUEST, statements=["bogus"]),
                timeout_seconds=60,
            )
        assert excinfo.value.code == "request_error"

    def test_reuse_only_without_limits_is_valid_locally(self, tmp_path):
        config = _wiki_root(tmp_path)
        request = dict(REQUEST, intent="reuse_only")
        request.pop("acquisition_limits")
        with patch.object(
            ff_financial_statements,
            "_run_bounded_json",
            return_value=(
                json.dumps(dict(ENVELOPE, status="not_found"), ensure_ascii=False).encode("utf-8"),
                b"",
                0,
            ),
        ):
            envelope = ff_financial_statements.fetch_statements(
                config_path=config, request=request, timeout_seconds=60
            )
        assert envelope["status"] == "not_found"

    def test_cwp_child_failure_maps_to_upstream_error(self, tmp_path):
        config = _wiki_root(tmp_path)
        with patch.object(
            ff_financial_statements,
            "_run_bounded_json",
            side_effect=FilingFetchError("child failed", code="upstream_error"),
        ):
            with pytest.raises(FilingFetchError) as excinfo:
                ff_financial_statements.fetch_statements(
                    config_path=config, request=REQUEST, timeout_seconds=60
                )
        assert excinfo.value.code == "upstream_error"

    def test_unknown_response_schema_is_rejected(self, tmp_path):
        config = _wiki_root(tmp_path)
        bogus = dict(ENVELOPE, schema_version="financial-statements-response/9")
        with patch.object(
            ff_financial_statements,
            "_run_bounded_json",
            return_value=(
                json.dumps(bogus, ensure_ascii=False).encode("utf-8"), b"", 0
            ),
        ):
            with pytest.raises(FilingFetchError):
                ff_financial_statements.fetch_statements(
                    config_path=config, request=REQUEST, timeout_seconds=60
                )


class TestCliMain:
    def _run_main(self, tmp_path, request, extra=(), stdin=True):
        argv = ["--config", str(_wiki_root(tmp_path)), *extra]
        if stdin:
            stdin_text = json.dumps(request, ensure_ascii=False)
        else:
            request_file = tmp_path / "request.json"
            request_file.write_text(
                json.dumps(request, ensure_ascii=False), encoding="utf-8"
            )
            argv += ["--request-file", str(request_file)]
            stdin_text = None
        from fetch_statements import main

        buffer = io.StringIO()
        with patch.object(
            ff_financial_statements,
            "_run_bounded_json",
            return_value=(
                json.dumps(ENVELOPE, ensure_ascii=False).encode("utf-8"), b"", 0
            ),
        ):
            if stdin_text is not None:
                with patch("sys.stdin", io.StringIO(stdin_text)):
                    with patch("sys.stdout", buffer):
                        code = main(argv)
            else:
                with patch("sys.stdout", buffer):
                    code = main(argv)
        return code, json.loads(buffer.getvalue())

    def test_main_success_envelope_exit_zero(self, tmp_path):
        code, payload = self._run_main(tmp_path, REQUEST)
        assert code == 0
        assert payload["schema_version"] == "financial-statements-response/1"

    def test_main_request_file_mode(self, tmp_path):
        code, payload = self._run_main(tmp_path, REQUEST, stdin=False)
        assert code == 0
        assert payload["status"] == "complete"

    def test_main_invalid_request_exits_two(self, tmp_path):
        code, payload = self._run_main(tmp_path, dict(REQUEST, market="XX"))
        assert code == 2
        assert payload["status"] == "request_error"
