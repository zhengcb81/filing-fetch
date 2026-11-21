"""F2-FF-SHORT: one short CLI call emits an optional, replay-safe observation.

Every case runs the real ``scripts/fetch_filing.py`` entry point against an
isolated deployment: an exclusive short temp root, an explicit config, and a
controlled mock connector.  The sidecar is compared with the same call run
without it; the business envelope, stderr and exit code must stay identical.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
SHARED_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "public_operation_isolation"
PY = sys.executable
OPERATIONS = ("catalog", "query", "local_prepare", "open", "transcript_import")

sys.path.insert(0, str(SCRIPTS))
import fetch_filing  # noqa: E402
import ff_short_feedback  # noqa: E402

LIMITS = {"max_bytes": 5_000_000, "timeout_seconds": 60, "max_cost_usd": "1.00"}


def _v2_request(intent: str = "reuse_only", **overrides) -> dict:
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
        request["acquisition_limits"] = dict(LIMITS)
    request.update(overrides)
    return request


def _latest_request(intent: str = "reuse_only") -> dict:
    request = {
        "schema_version": "2.0",
        "company_query": "AMD",
        "market": "US",
        "document_kind": "annual_report",
        "mode": "latest_as_of",
        "as_of_date": "2026-07-18",
        "filing_intent": intent,
    }
    if intent == "reuse_only":
        request["acquisition_limits"] = dict(LIMITS)
    return request


def _legacy_latest_request() -> dict:
    return {
        "schema_version": "1.2",
        "company_query": "AMD",
        "market": "US",
        "document_kind": "annual_report",
        "mode": "latest_as_of",
        "as_of_date": "2026-07-18",
    }


def _companion(intent: str = "fetch_if_missing") -> dict:
    option = {"intent": intent, "fiscal_year": 2026, "fiscal_quarter": 3}
    if intent == "fetch_if_missing":
        option["acquisition_limits"] = {
            "max_bytes": 1_000_000,
            "timeout_seconds": 10,
            "max_cost_usd": "0.00",
        }
    return option


class Harness:
    """One isolated deployment: empty cwd, explicit config, fixture services."""

    def __init__(
        self,
        base: Path,
        *,
        scenario: str = "reuse_hit",
        et_usage: str = "known",
        et_result: str = "fetched",
    ) -> None:
        self.base = base
        self.empty_cwd = base / "empty-cwd"
        self.service_dir = base / "service"
        self.empty_cwd.mkdir(parents=True, exist_ok=True)
        self.service_dir.mkdir(parents=True, exist_ok=True)
        self.service = self.service_dir / "connector.py"
        shutil.copyfile(FIXTURES / "short_feedback" / "connector.py", self.service)
        self.et_tool = self.service_dir / "transcript_tool.py"
        shutil.copyfile(SHARED_FIXTURES / "transcript_tool.py", self.et_tool)
        self.log = base / "calls.jsonl"
        self.config = base / "company_wiki.json"
        self.commands = {
            name: [PY, "-B", str(self.service), name] for name in OPERATIONS
        }
        self.config.write_text(
            json.dumps({
                "schema_version": "1.0",
                "connection": {"cwd": str(self.empty_cwd), "commands": self.commands},
                "earnings_transcripts_tool": str(self.et_tool),
            }),
            encoding="utf-8",
        )
        self.env = os.environ.copy()
        for name in (
            "PYTHONPATH", "EARNINGS_TRANSCRIPTS_TOOL", "FMP_API_KEY", "FMP_API_KEY_FILE",
            "RESEARCH_FEEDBACK_OUT", "RESEARCH_FEEDBACK_RUN_ID", "RESEARCH_FEEDBACK_ATTEMPT_ID",
        ):
            self.env.pop(name, None)
        self.env.update({
            "PYTHONUTF8": "1",
            "RESEARCH_FEEDBACK_DIR": str(self.base / "native-observations"),
            "FF_SHORT_CALL_LOG": str(self.log),
            "FF_SHORT_SCENARIO": scenario,
            "FF_SHORT_EMPTY_CWD": str(self.empty_cwd),
            "MBFF_CALL_LOG": str(self.log),
            "MBFF_ET_USAGE": et_usage,
            "MBFF_ET_RESULT": et_result,
        })
        self._sequence = 0

    def run(
        self,
        request: object,
        *,
        via: str = "file",
        raw: bool = False,
        out: Path | str | None = None,
        run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        env = dict(self.env)
        if out is not None:
            env["RESEARCH_FEEDBACK_OUT"] = str(out)
        if run_id is not None:
            env["RESEARCH_FEEDBACK_RUN_ID"] = run_id
        if attempt_id is not None:
            env["RESEARCH_FEEDBACK_ATTEMPT_ID"] = attempt_id
        args = ["--config", str(self.config)]
        text = request if raw else json.dumps(request, ensure_ascii=False)
        if via == "stdin":
            input_bytes = text.encode("utf-8")
        else:
            self._sequence += 1
            path = self.base / f"request-{self._sequence}.json"
            path.write_text(text, encoding="utf-8")
            args.extend(("--request-file", str(path)))
            input_bytes = b""
        return subprocess.run(
            [PY, "-B", str(SCRIPTS / "fetch_filing.py"), *args],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.empty_cwd),
            env=env,
            timeout=90,
        )

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


def _rows(path: Path | str) -> list[dict]:
    return [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _by_check(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["check_id"], []).append(row)
    return grouped


def _assert_row_shape(rows: list[dict]) -> None:
    assert rows, "the enabled sidecar must contain at least the start row"
    for row in rows:
        assert row["schema_version"] == "feedback-observation/1"
        assert row["owner"] == "filing-fetch"
        for name in ("run_id", "attempt_id", "step_id", "check_id", "expected", "actual"):
            assert isinstance(row[name], str) and row[name]
        assert row["disposition"] in ff_short_feedback.DISPOSITIONS
        assert row["evidence_ref"].startswith("ff-short/1/")
        assert not row["evidence_ref"].startswith("ff-job/")


def _assert_protocol(rows: list[dict]) -> None:
    _assert_row_shape(rows)
    start = rows[0]
    assert start["check_id"] == "action-started"
    assert start["terminal_check_id"] == "request-outcome"
    assert start["expected"] == start["actual"] == "started"
    assert [row["check_id"] for row in rows].count("action-started") == 1
    assert [row["check_id"] for row in rows].count("request-outcome") == 1


def _single(rows: list[dict], check_id: str) -> dict:
    matches = [row for row in rows if row["check_id"] == check_id]
    assert len(matches) == 1, (check_id, rows)
    return matches[0]


def test_exact_local_hit_observes_pure_reuse_without_changing_the_envelope(tmp_path):
    enabled_harness = Harness(tmp_path / "enabled")
    request = _v2_request()
    out = tmp_path / "observations.jsonl"
    enabled = enabled_harness.run(request, out=out, run_id="run-1", attempt_id="try-1")
    baseline = Harness(tmp_path / "baseline").run(request)

    assert enabled.returncode == baseline.returncode == 0
    assert enabled.stdout == baseline.stdout
    assert enabled.stderr == baseline.stderr

    rows = _rows(out)
    _assert_protocol(rows)
    outcome = _single(rows, "request-outcome")
    assert outcome["expected"] == "terminal"
    assert outcome["actual"] == "source_candidate/reused_existing"
    start = _single(rows, "provider-start")
    assert (start["expected"], start["actual"], start["disposition"]) == (
        "not_started", "not_started", "expected")
    usage = _single(rows, "provider-usage")
    assert (usage["expected"], usage["actual"], usage["disposition"]) == (
        "accounted", "not_applicable", "expected")
    download = _single(rows, "download-receipt")
    assert (download["actual"], download["disposition"]) == ("0", "expected")
    assert "transcript-provider-usage" not in {row["check_id"] for row in rows}
    assert {row["run_id"] for row in rows} == {"run-1"}
    assert {row["attempt_id"] for row in rows} == {"try-1"}
    assert len({row["step_id"] for row in rows}) == 1
    assert len({row["evidence_ref"] for row in rows}) == 1

    assert enabled_harness.operations() == ["catalog", "query"]
    calls = enabled_harness.calls()
    assert calls[0]["argv"][1] == "identify"
    assert calls[1]["stdin"]["allow_download"] is False
    assert "ensure" not in json.dumps(calls)
    # The launched producer never inherits the sidecar variables.
    for call in calls:
        assert call["feedback_out"] is None
        assert call["feedback_run_id"] is None
        assert call["feedback_attempt_id"] is None


def test_not_found_is_observed_with_proven_zero_usage(tmp_path):
    harness = Harness(tmp_path, scenario="query_miss")
    out = tmp_path / "observations.jsonl"
    completed = harness.run(_v2_request(), out=out)

    assert completed.returncode == 2
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["status"] == "not_found"
    cause = payload["filing"]["upstream_cause"]
    assert cause["operation"] == "query"
    assert cause["provider_started"] is False
    assert cause["usage_complete"] is True

    rows = _rows(out)
    _assert_protocol(rows)
    assert _single(rows, "request-outcome")["actual"] == "not_found/no_local_match"
    start = _single(rows, "provider-start")
    assert (start["actual"], start["disposition"]) == ("not_started", "expected")
    assert _single(rows, "provider-usage")["actual"] == "not_applicable"
    assert _single(rows, "download-receipt")["actual"] == "0"
    assert harness.operations() == ["catalog", "query", "local_prepare", "query"]


def test_latest_metadata_discovery_keeps_usage_unknown_without_native_metering(tmp_path):
    harness = Harness(tmp_path, scenario="latest_reuse")
    out = tmp_path / "observations.jsonl"
    completed = harness.run(_latest_request(), out=out)

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["filing"]["resolution_outcome"] == "reused_after_discovery"
    assert payload["downloads"] == 0
    assert "acquisition_observation" not in payload

    rows = _rows(out)
    _assert_protocol(rows)
    assert _single(rows, "request-outcome")["actual"] == (
        "source_candidate/reused_after_discovery")
    assert "provider-start" not in {row["check_id"] for row in rows}
    usage = _single(rows, "provider-usage")
    assert (usage["actual"], usage["disposition"]) == ("unknown", "unknown")
    assert _single(rows, "download-receipt")["actual"] == "0"

    operations = harness.calls()
    assert harness.operations() == ["catalog", "catalog"]
    ensure = operations[1]["argv"]
    assert "ensure" in ensure and "--source-ref-v2" in ensure
    assert ensure[ensure.index("--mode") + 1] == "latest_as_of"
    assert "--allow-download" not in ensure


def test_controlled_first_fetch_separates_usage_from_the_download_receipt(tmp_path):
    harness = Harness(tmp_path, scenario="download")
    out = tmp_path / "observations.jsonl"
    completed = harness.run(_v2_request("fetch_if_missing"), out=out)

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["filing"]["resolution_outcome"] == "downloaded_new"
    assert payload["downloads"] == 1

    rows = _rows(out)
    _assert_protocol(rows)
    assert _single(rows, "request-outcome")["actual"] == "source_candidate/downloaded_new"
    usage = _single(rows, "provider-usage")
    assert (usage["actual"], usage["disposition"]) == ("known", "expected")
    assert _single(rows, "download-receipt")["actual"] == "1"
    assert "provider-start" not in {row["check_id"] for row in rows}

    calls = harness.calls()
    assert harness.operations() == ["catalog", "catalog"]
    ensure = calls[1]["argv"]
    assert "ensure" in ensure and "--allow-download" in ensure
    assert sum(1 for call in calls if "ensure" in call["argv"]) == 1


def test_missing_limits_rejection_is_a_known_not_started_call(tmp_path):
    harness = Harness(tmp_path)
    request = _v2_request("fetch_if_missing")
    request.pop("acquisition_limits")
    out = tmp_path / "observations.jsonl"
    completed = harness.run(request, out=out)

    assert completed.returncode == 2
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["status"] == "request_error"
    assert payload["filing"]["request_diagnostic"] == {
        "schema_version": "filing-request-diagnostic/1",
        "reason": "acquisition_limits_invalid",
        "field_path": "acquisition_limits",
    }
    assert harness.calls() == []

    rows = _rows(out)
    _assert_protocol(rows)
    assert _single(rows, "request-outcome")["actual"] == (
        "request_error/acquisition_limits_invalid")
    start = _single(rows, "provider-start")
    assert (start["expected"], start["actual"], start["disposition"]) == (
        "not_started", "not_started", "expected")
    assert _single(rows, "provider-usage")["actual"] == "known"
    assert _single(rows, "download-receipt")["actual"] == "0"


def test_corrupt_item_surfaces_failed_import_with_known_zero_usage(tmp_path):
    harness = Harness(tmp_path, scenario="corrupt")
    out = tmp_path / "observations.jsonl"
    completed = harness.run(_v2_request("fetch_if_missing"), out=out)

    assert completed.returncode == 2
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["status"] == "upstream_error"
    failure = payload["filing"]["acquisition_failure"]
    assert failure["code"] == "canonical_import_failed"
    assert failure["provider_started"] is False
    assert failure["usage_complete"] is True
    assert payload["downloads"] == 0

    rows = _rows(out)
    _assert_protocol(rows)
    assert _single(rows, "request-outcome")["actual"] == (
        "upstream_error/canonical_import_failed")
    usage = _single(rows, "provider-usage")
    assert (usage["actual"], usage["disposition"]) == ("known", "expected")
    assert _single(rows, "download-receipt")["actual"] == "0"
    assert _single(rows, "request-outcome")["disposition"] == "deviation"
    assert all(r["disposition"] == "expected" for r in rows if r["check_id"] != "request-outcome")


def test_v2_gap_keeps_missing_metering_unknown(tmp_path):
    harness = Harness(tmp_path, scenario="ensure_gap")
    out = tmp_path / "observations.jsonl"
    completed = harness.run(_v2_request("fetch_if_missing"), out=out)

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["status"] == "gap"
    assert payload["filing"]["status"] == "gap"
    assert payload["downloads"] == 0

    rows = _rows(out)
    _assert_protocol(rows)
    assert _single(rows, "request-outcome")["actual"] == "gap"
    assert "provider-start" not in {row["check_id"] for row in rows}
    usage = _single(rows, "provider-usage")
    assert (usage["actual"], usage["disposition"]) == ("unknown", "unknown")
    assert _single(rows, "download-receipt")["actual"] == "0"
    assert harness.operations() == ["catalog", "catalog"]


def test_legacy_gap_keeps_missing_fields_unknown(tmp_path):
    harness = Harness(tmp_path, scenario="ensure_gap")
    request = _legacy_latest_request()
    out = tmp_path / "observations.jsonl"
    enabled = harness.run(request, out=out)
    baseline = Harness(tmp_path / "baseline", scenario="ensure_gap").run(request)

    assert enabled.returncode == baseline.returncode == 0
    assert enabled.stdout == baseline.stdout
    assert enabled.stderr == baseline.stderr
    payload = json.loads(enabled.stdout.decode("utf-8"))
    assert payload["status"] == "gap"
    assert "calls" not in payload and "downloads" not in payload

    rows = _rows(out)
    _assert_protocol(rows)
    assert _single(rows, "request-outcome")["actual"] == "gap"
    assert "provider-start" not in {row["check_id"] for row in rows}
    usage = _single(rows, "provider-usage")
    assert (usage["actual"], usage["disposition"]) == ("unknown", "unknown")
    download = _single(rows, "download-receipt")
    assert (download["actual"], download["disposition"]) == ("unknown", "unknown")


def test_companion_fee_is_a_separate_unknown_scope(tmp_path):
    harness = Harness(tmp_path, scenario="zero_companion")
    request = _v2_request("fetch_if_missing", companion_transcript=_companion())
    out = tmp_path / "observations.jsonl"
    completed = harness.run(request, out=out)

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["filing"]["resolution_outcome"] == "reused_existing"
    assert payload["transcript"]["status"] == "downloaded"
    assert payload["transcript"]["provider_requests"] == 1
    assert payload["transcript"]["provider_usage_complete"] is True

    rows = _rows(out)
    _assert_protocol(rows)
    filing_usage = _single(rows, "provider-usage")
    assert (filing_usage["actual"], filing_usage["disposition"]) == ("known", "expected")
    transcript_usage = _single(rows, "transcript-provider-usage")
    assert (transcript_usage["actual"], transcript_usage["disposition"]) == (
        "unknown", "unknown")
    assert transcript_usage["step_id"] == filing_usage["step_id"] + "/transcript"
    assert transcript_usage["evidence_ref"] == filing_usage["evidence_ref"]
    assert "provider-start" not in {row["check_id"] for row in rows}

    operations = harness.operations()
    assert operations == [
        "catalog", "catalog", "query", "et_tool", "transcript_import", "open",
    ]
    assert sum(1 for item in operations if item == "et_tool") == 1


def _import_observations(rows: list[dict], seen: set[tuple]) -> int:
    """Model the consumer's duplicate-import rule on the protocol identity."""
    added = 0
    for row in rows:
        key = (row["run_id"], row["attempt_id"], row["step_id"], row["check_id"])
        if key not in seen:
            seen.add(key)
            added += 1
    return added


