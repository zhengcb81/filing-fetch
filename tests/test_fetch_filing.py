"""filing-fetch contracts: identify -> resolve (reuse) / ensure (download)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from fetch_filing import (  # noqa: E402
    FilingFetchError,
    load_company_wiki_root,
    resolve_filing,
)


class FilingFetchTests(unittest.TestCase):
    @staticmethod
    def _wiki_root(parent: Path, name: str) -> Path:
        root = parent / name
        config = root / "config"
        config.mkdir(parents=True)
        (config / "source_catalog.yaml").write_text("schema_version: '1.0'\n", encoding="utf-8")
        (config / "source_acquisition.yaml").write_text("schema_version: '1.1'\n", encoding="utf-8")
        return root

    @staticmethod
    def _request() -> dict:
        return {
            "schema_version": "1.1",
            "company_query": "AMD",
            "market": "US",
            "document_kind": "annual_report",
            "fiscal_year": 2025,
            "as_of_date": "2026-07-18",
        }

    def _handle(self, root: Path) -> dict:
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

    @staticmethod
    def _identity_response() -> dict:
        return {
            "schema_version": "1.0",
            "query": "Advanced Micro Device",
            "normalized_query": "advancedmicrodevice",
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
                "matched_value": "Advanced Micro Devices",
                "score": 0.97,
                "verified": True,
                "active": True,
                "source_name": "SEC company tickers + Nasdaq symbol directory",
                "source_url": "https://www.sec.gov/files/company_tickers.json",
                "source_record_id": "urn:company-wiki:security:US:AMD",
                "identifiers": {"cik": "0000002488"},
            },
            "candidates": [],
        }

    def test_default_config_resolves_an_existing_company_wiki_root(self) -> None:
        root = load_company_wiki_root()

        self.assertTrue(root.is_dir())
        self.assertTrue((root / "config" / "source_catalog.yaml").is_file())

    def test_editing_config_moves_root_without_code_changes(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            first = self._wiki_root(parent, "wiki-one")
            second = self._wiki_root(parent, "wiki-two")
            config_path = parent / "company_wiki.json"
            config_path.write_text(
                json.dumps(
                    {"schema_version": "1.0", "company_wiki_root": "wiki-one"}
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_company_wiki_root(config_path=config_path), first)

            config_path.write_text(
                json.dumps(
                    {"schema_version": "1.0", "company_wiki_root": "wiki-two"}
                ),
                encoding="utf-8",
            )
            self.assertEqual(load_company_wiki_root(config_path=config_path), second)

    def test_resolve_uses_configured_root_when_root_is_omitted(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "moved-company-wiki")
            config_path = parent / "company_wiki.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "company_wiki_root": str(root),
                    }
                ),
                encoding="utf-8",
            )
            source_response = {
                "status": "reused_exact",
                "request_id": "urn:company-wiki:request:1",
                "matches": [self._handle(root)],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(source_response), stderr=""),
            ]

            with patch("fetch_filing.subprocess.run", side_effect=completed) as run:
                handle = resolve_filing(
                    request=self._request(),
                    config_path=config_path,
                )

            self.assertEqual(run.call_count, 2)
            source_command = run.call_args_list[1].args[0]
            self.assertEqual(run.call_args_list[1].kwargs["cwd"], root)
            self.assertIn(str(root / "config" / "source_catalog.yaml"), source_command)
            self.assertEqual(handle["request_id"], source_response["request_id"])

    def test_company_query_is_identified_before_read_only_resolve(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            request = {
                "schema_version": "1.1",
                "company_query": "Advanced Micro Device",
                "market": "US",
                "document_kind": "annual_report",
                "fiscal_year": 2025,
                "as_of_date": "2026-07-18",
            }
            source_response = {
                "status": "reused_exact",
                "request_id": "urn:company-wiki:request:query",
                "matches": [self._handle(root)],
            }
            completed = [
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(self._identity_response()),
                    stderr="",
                ),
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(source_response),
                    stderr="",
                ),
            ]

            with patch(
                "fetch_filing.subprocess.run", side_effect=completed
            ) as run:
                handle = resolve_filing(
                    request=request,
                    company_wiki_root=root,
                )

            self.assertEqual(run.call_count, 2)
            identify_command = run.call_args_list[0].args[0]
            resolve_command = run.call_args_list[1].args[0]
            self.assertEqual(
                identify_command[identify_command.index("--query") + 1],
                "Advanced Micro Device",
            )
            self.assertIn("--market", identify_command)
            self.assertIn("resolve", resolve_command)
            self.assertEqual(
                resolve_command[resolve_command.index("--entity") + 1],
                "Advanced Micro Devices, Inc.",
            )
            self.assertEqual(
                resolve_command[resolve_command.index("--security-id") + 1], "AMD"
            )
            self.assertNotIn("Advanced Micro Device", resolve_command)
            self.assertEqual(handle["company_identity"]["security_id"], "AMD")

    def test_company_query_builds_an_explicit_canonical_ensure_request(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            request = {
                "schema_version": "1.1",
                "company_query": "AMD",
                "document_kind": "annual_report",
                "fiscal_year": 2025,
                "as_of_date": "2026-07-18",
            }
            ensured = {
                "resolution": {
                    "status": "reused_equivalent",
                    "request_id": "urn:company-wiki:request:ensure-query",
                    "matches": [self._handle(root)],
                }
            }
            completed = [
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(self._identity_response()),
                    stderr="",
                ),
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=json.dumps(ensured),
                    stderr="",
                ),
            ]

            with patch(
                "fetch_filing.subprocess.run", side_effect=completed
            ) as run:
                resolve_filing(
                    request=request,
                    company_wiki_root=root,
                    allow_download=True,
                )

            ensure_command = run.call_args_list[1].args[0]
            self.assertIn("ensure", ensure_command)
            self.assertIn("--allow-download", ensure_command)
            self.assertEqual(
                ensure_command[ensure_command.index("--market") + 1], "US"
            )
            self.assertEqual(
                ensure_command[ensure_command.index("--security-id") + 1], "AMD"
            )

    def test_verified_cn_and_hk_queries_build_canonical_source_requests(self) -> None:
        cases = (
            (
                "中微公司",
                "CN",
                "中微半导体设备（上海）股份有限公司",
                "688012",
                "SSE",
            ),
            ("小米", "HK", "小米集團－Ｗ", "01810", "HKEX"),
        )
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            for query, market, canonical_name, security_id, exchange in cases:
                with self.subTest(query=query):
                    identity = self._identity_response()
                    identity.update(
                        {
                            "query": query,
                            "normalized_query": query,
                            "market_hint": market,
                        }
                    )
                    identity["resolved"].update(
                        {
                            "canonical_name": canonical_name,
                            "market": market,
                            "exchange": exchange,
                            "ticker": security_id,
                            "security_id": security_id,
                            "matched_value": query,
                        }
                    )
                    source_response = {
                        "status": "reused_exact",
                        "request_id": f"urn:company-wiki:request:{market}",
                        "matches": [self._handle(root)],
                    }
                    completed = [
                        subprocess.CompletedProcess(
                            args=[],
                            returncode=0,
                            stdout=json.dumps(identity),
                            stderr="",
                        ),
                        subprocess.CompletedProcess(
                            args=[],
                            returncode=0,
                            stdout=json.dumps(source_response),
                            stderr="",
                        ),
                    ]

                    with patch(
                        "fetch_filing.subprocess.run", side_effect=completed
                    ) as run:
                        handle = resolve_filing(
                            request={
                                "schema_version": "1.1",
                                "company_query": query,
                                "market": market,
                                "document_kind": "annual_report",
                                "as_of_date": "2026-07-18",
                            },
                            company_wiki_root=root,
                        )

                    source_command = run.call_args_list[1].args[0]
                    self.assertEqual(
                        source_command[source_command.index("--entity") + 1],
                        canonical_name,
                    )
                    self.assertEqual(
                        source_command[source_command.index("--market") + 1], market
                    )
                    self.assertEqual(
                        source_command[source_command.index("--security-id") + 1],
                        security_id,
                    )
                    self.assertEqual(
                        handle["company_identity"]["exchange"], exchange
                    )

    def test_ambiguous_company_query_stops_before_source_resolution(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            ambiguous = self._identity_response()
            ambiguous.update(
                {
                    "status": "ambiguous",
                    "reason": "multiple exact candidates",
                    "resolved": None,
                    "candidates": [ambiguous["resolved"]],
                }
            )
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(ambiguous),
                stderr="",
            )

            with patch(
                "fetch_filing.subprocess.run", return_value=completed
            ) as run:
                with self.assertRaisesRegex(
                    FilingFetchError, "not uniquely resolved: ambiguous"
                ):
                    resolve_filing(
                        request={
                            "schema_version": "1.1",
                            "company_query": "万科",
                            "document_kind": "annual_report",
                            "as_of_date": "2026-07-18",
                        },
                        company_wiki_root=root,
                    )

            self.assertEqual(run.call_count, 1)

    def test_unverified_or_inactive_identity_stops_before_source_resolution(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            for field in ("verified", "active"):
                with self.subTest(field=field):
                    identity = self._identity_response()
                    identity["resolved"][field] = False
                    completed = subprocess.CompletedProcess(
                        args=[],
                        returncode=0,
                        stdout=json.dumps(identity),
                        stderr="",
                    )
                    with patch(
                        "fetch_filing.subprocess.run", return_value=completed
                    ) as run:
                        with self.assertRaisesRegex(
                            FilingFetchError, "verified and active"
                        ):
                            resolve_filing(
                                request={
                                    "schema_version": "1.1",
                                    "company_query": "AMD",
                                    "document_kind": "annual_report",
                                    "as_of_date": "2026-07-18",
                                },
                                company_wiki_root=root,
                            )
                    self.assertEqual(run.call_count, 1)

    def test_unknown_conflicting_or_low_confidence_query_never_reaches_ensure(self) -> None:
        cases = (
            ("unknown company", "missing", "no matching security"),
            ("AMD", "conflict", "market hint conflicts with verified candidates"),
            ("微米公司", "ambiguous", "best candidate is below the resolve threshold"),
        )
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            for query, status, reason in cases:
                with self.subTest(query=query):
                    identity = self._identity_response()
                    candidate = identity["resolved"]
                    identity.update(
                        {
                            "query": query,
                            "status": status,
                            "reason": reason,
                            "resolved": None,
                            "candidates": [candidate],
                        }
                    )
                    completed = subprocess.CompletedProcess(
                        args=[],
                        returncode=0,
                        stdout=json.dumps(identity),
                        stderr="",
                    )
                    with patch(
                        "fetch_filing.subprocess.run", return_value=completed
                    ) as run:
                        with self.assertRaisesRegex(
                            FilingFetchError, "not uniquely resolved"
                        ):
                            resolve_filing(
                                request={
                                    "schema_version": "1.1",
                                    "company_query": query,
                                    "document_kind": "annual_report",
                                    "as_of_date": "2026-07-18",
                                },
                                company_wiki_root=root,
                                allow_download=True,
                            )
                    self.assertEqual(run.call_count, 1)

    def test_company_query_rejects_preselected_entity_or_security_id(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            for conflicting, field_name in (
                ({"entity": "guessed entity"}, "entity"),
                ({"security_id": "guessed ticker"}, "security_id"),
            ):
                with self.subTest(conflicting=conflicting):
                    with patch("fetch_filing.subprocess.run") as run:
                        with self.assertRaisesRegex(
                            FilingFetchError, "unknown request field"
                        ):
                            resolve_filing(
                                request={
                                    "schema_version": "1.1",
                                    "company_query": "AMD",
                                    "document_kind": "annual_report",
                                    "as_of_date": "2026-07-18",
                                    **conflicting,
                                },
                                company_wiki_root=root,
                            )
                    run.assert_not_called()

    def test_explicit_root_is_compatible_but_cannot_conflict_with_config(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "explicit-company-wiki")
            config_path = parent / "company_wiki.json"
            config_path.write_text(
                json.dumps(
                    {"schema_version": "1.0", "company_wiki_root": str(root)}
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "cannot be combined"):
                resolve_filing(
                    company_wiki_root=root,
                    config_path=config_path,
                    request=self._request(),
                )

    def test_unknown_config_token_fails_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "company_wiki.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "company_wiki_root": "${UNKNOWN_ROOT}/company-wiki",
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(FilingFetchError, "unsupported token"):
                load_company_wiki_root(config_path=config_path)

    def test_cli_main_guard_runs_and_resolves(self) -> None:
        """The __main__ guard is present: `python fetch_filing.py` actually executes main."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            config_path = parent / "company_wiki.json"
            config_path.write_text(
                json.dumps({"schema_version": "1.0", "company_wiki_root": str(root)}),
                encoding="utf-8",
            )
            source_response = {
                "status": "reused_exact",
                "request_id": "urn:company-wiki:request:cli",
                "matches": [self._handle(root)],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(source_response), stderr=""),
            ]
            request = json.dumps(self._request())
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                argv = ["--config", str(config_path)]
                import io

                original_stdin, original_stdout = sys.stdin, sys.stdout
                sys.stdin = io.StringIO(request)
                sys.stdout = io.StringIO()
                try:
                    exit_code = __import__("fetch_filing").main(argv)
                    output = sys.stdout.getvalue()
                finally:
                    sys.stdin, sys.stdout = original_stdin, original_stdout
            self.assertEqual(exit_code, 0)
            payload = json.loads(output)
            self.assertEqual(payload["status"], "capture_ready")
            self.assertEqual(
                payload["handle"]["request_id"], "urn:company-wiki:request:cli"
            )


    def test_unknown_request_field_is_rejected(self) -> None:
        """Schema 1.1 rejects unknown request fields so callers cannot depend on
        silent ineffective modifiers."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            with self.assertRaisesRegex(FilingFetchError, "unknown request field"):
                resolve_filing(
                    request={
                        "schema_version": "1.1",
                        "company_query": "AMD",
                        "document_kind": "annual_report",
                        "as_of_date": "2026-07-18",
                        "extra_field": "should be rejected",
                    },
                    company_wiki_root=root,
                )

    def test_legacy_explicit_identity_is_rejected(self) -> None:
        """An explicit entity/security_id request without company_query is
        rejected in schema 1.1."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            with self.assertRaisesRegex(FilingFetchError, "unknown request field"):
                resolve_filing(
                    request={
                        "schema_version": "1.1",
                        "entity": "ACME",
                        "market": "US",
                        "security_id": "ACME",
                        "document_kind": "annual_report",
                        "as_of_date": "2026-07-18",
                    },
                    company_wiki_root=root,
                )

    def test_invalid_fiscal_year_is_rejected(self) -> None:
        """A boolean fiscal_year must be rejected before any subprocess runs."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            with self.assertRaisesRegex(FilingFetchError, "fiscal_year"):
                resolve_filing(
                    request={
                        "schema_version": "1.1",
                        "company_query": "AMD",
                        "document_kind": "annual_report",
                        "fiscal_year": True,
                        "as_of_date": "2026-07-18",
                    },
                    company_wiki_root=root,
                )

    def test_capture_ready_without_required_fields_is_rejected(self) -> None:
        """A handle that claims capture_ready=True but is missing required
        fields (e.g. canonical_path, snapshot_sha256) must be rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            bare_handle = {"capture_ready": True, "missing_capture_fields": []}
            response = {
                "status": "reused_exact",
                "request_id": "urn:company-wiki:request:bare",
                "matches": [bare_handle],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "required"):
                    resolve_filing(
                        request=self._request(),
                        company_wiki_root=root,
                    )

    def test_handle_path_outside_wiki_root_is_rejected(self) -> None:
        """A handle whose canonical_path escapes the wiki companies/ subtree
        must be rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            escaped = self._handle(root)
            escaped["canonical_path"] = str(parent / "outside.pdf")
            response = {
                "status": "reused_exact",
                "request_id": "urn:company-wiki:request:outside",
                "matches": [escaped],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "outside"):
                    resolve_filing(
                        request=self._request(),
                        company_wiki_root=root,
                    )


    def test_handle_hash_mismatch_is_rejected(self) -> None:
        """A handle whose snapshot_sha256 does not match the file bytes is rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            bad = self._handle(root)
            bad["snapshot_sha256"] = "a" * 64
            response = {"status": "reused_exact", "request_id": "urn:bad-hash", "matches": [bad]}
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "not match"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_handle_invalid_sha256_is_rejected(self) -> None:
        """A handle with a non-hex snapshot_sha256 is rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            bad = self._handle(root)
            bad["snapshot_sha256"] = "NOT-A-HEX-DIGEST!@#$%^&*()"
            response = {"status": "reused_exact", "request_id": "urn:bad-digest", "matches": [bad]}
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "valid lowercase SHA"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_handle_non_https_url_is_rejected(self) -> None:
        """A handle without an HTTPS source URL is rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            bad = self._handle(root)
            bad["https_url"] = "http://insecure.example/report.pdf"
            response = {"status": "reused_exact", "request_id": "urn:bad-url", "matches": [bad]}
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "HTTPS"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_upstream_subprocess_nonzero_is_contract_error(self) -> None:
        """A nonzero subprocess exit from company-wiki must raise FilingFetchError."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="source_catalog: missing")
            with patch("fetch_filing.subprocess.run", return_value=completed):
                with self.assertRaisesRegex(FilingFetchError, "exited 1"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_upstream_invalid_json_is_contract_error(self) -> None:
        """Non-JSON stdout from company-wiki must raise FilingFetchError."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="not json", stderr="")
            with patch("fetch_filing.subprocess.run", return_value=completed):
                with self.assertRaisesRegex(FilingFetchError, "not JSON"):
                    resolve_filing(request=self._request(), company_wiki_root=root)


    def test_bad_request_schema_version_is_rejected(self) -> None:
        """A request with an unsupported schema_version must be rejected immediately."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            with self.assertRaisesRegex(FilingFetchError, "unsupported request schema"):
                resolve_filing(
                    request={"schema_version": "9.9", "company_query": "AMD", "document_kind": "annual_report", "as_of_date": "2026-07-18"},
                    company_wiki_root=root,
                )

    def test_missing_as_of_date_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            with self.assertRaisesRegex(FilingFetchError, "as_of_date"):
                resolve_filing(
                    request={"schema_version": "1.1", "company_query": "AMD", "document_kind": "annual_report"},
                    company_wiki_root=root,
                )

    def test_bad_as_of_date_format_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            with self.assertRaisesRegex(FilingFetchError, "YYYY-MM-DD"):
                resolve_filing(
                    request={"schema_version": "1.1", "company_query": "AMD", "document_kind": "annual_report", "as_of_date": "not-a-date"},
                    company_wiki_root=root,
                )

    def test_config_file_not_found_is_rejected(self) -> None:
        with self.assertRaisesRegex(FilingFetchError, "does not exist"):
            load_company_wiki_root(config_path=Path("/nonexistent/config.json"))

    def test_timeout_seconds_must_be_positive(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            with self.assertRaisesRegex(ValueError, "positive"):
                resolve_filing(request=self._request(), company_wiki_root=root, timeout_seconds=0)

    def test_out_of_range_fiscal_year_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            with self.assertRaisesRegex(FilingFetchError, "out of range"):
                resolve_filing(
                    request={"schema_version": "1.1", "company_query": "AMD", "document_kind": "annual_report", "fiscal_year": 1800, "as_of_date": "2026-07-18"},
                    company_wiki_root=root,
                )

    def test_config_invalid_json_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            config = Path(temporary) / "bad.json"
            config.write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(FilingFetchError, "invalid"):
                load_company_wiki_root(config_path=config)

    def test_config_non_object_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            config = Path(temporary) / "bad.json"
            config.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(FilingFetchError, "must be an object"):
                load_company_wiki_root(config_path=config)


    def test_config_wrong_fields_is_rejected(self) -> None:
        """A config dict with extra/missing fields must be rejected."""
        with TemporaryDirectory() as temporary:
            config = Path(temporary) / "bad.json"
            config.write_text(json.dumps({"schema_version": "1.0", "company_wiki_root": "/tmp", "extra": "nope"}), encoding="utf-8")
            with self.assertRaisesRegex(FilingFetchError, "exact schema_version"):
                load_company_wiki_root(config_path=config)

    def test_config_bad_schema_version_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            config = Path(temporary) / "bad.json"
            config.write_text(json.dumps({"schema_version": "9.9", "company_wiki_root": "/tmp"}), encoding="utf-8")
            with self.assertRaisesRegex(FilingFetchError, "schema_version must be"):
                load_company_wiki_root(config_path=config)

    def test_config_root_not_exist_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            config = Path(temporary) / "cfg.json"
            config.write_text(json.dumps({"schema_version": "1.0", "company_wiki_root": temporary + "/no-such-dir"}), encoding="utf-8")
            with self.assertRaisesRegex(FilingFetchError, "does not exist"):
                load_company_wiki_root(config_path=config)

    def test_config_root_not_directory_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            tmp = Path(temporary)
            (tmp / "not-a-dir").write_text("x", encoding="utf-8")
            config = tmp / "cfg.json"
            config.write_text(json.dumps({"schema_version": "1.0", "company_wiki_root": str(tmp / "not-a-dir")}), encoding="utf-8")
            with self.assertRaisesRegex(FilingFetchError, "must be a directory"):
                load_company_wiki_root(config_path=config)

    def test_config_missing_catalog_yaml_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            tmp = Path(temporary)
            (tmp / "empty").mkdir()
            config = tmp / "cfg.json"
            config.write_text(json.dumps({"schema_version": "1.0", "company_wiki_root": str(tmp / "empty")}), encoding="utf-8")
            with self.assertRaisesRegex(FilingFetchError, "source_catalog.yaml"):
                load_company_wiki_root(config_path=config)

    def test_config_empty_root_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            config = Path(temporary) / "cfg.json"
            config.write_text(json.dumps({"schema_version": "1.0", "company_wiki_root": "  "}), encoding="utf-8")
            with self.assertRaisesRegex(FilingFetchError, "non-empty"):
                load_company_wiki_root(config_path=config)

    def test_source_not_reusable_is_rejected(self) -> None:
        """A response whose status is not 'reused_exact'/'reused_equivalent' is rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            response = {"status": "not_found", "reason": "no matching filing"}
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "not reusable"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_upstream_non_object_json_is_contract_error(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr="")
            with patch("fetch_filing.subprocess.run", return_value=completed):
                with self.assertRaisesRegex(FilingFetchError, "must be an object"):
                    resolve_filing(request=self._request(), company_wiki_root=root)


    def test_identity_response_not_resolved_is_rejected(self) -> None:
        """An identity response with status != 'resolved' must be rejected."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            bad_identity = self._identity_response()
            bad_identity["status"] = "ambiguous"
            bad_identity["reason"] = "multiple matches"
            bad_identity["resolved"] = None
            with patch("fetch_filing.subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(bad_identity), stderr="")):
                with self.assertRaisesRegex(FilingFetchError, "not uniquely resolved"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_identity_response_bad_schema_is_rejected(self) -> None:
        """An identity response with an unsupported schema_version must be rejected."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            bad = self._identity_response()
            bad["schema_version"] = "9.9"
            with patch("fetch_filing.subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(bad), stderr="")):
                with self.assertRaisesRegex(FilingFetchError, "schema_version"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_identity_response_missing_resolved_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            bad = self._identity_response()
            bad.pop("resolved")
            with patch("fetch_filing.subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(bad), stderr="")):
                with self.assertRaisesRegex(FilingFetchError, "identity is missing"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_explicit_download_requires_market_and_security_id(self) -> None:
        """allow_download=True without market/security_id must raise."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            identity = self._identity_response()
            identity["resolved"]["market"] = "ZZ"  # unsupported market
            identity["resolved"]["security_id"] = ""  # empty
            with patch("fetch_filing.subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(identity), stderr="")):
                with self.assertRaisesRegex(FilingFetchError, "non-empty"):
                    resolve_filing(request=self._request(), company_wiki_root=root, allow_download=True)


    def test_handle_future_published_date_is_rejected(self) -> None:
        """A handle dated after the request as_of_date must be rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            future = self._handle(root)
            future["published_date"] = "2027-01-01"
            response = {"status": "reused_exact", "request_id": "urn:future", "matches": [future]}
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "after"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_main_fatal_error_exit_code(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            config_path = parent / "company_wiki.json"
            config_path.write_text(
                json.dumps({"schema_version": "1.0", "company_wiki_root": str(root)}),
                encoding="utf-8",
            )
            source_response = {
                "status": "reused_exact",
                "request_id": "urn:cli",
                "matches": [self._handle(root)],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(source_response), stderr=""),
            ]
            request = json.dumps(self._request())
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                import io
                argv = ["--config", str(config_path), "--timeout-seconds", "0.5"]
                original_stdin, original_stdout = sys.stdin, sys.stdout
                sys.stdin = io.StringIO(request)
                sys.stdout = io.StringIO()
                try:
                    exit_code = __import__("fetch_filing").main(argv)
                finally:
                    sys.stdin, sys.stdout = original_stdin, original_stdout
            self.assertEqual(exit_code, 0)  # should succeed with valid timeout

    def test_handle_resolve_error_is_rejected(self) -> None:
        """A handle with a non-resolvable canonical_path must be rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            bad = self._handle(root)
            bad["canonical_path"] = str(parent / "subdir" / "report.pdf")
            response = {"status": "reused_exact", "request_id": "urn:badpath", "matches": [bad]}
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "outside"):
                    resolve_filing(request=self._request(), company_wiki_root=root)


    def test_handle_byte_size_mismatch_is_rejected(self) -> None:
        """A handle whose byte_size does not match the canonical file is rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            bad = self._handle(root)
            bad["byte_size"] = 99999
            response = {"status": "reused_exact", "request_id": "urn:bad-size", "matches": [bad]}
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "byte_size"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_handle_bad_published_date_format_is_rejected(self) -> None:
        """A handle whose published_date is not YYYY-MM-DD is rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            bad = self._handle(root)
            bad["published_date"] = "not-a-date"
            response = {"status": "reused_exact", "request_id": "urn:bad-date", "matches": [bad]}
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "YYYY-MM-DD"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_handle_missing_file_is_rejected(self) -> None:
        """A handle whose canonical_path does not point to a regular file is rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            bad = self._handle(root)
            import os as _os
            _os.remove(bad["canonical_path"])
            response = {"status": "reused_exact", "request_id": "urn:no-file", "matches": [bad]}
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "not a regular file"):
                    resolve_filing(request=self._request(), company_wiki_root=root)


    def test_main_bad_request_non_dict(self) -> None:
        """main() must reject a non-dict JSON request."""
        import io as _io
        argv: list[str] = []
        original_stdin, original_stdout = sys.stdin, sys.stdout
        sys.stdin = _io.StringIO("[]")
        sys.stdout = _io.StringIO()
        try:
            exit_code = __import__("fetch_filing").main(argv)
            self.assertNotEqual(exit_code, 0)
        finally:
            sys.stdin, sys.stdout = original_stdin, original_stdout

    def test_main_bad_timeout_is_rejected_by_cli(self) -> None:
        """CLI rejects non-positive timeout-seconds."""
        import io as _io
        request = json.dumps(self._request())
        argv = ["--timeout-seconds", "0"]
        original_stdin, original_stdout = sys.stdin, sys.stdout
        sys.stdin = _io.StringIO(request)
        sys.stdout = _io.StringIO()
        try:
            exit_code = __import__("fetch_filing").main(argv)
            self.assertNotEqual(exit_code, 0)
        finally:
            sys.stdin, sys.stdout = original_stdin, original_stdout

    def test_main_fatal_path_catches_unexpected_errors(self) -> None:
        """Unexpected exceptions in main() must yield exit code 1."""
        with patch("fetch_filing.resolve_filing", side_effect=RuntimeError("boom")):
            import io as _io
            request = json.dumps(self._request())
            argv: list[str] = []
            original_stdin, original_stdout = sys.stdin, sys.stdout
            sys.stdin = _io.StringIO(request)
            sys.stdout = _io.StringIO()
            try:
                exit_code = __import__("fetch_filing").main(argv)
                self.assertEqual(exit_code, 1)
            finally:
                sys.stdin, sys.stdout = original_stdin, original_stdout


if __name__ == "__main__":
    unittest.main()
