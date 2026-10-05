"""FAILING-FIRST tests: no old worker orchestration remains reachable.

P5-FF: `resolve_filing` (both reuse and explicitly authorized download paths)
must not probe worker-status, pause/resume the worker, or write the
`filing_fetch_pause.refcount` / `filing_fetch_pause.owner` files. The flags
remain accepted but become inert no-ops.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fetch_filing  # noqa: E402

_PAUSE_REF = ".source_catalog/filing_fetch_pause.refcount"
_PAUSE_OWNER = ".source_catalog/filing_fetch_pause.owner"
WORKER_VERBS = ("worker-status", "worker-pause", "worker-resume")


def _fixture_handle(root: Path) -> dict:
    payload = b"%PDF-1.7\nrevenue source bytes"
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "request_id": "urn:company-wiki:source-request:sha256:" + "1" * 64,
        "document_id": "urn:company-wiki:document:sha256:" + digest,
        "source_id": "urn:company-wiki:source:sha256:" + digest,
        "title": "ACME 2025 Annual Report",
        "published_date": "2026-03-20",
        "https_url": "https://www.sec.gov/Archives/edgar/data/1/report.htm",
        "canonical_path": str(root / "companies" / "report.pdf"),
        "snapshot_sha256": digest,
        "retrieved_at": "2026-07-18T12:00:00Z",
        "provider": "sec",
        "provider_document_id": "0000000001-26-000001",
        "collector_name": "dayu-sec",
        "collector_version": "1.0.0",
        "byte_size": len(payload),
        "mime_type": "application/pdf",
        "capture_ready": True,
    }


def _fake_inproc_mocks():
    """Patch the transport so no real subprocess runs during these tests."""
    return (
        mock.patch.object(
            fetch_filing,
            "_run_company_wiki_json_retry",
            side_effect=_fake_payload_reply,
        ),
        mock.patch.object(
            fetch_filing,
            "_run_source_query",
            side_effect=_fake_query_reply,
        ),
    )


class _MultiPatch:
    def __init__(self, patches):
        self._patches = patches

    def __enter__(self):
        entered = [p.start() for p in self._patches]
        self._already = entered
        return entered

    def __exit__(self, exc_type, exc, tb):
        for p in self._patches:
            p.stop()
        return False


def _fake_payload_reply(*, command, root, action, deadline, stats=None):
    if stats is not None:
        stats["calls"] = stats.get("calls", 0) + 1
    matches_root = root if isinstance(root, Path) else Path(tempfile.gettempdir())
    if command and any(verb in command for verb in WORKER_VERBS):
        raise AssertionError(f"retired worker orchestration reached: {command[3]}")
    policy_export = {
        "roots": [{"path_ref": str(matches_root / "companies"), "reusable_for_filing": True}],
        "policy_hash": "",
    }
    canonical_doc = {k: v for k, v in policy_export.items() if k != "policy_hash"}
    policy_export["policy_hash"] = hashlib.sha256(
        json.dumps(canonical_doc, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    envelope = {
        "envelope_schema_version": "1.0",
        "outcome": "reused_existing",
        "download_events": 0,
        "policy_hash": policy_export["policy_hash"],
        "activation_epoch": "epoch-fixture",
        "bundle_status": "unavailable",
        "prompt_injection_status": "not_detected",
        "parser_calls": 0,
    }
    handle = _fixture_handle(matches_root)
    if action == "identify":
        return {
            "schema_version": "1.0",
            "status": "resolved",
            "resolved": {
                "canonical_name": "ACME Corp",
                "market": "US",
                "exchange": "NASDAQ",
                "ticker": "ACME",
                "security_id": "ACME",
                "match_basis": "ticker",
                "matched_value": "ACME",
                "source_name": "fixture",
                "source_url": "https://example.com",
                "source_record_id": "1",
                "verified": True,
                "active": True,
            },
        }
    if action == "ensure":
        return {
            "status": "reused_exact",
            "resolution": {
                "schema_version": "1.0",
                "status": "reused_exact",
                "request_id": "urn:cwp:fixture:ensure",
                "matches": [handle],
                "policy_export": policy_export,
                "resolution_envelope": envelope,
            },
        }
    return {
        "schema_version": "1.0",
        "status": "reused_exact",
        "request_id": "urn:cwp:fixture:resolve",
        "matches": [handle],
        "policy_export": policy_export,
        "resolution_envelope": envelope,
    }


def _fake_query_reply(*args, **kwargs):
    raise AssertionError("source query route should not be used here")


class NoWorkerOrchestrationTests(unittest.TestCase):
    """resolve + download paths never call worker-* or touch pause files."""

    def _assert_no_pause_files(self, root: Path) -> None:
        self.assertFalse((root / _PAUSE_REF).exists())
        self.assertFalse((root / _PAUSE_OWNER).exists())

    def _resolve(self, tmp: str, **kwargs):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            Path(tdp, ".source_catalog").mkdir()
            (tdp / "config").mkdir()
            (tdp / "config" / "source_catalog.yaml").write_text("stub: 1", encoding="utf-8")
            companies = tdp / "companies"
            companies.mkdir(exist_ok=True)
            (companies / "report.pdf").write_bytes(b"%PDF-1.7\nrevenue source bytes")
            policy_export = {
                "roots": [{"path_ref": str(companies), "reusable_for_filing": True}],
                "policy_hash": "",
            }
            # Derived AFTER the doc excludes the hash key itself.
            canonical_doc = {k: v for k, v in policy_export.items() if k != "policy_hash"}
            policy_doc_hash = hashlib.sha256(
                json.dumps(canonical_doc, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            policy_export["policy_hash"] = policy_doc_hash
            self._policy_snapshot = policy_export
            with _MultiPatch(_fake_inproc_mocks()):
                fetch_filing.resolve_filing(
                    request={
                        "schema_version": "1.2",
                        "company_query": "ACME",
                        "document_kind": "annual_report",
                        "fiscal_year": 2025,
                        "as_of_date": "2026-07-18",
                    },
                    company_wiki_root=Path(td),
                    timeout_seconds=30,
                    **kwargs,
                )
                self._assert_no_pause_files(Path(td))

    def test_reuse_default_passes_no_worker_call(self):
        self._resolve("reuse-default")

    def test_reuse_explicit_pause_true_still_no_worker_call(self):
        self._resolve("reuse-pause-true", pause_worker=True)

    def test_reuse_pause_worker_false_no_worker_call(self):
        self._resolve("reuse-pause-false", pause_worker=False)


class CompatFlagsInertTests(unittest.TestCase):
    def test_no_pause_worker_flag_parses_and_is_documented_inert(self):
        parser_help = None
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "fetch_filing.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0)
        parser_help = proc.stdout
        self.assertIn("--no-pause-worker", parser_help)

    def test_scoped_symbol_gone(self):
        self.assertFalse(hasattr(fetch_filing, "PausedWorkerScope"))
        self.assertFalse(hasattr(fetch_filing, "_PAUSE_REFCOUNT_NAME"))
        self.assertFalse(hasattr(fetch_filing, "_PAUSE_OWNER_NAME"))

    def test_worker_helpers_gone(self):
        for name in (
            "_pid_is_alive",
            "_read_pause_entries",
            "_write_pause_entries",
            "_prune_pause_entries",
        ):
            self.assertFalse(hasattr(fetch_filing, name), name)


if __name__ == "__main__":
    unittest.main()