def test_same_run_and_attempt_keep_two_content_identities_and_reimport_adds_nothing(
    tmp_path,
):
    reuse = Harness(tmp_path / "reuse", scenario="reuse_hit")
    download = Harness(tmp_path / "download", scenario="download")
    out = tmp_path / "observations.jsonl"
    first = reuse.run(_v2_request(), out=out, run_id="run-x", attempt_id="a1")
    second = download.run(
        _v2_request("fetch_if_missing"), out=out, run_id="run-x", attempt_id="a1")
    assert first.returncode == 0 and second.returncode == 0

    rows = _rows(out)
    _assert_row_shape(rows)
    starts = [row for row in rows if row["check_id"] == "action-started"]
    outcomes = [row for row in rows if row["check_id"] == "request-outcome"]
    assert len(starts) == len(outcomes) == 2
    assert len({row["evidence_ref"] for row in starts}) == 2
    assert len({row["step_id"] for row in starts}) == 2
    assert {row["run_id"] for row in rows} == {"run-x"}
    assert {row["attempt_id"] for row in rows} == {"a1"}
    assert {row["actual"] for row in outcomes} == {
        "source_candidate/reused_existing", "source_candidate/downloaded_new",
    }

    # Every row owns a unique protocol identity, so importing the same file
    # twice adds zero new records; reading it never rewrites the bytes.
    seen: set[tuple] = set()
    assert _import_observations(rows, seen) == len(rows)
    assert _import_observations(rows, seen) == 0
    before = out.read_bytes()
    assert _rows(out) == rows
    assert out.read_bytes() == before


