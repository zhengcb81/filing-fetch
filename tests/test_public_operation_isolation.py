"""MB-FF public operation isolation.

The real FF entry points run as subprocesses from an empty working directory.
Every company-wiki/ET operation is a configured fixture command; no sibling
checkout, production ``config/company_wiki.json`` or inherited ``PYTHONPATH``
is visible.  These tests observe the launched argv/cwd/stdin instead of
patching FF's private helpers.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
# C-phase runs this same module against the canonical installed runtime by
# setting MBFF_RUNTIME_ROOT; the default stays the checkout under test.
RUNTIME_ROOT = Path(os.environ.get("MBFF_RUNTIME_ROOT", str(ROOT)))
SCRIPTS = RUNTIME_ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "public_operation_isolation"
PY = sys.executable
OPERATIONS = (
    "catalog",
    "query",
    "local_prepare",
    "open",
    "transcript_import",
    "financial_statements",
)


def _v2_request(*, intent: str = "reuse_only", companion: dict | None = None) -> dict:
    request = {
        "schema_version": "2.0",
        "company_query": "AMD",
        "market": "US",
        "document_kind": "annual_report",
        "fiscal_year": 2025,
        "as_of_date": "2026-07-18",
        "filing_intent": intent,
    }
    if intent == "fetch_if_missing":
        request["acquisition_limits"] = {
            "max_bytes": 5_000_000,
            "timeout_seconds": 30,
            "max_cost_usd": "1.00",
        }
    if companion is not None:
        request["companion_transcript"] = companion
    return request


def _companion(*, intent: str = "fetch_if_missing") -> dict:
    option = {
        "intent": intent,
        "fiscal_year": 2026,
        "fiscal_quarter": 3,
    }
    if intent != "reuse_only":
        option["acquisition_limits"] = {
            "max_bytes": 1_000_000,
            "timeout_seconds": 10,
            "max_cost_usd": "0.00",
        }
    return option


def _statements_request() -> dict:
    return {
        "schema_version": "financial-statements-request/1",
        "company_query": "中微公司",
        "market": "CN",
        "statements": ["income_statement", "balance_sheet", "cash_flow"],
        "report_types": ["annual", "semi_annual", "q1", "q3"],
        "period_end_from": "2016-01-01",
        "period_end_to": "2026-06-30",
        "knowledge_mode": "current_snapshot",
        "as_of_date": "2026-10-25",
        "intent": "fetch_if_missing",
        "acquisition_limits": {
            "max_bytes": 8_000_000,
            "timeout_seconds": 60,
            "max_cost_usd": "0.00",
        },
    }


class Harness:
    """One isolated deployment: empty cwd, explicit config, fixture services."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        scenario: str = "query_hit",
        query_sequence: str = "found",
        statements_status: str = "complete",
        import_mode: str = "imported",
        et_usage: str = "known",
        et_result: str = "fetched",
        statements_diagnostic_bytes: int | None = None,
        poison_company_wiki: bool = False,
        commands: dict[str, list[str]] | None = None,
    ) -> None:
        self.base = tmp_path / "deployment"
        self.empty_cwd = self.base / "empty-cwd"
        self.service_dir = self.base / "service"
        self.et_dir = self.base / "et-tools"
        self.jobs_dir = self.base / "jobs"
        for directory in (self.empty_cwd, self.service_dir, self.et_dir, self.jobs_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.service = self.service_dir / "independent_service.py"
        self.service.write_text(
            (FIXTURES / "independent_service.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.et_tool = self.et_dir / "transcript_tool.py"
        self.et_tool.write_text(
            (FIXTURES / "transcript_tool.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.log = self.base / "calls.jsonl"
        self.config = self.base / "company_wiki.json"
        if commands is None:
            commands = {
                name: [PY, "-B", str(self.service), name] for name in OPERATIONS
            }
        self.commands = commands
        self.config.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "connection": {
                        "cwd": str(self.empty_cwd),
                        "commands": commands,
                    },
                    "earnings_transcripts_tool": str(self.et_tool),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.env = os.environ.copy()
        for name in (
            "PYTHONPATH",
            "EARNINGS_TRANSCRIPTS_TOOL",
            "FMP_API_KEY",
            "FMP_API_KEY_FILE",
        ):
            self.env.pop(name, None)
        self.env.update(
            {
                "PYTHONUTF8": "1",
                "MBFF_CALL_LOG": str(self.log),
                "MBFF_SCENARIO": scenario,
                "MBFF_EMPTY_CWD": str(self.empty_cwd),
                "MBFF_QUERY_SEQUENCE": query_sequence,
                "MBFF_STATEMENTS_STATUS": statements_status,
                "MBFF_IMPORT_MODE": import_mode,
                "MBFF_ET_USAGE": et_usage,
                "MBFF_ET_RESULT": et_result,
            }
        )
        if statements_diagnostic_bytes is not None:
            self.env["MBFF_STATEMENTS_DIAGNOSTIC_BYTES"] = str(
                statements_diagnostic_bytes
            )
        if poison_company_wiki:
            poison = self.base / "poison"
            package = poison / "company_wiki"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text(
                'raise RuntimeError("FF imported a sibling company_wiki implementation")\n',
                encoding="utf-8",
            )
            self.env["PYTHONPATH"] = str(poison)

    def write_json(self, name: str, payload: dict) -> Path:
        path = self.base / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def run(
        self,
        script: str,
        arguments: list[str],
        *,
        stdin: dict | None = None,
        timeout: float = 90,
    ) -> subprocess.CompletedProcess[bytes]:
        input_bytes = (
            json.dumps(stdin, ensure_ascii=False).encode("utf-8")
            if stdin is not None
            else b""
        )
        return subprocess.run(
            [PY, "-B", str(SCRIPTS / script), *arguments],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.empty_cwd),
            env=self.env,
            timeout=timeout,
        )

    def run_json(
        self,
        script: str,
        arguments: list[str],
        *,
        stdin: dict | None = None,
        expected_exit: int = 0,
    ) -> dict:
        completed = self.run(script, arguments, stdin=stdin)
        assert completed.returncode == expected_exit, (
            f"{script} exit {completed.returncode}\n"
            f"stdout={completed.stdout.decode('utf-8', 'replace')}\n"
            f"stderr={completed.stderr.decode('utf-8', 'replace')}"
        )
        return json.loads(completed.stdout.decode("utf-8"))

    def calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [
            json.loads(line)
            for line in self.log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def operations(self) -> list[str]:
        return [call["operation"] for call in self.calls()]

    def request_path(self, payload: dict, name: str = "request.json") -> str:
        return str(self.write_json(name, payload))

    def filing_arguments(self, request: dict, name: str = "request.json") -> list[str]:
        return ["--config", str(self.config), "--request-file", self.request_path(request, name)]


def _assert_no_sibling_environment(calls: list[dict], empty_cwd: Path) -> None:
    assert calls, "no fixture service was launched"
    for call in calls:
        assert call["cwd"] == str(empty_cwd), call
        assert call["pythonpath"] is None, call
        assert call["full_argv"][0].endswith("independent_service.py"), call


def test_filing_query_hit_is_provider_free_and_uses_only_query_command(tmp_path):
    harness = Harness(tmp_path)
    payload = harness.run_json("fetch_filing.py", harness.filing_arguments(_v2_request()))
    calls = harness.calls()
    _assert_no_sibling_environment(calls, harness.empty_cwd)
    assert harness.operations() == ["catalog", "query"]
    assert calls[0]["argv"][1] == "identify"
    assert calls[1]["stdin"]["allow_download"] is False
    assert calls[1]["stdin"]["entity"] == "Advanced Micro Devices, Inc."
    assert payload["schema_version"] == "2.0"
    assert payload["status"] == "source_candidate"
    assert payload["filing"]["status"] == "source_candidate"
    assert payload["filing"]["download_events"] == 0
    assert payload["transcript"]["status"] == "not_requested"
    assert payload["calls"] == 2
    assert payload["downloads"] == 0
    assert "ensure" not in json.dumps(calls)
    assert "local_prepare" not in harness.operations()


def test_filing_query_miss_prepares_local_once_then_queries_again(tmp_path):
    harness = Harness(tmp_path, query_sequence="not_found,found")
    payload = harness.run_json("fetch_filing.py", harness.filing_arguments(_v2_request()))
    calls = harness.calls()
    _assert_no_sibling_environment(calls, harness.empty_cwd)
    assert harness.operations() == ["catalog", "query", "local_prepare", "query"]
    prepare = calls[2]
    assert prepare["stdin"]["schema_version"] == "local-source-prepare-request/1"
    assert prepare["stdin"]["source_request"]["allow_download"] is False
    assert calls[3]["stdin"]["allow_download"] is False
    assert payload["status"] == "source_candidate"
    assert payload["filing"]["download_events"] == 0
    assert payload["calls"] == 4
    assert "ensure" not in json.dumps(calls)


def test_query_miss_prepare_then_still_missing_does_not_ensure(tmp_path):
    harness = Harness(tmp_path, query_sequence="not_found,not_found")
    completed = harness.run("fetch_filing.py", harness.filing_arguments(_v2_request()))
    assert completed.returncode == 2, completed.stderr.decode("utf-8", "replace")
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["status"] == "not_found"
    assert payload["calls"] == 4
    assert harness.operations() == ["catalog", "query", "local_prepare", "query"]
    assert "ensure" not in json.dumps(harness.calls())


def test_filing_ensure_is_one_bounded_operation_and_gap_stays_gap(tmp_path):
    harness = Harness(tmp_path)
    request = _v2_request(intent="fetch_if_missing")
    payload = harness.run_json("fetch_filing.py", harness.filing_arguments(request))
    calls = harness.calls()
    _assert_no_sibling_environment(calls, harness.empty_cwd)
    assert harness.operations() == ["catalog", "catalog"]
    ensure = calls[1]
    assert ensure["argv"][1] == "ensure"
    assert "--source-ref-v2" in ensure["argv"]
    assert "--allow-download" in ensure["argv"]
    assert payload["status"] == "source_candidate"
    assert payload["filing"]["download_events"] == 0
    assert payload["downloads"] == 0

    gap_harness = Harness(tmp_path / "gap", scenario="ensure_gap")
    gap_payload = gap_harness.run_json(
        "fetch_filing.py", gap_harness.filing_arguments(_v2_request(intent="fetch_if_missing"))
    )
    assert gap_payload["status"] == "gap"
    assert gap_payload["filing"]["status"] == "gap"
    assert gap_payload["filing"]["download_events"] == 0
    assert gap_payload["downloads"] == 0
    assert gap_harness.operations() == ["catalog", "catalog"]


def test_transcript_companion_uses_query_open_import_and_independent_et_command(tmp_path):
    harness = Harness(tmp_path)
    request = _v2_request(companion=_companion())
    payload = harness.run_json("fetch_filing.py", harness.filing_arguments(request))
    calls = harness.calls()
    _assert_no_sibling_environment(
        [call for call in calls if call["operation"] != "et_tool"], harness.empty_cwd
    )
    assert harness.operations() == [
        "catalog",
        "query",
        "query",
        "et_tool",
        "transcript_import",
        "open",
    ]
    et_call = calls[3]
    assert et_call["cwd"] == str(harness.et_dir)
    assert et_call["cwd"] != str(harness.empty_cwd)
    assert et_call["full_argv"][0] == str(harness.et_tool)
    assert et_call["executable"] == PY
    assert et_call["argv"] == [
        "--request-stdin",
        "--include-source-payload",
        "--report-usage",
    ]
    assert et_call["has_fmp_key"] is False
    assert et_call["has_fmp_key_file"] is False
    import_call = calls[4]
    assert import_call["stdin"]["schema_version"] == (
        "company-wiki-transcript-import-request/2"
    )
    assert import_call["stdin"]["candidate"]["document_kind"] == "investor_call_transcript"
    open_call = calls[5]
    assert open_call["cwd"] == str(harness.empty_cwd)
    assert "--document-id" in open_call["argv"]
    transcript = payload["transcript"]
    assert transcript["status"] == "downloaded"
    assert transcript["provider"] == "fmp"
    assert transcript["provider_requests"] == 1
    assert transcript["provider_response_bytes"] > 0
    assert transcript["provider_usage_complete"] is True
    assert payload["filing"]["download_events"] == 0


def test_statements_uses_only_public_three_table_operation(tmp_path):
    harness = Harness(tmp_path)
    payload = harness.run_json(
        "fetch_statements.py",
        ["--config", str(harness.config), "--request-file",
         harness.request_path(_statements_request(), "statements.json")],
    )
    calls = harness.calls()
    _assert_no_sibling_environment(calls, harness.empty_cwd)
    assert harness.operations() == ["financial_statements"]
    request = calls[0]["stdin"]
    assert request["statements"] == [
        "income_statement",
        "balance_sheet",
        "cash_flow",
    ]
    assert "command" not in request and "cwd" not in request
    assert payload["status"] == "complete"
    assert [item["statement_type"] for item in payload["statements"]] == [
        "income_statement",
        "balance_sheet",
        "cash_flow",
    ]


@pytest.mark.parametrize("status", ["complete", "partial", "not_found", "unavailable"])
def test_statements_preserves_business_status(tmp_path, status):
    harness = Harness(tmp_path, statements_status=status)
    payload = harness.run_json(
        "fetch_statements.py",
        ["--config", str(harness.config), "--request-file",
         harness.request_path(_statements_request(), "statements.json")],
    )
    assert payload["status"] == status
    assert harness.operations() == ["financial_statements"]


def test_statements_structured_refusal_is_a_business_answer_not_upstream(tmp_path):
    harness = Harness(tmp_path, statements_status="request_error")
    payload = harness.run_json(
        "fetch_statements.py",
        ["--config", str(harness.config), "--request-file",
         harness.request_path(_statements_request(), "statements.json")],
        expected_exit=2,
    )
    assert payload["status"] == "request_error"
    assert payload["error"] == "fixture request refusal"


def test_statements_rejects_unknown_response_version(tmp_path):
    harness = Harness(tmp_path)
    original = (FIXTURES / "independent_service.py").read_text(encoding="utf-8")
    harness.service.write_text(
        original.replace(
            '"schema_version": "financial-statements-response/1",\n        "status": status,',
            '"schema_version": "financial-statements-response/2",\n        "status": status,',
        ),
        encoding="utf-8",
    )
    payload = harness.run_json(
        "fetch_statements.py",
        ["--config", str(harness.config), "--request-file",
         harness.request_path(_statements_request(), "statements.json")],
        expected_exit=2,
    )
    assert payload["status"] == "upstream_error"


def test_optional_large_diagnostic_does_not_mask_business_stdout(tmp_path):
    harness = Harness(tmp_path, statements_diagnostic_bytes=16_000)
    payload = harness.run_json(
        "fetch_statements.py",
        ["--config", str(harness.config), "--request-file",
         harness.request_path(_statements_request(), "statements.json")],
    )
    assert payload["status"] == "complete"
    assert len(payload["statements"]) == 3


def test_job_reuse_runs_through_the_same_connection_without_redownload(tmp_path):
    harness = Harness(tmp_path)
    body = {
        "schema_version": "ff-job/1",
        "command_id": "mbff-cmd-1",
        "kind": "filing.acquire",
        "idempotency_key": "mbff-idem-1",
        "request": _v2_request(),
    }
    submitted = harness.run_json(
        "ff_job.py",
        ["--jobs-dir", str(harness.jobs_dir), "submit", "--request-file",
         harness.request_path(body, "job.json")],
    )
    assert submitted["status"] == "ok"
    owner_job_id = submitted["owner_job_id"]
    assert owner_job_id.startswith("ffjob-")

    ran = harness.run_json(
        "ff_job.py",
        ["--jobs-dir", str(harness.jobs_dir), "run", "--owner-job-id", owner_job_id,
         "--config", str(harness.config), "--timeout-seconds", "30"],
    )
    assert ran["job"]["status"] == "succeeded"
    calls_after_run = harness.calls()
    _assert_no_sibling_environment(calls_after_run, harness.empty_cwd)
    assert harness.operations() == ["catalog", "query"]
    assert "ensure" not in json.dumps(calls_after_run)
    assert ran["job"]["result"]["download_events"] == 0

    again = harness.run_json(
        "ff_job.py",
        ["--jobs-dir", str(harness.jobs_dir), "run", "--owner-job-id", owner_job_id,
         "--config", str(harness.config), "--timeout-seconds", "30"],
    )
    assert again["job"]["status"] == "succeeded"
    assert len(harness.calls()) == len(calls_after_run), "idempotent run reacquired"

    status = harness.run_json(
        "ff_job.py",
        ["--jobs-dir", str(harness.jobs_dir), "get_status", "--owner-job-id", owner_job_id],
    )
    assert status["job"]["status"] == "succeeded"
    listed = harness.run_json(
        "ff_job.py", ["--jobs-dir", str(harness.jobs_dir), "list_jobs"]
    )
    assert listed["page"]["total"] == 1
    assert listed["items"][0]["owner_job_id"] == owner_job_id


def test_job_companion_runs_end_to_end(tmp_path):
    harness = Harness(tmp_path)
    body = {
        "schema_version": "ff-job/1",
        "command_id": "mbff-cmd-companion",
        "kind": "filing.acquire",
        "idempotency_key": "mbff-idem-companion",
        "request": _v2_request(companion=_companion()),
    }
    submitted = harness.run_json(
        "ff_job.py",
        ["--jobs-dir", str(harness.jobs_dir), "submit", "--request-file",
         harness.request_path(body, "job.json")],
    )
    ran = harness.run_json(
        "ff_job.py",
        ["--jobs-dir", str(harness.jobs_dir), "run", "--owner-job-id",
         submitted["owner_job_id"], "--config", str(harness.config),
         "--timeout-seconds", "30"],
    )
    assert ran["job"]["status"] == "succeeded"
    assert ran["job"]["result"]["download_events"] == 0
    assert harness.operations() == [
        "catalog",
        "query",
        "query",
        "et_tool",
        "transcript_import",
        "open",
    ]


def test_job_engine_uses_one_connection_snapshot(tmp_path, monkeypatch):
    harness = Harness(tmp_path)
    import fetch_filing
    import ff_job_runner

    original = fetch_filing.load_connection_root
    loaded = []

    def counting(config_path, *, skill_root):
        value = original(config_path, skill_root=skill_root)
        loaded.append(value)
        return value

    monkeypatch.setattr(fetch_filing, "load_connection_root", counting)
    envelope, _ = ff_job_runner._run_filing_engine(
        _v2_request(companion=_companion()),
        config_path=harness.config,
        timeout_seconds=30,
        stats={"calls": 0, "downloads": 0},
    )
    assert len(loaded) == 1
    assert envelope["transcript"]["status"] == "downloaded"


def test_explicit_request_context_is_used_without_reloading(tmp_path, monkeypatch):
    harness = Harness(tmp_path)
    import fetch_filing

    context = fetch_filing.RequestContext(
        harness.config,
        fetch_filing.load_company_wiki_root(config_path=harness.config),
    )

    def forbidden(**kwargs):
        raise AssertionError("explicit request_context must not reload config")

    monkeypatch.setattr(fetch_filing, "load_company_wiki_root", forbidden)
    monkeypatch.setenv("MBFF_CALL_LOG", str(harness.log))
    monkeypatch.setenv("MBFF_EMPTY_CWD", str(harness.empty_cwd))
    handle = fetch_filing.resolve_filing(
        request=_v2_request(), request_context=context, source_ref_v2=True
    )
    assert handle["source_ref"]["content_sha256"]
    assert harness.operations() == ["catalog", "query"]


def test_query_hit_never_imports_a_sibling_company_wiki(tmp_path):
    harness = Harness(tmp_path, poison_company_wiki=True)
    payload = harness.run_json("fetch_filing.py", harness.filing_arguments(_v2_request()))
    assert payload["status"] == "source_candidate"
    assert harness.operations() == ["catalog", "query"]


def test_import_failure_keeps_known_provider_usage(tmp_path):
    harness = Harness(tmp_path, import_mode="rejected", et_usage="known")
    request = _v2_request(companion=_companion())
    payload = harness.run_json("fetch_filing.py", harness.filing_arguments(request))
    assert harness.operations() == [
        "catalog",
        "query",
        "query",
        "et_tool",
        "transcript_import",
    ]
    transcript = payload["transcript"]
    assert transcript["status"] == "upstream_error"
    assert transcript["reason"] == "transcript_import_rejected"
    assert transcript["provider_requests"] == 1
    assert transcript["provider_response_bytes"] > 0
    assert transcript["provider_usage_complete"] is True


def test_unknown_provider_usage_stays_unknown_not_zero(tmp_path):
    harness = Harness(tmp_path, import_mode="rejected", et_usage="unknown")
    request = _v2_request(companion=_companion())
    payload = harness.run_json("fetch_filing.py", harness.filing_arguments(request))
    transcript = payload["transcript"]
    assert transcript["status"] == "upstream_error"
    assert transcript["provider_requests"] is None
    assert transcript["provider_response_bytes"] is None
    assert transcript["provider_usage_complete"] is False


def test_invalid_et_stdout_keeps_usage_and_never_invokes_import(tmp_path):
    harness = Harness(tmp_path, et_result="bad_json", et_usage="known")
    request = _v2_request(companion=_companion())
    payload = harness.run_json("fetch_filing.py", harness.filing_arguments(request))
    assert harness.operations() == ["catalog", "query", "query", "et_tool"]
    transcript = payload["transcript"]
    assert transcript["status"] == "provider_unavailable"
    assert transcript["reason"] == "provider_result_invalid"
    assert transcript["provider_requests"] == 1
    assert transcript["provider_usage_complete"] is True


def test_business_requests_cannot_carry_command_fields(tmp_path):
    harness = Harness(tmp_path)
    for script, payload, name in (
        ("fetch_filing.py", {**_v2_request(), "command": ["evil"]}, "filing.json"),
        ("fetch_statements.py", {**_statements_request(), "cwd": "arbitrary"}, "statements.json"),
    ):
        result = harness.run_json(
            script,
            ["--config", str(harness.config), "--request-file",
             harness.request_path(payload, name)],
            expected_exit=2,
        )
        assert result["status"] == "request_error"
    assert harness.calls() == []

    body = {
        "schema_version": "ff-job/1",
        "command_id": "mbff-cmd-bad",
        "kind": "filing.acquire",
        "idempotency_key": "mbff-idem-bad",
        "request": {**_v2_request(), "command": ["evil"]},
    }
    rejected = harness.run_json(
        "ff_job.py",
        ["--jobs-dir", str(harness.jobs_dir), "submit", "--request-file",
         harness.request_path(body, "job.json")],
        expected_exit=2,
    )
    assert rejected["status"] == "request_error"
    assert harness.calls() == []


def test_unconfigured_operation_is_named_and_never_guessed(tmp_path):
    harness = Harness(
        tmp_path,
        commands={"catalog": [PY, "-B", str(FIXTURES / "independent_service.py"), "catalog"]},
    )
    result = harness.run_json(
        "fetch_statements.py",
        ["--config", str(harness.config), "--request-file",
         harness.request_path(_statements_request(), "statements.json")],
        expected_exit=1,
    )
    assert result["status"] == "fatal"
    assert "financial_statements" in result["error"]
    assert harness.calls() == []


def test_one_request_resolves_one_connection_snapshot(tmp_path, monkeypatch):
    """The CLI composition root must not load the same config twice."""
    harness = Harness(tmp_path)
    request = _v2_request(companion=_companion())
    request_file = harness.request_path(request)

    import fetch_filing
    import transcript_tool_transport

    assert Path(fetch_filing.__file__).resolve() == (SCRIPTS / "fetch_filing.py").resolve()
    original = fetch_filing.load_connection_root
    loads: list[Path] = []
    loaded_connections = []

    def counting(config_path, *, skill_root):
        loads.append(Path(config_path))
        connection = original(config_path, skill_root=skill_root)
        loaded_connections.append(connection)
        return connection

    real_transport = transcript_tool_transport.EarningsTranscriptsTransport
    seen: dict = {}

    class CapturingTransport(real_transport):
        def __init__(self, **kwargs):
            seen["wiki_root"] = kwargs.get("wiki_root")
            super().__init__(**kwargs)

    monkeypatch.setattr(fetch_filing, "load_connection_root", counting)
    monkeypatch.setattr(
        transcript_tool_transport, "EarningsTranscriptsTransport", CapturingTransport
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = fetch_filing.main(
            ["--config", str(harness.config), "--request-file", request_file]
        )
    assert exit_code == 0, output.getvalue()
    assert len(loads) == 1, f"config loaded {len(loads)} times: {loads}"
    assert seen["wiki_root"] is loaded_connections[0]
    assert json.loads(output.getvalue())["transcript"]["status"] == "downloaded"


def test_public_samples_expose_required_public_fields():
    samples = FIXTURES / "samples"
    expected = {
        "source_ref.json": {
            "schema_version", "document_id", "source_id", "content_sha256",
            "byte_size", "mime_type",
        },
        "source_candidate.json": {
            "source_ref", "document_id", "source_id", "title", "market",
            "security_id", "capture_ready",
        },
        "query_found.json": {
            "schema_version", "status", "request_id", "matches", "candidates",
        },
        "query_not_found.json": {
            "schema_version", "status", "request_id", "matches", "candidates",
        },
        "local_prepare_ready.json": {
            "schema_version", "status", "reason", "source_ref",
            "blocks_download", "download_events",
        },
        "operation_completed.json": {
            "operation_schema_version", "operation", "status", "request_id",
            "outcome", "download_events", "source_ref", "candidate",
        },
        "operation_gap.json": {
            "operation_schema_version", "operation", "status", "request_id",
            "outcome", "download_events", "gap_plan",
        },
        "transcript_import_response.json": {
            "schema_version", "status", "source_ref", "content_sha256",
        },
        "transcript_usage_known.json": {
            "schema_version", "request_id", "usage_complete", "usage",
        },
        "transcript_usage_unknown.json": {
            "schema_version", "request_id", "usage_complete", "usage",
        },
        "error_envelope.json": {
            "schema_version", "status", "filing", "transcript", "calls",
            "downloads",
        },
    }
    for name, keys in expected.items():
        payload = json.loads((samples / name).read_text(encoding="utf-8"))
        assert keys <= set(payload), name
    unknown = json.loads(
        (samples / "transcript_usage_unknown.json").read_text(encoding="utf-8")
    )
    assert unknown["usage"] is None
    assert unknown["usage_complete"] is False


def test_scripts_never_import_a_sibling_implementation():
    forbidden = {
        "company_wiki",
        "httpx",
        "requests",
        "sqlite3",
        "fitz",
        "docling",
        "sina_provider",
        "canonical_writer",
        "repository",
        "urllib.request",
    }
    violations: list[str] = []
    for path in sorted(SCRIPTS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if any(name == item or name.startswith(item + ".") for item in forbidden):
                    violations.append(f"{path.name}: {name}")
    assert violations == []
