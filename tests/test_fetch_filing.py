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
            "entity": "ACME",
            "market": "US",
            "security_id": "ACME",
            "document_kind": "annual_report",
            "fiscal_year": 2025,
            "as_of_date": "2026-07-18",
        }

    def _handle(self, root: Path) -> dict:
        source = root / "report.pdf"
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
            response = {
                "status": "reused_exact",
                "request_id": "urn:company-wiki:request:1",
                "matches": [self._handle(parent)],
            }
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(response),
                stderr="",
            )

            with patch("fetch_filing.subprocess.run", return_value=completed) as run:
                handle = resolve_filing(
                    request=self._request(),
                    config_path=config_path,
                )

            command = run.call_args.args[0]
            self.assertEqual(run.call_args.kwargs["cwd"], root)
            self.assertIn(str(root / "config" / "source_catalog.yaml"), command)
            self.assertEqual(handle["request_id"], response["request_id"])

    def test_company_query_is_identified_before_read_only_resolve(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            request = {
                "company_query": "Advanced Micro Device",
                "market": "US",
                "document_kind": "annual_report",
                "fiscal_year": 2025,
                "as_of_date": "2026-07-18",
            }
            source_response = {
                "status": "reused_exact",
                "request_id": "urn:company-wiki:request:query",
                "matches": [self._handle(parent)],
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
                "company_query": "AMD",
                "document_kind": "annual_report",
                "fiscal_year": 2025,
                "as_of_date": "2026-07-18",
            }
            ensured = {
                "resolution": {
                    "status": "reused_equivalent",
                    "request_id": "urn:company-wiki:request:ensure-query",
                    "matches": [self._handle(parent)],
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
                        "matches": [self._handle(parent)],
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
            for conflicting in (
                {"entity": "guessed entity"},
                {"security_id": "guessed ticker"},
            ):
                with self.subTest(conflicting=conflicting):
                    with patch("fetch_filing.subprocess.run") as run:
                        with self.assertRaisesRegex(
                            FilingFetchError, "cannot be combined"
                        ):
                            resolve_filing(
                                request={
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
            response = {
                "status": "reused_exact",
                "request_id": "urn:company-wiki:request:cli",
                "matches": [self._handle(parent)],
            }
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(response), stderr=""
            )
            request = json.dumps(self._request())
            with patch("fetch_filing.subprocess.run", return_value=completed):
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


if __name__ == "__main__":
    unittest.main()