def test_disabled_and_broken_sidecars_leave_the_business_result_untouched(tmp_path):
    baseline = Harness(tmp_path / "baseline").run(_v2_request())
    assert baseline.returncode == 0

    broken = Harness(tmp_path / "broken").run(_v2_request(), out=tmp_path)
    assert broken.returncode == baseline.returncode
    assert broken.stdout == baseline.stdout
    assert broken.stderr == baseline.stderr

    missing_dir = Harness(tmp_path / "missing").run(
        _v2_request(), out=tmp_path / "absent" / "observations.jsonl")
    assert missing_dir.returncode == baseline.returncode
    assert missing_dir.stdout == baseline.stdout
    assert missing_dir.stderr == baseline.stderr
    assert not (tmp_path / "absent").exists()

    disabled = Harness(tmp_path / "disabled")
    disabled.run(_v2_request())
    assert not (disabled.base / "observations.jsonl").exists()


def test_bad_json_is_a_named_request_error_and_keeps_the_start_pair(tmp_path):
    harness = Harness(tmp_path)
    out = tmp_path / "observations.jsonl"
    completed = harness.run("{", raw=True, out=out)

    assert completed.returncode == 2
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["status"] == "request_error"
    rows = _rows(out)
    _assert_protocol(rows)
    assert _single(rows, "request-outcome")["actual"] == "request_error"
    assert _single(rows, "provider-start")["actual"] == "not_started"
    assert _single(rows, "provider-usage")["actual"] == "known"
    assert harness.calls() == []


