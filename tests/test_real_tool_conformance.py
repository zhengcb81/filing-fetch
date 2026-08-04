"""Live consistency: filing-fetch contracts against the PRODUCTION wiki.

These tests invoke the real company-wiki CLI exactly as filing-fetch does
(``identify --query`` / ``resolve|ensure --entity``) and one full filing-fetch
round-trip.  All commands are read-only except the single ensure case, which
appends one "missing" acquisition-journal record (semantically accurate,
append-only).  Skipped when the CLI or the default config is unavailable.

Suite budget: ~30-45s (well under the 60s plan target).
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from fetch_filing import load_company_wiki_root  # noqa: E402


def _wiki_available() -> bool:
    try:
        root = load_company_wiki_root()
    except Exception:
        return False
    return (root / "config" / "source_catalog.yaml").is_file()


@unittest.skipUnless(_wiki_available(), "production company-wiki not available")
class LiveConformanceTests(unittest.TestCase):
    """The upstream contract filing-fetch depends on, verified live."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = load_company_wiki_root()
        cls.config = cls.root / "config" / "source_catalog.yaml"

    def _command(self, *args: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "company_wiki.source_catalog.cli",
            "--config",
            str(self.config),
            *args,
        ]

    def _run(self, *args: str) -> tuple[int, dict, str]:
        completed = subprocess.run(
            self._command(*args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            check=False,
            timeout=90,
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            payload = {}
        return completed.returncode, payload, completed.stderr

    # -- identify: the exact command shape filing-fetch builds ------------

    def test_identify_cn_resolves_verified_identity(self) -> None:
        rc, payload, err = self._run("identify", "--query", "贵州茅台", "--market", "CN")
        self.assertEqual(rc, 0, err)
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["status"], "resolved")
        resolved = payload["resolved"]
        self.assertEqual(resolved["market"], "CN")
        self.assertTrue(resolved["verified"])
        self.assertTrue(resolved["active"])
        self.assertEqual(resolved["security_id"], "600519")

    def test_identify_hk_resolves_verified_identity(self) -> None:
        rc, payload, err = self._run("identify", "--query", "腾讯", "--market", "HK")
        self.assertEqual(rc, 0, err)
        self.assertEqual(payload["status"], "resolved")
        resolved = payload["resolved"]
        self.assertEqual(resolved["market"], "HK")
        self.assertEqual(resolved["security_id"], "00700")
        self.assertTrue(resolved["verified"])
        self.assertTrue(resolved["active"])

    def test_identify_us_resolves_verified_identity(self) -> None:
        rc, payload, err = self._run("identify", "--query", "AMD", "--market", "US")
        self.assertEqual(rc, 0, err)
        self.assertEqual(payload["status"], "resolved")
        resolved = payload["resolved"]
        self.assertEqual(resolved["market"], "US")
        self.assertEqual(resolved["security_id"], "AMD")
        self.assertTrue(resolved["verified"])
        self.assertTrue(resolved["active"])

    def test_identify_ambiguous_is_structured_not_failed(self) -> None:
        """identify always exits 0; ambiguity is a structured status with
        resolved=null (never a stderr failure)."""
        rc, payload, err = self._run("identify", "--query", "万科", "--market", "CN")
        self.assertEqual(rc, 0, err)
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["status"], "ambiguous")
        self.assertIsNone(payload["resolved"])
        self.assertTrue(payload["candidates"])

    def test_identify_is_deterministic(self) -> None:
        first = self._run("identify", "--query", "AMD", "--market", "US")
        second = self._run("identify", "--query", "AMD", "--market", "US")
        self.assertEqual(first[1], second[1])

    # -- ensure --entity: the response envelope filing-fetch parses --------

    def test_ensure_entity_without_download_reports_missing(self) -> None:
        """ensure --entity nests the resolution under a top-level
        ``resolution`` key (acquisition_service contract).  Uses a request
        that is guaranteed missing in production (茅台 quarterly is never
        indexed); the only side effect is one append-only journal record.
        Retries briefly against transient catalog-lock contention."""
        import time

        rc, payload, err = 1, {}, ""
        for _attempt in range(3):
            rc, payload, err = self._run(
                "ensure",
                "--entity",
                "贵州茅台",
                "--market",
                "CN",
                "--security-id",
                "600519",
                "--document-kind",
                "quarterly_report",
                "--fiscal-year",
                "2025",
                "--as-of-date",
                "2026-08-01",
            )
            if rc == 0 or "catalog operation already running" not in err:
                break
            time.sleep(5)
        if rc != 0 and "catalog operation already running" in err:
            self.skipTest("production catalog locked at test time")
        self.assertEqual(rc, 0, err)
        self.assertEqual(payload["schema_version"], "1.0")
        resolution = payload.get("resolution")
        self.assertIsInstance(resolution, dict)
        self.assertEqual(resolution["schema_version"], "1.0")
        self.assertEqual(resolution["status"], "missing")
        self.assertFalse(resolution["download_allowed"])

    # -- production round-trip through the real filing-fetch subprocess ----

    def test_production_round_trip_reuses_capture_ready_document(self) -> None:
        """Find a capture_ready document in the production catalog and fetch
        it with the real filing-fetch subprocess (reuse-only): exit 0."""
        document = self._find_capture_ready_document()
        if document is None:
            self.skipTest("no capture-ready 宁德时代 FY2024 annual in production")
        request = json.dumps(
            {
                "schema_version": "1.1",
                "company_query": "宁德时代",
                "market": "CN",
                "document_kind": "annual_report",
                "fiscal_year": 2024,
                "as_of_date": "2026-08-01",
            },
            ensure_ascii=False,
        )
        proc = subprocess.run(
            [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "fetch_filing.py"),
                "--timeout-seconds",
                "60",
            ],
            input=request,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["status"], "capture_ready")
        self.assertTrue(payload["handle"]["capture_ready"])

    @staticmethod
    def _find_capture_ready_document() -> dict | None:
        """Dynamically locate the 宁德时代 FY2024 annual in the production
        catalog and verify it is capture-ready (https source_url, published
        date, canonical active location, file present).  Returns the document
        row or None (-> skip the round-trip)."""
        import sqlite3

        database = (
            Path.home()
            / "Projects"
            / "company-wiki"
            / ".source_catalog"
            / "catalog.sqlite3"
        )
        if not database.is_file():
            return None
        try:
            connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        except sqlite3.Error:
            return None
        try:
            row = connection.execute(
                """
                SELECT d.document_id, d.published_date, d.metadata_json
                FROM documents d
                JOIN document_entities de ON de.document_id = d.document_id
                JOIN entities e ON e.entity_id = de.entity_id
                WHERE e.name = ? AND d.document_kind = 'annual_report'
                  AND d.published_date IS NOT NULL
                  AND d.metadata_json LIKE '%https%'
                ORDER BY d.published_date DESC LIMIT 1
                """,
                ("宁德时代",),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        document_id, published_date, metadata_json = row
        canonical = Path.home() / "Projects" / "company-wiki" / "companies"
        found = False
        for sidecar in (canonical / "宁德时代").rglob("*.source.json"):
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if (
                str(meta.get("source_url") or "").startswith("https://")
                and meta.get("fiscal_year") == 2024
            ):
                found = True
                break
        if not found:
            return None
        return {
            "document_id": document_id,
            "published_date": published_date,
            "metadata_json": metadata_json,
        }


if __name__ == "__main__":
    unittest.main()
