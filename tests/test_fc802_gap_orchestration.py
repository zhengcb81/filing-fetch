"""FC-802 RED/acceptance tests: latest_as_of gap orchestration.

filing-fetch no longer maps GAP to not_found: latest_as_of returns the
structured gap plan (fetch=0); allow_download=True WITH a valid
authorization block invokes the company-wiki close-gap transaction and
returns the final handle; without authorization it stays a structured
gap.  filing-fetch stays thin — it assembles the binding from evidence
company-wiki already provided (plan hash, envelope policy hash) plus the
caller's authorization; it never re-derives provider/root/identity rules.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_fetch_filing import FilingFetchTests

from fetch_filing import FilingFetchError, resolve_filing  # noqa: E402
from filing_contracts import validate_request  # noqa: E402


class Fc802GapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parent = Path(tempfile.mkdtemp())

    @staticmethod
    def _wiki_root(parent: Path, name: str) -> Path:
        root = parent / name
        config = root / "config"
        config.mkdir(parents=True)
        (config / "source_catalog.yaml").write_text(
            "schema_version: '1.0'\n", encoding="utf-8")
        (config / "source_acquisition.yaml").write_text(
            "schema_version: '1.1'\n", encoding="utf-8")
        return root

    def _handle(self, root: Path) -> dict:
        import hashlib

        companies = root / "companies"
        companies.mkdir(exist_ok=True)
        source = companies / "report.pdf"
        source.write_bytes(b"%PDF-1.7\nrevenue source bytes")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        return {
            "request_id": "urn:company-wiki:source-request:sha256:" + "1" * 64,
            "document_id": "urn:company-wiki:document:sha256:" + digest,
            "source_id": "urn:company-wiki:source:sha256:" + digest,
            "title": "ACME 2025 Annual Report",
            "published_date": "2026-03-20",
            "https_url": "https://www.sec.gov/Archives/edgar/data/1/report.htm",
            "canonical_location_id": "urn:company-wiki:location:sha256:" + "2" * 64,
            "canonical_path": str(source),
            "snapshot_sha256": digest,
            "retrieved_at": "2026-07-18T12:00:00Z",
            "provider": "sec",
            "provider_document_id": "0000000001-26-000001",
            "collector_name": "dayu-sec",
            "collector_version": "1.0.0",
            "byte_size": source.stat().st_size,
            "mime_type": "application/pdf",
            "capture_ready": True,
        }

    def _identity_response(self) -> dict:
        return {
            "schema_version": "1.0",
            "query": "AMD",
            "normalized_query": "amd",
            "market_hint": "US",
            "exchange_hint": None,
            "status": "resolved",
            "reason": "unique strong fuzzy match",
            "resolved": {
                "canonical_name": "Advanced Micro Devices, Inc.",
                "market": "US",
                "exchange": "NASDAQ",
                "ticker": "AMD",
                "security_id": "AMD",
                "match_basis": "strong_fuzzy",
                "matched_value": "AMD",
                "score": 0.97,
                "verified": True,
                "active": True,
                "source_name": "fixture",
                "source_url": "https://x",
                "source_record_id": "urn:test:AMD",
                "identifiers": {},
            },
            "candidates": [],
        }

    def _worker_status_response(self) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"desired_state": "enabled",
                               "runtime_state": "stopped"}),
            stderr="")

    def _gap_ensure(self) -> dict:
        return {
            "schema_version": "1.0",
            "status": "gap",
            "acquisition": {
                "gap_plan": {
                    "schema_version": "1.0",
                    "request_id": "urn:company-wiki:source-request:sha256:" + "g" * 64,
                    "as_of_date": "2026-07-18",
                    "document_kind": "annual_report",
                    "entity": "Advanced Micro Devices, Inc.",
                    "market": "US",
                    "reuse": [],
                    "missing": [{"provider_document_id": "acc-2025"}],
                    "newer_revision": [],
                    "not_published": False,
                    "provider_unavailable": False,
                    "provider_reason": None,
                    "future": [],
                    "gap_hash": "c" * 64,
                }
            },
            "resolution": {
                "schema_version": "1.0",
                "status": "missing",
                "reason": "metadata_only_gap_plan",
                "request_id": "urn:company-wiki:source-request:sha256:" + "g" * 64,
                "resolution_envelope": {
                    "envelope_schema_version": "1.0",
                    "outcome": "gap",
                    "download_events": 0,
                    "policy_hash": "b" * 64,
                    "activation_epoch": "epoch-1",
                    "bundle_status": "unavailable",
                },
                "matches": [],
            },
        }

    def _latest_request(self) -> dict:
        return {
            "schema_version": "1.2",
            "company_query": "AMD",
            "market": "US",
            "document_kind": "annual_report",
            "mode": "latest_as_of",
            "as_of_date": "2026-07-18",
        }

    def test_gap_structured_without_download(self) -> None:
        """latest_as_of + no download returns the structured gap plan — it
        is NOT mapped to not_found and nothing is fetched."""
        root = self._wiki_root(self.parent, "company-wiki")
        completed = [
            subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps(self._identity_response()), stderr=""),
            subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps(self._gap_ensure()), stderr=""),
        ]
        with patch("fetch_filing.subprocess.run", side_effect=completed) as run:
            result = resolve_filing(
                request=self._latest_request(), company_wiki_root=root)
        self.assertEqual(run.call_count, 2)
        ensure_command = run.call_args_list[1].args[0]
        self.assertIn("ensure", ensure_command)
        self.assertNotIn("--allow-download", ensure_command)
        self.assertEqual(result["status"], "gap")
        self.assertEqual(result["gap_plan"]["gap_hash"], "c" * 64)

    def test_allow_download_without_authorization_stays_gap(self) -> None:
        """allow_download=True without an authorization block never
        downloads — the structured gap is returned."""
        root = self._wiki_root(self.parent, "company-wiki")
        completed = [
            subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps(self._identity_response()), stderr=""),
            self._worker_status_response(),
            subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps(self._gap_ensure()), stderr=""),
        ]
        with patch("fetch_filing.subprocess.run", side_effect=completed) as run:
            result = resolve_filing(
                request=self._latest_request(), company_wiki_root=root,
                allow_download=True)
        self.assertEqual(run.call_count, 3)
        ensure_command = run.call_args_list[2].args[0]
        self.assertIn("--allow-download", ensure_command)
        self.assertNotIn("close-gap", " ".join(ensure_command))
        self.assertEqual(result["status"], "gap")

    def test_authorized_close_gap_returns_handle(self) -> None:
        """allow_download=True + a valid authorization invokes the
        company-wiki close-gap transaction and returns the final handle."""
        root = self._wiki_root(self.parent, "company-wiki")
        closed = {
            "schema_version": "1.0",
            "txn_id": "urn:company-wiki:close-gap:sha256:" + "t" * 64,
            "status": "completed",
            "reason": "gap_closed_downloaded",
            "fetch_events": 1,
            "outcome": "downloaded_new",
            "resolution": {
                "schema_version": "1.0",
                "status": "reused_exact",
                "request_id": "urn:req:closed",
                "matches": [self._handle(root)],
            },
            "envelope": {
                "envelope_schema_version": "1.0",
                "outcome": "downloaded_new",
                "download_events": 1,
                "policy_hash": "b" * 64,
                "activation_epoch": "epoch-1",
                "bundle_status": "unavailable",
            },
        }
        completed = [
            subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps(self._identity_response()), stderr=""),
            self._worker_status_response(),  # ensure pause scope
            subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps(self._gap_ensure()), stderr=""),
            self._worker_status_response(),  # close-gap pause scope
            subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps(closed), stderr=""),
        ]
        request = self._latest_request()
        request["authorization"] = {
            "provider": "sec",
            "allowed_accessions": ["acc-2025"],
            "max_items": 1,
            "max_bytes": 5_000_000,
            "expires_at": "2099-01-01T00:00:00Z",
        }
        captured = {}

        def _run(*args, **kwargs):
            argv = args[0]
            if "close-gap" in argv:
                flag = argv[argv.index("--binding-file") + 1]
                captured["binding"] = json.loads(
                    Path(flag).read_text(encoding="utf-8"))
            return completed.pop(0)

        with patch("fetch_filing.subprocess.run", side_effect=_run) as run:
            handle = resolve_filing(
                request=request, company_wiki_root=root, allow_download=True)
        self.assertEqual(run.call_count, 5)
        close_command = run.call_args_list[4].args[0]
        self.assertIn("close-gap", close_command)
        binding = captured["binding"]
        self.assertEqual(binding["gap_plan_hash"], "c" * 64)
        self.assertEqual(binding["policy_hash"], "b" * 64)
        self.assertEqual(binding["allowed_accessions"], ["acc-2025"])
        self.assertEqual(handle["request_id"], "urn:req:closed")
        self.assertEqual(handle["resolution_envelope"]["outcome"], "downloaded_new")

    def test_exact_mode_missing_still_not_found(self) -> None:
        """Only GAP is structured — an exact-mode miss keeps the not_found
        error semantics."""
        root = self._wiki_root(self.parent, "company-wiki")
        source_response = {
            "schema_version": "1.0",
            "status": "missing",
            "reason": "no match",
            "request_id": "urn:req:missing",
            "matches": [],
        }
        completed = [
            subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps(self._identity_response()), stderr=""),
            subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps(source_response), stderr=""),
        ]
        with patch("fetch_filing.subprocess.run", side_effect=completed):
            with self.assertRaisesRegex(FilingFetchError, "not reusable"):
                resolve_filing(
                    request=FilingFetchTests._request(),
                    company_wiki_root=root)

    def test_invalid_authorization_block_is_request_error(self) -> None:
        """An authorization block missing required fields is a request
        error — never silently ignored."""
        request = self._latest_request()
        request["authorization"] = {"allowed_accessions": ["acc-2025"]}
        with self.assertRaisesRegex(FilingFetchError, "authorization"):
            validate_request(request)

    def test_main_passes_gap_through_unwrapped(self) -> None:
        """FC-802 F1 regression: a structured gap is printed as-is — the
        CLI must never wrap it as a capture_ready handle.  main() reads
        the request file BEFORE resolve_filing, so a valid request file
        must exist for the mocked gap to flow through the output branch."""
        import io
        from contextlib import redirect_stdout

        import fetch_filing

        request_file = self.parent / "gap-request.json"
        request_file.write_text(json.dumps({
            "schema_version": "1.2",
            "company_query": "AMD",
            "document_kind": "annual_report",
            "mode": "latest_as_of",
            "as_of_date": "2026-07-18",
        }), encoding="utf-8")
        gap = {"status": "gap", "gap_plan": {"gap_hash": "c" * 64},
               "resolution": {"status": "missing"}}
        with patch("fetch_filing.resolve_filing", return_value=gap):
            with redirect_stdout(io.StringIO()) as buf:
                rc = fetch_filing.main([
                    "--config", "x", "--request-file", str(request_file)])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["status"], "gap")
        self.assertEqual(payload["gap_plan"]["gap_hash"], "c" * 64)
        self.assertNotIn("capture_ready", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