def test_non_object_request_is_a_named_request_error(tmp_path):
    harness = Harness(tmp_path)
    out = tmp_path / "observations.jsonl"
    completed = harness.run([], out=out)

    assert completed.returncode == 2
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["status"] == "request_error"
    rows = _rows(out)
    _assert_protocol(rows)
    assert _single(rows, "request-outcome")["actual"] == "request_error"
    assert _single(rows, "provider-usage")["actual"] == "known"
    assert harness.calls() == []


@pytest.mark.parametrize(
    ("scenario", "body"),
    [
        ("latest_reuse", _latest_request()),
        ("download", _v2_request("fetch_if_missing")),
        ("ensure_gap", _v2_request("fetch_if_missing")),
        ("corrupt", _v2_request("fetch_if_missing")),
        ("zero_companion", _v2_request(
            "fetch_if_missing", companion_transcript=_companion())),
    ],
    ids=["latest", "download", "gap", "corrupt", "companion"],
)
def test_enabling_the_sidecar_never_changes_the_business_result(
    tmp_path, scenario, body,
):
    enabled = Harness(tmp_path / "enabled", scenario=scenario).run(
        body, out=tmp_path / f"{scenario}.jsonl")
    baseline = Harness(tmp_path / "baseline", scenario=scenario).run(body)
    assert enabled.returncode == baseline.returncode
    assert enabled.stdout == baseline.stdout
    assert enabled.stderr == baseline.stderr


