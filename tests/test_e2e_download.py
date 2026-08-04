"""Real download E2E (opt-in): FILING_FETCH_E2E_DOWNLOAD=1.

Uses the real production download tools (StockInfoDLSimple for CN,
dayu-agent venv for HK/US) with the IsolatedWiki fixture: downloads land
inside a temporary wiki root, never the production wiki.  Gated on the
environment variable AND on the tool paths existing.

Design notes (mirroring StockInfoDLSimple/v2-clean-rewrite E2E):
- the test runs filing-fetch exactly as a user would (subprocess)
- expected artifacts are verified structurally afterwards (directory
  layout, sidecar completeness) and idempotency via a second run
  (file mtime unchanged + acquisition-journal outcome counts)
- per-test deadline: 600s for CN; 900s for dayu (dayu waits for
  Docling+RapidOCR conversion before exiting; the plan's 600s was set
  before that cost was known — both stay under the 1800s acquisition
  timeout)
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "tests"))

from e2e_support.isolated_wiki import IsolatedWiki, cleanup_temporary  # noqa: E402

_TOOL_PATHS = (
    Path.home()
    / "Projects"
    / "StockInfoDLSimple"
    / "v2-clean-rewrite"
    / "src"
    / "company_wiki_adapter_cli.py",
    Path.home() / "Projects" / "dayu-agent" / "dayu-agent" / ".venv" / "Scripts" / "python.exe",
)

_DOWNLOAD_GATE = os.environ.get("FILING_FETCH_E2E_DOWNLOAD") == "1"
_TOOLS_PRESENT = all(path.exists() for path in _TOOL_PATHS)


@unittest.skipUnless(_DOWNLOAD_GATE, "set FILING_FETCH_E2E_DOWNLOAD=1 to run real downloads")
@unittest.skipUnless(_TOOLS_PRESENT, "production download tools not found")
class DownloadE2E(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.wiki = IsolatedWiki(Path(self._temporary.name))
        self.wiki.use_production_adapters()

    def tearDown(self) -> None:
        cleanup_temporary(self._temporary)

    # -- shared assertions ------------------------------------------------

    def _assert_no_residue(self) -> None:
        """Every case ends with no catalog operation lock and no staged bytes.

        The writer leaves empty request-id directories behind in staging
        (upstream behavior); only files would indicate uncommitted bytes."""
        self.assertFalse(
            (self.wiki.catalog_dir / "operation.lock").exists(),
            "operation.lock must not be left behind",
        )
        staging = self.wiki.catalog_dir / "staging"
        if staging.is_dir():
            leftovers = [path for path in staging.rglob("*") if path.is_file()]
            self.assertEqual(leftovers, [], "no staged bytes may remain after import")

    def _assert_capture_ready_layout(self, payload: dict) -> Path:
        """The downloaded file sits under companies/<entity>/raw/financial_reports/<kind>/
        with a complete sidecar (https url, published_date, content hash)."""
        self.assertEqual(payload["status"], "capture_ready")
        handle = payload["handle"]
        self.assertTrue(handle["capture_ready"], handle)
        canonical = Path(handle["canonical_path"])
        self.assertTrue(canonical.is_file(), canonical)
        parts = canonical.parts
        self.assertIn("companies", parts)
        self.assertIn("financial_reports", parts)
        sidecar = Path(str(canonical) + ".source.json")
        self.assertTrue(sidecar.is_file(), sidecar)
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        # The four capture_ready conditions at their sources: https source_url,
        # published date (manifest derives it from filing_date), content hash,
        # capture trace (adapter identity + retrieved_at).
        self.assertTrue(str(meta.get("source_url") or "").startswith("https://"))
        self.assertTrue(meta.get("filing_date"), meta)
        self.assertEqual(len(str(meta.get("content_sha256") or "")), 64)
        self.assertTrue(meta.get("retrieved_at"), meta)
        return canonical

    def _assert_idempotent_reuse(
        self, request: dict, canonical: Path, deadline: float
    ) -> None:
        """A second run must reuse: same bytes (mtime unchanged) and no new
        downloaded_new journal outcome."""
        before_mtime = canonical.stat().st_mtime_ns
        before_outcomes = self.wiki.journal_outcomes()
        rc, out, err = self.wiki.run_fetch(request, allow_download=True, timeout=deadline)
        self.assertEqual(rc, 0, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "capture_ready")
        self.assertEqual(canonical.stat().st_mtime_ns, before_mtime)
        after_outcomes = self.wiki.journal_outcomes()
        self.assertEqual(
            after_outcomes.count("downloaded_new"), before_outcomes.count("downloaded_new"),
            "second run must not download again",
        )
        self.assertIn("reused_before_download", after_outcomes)

    # -- scenarios --------------------------------------------------------

    def test_download_cn_annual_report(self) -> None:
        """宁德时代 FY2024 annual via StockInfoDLSimple/cninfo, then reuse.

        (贵州茅台 FY2024 yields TWO cninfo candidates — Chinese + English
        annual — so the coordinator legitimately returns AMBIGUOUS and
        filing-fetch maps it to not_found; CATL yields exactly one.)"""
        deadline = 600.0
        request = {
            "schema_version": "1.1",
            "company_query": "宁德时代",
            "market": "CN",
            "document_kind": "annual_report",
            "fiscal_year": 2024,
            "as_of_date": "2026-07-31",
        }
        rc, out, err = self.wiki.run_fetch(request, allow_download=True, timeout=deadline)
        self.assertEqual(rc, 0, out + err)
        canonical = self._assert_capture_ready_layout(json.loads(out))
        self.assertIn("annual", canonical.parts)
        self.assertIn("downloaded_new", self.wiki.journal_outcomes())
        self._assert_no_residue()
        self._assert_idempotent_reuse(request, canonical, deadline)

    def test_download_us_annual_report(self) -> None:
        """AMD 10-K via dayu-sec, then reuse."""
        deadline = 900.0
        request = {
            "schema_version": "1.1",
            "company_query": "AMD",
            "market": "US",
            "document_kind": "annual_report",
            "fiscal_year": 2025,
            "as_of_date": "2026-07-31",
        }
        rc, out, err = self.wiki.run_fetch(request, allow_download=True, timeout=deadline)
        self.assertEqual(rc, 0, out + err)
        canonical = self._assert_capture_ready_layout(json.loads(out))
        self.assertIn("downloaded_new", self.wiki.journal_outcomes())
        self._assert_no_residue()
        self._assert_idempotent_reuse(request, canonical, deadline)

    def test_download_hk_annual_report(self) -> None:
        """腾讯 annual via dayu-hkex, then reuse.

        fiscal_year is mandatory for the dayu adapter; the year must match
        dayu's title inference — the latest annual in range is the FY2025
        report ("2025 年報", filed 2026-04-09).  A pinned 2024 was the root
        cause of the original hang: the adapter downloaded the 2025 report
        and ``_candidate_from_meta`` rejected it on the year filter."""
        deadline = 900.0
        request = {
            "schema_version": "1.1",
            "company_query": "腾讯",
            "market": "HK",
            "document_kind": "annual_report",
            "fiscal_year": 2025,
            "as_of_date": "2026-07-31",
        }
        rc, out, err = self.wiki.run_fetch(request, allow_download=True, timeout=deadline)
        self.assertEqual(rc, 0, out + err)
        canonical = self._assert_capture_ready_layout(json.loads(out))
        self.assertIn("downloaded_new", self.wiki.journal_outcomes())
        self._assert_no_residue()
        self._assert_idempotent_reuse(request, canonical, deadline)

    def test_download_rejects_corrupted_local_copy(self) -> None:
        """Pinned reality (plan drift): after scan, a corrupted file is caught
        by filing-fetch's deep handle validation (upstream_error) and the
        current upstream flow has no quarantine-and-redownload repair path —
        ensure reuses the DB-consistent handle and fails the same way.  The
        safety property: corrupted bytes are never served, and no new
        download is attempted."""
        self.wiki.seed_market("CN")
        self.wiki.scan()
        target = self.wiki.root / "companies" / "宁德时代" / "raw" / "financial_reports" / "annual"
        source = target / "2025-03-14_cninfo_1222806982_2024年年度报告.pdf"
        raw = bytearray(source.read_bytes())
        raw[0] ^= 0xFF
        source.write_bytes(bytes(raw))
        request = {
            "schema_version": "1.1",
            "company_query": "宁德时代",
            "market": "CN",
            "document_kind": "annual_report",
            "fiscal_year": 2024,
            "as_of_date": "2026-07-31",
        }
        rc, out, err = self.wiki.run_fetch(request, allow_download=False, timeout=300)
        self.assertEqual(rc, 2, out + err)
        self.assertEqual(json.loads(out)["status"], "upstream_error")
        rc, out, err = self.wiki.run_fetch(request, allow_download=True, timeout=300)
        self.assertEqual(rc, 2, out + err)
        self.assertEqual(json.loads(out)["status"], "upstream_error")
        # The journal records the REUSED acquisition (before filing-fetch's
        # deep validation rejects the handle) — but never a download.
        self.assertNotIn("downloaded_new", self.wiki.journal_outcomes())
        self._assert_no_residue()


if __name__ == "__main__":
    unittest.main()
