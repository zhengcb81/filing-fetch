"""Run filing-fetch's live T3 probes using explicitly bound public CWP workspaces."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

from ff_process_transport import run_bounded_json
from ff_runtime_feedback import cause_details, owner_child_environment
from ff_t3_workspace import Workspace, WorkspaceClient, WorkspaceUnavailable

T3_TIMEOUT_SECONDS = 180
T3_DOWNLOAD_LIMITS = {
    "max_bytes": 50 * 1024 * 1024,
    "timeout_seconds": T3_TIMEOUT_SECONDS,
    "max_cost_usd": "0",
}
T3_ANNUAL_SAMPLES = {
    "cn_annual": ("宁德时代", "CN", 2024),
    "hk_annual": ("腾讯", "HK", 2025),
    "us_annual": ("AMD", "US", 2025),
}
T3_CASES = (*T3_ANNUAL_SAMPLES, "corrupt_original")
FF_CLI = Path(__file__).with_name("fetch_filing.py")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise AssertionError(reason)


def _fetch(config: Path, request: dict, *, download: bool, expected_exit: int) -> dict:
    command = [sys.executable, "-B", str(FF_CLI), "--config", str(config),
               "--timeout-seconds", str(T3_TIMEOUT_SECONDS)]
    if download:
        command.append("--allow-download")
    raw, _, exit_code = run_bounded_json(
        command, cwd=str(config.parent), env=owner_child_environment(),
        input_bytes=json.dumps(request, ensure_ascii=True).encode("utf-8"),
        timeout_seconds=T3_TIMEOUT_SECONDS + 60, allow_nonzero_exit=True,
    )
    _require(exit_code == expected_exit, "unexpected filing-fetch exit")
    payload = json.loads(raw)
    _require(isinstance(payload, dict), "invalid filing-fetch payload")
    return payload


def _request(company: str, market: str, year: int) -> dict:
    return {
        "schema_version": "1.1",
        "company_query": company,
        "market": market,
        "document_kind": "annual_report",
        "fiscal_year": year,
        "as_of_date": "2026-07-31",
    }


def _capture_identity(response: dict, expected_count: int) -> tuple[str, str]:
    _require(response["status"] == "capture_ready" and response["downloads"] == expected_count,
             "unexpected acquisition result")
    handle = response["handle"]
    digest = handle.get("snapshot_sha256")
    source_id = handle.get("source_id")
    _require(handle.get("capture_ready") is True and isinstance(digest, str)
             and bool(_SHA256.fullmatch(digest)) and isinstance(source_id, str)
             and bool(source_id), "invalid source handle")
    return source_id, digest


def _annual(workspace: Workspace, config: Path, company: str, market: str, year: int) -> None:
    request = {**_request(company, market, year), "acquisition_limits": T3_DOWNLOAD_LIMITS}
    first = _fetch(config, request, download=True, expected_exit=0)
    source_id, digest = _capture_identity(first, 1)
    initial = workspace.observe("first")
    _require(initial.get("source_id") == source_id and initial.get("sha256") == digest
             and initial.get("provenance_complete") is True
             and initial.get("no_residue") is True and initial.get("downloaded_new") == 1,
             "owner did not verify one durable capture")
    _require(type(initial.get("mtime_ns")) is int, "owner did not verify original mtime")

    second = _fetch(config, request, download=True, expected_exit=0)
    _require(_capture_identity(second, 0) == (source_id, digest),
             "repeat request changed the source identity")
    reused = workspace.observe("reused")
    _require(reused.get("source_id") == source_id and reused.get("sha256") == digest
             and reused.get("mtime_ns") == initial["mtime_ns"]
             and reused.get("downloaded_new") == 1 and reused.get("reused_before_download") is True
             and reused.get("no_residue") is True, "owner did not verify unchanged reuse")


def _corrupt(workspace: Workspace, config: Path) -> None:
    request = _request(*T3_ANNUAL_SAMPLES["cn_annual"])
    reused = _fetch(config, request, download=False, expected_exit=2)
    _require(reused["status"] == "upstream_error", "corrupt original was accepted on reuse")
    ensured = _fetch(config, {**request, "acquisition_limits": T3_DOWNLOAD_LIMITS},
                     download=True, expected_exit=2)
    cause = ensured["upstream_cause"]
    _require("handle" not in ensured and cause["operation"] == "ensure"
             and cause["provider_started"] is False and ensured["downloads"] == 0,
             "corrupt original triggered acquisition")
    facts = workspace.observe("corrupt")
    _require(facts.get("corrupt_original_unchanged") is True and facts.get("downloaded_new") == 0
             and facts.get("no_residue") is True, "owner did not verify corrupt-file preservation")


def probe_case(client: WorkspaceClient, run_id: str, case: str) -> None:
    with client.open(run_id, case) as workspace, TemporaryDirectory(prefix="ff-t3-") as temporary:
        config = Path(temporary) / "connection.json"
        config.write_text(json.dumps({"schema_version": "1.0", "connection": workspace.connection}),
                          encoding="utf-8")
        if case == "corrupt_original":
            _corrupt(workspace, config)
        else:
            _annual(workspace, config, *T3_ANNUAL_SAMPLES[case])


def run_cases(report: Callable[[str, str, str | None, dict | None], None], *,
              config: Path, run_id: str) -> None:
    try:
        client = WorkspaceClient(config, skill_root=FF_CLI.parent.parent)
    except WorkspaceUnavailable as error:
        reason = "workspace_not_configured"
        detail = cause_details(error, reason=reason)
        for case in T3_CASES:
            report(case, "blocked", reason, detail)
        return
    for case in T3_CASES:
        try:
            probe_case(client, run_id, case)
        except Exception as error:
            reason = "assertion_failed" if isinstance(error, AssertionError) else "test_error"
            report(case, "failed", reason, cause_details(error, reason=reason))
        else:
            report(case, "passed", None, None)