def test_real_utf8_stdin_smoke_writes_the_same_observation(tmp_path):
    harness = Harness(tmp_path / "stdin")
    request = _v2_request(company_query="腾讯控股")
    out = tmp_path / "observations.jsonl"
    completed = harness.run(request, via="stdin", out=out)

    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    payload = json.loads(completed.stdout.decode("utf-8"))
    assert payload["status"] == "source_candidate"
    rows = _rows(out)
    _assert_protocol(rows)
    assert _single(rows, "request-outcome")["actual"] == "source_candidate/reused_existing"
    assert harness.operations() == ["catalog", "query"]
    assert harness.calls()[1]["stdin"]["entity"] == "Advanced Micro Devices, Inc."


def test_short_adapter_rejects_an_unwritable_sidecar_without_raising(tmp_path):
    observation = ff_short_feedback.ShortObservation(
        tmp_path, run_id="run", attempt_id="a1", operation_id="0" * 32,
    )
    observation.started()
    observation.finished(output={"status": "request_error"})


def _identity() -> dict[str, str]:
    return {
        "schema_version": "feedback-observation/1",
        "owner": "filing-fetch",
        "run_id": "run-unit",
        "attempt_id": "try-unit",
        "step_id": "short-filing/unit",
        "evidence_ref": "ff-short/1/unit",
    }


