"""filing-fetch contracts: identify -> resolve (reuse) / ensure (download)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import call, patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from fetch_filing import (  # noqa: E402
    FilingFetchError,
    _run_company_wiki_json,
    load_company_wiki_root,
    main,
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

    @staticmethod
    def _worker_status_response(
        *, desired: str = "enabled", runtime: str = "stopped"
    ) -> subprocess.CompletedProcess:
        """A worker-status response that makes the pause scope a no-op.

        ``runtime == "stopped"`` keeps mock-based tests at three subprocess
        calls (identity, worker-status, ensure); pause/resume paths are covered
        by dedicated tests.
        """
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"desired_state": desired, "runtime_state": runtime}),
            stderr="",
        )

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
                "schema_version": "1.0",
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
                "schema_version": "1.0",
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
                    "schema_version": "1.0",
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
                self._worker_status_response(),
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

            ensure_command = run.call_args_list[2].args[0]
            self.assertIn("ensure", ensure_command)
            self.assertIn("--allow-download", ensure_command)
            self.assertIn("--allow-acquisition-while-paused", ensure_command)
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
                        "schema_version": "1.0",
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
                with self.assertRaises(FilingFetchError) as ctx:
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
            self.assertIn("not uniquely resolved: ambiguous", str(ctx.exception))
            self.assertEqual(ctx.exception.code, "identity_error")

    def test_ambiguous_identity_surfaces_candidates_on_exception(self) -> None:
        # G7: when identify returns multiple candidates, filing-fetch must
        # forward them on the error so callers can disambiguate. Today the
        # candidates field is dropped and only a bare identity_error is raised.
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            base = self._identity_response()
            candidate_a = dict(base["resolved"])
            candidate_a.update(
                {"ticker": "GOOGL", "security_id": "GOOGL", "canonical_name": "Alphabet Inc."}
            )
            candidate_b = dict(base["resolved"])
            candidate_b.update(
                {"ticker": "GOOG", "security_id": "GOOG", "canonical_name": "Alphabet Inc."}
            )
            ambiguous = dict(base)
            ambiguous.update(
                {
                    "status": "ambiguous",
                    "reason": "multiple exact candidates",
                    "resolved": None,
                    "candidates": [candidate_a, candidate_b],
                }
            )
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(ambiguous), stderr=""
            )
            with patch("fetch_filing.subprocess.run", return_value=completed):
                with self.assertRaises(FilingFetchError) as ctx:
                    resolve_filing(
                        request={
                            "schema_version": "1.1",
                            "company_query": "Alphabet",
                            "document_kind": "annual_report",
                            "as_of_date": "2026-07-18",
                        },
                        company_wiki_root=root,
                    )
            candidates = ctx.exception.candidates
            self.assertIsInstance(candidates, list)
            self.assertEqual(len(candidates), 2)
            self.assertEqual([c["ticker"] for c in candidates], ["GOOGL", "GOOG"])

    def test_main_emits_candidates_and_hint_on_ambiguous_identity(self) -> None:
        # The CLI error response must carry candidates plus a disambiguation
        # hint so a user can resolve the ambiguity from the response alone.
        candidates = [
            {"ticker": "GOOGL", "canonical_name": "Alphabet Inc.", "market": "US", "exchange": "NASDAQ"},
            {"ticker": "GOOG", "canonical_name": "Alphabet Inc.", "market": "US", "exchange": "NASDAQ"},
        ]
        with TemporaryDirectory() as temporary:
            request_path = Path(temporary) / "request.json"
            request_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.1",
                        "company_query": "Alphabet",
                        "document_kind": "annual_report",
                        "as_of_date": "2026-07-18",
                    }
                ),
                encoding="utf-8",
            )

            def _raise(**_kwargs):
                raise FilingFetchError(
                    "company identity is not uniquely resolved: ambiguous",
                    code="identity_error",
                    candidates=candidates,
                )

            buffer = StringIO()
            with patch("fetch_filing.resolve_filing", side_effect=_raise):
                with contextlib.redirect_stdout(buffer):
                    rc = main(["--request-file", str(request_path)])
            self.assertEqual(rc, 2)
            response = json.loads(buffer.getvalue())
            self.assertEqual(response["error_code"], "identity_error")
            self.assertEqual(response["candidates"], candidates)
            self.assertIn("hint", response)
            self.assertTrue(response["hint"].strip())

    def test_resolve_not_found_carries_debug_trace_on_error(self) -> None:
        # Phase 19.6: when company-wiki resolve returns not_found, the
        # per-candidate exclusion trace must ride on the FilingFetchError so
        # the caller can explain the miss (today the trace is dropped).
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            trace = [
                "entity_gate_rejected: 12",
                "Alphabet 2025 Annual Report: identity_conflict_market_or_security_id",
            ]
            response = {
                "schema_version": "1.0",
                "status": "not_found",
                "reason": "no_existing_source_satisfies_request",
                "debug_trace": trace,
            }
            completed = [
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""
                ),
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(response), stderr=""
                ),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaises(FilingFetchError) as ctx:
                    resolve_filing(request=self._request(), company_wiki_root=root)
            self.assertEqual(ctx.exception.code, "not_found")
            self.assertEqual(ctx.exception.debug_trace, trace)

    def test_main_debug_flag_emits_debug_trace(self) -> None:
        # Phase 19.6: with --debug, the CLI error response carries the
        # per-candidate exclusion trace from the resolve step.
        trace = [
            "entity_gate_rejected: 12",
            "Alphabet 2025 Annual Report: identity_conflict_market_or_security_id",
        ]
        with TemporaryDirectory() as temporary:
            request_path = Path(temporary) / "request.json"
            request_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.1",
                        "company_query": "Alphabet",
                        "document_kind": "annual_report",
                        "as_of_date": "2026-07-18",
                    }
                ),
                encoding="utf-8",
            )

            def _raise(**_kwargs):
                raise FilingFetchError(
                    "source is not reusable: not_found",
                    code="not_found",
                    debug_trace=trace,
                )

            buffer = StringIO()
            with patch("fetch_filing.resolve_filing", side_effect=_raise):
                with contextlib.redirect_stdout(buffer):
                    rc = main(["--debug", "--request-file", str(request_path)])
            self.assertEqual(rc, 2)
            response = json.loads(buffer.getvalue())
            self.assertEqual(response["debug_trace"], trace)

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
                "schema_version": "1.0",
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
                "schema_version": "1.0",
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
                "schema_version": "1.0",
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
            response = {"schema_version": "1.0", "status": "reused_exact", "request_id": "urn:bad-hash", "matches": [bad]}
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
            response = {"schema_version": "1.0", "status": "reused_exact", "request_id": "urn:bad-digest", "matches": [bad]}
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
            response = {"schema_version": "1.0", "status": "reused_exact", "request_id": "urn:bad-url", "matches": [bad]}
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
            with self.assertRaisesRegex(FilingFetchError, "schema_version/company_wiki_root"):
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
            response = {"schema_version": "1.0", "status": "not_found", "reason": "no matching filing"}
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
            response = {"schema_version": "1.0", "status": "reused_exact", "request_id": "urn:future", "matches": [future]}
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "after"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_main_cli_accepts_fractional_timeout(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            config_path = parent / "company_wiki.json"
            config_path.write_text(
                json.dumps({"schema_version": "1.0", "company_wiki_root": str(root)}),
                encoding="utf-8",
            )
            source_response = {
                "schema_version": "1.0",
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
            response = {"schema_version": "1.0", "status": "reused_exact", "request_id": "urn:badpath", "matches": [bad]}
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
            response = {"schema_version": "1.0", "status": "reused_exact", "request_id": "urn:bad-size", "matches": [bad]}
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
            response = {"schema_version": "1.0", "status": "reused_exact", "request_id": "urn:bad-date", "matches": [bad]}
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
            response = {"schema_version": "1.0", "status": "reused_exact", "request_id": "urn:no-file", "matches": [bad]}
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


    # --- conformance: upstream contract hardening (Phase 9.10) ---

    def test_ensure_response_missing_resolution_key_fails(self) -> None:
        """An ensure response without a 'resolution' key must be rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            identity = self._identity_response()
            bad_ensure = {"status": "reused_exact", "matches": [self._handle(root)]}
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(identity), stderr=""),
                self._worker_status_response(),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(bad_ensure), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "resolution"):
                    resolve_filing(request=self._request(), company_wiki_root=root, allow_download=True)

    def test_upstream_subprocess_oserror_fails(self) -> None:
        """A subprocess OSError must be wrapped in FilingFetchError."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            with patch("fetch_filing.subprocess.run", side_effect=OSError("spawn failed")):
                with self.assertRaisesRegex(FilingFetchError, "failed"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_resolve_non_dict_response_fails(self) -> None:
        """A resolve response that is not a dict must be rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            identity = self._identity_response()
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(identity), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout='"just a string"', stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "must be an object"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_ensure_status_not_reusable_is_rejected(self) -> None:
        """An ensure response with status not in {reused_exact, reused_equivalent} is rejected."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            identity = self._identity_response()
            ensure = {"resolution": {"schema_version": "1.0", "status": "not_found", "reason": "no match"}}
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(identity), stderr=""),
                self._worker_status_response(),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(ensure), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "not reusable"):
                    resolve_filing(request=self._request(), company_wiki_root=root, allow_download=True)

    def test_resolve_multi_match_with_different_hashes_fails(self) -> None:
        """Multiple non-identical matches must be rejected (no silent pick)."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            identity = self._identity_response()
            a = self._handle(root)
            a["snapshot_sha256"] = "a" * 64
            b = self._handle(root)
            b["snapshot_sha256"] = "b" * 64
            response = {"schema_version": "1.0", "status": "reused_exact", "request_id": "urn:multi", "matches": [a, b]}
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(identity), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "exactly one"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    # --- Phase 16.4: stdin accepts UTF-8 Chinese queries ---

    def test_cli_stdin_accepts_utf8_chinese_query(self):
        """A UTF-8 Chinese company query piped via stdin must reach the
        identity resolver intact: Windows pipes are decoded with the locale
        codepage (GBK) by default, corrupting the query (Phase 16.4).

        Live-dependency guard: this runs against the production wiki (the
        紫金矿业 FY2024 filing must be indexed); CI clones a clean company-wiki
        with no production companies/, so it skips there."""
        from e2e_support.isolated_wiki import PRODUCTION_WIKI
        security_master = PRODUCTION_WIKI / "config" / ".source_catalog" / "security_master"
        if not security_master.is_dir() or not any(security_master.iterdir()):
            self.skipTest("production security-master snapshots not present")
        script = SKILL_ROOT / "scripts" / "fetch_filing.py"
        request = json.dumps(
            {
                "schema_version": "1.1",
                "company_query": "紫金矿业",
                "market": "CN",
                "document_kind": "annual_report",
                "fiscal_year": 2024,
                "as_of_date": "2026-07-31",
            },
            ensure_ascii=False,
        )
        env = dict(os.environ)
        env.pop("PYTHONUTF8", None)
        proc = subprocess.run(
            [sys.executable, str(script), "--timeout-seconds", "180"],
            input=request.encode("utf-8"),
            capture_output=True,
            cwd=str(SKILL_ROOT / "scripts"),
            env=env,
            timeout=240,
        )
        payload = json.loads(proc.stdout.decode("utf-8"))
        # FY2024 was downloaded in Phase 15.6: reuse-first must be capture_ready.
        # A GBK-corrupted query fails earlier with an identity error.
        assert payload["status"] == "capture_ready", payload.get("error")

    # --- Phase 15.2: catalog lock contention is retryable ---

    def test_catalog_lock_error_is_classified_retryable(self) -> None:
        """A company-wiki CatalogOperationLockedError must be classified as
        catalog_locked / retryable, not fatal; other upstream errors must stay
        fail-closed (fatal / not retryable)."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            for error_type, expected_code, expected_retryable in (
                ("CatalogOperationLockedError", "catalog_locked", True),
                ("SomeOtherUpstreamError", "fatal", False),
            ):
                with self.subTest(error_type=error_type):
                    failed = subprocess.CompletedProcess(
                        args=[],
                        returncode=1,
                        stdout="",
                        stderr=json.dumps(
                            {
                                "status": "failed",
                                "error_type": error_type,
                                "error": "catalog operation already running: pid=15536",
                            }
                        ),
                    )
                    with patch("fetch_filing.subprocess.run", return_value=failed):
                        with self.assertRaises(FilingFetchError) as ctx:
                            _run_company_wiki_json(
                                command=["company_wiki.source_catalog.cli"],
                                root=root,
                                timeout_seconds=30,
                                action="resolve",
                            )
                    self.assertEqual(ctx.exception.code, expected_code)
                    self.assertEqual(ctx.exception.retryable, expected_retryable)

    def test_catalog_lock_retries_with_backoff_then_succeeds(self) -> None:
        """Lock contention is retried with exponential backoff (5s, 10s) and
        recovers once the catalog is free, within the overall deadline."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            locked = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr=json.dumps(
                    {
                        "status": "failed",
                        "error_type": "CatalogOperationLockedError",
                        "error": "catalog operation already running: pid=15536",
                    }
                ),
            )
            ok_identity = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""
            )
            source_response = {
                "schema_version": "1.0",
                "status": "reused_exact",
                "request_id": "urn:company-wiki:request:after-lock",
                "matches": [self._handle(root)],
            }
            ok_source = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(source_response), stderr=""
            )
            completed = [ok_identity, locked, locked, ok_source]
            with patch("fetch_filing.subprocess.run", side_effect=completed) as run:
                with patch("fetch_filing.time.sleep") as sleep:
                    handle = resolve_filing(
                        request=self._request(),
                        company_wiki_root=root,
                    )
            self.assertEqual(run.call_count, 4)  # identify + 3 resolve attempts
            self.assertEqual(sleep.call_args_list, [call(5.0), call(10.0)])
            self.assertEqual(handle["request_id"], source_response["request_id"])


    # --- Phase 2: request validation boundaries ---

    def test_missing_company_query_is_request_error(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            request = self._request()
            del request["company_query"]
            with self.assertRaises(FilingFetchError) as ctx:
                resolve_filing(request=request, company_wiki_root=root)
            self.assertEqual(ctx.exception.code, "request_error")
            self.assertIn("company_query", str(ctx.exception))

    def test_blank_company_query_is_request_error(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            for query in ("  ", " AMD "):
                with self.subTest(query=query):
                    request = self._request()
                    request["company_query"] = query
                    with self.assertRaises(FilingFetchError) as ctx:
                        resolve_filing(request=request, company_wiki_root=root)
                    self.assertEqual(ctx.exception.code, "request_error")

    def test_invalid_market_hint_is_request_error(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            request = self._request()
            request["market"] = "XX"
            with self.assertRaises(FilingFetchError) as ctx:
                resolve_filing(request=request, company_wiki_root=root)
            self.assertEqual(ctx.exception.code, "request_error")
            self.assertIn("market", str(ctx.exception))

    def test_float_fiscal_year_is_request_error(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            request = self._request()
            request["fiscal_year"] = 2026.0
            with self.assertRaises(FilingFetchError) as ctx:
                resolve_filing(request=request, company_wiki_root=root)
            self.assertEqual(ctx.exception.code, "request_error")

    def test_non_padded_as_of_date_is_request_error(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            request = self._request()
            request["as_of_date"] = "2026-7-18"
            with self.assertRaises(FilingFetchError) as ctx:
                resolve_filing(request=request, company_wiki_root=root)
            self.assertEqual(ctx.exception.code, "request_error")

    # --- Phase 2: error classification codes ---

    def test_config_errors_carry_config_error_code(self) -> None:
        with TemporaryDirectory() as temporary:
            tmp = Path(temporary)
            cases = []
            missing = tmp / "missing.json"
            cases.append((missing, "does not exist"))
            bad_json = tmp / "bad.json"
            bad_json.write_text("not json", encoding="utf-8")
            cases.append((bad_json, "invalid"))
            empty = tmp / "empty"
            empty.mkdir()
            no_catalog = tmp / "no-catalog.json"
            no_catalog.write_text(
                json.dumps({"schema_version": "1.0", "company_wiki_root": str(empty)}),
                encoding="utf-8",
            )
            cases.append((no_catalog, "source_catalog.yaml"))
            not_dir = tmp / "not-a-dir"
            not_dir.write_text("x", encoding="utf-8")
            not_dir_cfg = tmp / "not-dir.json"
            not_dir_cfg.write_text(
                json.dumps({"schema_version": "1.0", "company_wiki_root": str(not_dir)}),
                encoding="utf-8",
            )
            cases.append((not_dir_cfg, "must be a directory"))
            for config_path, needle in cases:
                with self.subTest(config=config_path.name):
                    with self.assertRaises(FilingFetchError) as ctx:
                        load_company_wiki_root(config_path=config_path)
                    self.assertEqual(ctx.exception.code, "config_error")
                    self.assertIn(needle, str(ctx.exception))

    def test_identity_failures_carry_identity_error_code(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            ambiguous = self._identity_response()
            ambiguous["status"] = "ambiguous"
            ambiguous["reason"] = "multiple exact candidates"
            ambiguous["resolved"] = None
            unverified = self._identity_response()
            unverified["resolved"]["verified"] = False
            inactive = self._identity_response()
            inactive["resolved"]["active"] = False
            bad_schema = self._identity_response()
            bad_schema["schema_version"] = "9.9"
            unsupported_market = self._identity_response()
            unsupported_market["resolved"]["market"] = "ZZ"
            for identity in (ambiguous, unverified, inactive, bad_schema, unsupported_market):
                with self.subTest(status=identity["status"]):
                    completed = subprocess.CompletedProcess(
                        args=[], returncode=0, stdout=json.dumps(identity), stderr=""
                    )
                    with patch("fetch_filing.subprocess.run", return_value=completed):
                        with self.assertRaises(FilingFetchError) as ctx:
                            resolve_filing(request=self._request(), company_wiki_root=root)
                    self.assertEqual(ctx.exception.code, "identity_error")

    def test_missing_source_carries_not_found_code(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            for status in ("missing", "ambiguous", "identity_conflict"):
                with self.subTest(status=status):
                    response = {
                        "schema_version": "1.0",
                        "status": status,
                        "reason": f"why-{status}",
                    }
                    completed = [
                        subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                        subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
                    ]
                    with patch("fetch_filing.subprocess.run", side_effect=completed):
                        with self.assertRaises(FilingFetchError) as ctx:
                            resolve_filing(request=self._request(), company_wiki_root=root)
                    self.assertEqual(ctx.exception.code, "not_found")

    def test_ensure_missing_carries_not_found_code(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            ensure = {
                "resolution": {"schema_version": "1.0", "status": "missing", "reason": "no filing"}
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                self._worker_status_response(),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(ensure), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaises(FilingFetchError) as ctx:
                    resolve_filing(request=self._request(), company_wiki_root=root, allow_download=True)
            self.assertEqual(ctx.exception.code, "not_found")

    def test_capture_not_ready_carries_not_found_code(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            not_ready = self._handle(root)
            not_ready["capture_ready"] = False
            not_ready["missing_capture_fields"] = ["https_url", "capture_trace"]
            response = {
                "schema_version": "1.0",
                "status": "reused_exact",
                "request_id": "urn:not-ready",
                "matches": [not_ready],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaises(FilingFetchError) as ctx:
                    resolve_filing(request=self._request(), company_wiki_root=root)
            self.assertEqual(ctx.exception.code, "not_found")
            self.assertIn("https_url", str(ctx.exception))
            self.assertIn("capture_trace", str(ctx.exception))

    def test_multi_match_carries_upstream_error_code(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            response = {
                "schema_version": "1.0",
                "status": "reused_exact",
                "request_id": "urn:multi",
                "matches": [self._handle(root), self._handle(root)],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaises(FilingFetchError) as ctx:
                    resolve_filing(request=self._request(), company_wiki_root=root)
            self.assertEqual(ctx.exception.code, "upstream_error")

    def test_worker_paused_maps_to_retryable_worker_paused(self) -> None:
        """A paused-worker upstream failure maps to worker_paused (retryable)
        and is NOT auto-retried like catalog_locked; exit code stays 2."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            config_path = parent / "company_wiki.json"
            config_path.write_text(
                json.dumps({"schema_version": "1.0", "company_wiki_root": str(root)}),
                encoding="utf-8",
            )
            paused = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr=json.dumps(
                    {
                        "status": "failed",
                        "error_type": "RuntimeError",
                        "error": "source acquisition is paused; start the worker to resume",
                    }
                ),
            )
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                paused,
            ]
            import io as _io

            request = json.dumps(self._request())
            original_stdin, original_stdout = sys.stdin, sys.stdout
            sys.stdin = _io.StringIO(request)
            sys.stdout = _io.StringIO()
            try:
                with patch("fetch_filing.subprocess.run", side_effect=completed) as run:
                    exit_code = __import__("fetch_filing").main(["--config", str(config_path)])
                output = sys.stdout.getvalue()
            finally:
                sys.stdin, sys.stdout = original_stdin, original_stdout
            self.assertEqual(exit_code, 2)
            payload = json.loads(output)
            self.assertEqual(payload["status"], "worker_paused")
            self.assertEqual(payload["error_code"], "worker_paused")
            self.assertTrue(payload["retryable"])
            self.assertEqual(run.call_count, 2)  # identify + one resolve: no retry

    def test_resolve_schema_version_mismatch_is_upstream_error(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            response = {
                "schema_version": "9.9",
                "status": "reused_exact",
                "request_id": "urn:schema",
                "matches": [self._handle(root)],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaises(FilingFetchError) as ctx:
                    resolve_filing(request=self._request(), company_wiki_root=root)
            self.assertEqual(ctx.exception.code, "upstream_error")
            self.assertIn("schema_version", str(ctx.exception))

    def test_ensure_resolution_schema_version_mismatch_is_upstream_error(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            ensure = {
                "resolution": {
                    "schema_version": "9.9",
                    "status": "reused_exact",
                    "request_id": "urn:schema",
                    "matches": [self._handle(root)],
                }
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                self._worker_status_response(),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(ensure), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaises(FilingFetchError) as ctx:
                    resolve_filing(request=self._request(), company_wiki_root=root, allow_download=True)
            self.assertEqual(ctx.exception.code, "upstream_error")
            self.assertIn("schema_version", str(ctx.exception))

    # --- Phase 2: deadline and timeout propagation ---

    def test_timeout_seconds_must_be_finite(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            for bad in (float("inf"), float("nan")):
                with self.subTest(timeout=bad):
                    with self.assertRaisesRegex(ValueError, "finite"):
                        resolve_filing(
                            request=self._request(), company_wiki_root=root, timeout_seconds=bad
                        )

    def test_subprocess_receives_remaining_deadline(self) -> None:
        """The deadline budget, not the full timeout, is passed to each
        subprocess.run as its timeout kwarg."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            source_response = {
                "schema_version": "1.0",
                "status": "reused_exact",
                "request_id": "urn:deadline",
                "matches": [self._handle(root)],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(source_response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed) as run:
                with patch("fetch_filing.time.monotonic", side_effect=[100.0, 100.0, 100.0]):
                    resolve_filing(request=self._request(), company_wiki_root=root, timeout_seconds=30)
            self.assertEqual(run.call_count, 2)
            for call_args in run.call_args_list:
                self.assertEqual(call_args.kwargs["timeout"], 30.0)

    def test_deadline_exhausted_before_resolve_is_upstream_error(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            with patch("fetch_filing.subprocess.run") as run:
                with patch("fetch_filing.time.monotonic", side_effect=[100.0, 131.0]):
                    with self.assertRaises(FilingFetchError) as ctx:
                        resolve_filing(request=self._request(), company_wiki_root=root, timeout_seconds=30)
            self.assertEqual(ctx.exception.code, "upstream_error")
            run.assert_not_called()

    def test_catalog_locked_until_deadline_is_upstream_error(self) -> None:
        """Constantly locked catalog: backoff retries exhaust the deadline and
        the failure surfaces as upstream_error, not a hang."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            locked = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr=json.dumps(
                    {
                        "status": "failed",
                        "error_type": "CatalogOperationLockedError",
                        "error": "catalog operation already running: pid=15536",
                    }
                ),
            )
            with patch("fetch_filing.subprocess.run", return_value=locked) as run:
                with patch("fetch_filing.time.sleep") as sleep:
                    with patch(
                        "fetch_filing.time.monotonic", side_effect=[100.0, 100.0, 105.0, 108.0]
                    ):
                        with self.assertRaises(FilingFetchError) as ctx:
                            resolve_filing(
                                request=self._request(), company_wiki_root=root, timeout_seconds=8
                            )
            self.assertEqual(ctx.exception.code, "upstream_error")
            self.assertEqual(run.call_count, 2)
            self.assertEqual(sleep.call_args_list, [call(5.0), call(3.0)])

    def test_upstream_subprocess_timeout_is_upstream_error(self) -> None:
        """A subprocess timeout (attempt outlived the deadline budget) must
        classify as upstream_error, not fatal (Phase 3 E2E scenario 12)."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            with patch(
                "fetch_filing.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["x"], timeout=8),
            ):
                with self.assertRaises(FilingFetchError) as ctx:
                    resolve_filing(request=self._request(), company_wiki_root=root)
            self.assertEqual(ctx.exception.code, "upstream_error")

    def test_worker_paused_is_not_auto_retried(self) -> None:
        """worker_paused is retryable by the caller but filing-fetch itself
        must not spin on it (unlike catalog_locked backoff)."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            paused = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr=json.dumps(
                    {
                        "status": "failed",
                        "error_type": "RuntimeError",
                        "error": "source acquisition is paused; ...",
                    }
                ),
            )
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                paused,
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed) as run:
                with patch("fetch_filing.time.sleep") as sleep:
                    with self.assertRaises(FilingFetchError) as ctx:
                        resolve_filing(request=self._request(), company_wiki_root=root)
            self.assertEqual(ctx.exception.code, "worker_paused")
            self.assertEqual(run.call_count, 2)  # identify + one resolve, no retry
            sleep.assert_not_called()

    # --- Phase 2: handle boundaries ---

    def test_published_date_equal_as_of_date_is_accepted(self) -> None:
        """published_date == as_of_date is the inclusive boundary and must pass."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            handle = self._handle(root)
            handle["published_date"] = "2026-07-18"
            response = {
                "schema_version": "1.0",
                "status": "reused_exact",
                "request_id": "urn:edge",
                "matches": [handle],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                result = resolve_filing(request=self._request(), company_wiki_root=root)
            self.assertEqual(result["published_date"], "2026-07-18")

    def test_relative_canonical_path_is_resolved_against_wiki_root(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            handle = self._handle(root)
            handle["canonical_path"] = "companies/report.pdf"
            response = {
                "schema_version": "1.0",
                "status": "reused_exact",
                "request_id": "urn:relative",
                "matches": [handle],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                result = resolve_filing(request=self._request(), company_wiki_root=root)
            self.assertEqual(result["canonical_path"], "companies/report.pdf")

    def test_bool_byte_size_is_rejected(self) -> None:
        """bool is an int subclass and must not pass as byte_size."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            bad = self._handle(root)
            bad["byte_size"] = True
            response = {
                "schema_version": "1.0",
                "status": "reused_exact",
                "request_id": "urn:bool-size",
                "matches": [bad],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaisesRegex(FilingFetchError, "byte_size"):
                    resolve_filing(request=self._request(), company_wiki_root=root)

    def test_single_non_dict_match_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            response = {
                "schema_version": "1.0",
                "status": "reused_exact",
                "request_id": "urn:non-dict",
                "matches": ["x"],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaises(FilingFetchError) as ctx:
                    resolve_filing(request=self._request(), company_wiki_root=root)
            self.assertEqual(ctx.exception.code, "upstream_error")
            self.assertIn("exactly one", str(ctx.exception))

    def test_missing_request_id_in_resolution_is_rejected(self) -> None:
        """A resolution without request_id injects None into the handle and
        must be rejected by the new non-empty check."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            response = {
                "schema_version": "1.0",
                "status": "reused_exact",
                "matches": [self._handle(root)],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                with self.assertRaises(FilingFetchError) as ctx:
                    resolve_filing(request=self._request(), company_wiki_root=root)
            self.assertEqual(ctx.exception.code, "upstream_error")
            self.assertIn("request_id", str(ctx.exception))

    def test_handle_extra_fields_are_tolerated(self) -> None:
        """Forward compatibility: unknown handle fields must not be rejected."""
        with TemporaryDirectory() as temporary:
            root = self._wiki_root(Path(temporary), "company-wiki")
            handle = self._handle(root)
            handle["future_field"] = "future value"
            response = {
                "schema_version": "1.0",
                "status": "reused_exact",
                "request_id": "urn:extra",
                "matches": [handle],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(response), stderr=""),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed):
                result = resolve_filing(request=self._request(), company_wiki_root=root)
            self.assertEqual(result["future_field"], "future value")

    # --- Phase 2: CLI main() boundaries ---

    def test_main_request_file_happy_path(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            config_path = parent / "company_wiki.json"
            config_path.write_text(
                json.dumps({"schema_version": "1.0", "company_wiki_root": str(root)}),
                encoding="utf-8",
            )
            request_file = parent / "request.json"
            request_file.write_text(json.dumps(self._request()), encoding="utf-8")
            source_response = {
                "schema_version": "1.0",
                "status": "reused_exact",
                "request_id": "urn:file",
                "matches": [self._handle(root)],
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(source_response), stderr=""),
            ]
            import io as _io

            original_stdin, original_stdout = sys.stdin, sys.stdout
            sys.stdin = _io.StringIO("")  # must be ignored when --request-file is given
            sys.stdout = _io.StringIO()
            try:
                with patch("fetch_filing.subprocess.run", side_effect=completed):
                    exit_code = __import__("fetch_filing").main(
                        ["--config", str(config_path), "--request-file", str(request_file)]
                    )
                output = sys.stdout.getvalue()
            finally:
                sys.stdin, sys.stdout = original_stdin, original_stdout
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output)["handle"]["request_id"], "urn:file")

    def test_main_request_file_invalid_json_is_request_error_exit_2(self) -> None:
        with TemporaryDirectory() as temporary:
            request_file = Path(temporary) / "request.json"
            request_file.write_text("not json", encoding="utf-8")
            import io as _io

            original_stdin, original_stdout = sys.stdin, sys.stdout
            sys.stdin = _io.StringIO("")
            sys.stdout = _io.StringIO()
            try:
                exit_code = __import__("fetch_filing").main(
                    ["--request-file", str(request_file)]
                )
                output = sys.stdout.getvalue()
            finally:
                sys.stdin, sys.stdout = original_stdin, original_stdout
            self.assertEqual(exit_code, 2)
            payload = json.loads(output)
            self.assertEqual(payload["status"], "request_error")
            self.assertFalse(payload["retryable"])

    def test_main_empty_stdin_is_request_error_exit_2(self) -> None:
        import io as _io

        original_stdin, original_stdout = sys.stdin, sys.stdout
        sys.stdin = _io.StringIO("")
        sys.stdout = _io.StringIO()
        try:
            exit_code = __import__("fetch_filing").main([])
            output = sys.stdout.getvalue()
        finally:
            sys.stdin, sys.stdout = original_stdin, original_stdout
        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(output)["status"], "request_error")

    def test_main_allow_download_flag_builds_ensure_command(self) -> None:
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            config_path = parent / "company_wiki.json"
            config_path.write_text(
                json.dumps({"schema_version": "1.0", "company_wiki_root": str(root)}),
                encoding="utf-8",
            )
            ensure = {
                "resolution": {
                    "schema_version": "1.0",
                    "status": "reused_exact",
                    "request_id": "urn:ensure",
                    "matches": [self._handle(root)],
                }
            }
            completed = [
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""),
                self._worker_status_response(),
                subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(ensure), stderr=""),
            ]
            import io as _io

            original_stdin, original_stdout = sys.stdin, sys.stdout
            sys.stdin = _io.StringIO(json.dumps(self._request()))
            sys.stdout = _io.StringIO()
            try:
                with patch("fetch_filing.subprocess.run", side_effect=completed) as run:
                    exit_code = __import__("fetch_filing").main(
                        ["--config", str(config_path), "--allow-download"]
                    )
            finally:
                sys.stdin, sys.stdout = original_stdin, original_stdout
            self.assertEqual(exit_code, 0)
            ensure_command = run.call_args_list[2].args[0]
            self.assertIn("ensure", ensure_command)
            self.assertIn("--allow-download", ensure_command)
            self.assertIn("--allow-acquisition-while-paused", ensure_command)

    # --- Worker pause-around orchestration ---

    def test_allow_download_pauses_and_resumes_running_worker(self) -> None:
        """A running, enabled worker is paused before the download and resumed
        afterwards, so its batch continues once the fetch completes."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            ensure = {
                "resolution": {
                    "schema_version": "1.0",
                    "status": "reused_exact",
                    "request_id": "urn:ensure",
                    "matches": [self._handle(root)],
                }
            }
            completed = [
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""
                ),
                self._worker_status_response(desired="enabled", runtime="running"),
                subprocess.CompletedProcess(
                    args=[], returncode=0,
                    stdout=json.dumps({"desired_state": "paused", "runtime_state": "stopped"}),
                    stderr="",
                ),
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(ensure), stderr=""
                ),
                subprocess.CompletedProcess(
                    args=[], returncode=0,
                    stdout=json.dumps({"desired_state": "enabled", "runtime_state": "running"}),
                    stderr="",
                ),
            ]
            with patch("fetch_filing._pid_is_alive", return_value=True):
                with patch("fetch_filing.subprocess.run", side_effect=completed) as run:
                    resolve_filing(request=self._request(), company_wiki_root=root, allow_download=True)
            calls = [c.args[0] for c in run.call_args_list]
            self.assertIn("worker-status", calls[1])
            self.assertIn("worker-pause", calls[2])
            self.assertIn("ensure", calls[3])
            self.assertIn("--allow-acquisition-while-paused", calls[3])
            self.assertIn("worker-resume", calls[4])
            # refcount and owner marker are cleaned up after the resume
            self.assertFalse((root / ".source_catalog" / "filing_fetch_pause.owner").exists())
            self.assertFalse((root / ".source_catalog" / "filing_fetch_pause.refcount").exists())

    def test_user_paused_worker_is_respected_and_never_resumed(self) -> None:
        """A worker paused by the user (no filing-fetch owner marker) is not
        resumed; the download still proceeds via the explicit opt-in flag."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            ensure = {
                "resolution": {
                    "schema_version": "1.0",
                    "status": "reused_exact",
                    "request_id": "urn:ensure",
                    "matches": [self._handle(root)],
                }
            }
            completed = [
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""
                ),
                self._worker_status_response(desired="paused", runtime="stopped"),
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(ensure), stderr=""
                ),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed) as run:
                resolve_filing(request=self._request(), company_wiki_root=root, allow_download=True)
            calls = [c.args[0] for c in run.call_args_list]
            self.assertEqual(len(calls), 3)  # identify, worker-status, ensure
            self.assertNotIn("worker-pause", calls[2])
            self.assertIn("--allow-acquisition-while-paused", calls[2])
            # no resume, no refcount/marker artifacts
            self.assertFalse((root / ".source_catalog" / "filing_fetch_pause.owner").exists())
            self.assertFalse((root / ".source_catalog" / "filing_fetch_pause.refcount").exists())

    def test_stopped_worker_skips_pause_and_resume(self) -> None:
        """A worker that is not running needs no pause; the download proceeds."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            ensure = {
                "resolution": {
                    "schema_version": "1.0",
                    "status": "reused_exact",
                    "request_id": "urn:ensure",
                    "matches": [self._handle(root)],
                }
            }
            completed = [
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""
                ),
                self._worker_status_response(desired="enabled", runtime="stopped"),
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(ensure), stderr=""
                ),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed) as run:
                resolve_filing(request=self._request(), company_wiki_root=root, allow_download=True)
            calls = [c.args[0] for c in run.call_args_list]
            self.assertEqual(len(calls), 3)
            self.assertNotIn("worker-pause", calls[2])
            self.assertIn("--allow-acquisition-while-paused", calls[2])

    def test_ensure_failure_still_resumes_worker(self) -> None:
        """An ensure failure inside the pause scope must not leave the worker
        paused: __exit__ runs on the exception path and resumes it."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            completed = [
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""
                ),
                self._worker_status_response(desired="enabled", runtime="running"),
                subprocess.CompletedProcess(
                    args=[], returncode=0,
                    stdout=json.dumps({"desired_state": "paused", "runtime_state": "stopped"}),
                    stderr="",
                ),
                subprocess.CompletedProcess(
                    args=[], returncode=1, stdout="",
                    stderr='{"error_type": "RuntimeError", "error": "boom"}',
                ),
                subprocess.CompletedProcess(
                    args=[], returncode=0,
                    stdout=json.dumps({"desired_state": "enabled", "runtime_state": "running"}),
                    stderr="",
                ),
            ]
            with patch("fetch_filing._pid_is_alive", return_value=True):
                with patch("fetch_filing.subprocess.run", side_effect=completed) as run:
                    with self.assertRaises(FilingFetchError):
                        resolve_filing(
                            request=self._request(), company_wiki_root=root,
                            allow_download=True,
                        )
            calls = [c.args[0] for c in run.call_args_list]
            self.assertIn("worker-resume", calls[4])
            self.assertFalse((root / ".source_catalog" / "filing_fetch_pause.owner").exists())
            self.assertFalse((root / ".source_catalog" / "filing_fetch_pause.refcount").exists())

    def test_no_pause_worker_restores_legacy_command(self) -> None:
        """--no-pause-worker keeps the legacy behavior: no worker-status call
        and no paused-guard opt-in flag."""
        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            ensure = {
                "resolution": {
                    "schema_version": "1.0",
                    "status": "reused_exact",
                    "request_id": "urn:ensure",
                    "matches": [self._handle(root)],
                }
            }
            completed = [
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(self._identity_response()), stderr=""
                ),
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=json.dumps(ensure), stderr=""
                ),
            ]
            with patch("fetch_filing.subprocess.run", side_effect=completed) as run:
                resolve_filing(
                    request=self._request(), company_wiki_root=root,
                    allow_download=True, pause_worker=False,
                )
            calls = [c.args[0] for c in run.call_args_list]
            self.assertEqual(len(calls), 2)
            self.assertNotIn("--allow-acquisition-while-paused", calls[1])

    # --- Config-driven handle path allowance (ADR-008 Strategy B) ---

    def test_validate_handle_accepts_configured_allowed_root(self) -> None:
        """A handle inside a configured allowed root (e.g. the dayu portfolio)
        passes the path fence."""
        from filing_contracts import validate_handle

        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            portfolio = parent / "portfolio"
            portfolio.mkdir(parents=True)
            payload = b"portfolio filing bytes"
            target = portfolio / "6082" / "annual.pdf"
            target.parent.mkdir(parents=True)
            target.write_bytes(payload)
            handle = self._handle(root)
            handle["canonical_path"] = str(target)
            handle["snapshot_sha256"] = hashlib.sha256(payload).hexdigest()
            handle["byte_size"] = len(payload)

            validate_handle(
                handle,
                self._request(),
                root,
                allowed_roots=[portfolio],
            )  # must not raise

    def test_validate_handle_rejects_outside_configured_allowance(self) -> None:
        """A handle outside every configured allowed root is rejected."""
        from filing_contracts import validate_handle

        with TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = self._wiki_root(parent, "company-wiki")
            portfolio = parent / "portfolio"
            portfolio.mkdir(parents=True)
            payload = b"portfolio filing bytes"
            target = portfolio / "6082" / "annual.pdf"
            target.parent.mkdir(parents=True)
            target.write_bytes(payload)
            handle = self._handle(root)
            handle["canonical_path"] = str(target)
            handle["snapshot_sha256"] = hashlib.sha256(payload).hexdigest()
            handle["byte_size"] = len(payload)

            with self.assertRaisesRegex(FilingFetchError, "outside"):
                validate_handle(
                    handle,
                    self._request(),
                    root,
                    allowed_roots=[root / "companies"],
                )




if __name__ == "__main__":
    unittest.main()
