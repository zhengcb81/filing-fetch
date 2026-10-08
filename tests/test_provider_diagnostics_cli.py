"""R6-FF-CAUSE CLI acceptance: optional diagnostics on the public v1/v2 CLIs.

The optional ``upstream_cause`` field appears on FAILURES only (v1 top-level,
v2 inside ``filing``); success/gap envelopes, golden shapes, stats
calls/downloads, the zero-download reuse trace and the "failure is not an
empty success" rule all stay byte-compatible with the pre-lane contracts.
The last tests drive the REAL public CLI as a subprocess through the real
bounded process layer with an in-tree fake ``company_wiki`` package — no
network, no real provider, no CWP checkout required.
"""

from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "tests"))

import fetch_filing  # noqa: E402
from fetch_filing import FilingFetchError  # noqa: E402


CAUSE = {
    "schema_version": "filing-upstream-cause/1",
    "operation": "ensure",
    "code": "legacy_evidence_archived",
    "provider_started": None,
    "usage_complete": None,
    "retry_scope": "none",
}

# The in-tree fake company_wiki CLI fails the FIRST producer call, which for
# every public request is the identify step.
IDENTIFY_CAUSE = {**CAUSE, "operation": "identify"}


def v1_request() -> dict:
    return {
        "schema_version": "1.2",
        "company_query": "ACME",
        "market": "US",
        "document_kind": "annual_report",
        "mode": "exact",
        "fiscal_year": 2025,
        "as_of_date": "2026-10-08",
    }


def v2_request() -> dict:
    return {
        "schema_version": "2.0",
        "company_query": "ACME",
        "market": "US",
        "document_kind": "annual_report",
        "mode": "exact",
        "fiscal_year": 2025,
        "as_of_date": "2026-10-08",
        "filing_intent": "reuse_only",
    }


def run_main(monkeypatch: pytest.MonkeyPatch, value: dict, args: list[str] | None = None):
    stdin = StringIO(json.dumps(value))
    stdout = StringIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    rc = fetch_filing.main(args or [])
    return rc, json.loads(stdout.getvalue())


def _source_candidate() -> dict:
    sha = "b" * 64
    return {
        "source_ref": {
            "schema_version": "2.0",
            "document_id": f"urn:company-wiki:document:sha256:{sha}",
            "source_id": f"urn:company-wiki:source:sha256:{sha}",
            "content_sha256": sha,
            "byte_size": 10,
            "mime_type": "application/pdf",
        },
        "document_kind": "annual_report",
        "fiscal_year": 2025,
        "fiscal_period": None,
        "resolution_outcome": "reused_existing",
        "download_events": 0,
        "prompt_injection_status": "not_reviewed",
        "company_identity": {
            "canonical_name": "Acme Inc.",
            "market": "US",
            "security_id": "ACME",
            "ticker": "ACME",
            "exchange": "NASDAQ",
            "verified": True,
            "active": True,
        },
    }


# ---------------------------------------------------------------------------
# Failure envelopes gain the optional field; nothing else moves
# ---------------------------------------------------------------------------

def test_v1_failure_carries_optional_upstream_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**kwargs: Any) -> dict:
        kwargs["stats"]["calls"] = 2
        kwargs["stats"]["downloads"] = 0
        raise FilingFetchError(
            "company-wiki ensure exited 1",
            code="fatal",
            stage="ensure",
            attempts=1,
            upstream_cause=dict(CAUSE),
        )

    monkeypatch.setattr(fetch_filing, "resolve_filing", boom)
    rc, out = run_main(monkeypatch, v1_request())
    assert rc == 2
    assert out["status"] == "fatal"
    assert out["error_code"] == "fatal"
    assert out["retryable"] is False
    assert out["stage"] == "ensure"
    assert out["upstream_cause"] == CAUSE
    # Existing reconciliation counters keep their meaning (READ-09/READ-10).
    assert out["calls"] == 2
    assert out["downloads"] == 0