def test_unit_rows_keep_protocol_shape_and_missing_metering_stays_unknown():
    rows = ff_short_feedback.observation_rows(
        output={
            "schema_version": "2.0",
            "status": "source_candidate",
            "filing": {"status": "source_candidate", "resolution_outcome": "reused_existing",
                       "download_events": 0},
            "transcript": {"status": "not_requested"},
            "calls": 2,
            "downloads": 0,
        },
        stats={"calls": 2, "downloads": 0},
        request=_v2_request("fetch_if_missing"),
        allow_download=True,
        identity=_identity(),
    )
    _assert_row_shape(rows)
    assert _single(rows, "provider-usage")["actual"] == "unknown"
    assert _single(rows, "download-receipt")["actual"] == "0"


def test_unit_reuse_started_provider_is_a_deviation_with_the_ff_rule_signature():
    observation = {
        "schema_version": "acquisition-observation/1",
        "usage_scope": "operation",
        "outcome": "downloaded_new",
        "provider_started": True,
        "usage_complete": True,
        "wire_body_bytes": 10,
        "wire_usage_complete": True,
        "entity_body_bytes": 10,
        "http_exchanges": 1,
        "http_exchanges_complete": True,
        "cost_usd": "0.01",
        "http_observation": None,
    }
    rows = ff_short_feedback.observation_rows(
        output={
            "schema_version": "2.0",
            "status": "source_candidate",
            "filing": {"status": "source_candidate", "resolution_outcome": "reused_existing",
                       "download_events": 0},
            "transcript": {"status": "not_requested"},
            "calls": 2,
            "downloads": 0,
            "acquisition_observation": observation,
        },
        stats={"calls": 2, "downloads": 0},
        request=_v2_request(),
        allow_download=False,
        identity=_identity(),
    )
    start = _single(rows, "provider-start")
    assert (start["actual"], start["disposition"]) == ("started", "deviation")
    assert start["issue_key"] == "reuse-started-provider"
    assert _single(rows, "provider-usage")["actual"] == "known"


def test_unit_v1_success_reads_the_resolution_envelope_and_keeps_unknown_metering():
    reuse = ff_short_feedback.observation_rows(
        output={
            "schema_version": "1.1",
            "status": "capture_ready",
            "handle": {"resolution_envelope": {
                "outcome": "reused_exact", "download_events": 0}},
            "calls": 2,
            "downloads": 0,
        },
        stats={"calls": 2, "downloads": 0},
        request={"schema_version": "1.2", "fiscal_year": 2025},
        allow_download=False,
        identity=_identity(),
    )
    _assert_row_shape(reuse)
    assert _single(reuse, "request-outcome")["actual"] == "capture_ready/reused_exact"
    assert _single(reuse, "provider-usage")["actual"] == "not_applicable"
    assert _single(reuse, "download-receipt")["actual"] == "0"

    ensure = ff_short_feedback.observation_rows(
        output={
            "schema_version": "1.1",
            "status": "capture_ready",
            "handle": {"resolution_envelope": {
                "outcome": "reused_exact", "download_events": 0}},
            "calls": 2,
            "downloads": 0,
        },
        stats={"calls": 2, "downloads": 0},
        request={"schema_version": "1.2", "fiscal_year": 2025},
        allow_download=True,
        identity=_identity(),
    )
    usage = _single(ensure, "provider-usage")
    assert (usage["actual"], usage["disposition"]) == ("unknown", "unknown")


def test_unit_v1_error_without_usage_fields_stays_unknown():
    rows = ff_short_feedback.observation_rows(
        output={
            "schema_version": "1.1",
            "status": "upstream_error",
            "error": "safe fixed text",
            "error_code": "upstream_error",
            "retryable": True,
        },
        stats={"calls": 1, "downloads": 0},
        request={"schema_version": "1.2", "mode": "latest_as_of"},
        allow_download=False,
        identity=_identity(),
    )
    _assert_row_shape(rows)
    assert _single(rows, "request-outcome")["actual"] == "upstream_error"
    usage = _single(rows, "provider-usage")
    assert (usage["actual"], usage["disposition"]) == ("unknown", "unknown")
    download = _single(rows, "download-receipt")
    assert (download["actual"], download["disposition"]) == ("unknown", "unknown")