def test_v2_failure_carries_upstream_cause_inside_filing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**kwargs: Any) -> dict:
        kwargs["stats"]["calls"] = 1
        kwargs["stats"]["downloads"] = 0
        raise FilingFetchError(
            "company-wiki ensure exited 1",
            code="fatal",
            stage="ensure",
            attempts=1,
            upstream_cause=dict(CAUSE),
        )

    monkeypatch.setattr(fetch_filing, "resolve_filing", boom)
    rc, out = run_main(monkeypatch, v2_request())
    assert rc == 2
    assert out["status"] == "fatal"
    # A failure is never an empty success: no source_ref, no candidate status.
    assert out["filing"]["status"] == "fatal"
    assert "source_ref" not in out["filing"]
    assert out["filing"]["upstream_cause"] == CAUSE
    assert "upstream_cause" not in out  # v2 nests it inside filing only
    assert out["transcript"] == {"status": "not_requested", "retryable": False}
    assert out["calls"] == 1
    assert out["downloads"] == 0


def test_v2_failure_without_cause_omits_the_field_entirely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**kwargs: Any) -> dict:
        raise FilingFetchError("identity problem", code="identity_error")

    monkeypatch.setattr(fetch_filing, "resolve_filing", boom)
    rc, out = run_main(monkeypatch, v2_request())
    assert rc == 2
    assert "upstream_cause" not in out["filing"]
    assert "upstream_cause" not in out


# ---------------------------------------------------------------------------
# Success/gap envelopes unchanged: the field is failure-only
# ---------------------------------------------------------------------------

def test_v1_success_envelope_has_no_cause_field(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict] = []

    def fake_resolve(**kwargs: Any) -> dict:
        seen.append(kwargs)
        kwargs["stats"]["calls"] = 1
        kwargs["stats"]["downloads"] = 0
        return {"document_id": "legacy", "canonical_path": "inside/legacy.pdf"}

    monkeypatch.setattr(fetch_filing, "resolve_filing", fake_resolve)
    rc, out = run_main(monkeypatch, v1_request())
    assert rc == 0
    assert out == {
        "schema_version": "1.1",
        "status": "capture_ready",
        "handle": {"document_id": "legacy", "canonical_path": "inside/legacy.pdf"},
        "calls": 1,
        "downloads": 0,
    }


def test_v2_success_envelope_keeps_zero_download_reuse_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_resolve(**kwargs: Any) -> dict:
        kwargs["stats"]["calls"] = 3
        kwargs["stats"]["downloads"] = 0
        return _source_candidate()

    monkeypatch.setattr(fetch_filing, "resolve_filing", fake_resolve)

    def fake_companion(**kwargs: Any) -> dict:
        return {"status": "not_requested", "retryable": False}

    monkeypatch.setattr(fetch_filing, "_resolve_v2_companion", fake_companion)
    rc, out = run_main(monkeypatch, v2_request())
    assert rc == 0
    assert out["status"] == "source_candidate"
    assert out["filing"]["download_events"] == 0
    assert out["downloads"] == 0
    assert out["calls"] == 3
    assert "upstream_cause" not in out
    assert "upstream_cause" not in out["filing"]