def test_unit_v1_error_uses_the_typed_exception_observation():
    observation = {
        "schema_version": "acquisition-observation/1",
        "usage_scope": "operation",
        "outcome": "reused_before_download",
        "provider_started": False,
        "usage_complete": True,
        "wire_body_bytes": 0,
        "wire_usage_complete": True,
        "entity_body_bytes": 0,
        "http_exchanges": 0,
        "http_exchanges_complete": True,
        "cost_usd": "0.00",
        "http_observation": None,
    }
    error = fetch_filing.FilingFetchError(
        "safe fixed text", code="upstream_error",
        acquisition_observation=observation,
    )
    rows = ff_short_feedback.observation_rows(
        output={
            "schema_version": "1.1",
            "status": "upstream_error",
            "error": "safe fixed text",
            "error_code": "upstream_error",
            "retryable": True,
        },
        error=error,
        stats={"calls": 1, "downloads": 0},
        request={"schema_version": "1.2", "mode": "latest_as_of"},
        allow_download=False,
        identity=_identity(),
    )
    _assert_row_shape(rows)
    usage = _single(rows, "provider-usage")
    assert (usage["actual"], usage["disposition"]) == ("known", "expected")


def test_unit_rejected_v1_companion_scope_is_a_known_zero():
    rows = ff_short_feedback.observation_rows(
        output={
            "schema_version": "1.1",
            "status": "request_error",
            "error": "unknown field",
            "error_code": "request_error",
            "retryable": False,
            "calls": 0,
            "downloads": 0,
        },
        stats={"calls": 0, "downloads": 0},
        request={
            "schema_version": "1.2",
            "companion_transcript": {"intent": "fetch_if_missing"},
        },
        allow_download=False,
        identity=_identity(),
    )
    _assert_row_shape(rows)
    row = _single(rows, "transcript-provider-usage")
    assert (row["actual"], row["disposition"]) == ("known", "expected")


def test_unit_request_rejection_before_dispatch_is_known_zero():
    rows = ff_short_feedback.observation_rows(
        output={
            "schema_version": "2.0",
            "status": "request_error",
            "filing": {"status": "request_error", "reason": "missing limits",
                       "retryable": False},
            "transcript": {"status": "not_requested"},
            "calls": 0,
            "downloads": 0,
        },
        stats={"calls": 0, "downloads": 0},
        request={"schema_version": "2.0", "filing_intent": "fetch_if_missing"},
        allow_download=None,
        identity=_identity(),
    )
    _assert_row_shape(rows)
    start = _single(rows, "provider-start")
    assert (start["expected"], start["actual"], start["disposition"]) == (
        "not_started", "not_started", "expected")
    assert _single(rows, "provider-usage")["actual"] == "known"
    assert _single(rows, "download-receipt")["actual"] == "0"


@pytest.mark.parametrize("out", [None, ""])
def test_missing_explicit_sidecar_uses_native_outbox(out, tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCH_FEEDBACK_DIR", str(tmp_path))
    if out is None:
        monkeypatch.delenv(ff_short_feedback.OUT_ENV, raising=False)
    else:
        monkeypatch.setenv(ff_short_feedback.OUT_ENV, out)
    observation = ff_short_feedback.begin_observation()
    assert observation is not None
    observation.finished(output={"status":"request_error"})
    assert list(tmp_path.glob("feedback-*.ready"))


@pytest.mark.parametrize("bad_intent", [[], {}])
def test_invalid_intent_type_keeps_native_error_and_terminal_observation(tmp_path, bad_intent):
    harness = Harness(tmp_path)
    out = tmp_path / "observations.jsonl"
    request = _v2_request(filing_intent=bad_intent)
    baseline = harness.run(request)
    observed = harness.run(request, out=out)

    assert (observed.returncode, observed.stdout, observed.stderr) == (
        baseline.returncode, baseline.stdout, baseline.stderr,
    )
    assert observed.returncode != 0
    rows = _rows(out)
    _assert_protocol(rows)
    outcome = _single(rows, "request-outcome")
    assert outcome["disposition"] == "deviation"
    assert outcome["issue_key"]
    assert outcome["actual"].split("/", 1)[0] == json.loads(baseline.stdout)["status"]
    assert harness.calls() == []


def test_install_manifest_publishes_the_short_adapter():
    sys.path.insert(0, str(ROOT / "tools"))
    import sync_installs_b3

    manifest = sync_installs_b3.manifest(sync_installs_b3.CANONICAL)
    assert "scripts/ff_short_feedback.py" in manifest