def test_v2_gap_envelope_has_no_cause_field(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_resolve(**kwargs: Any) -> dict:
        kwargs["stats"]["calls"] = 2
        kwargs["stats"]["downloads"] = 0
        return {
            "status": "gap",
            "gap_plan": {"schema_version": "1.0", "gap_hash": "c" * 64, "request_id": "req-1"},
            "resolution": {"status": "missing", "reason": "metadata_only_gap_plan"},
        }

    monkeypatch.setattr(fetch_filing, "resolve_filing", fake_resolve)
    rc, out = run_main(monkeypatch, v2_request())
    assert rc == 0
    assert out["status"] == "gap"
    assert out["filing"]["status"] == "gap"
    assert out["filing"]["download_events"] == 0
    assert "upstream_cause" not in out["filing"]


# ---------------------------------------------------------------------------
# Real public CLI through the real bounded process layer (offline)
# ---------------------------------------------------------------------------

_FAKE_CWP_CLI = """\
import json, sys
payload = {
    "status": "failed",
    "error_type": "legacy_evidence_archived",
    "error": "cold evidence only; path C:\\\\Users\\\\leaker\\\\FMP_API_KEY.txt "
             "api_key=sk-live-not-a-real-key",
    "retryable": False,
}
sys.stderr.write(json.dumps(payload) + "\\n")
sys.exit(1)
"""


def _wiki_root(parent: Path) -> Path:
    root = parent / "company-wiki"
    config = root / "config"
    config.mkdir(parents=True)
    (config / "source_catalog.yaml").write_text("schema_version: '1.0'\n", encoding="utf-8")
    (parent / "ff-config.json").write_text(
        json.dumps({"schema_version": "1.0", "company_wiki_root": str(root)}), encoding="utf-8"
    )
    return root


def _run_public_cli(tmp: Path, request: dict) -> tuple[int, dict]:
    request_file = tmp / "request.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "fetch_filing.py"),
            "--request-file",
            str(request_file),
            "--config",
            str(tmp / "ff-config.json"),
            "--timeout-seconds",
            "30",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(tmp),
    )
    return proc.returncode, json.loads(proc.stdout)


def test_real_cli_propagates_named_structured_failure_v1(tmp_path: Path) -> None:
    root = _wiki_root(tmp_path)
    package = root / "company_wiki" / "source_catalog"
    package.mkdir(parents=True)
    (root / "company_wiki" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text(_FAKE_CWP_CLI, encoding="utf-8")
    rc, out = _run_public_cli(tmp_path, v1_request())
    assert rc == 2
    assert out["error_code"] == "fatal"
    assert out["upstream_cause"] == IDENTIFY_CAUSE
    rendered = json.dumps(out)
    assert "api_key" not in rendered
    assert "FMP_API_KEY" not in rendered
    assert "Traceback" not in rendered


def test_real_cli_propagates_named_structured_failure_v2(tmp_path: Path) -> None:
    root = _wiki_root(tmp_path)
    package = root / "company_wiki" / "source_catalog"
    package.mkdir(parents=True)
    (root / "company_wiki" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text(_FAKE_CWP_CLI, encoding="utf-8")
    rc, out = _run_public_cli(tmp_path, v2_request())
    assert rc == 2
    assert out["status"] == "fatal"
    assert out["filing"]["upstream_cause"] == IDENTIFY_CAUSE


def test_real_cli_keeps_unknown_on_unstructured_traceback(tmp_path: Path) -> None:
    # No company_wiki package under the wiki root: the real child fails with a
    # Python traceback on stderr (unstructured) — the cause must stay unknown
    # and none of the traceback may reach the response.
    _wiki_root(tmp_path)
    rc, out = _run_public_cli(tmp_path, v1_request())
    assert rc == 2
    assert out["error_code"] == "fatal"
    assert out["upstream_cause"]["code"] == "unknown"
    assert out["upstream_cause"]["retry_scope"] == "none"
    rendered = json.dumps(out)
    assert "Traceback" not in rendered
    assert "ModuleNotFoundError" not in rendered


def test_real_cli_config_error_has_no_upstream_cause(tmp_path: Path) -> None:
    # A config failure happens before any producer operation: no operation,
    # no cause — the field is genuinely optional, not always-on.
    root = tmp_path / "company-wiki"
    (root / "config").mkdir(parents=True)
    (tmp_path / "ff-config.json").write_text(
        json.dumps({"schema_version": "1.0", "company_wiki_root": str(root)}), encoding="utf-8"
    )
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(v1_request()), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "fetch_filing.py"),
            "--request-file",
            str(request_file),
            "--config",
            str(tmp_path / "ff-config.json"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(tmp_path),
    )
    assert proc.returncode == 2
    out = json.loads(proc.stdout)
    assert out["error_code"] == "config_error"
    assert "upstream_cause" not in out
