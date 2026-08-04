"""Real company-wiki code, fully temporary state: the three-layer matrix.

Read-only scenarios share one scanned instance (setUpClass); mutating
scenarios each build their own instance.  Everything is offline: identify
uses copied production security-master snapshots, and the acquisition
config uses no-op adapters (discovery returns zero candidates).
"""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "tests"))

# Hermetic path (Phase 6 C2 / F-06): the e2e drives real company-wiki code, so
# make the sibling company-wiki source tree importable instead of relying on an
# implicit global install.  When the repo is not present, the import below fails
# loudly rather than silently testing a different installed copy.
_COMPANY_WIKI_SRC = Path.home() / "Projects" / "company-wiki" / "src"
sys.path.insert(0, str(_COMPANY_WIKI_SRC))

from e2e_support.isolated_wiki import IsolatedWiki, cleanup_temporary  # noqa: E402
from company_wiki.source_catalog.lock import CatalogOperationLock  # noqa: E402


def _hold_lock_for(
    catalog_dir: Path, seconds: float, acquired: threading.Event
) -> threading.Thread:
    """Hold the catalog operation lock for ``seconds``, then release it."""

    def run() -> None:
        with CatalogOperationLock(catalog_dir, operation="e2e-hold"):
            acquired.set()
            time.sleep(seconds)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _hold_lock_until_release(
    catalog_dir: Path, release: threading.Event, acquired: threading.Event
) -> threading.Thread:
    """Hold the catalog operation lock until ``release`` is set."""

    def run() -> None:
        with CatalogOperationLock(catalog_dir, operation="e2e-hold"):
            acquired.set()
            release.wait(60)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


class SharedReadOnlyE2E(unittest.TestCase):
    """Scenarios 1-6 and 9: one scanned instance reused across fetches."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = TemporaryDirectory()
        cls.wiki = IsolatedWiki(Path(cls._temporary.name))
        for market in ("CN", "US", "HK"):
            cls.wiki.seed_market(market)
        cls.wiki.scan()

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_temporary(cls._temporary)

    def _files_before(self) -> set[str]:
        return {
            str(path.relative_to(self.wiki.root))
            for path in self.wiki.root.rglob("*")
            if path.is_file() and ".source_catalog" not in path.parts
        }

    def test_e2e_reuse_cn_annual_report(self) -> None:
        """CN seed exists: identify + resolve, exit 0, capture_ready, no downloads."""
        files = self._files_before()
        rc, out, err = self.wiki.run_fetch(
            {
                "schema_version": "1.1",
                "company_query": "宁德时代",
                "market": "CN",
                "document_kind": "annual_report",
                "fiscal_year": 2024,
                "as_of_date": "2026-07-31",
            }
        )
        self.assertEqual(rc, 0, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "capture_ready")
        self.assertTrue(payload["handle"]["capture_ready"])
        parts = Path(payload["handle"]["canonical_path"]).parts
        self.assertIn("financial_reports", parts)
        self.assertIn("annual", parts)
        self.assertEqual(payload["handle"]["company_identity"]["security_id"], "300750")
        self.assertEqual(self._files_before(), files)  # reuse only: nothing written

    def test_e2e_reuse_us_annual_report(self) -> None:
        """US seed: canonical_name 'Apple Inc.' vs directory 'Apple Inc' still
        matches via the sidecar security_id (AAPL) fallback."""
        rc, out, err = self.wiki.run_fetch(
            {
                "schema_version": "1.1",
                "company_query": "Apple",
                "market": "US",
                "document_kind": "annual_report",
                "fiscal_year": 2025,
                "as_of_date": "2026-07-31",
            }
        )
        self.assertEqual(rc, 0, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "capture_ready")
        self.assertEqual(payload["handle"]["company_identity"]["canonical_name"], "Apple Inc.")
        self.assertIn("10-K", payload["handle"]["title"])

    def test_e2e_hk_old_sidecar_reuse(self) -> None:
        """HK seed uses the old 4-field sidecar whose source_url is https:
        after scan fills hash + capture_trace it is capture_ready and reusable."""
        rc, out, err = self.wiki.run_fetch(
            {
                "schema_version": "1.1",
                "company_query": "腾讯",
                "market": "HK",
                "document_kind": "annual_report",
                "fiscal_year": 2024,
                "as_of_date": "2026-07-31",
            }
        )
        self.assertEqual(rc, 0, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "capture_ready")
        self.assertTrue(payload["handle"]["capture_ready"])

    def test_e2e_missing_filing_reuse_only(self) -> None:
        """A document kind that was never seeded: not_found, no download."""
        files = self._files_before()
        rc, out, err = self.wiki.run_fetch(
            {
                "schema_version": "1.1",
                "company_query": "宁德时代",
                "market": "CN",
                "document_kind": "quarterly_report",
                "as_of_date": "2026-07-31",
            }
        )
        self.assertEqual(rc, 2, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "not_found")
        self.assertFalse(payload["retryable"])
        self.assertEqual(self._files_before(), files)

    def test_e2e_missing_fiscal_year(self) -> None:
        rc, out, err = self.wiki.run_fetch(
            {
                "schema_version": "1.1",
                "company_query": "宁德时代",
                "market": "CN",
                "document_kind": "annual_report",
                "fiscal_year": 1999,
                "as_of_date": "2026-07-31",
            }
        )
        self.assertEqual(rc, 2, out + err)
        self.assertEqual(json.loads(out)["status"], "not_found")

    def test_e2e_as_of_before_publication(self) -> None:
        """as_of_date before published_date -> future match -> MISSING."""
        rc, out, err = self.wiki.run_fetch(
            {
                "schema_version": "1.1",
                "company_query": "宁德时代",
                "market": "CN",
                "document_kind": "annual_report",
                "fiscal_year": 2024,
                "as_of_date": "2025-01-01",
            }
        )
        self.assertEqual(rc, 2, out + err)
        self.assertEqual(json.loads(out)["status"], "not_found")

    def test_e2e_ambiguous_identity(self) -> None:
        """万科 resolves ambiguous against the production snapshot."""
        rc, out, err = self.wiki.run_fetch(
            {
                "schema_version": "1.1",
                "company_query": "万科",
                "market": "CN",
                "document_kind": "annual_report",
                "as_of_date": "2026-07-31",
            }
        )
        self.assertEqual(rc, 2, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "identity_error")
        self.assertFalse(payload["retryable"])


class MutatingE2E(unittest.TestCase):
    """Each mutating scenario gets its own isolated instance."""

    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.wiki = IsolatedWiki(Path(self._temporary.name))

    def tearDown(self) -> None:
        cleanup_temporary(self._temporary)


class TestPartialProvenance(MutatingE2E):
    def test_e2e_partial_provenance_capture_not_ready(self) -> None:
        """A synthetic old-style sidecar with a non-https source_url never
        becomes capture_ready: resolver drops it and the fetch is not_found
        (plan-drift note: Phase 16.2 drops the handle silently, so the
        missing_capture_fields detail cannot propagate through resolve; the
        mock test test_capture_not_ready_carries_not_found_code pins it)."""
        self.wiki.seed_market("CN")
        target = self.wiki.root / "companies" / "宁德时代" / "raw" / "financial_reports" / "annual"
        sidecar = target / "2025-03-14_cninfo_1222806982_2024年年度报告.pdf.source.json"
        sidecar.write_text(
            json.dumps(
                {
                    "market": "CN",
                    "security_id": "300750",
                    "source_title": "2024年年度报告",
                    "published_date": "2025-03-14",
                    "source_url": "http://insecure.example/finalpage/1222806982.PDF",
                }
            ),
            encoding="utf-8",
        )
        self.wiki.scan()
        rc, out, err = self.wiki.run_fetch(
            {
                "schema_version": "1.1",
                "company_query": "宁德时代",
                "market": "CN",
                "document_kind": "annual_report",
                "fiscal_year": 2024,
                "as_of_date": "2026-07-31",
            }
        )
        self.assertEqual(rc, 2, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "not_found")


class TestCorruptedBytes(MutatingE2E):
    def test_e2e_corrupted_bytes_after_scan(self) -> None:
        """Scan records the true hash; corrupting the bytes afterwards makes
        filing-fetch's deep handle validation reject the reused handle."""
        self.wiki.seed_market("CN")
        self.wiki.scan()
        target = self.wiki.root / "companies" / "宁德时代" / "raw" / "financial_reports" / "annual"
        source = target / "2025-03-14_cninfo_1222806982_2024年年度报告.pdf"
        raw = bytearray(source.read_bytes())
        raw[0] ^= 0xFF  # same length, different bytes
        source.write_bytes(bytes(raw))
        rc, out, err = self.wiki.run_fetch(
            {
                "schema_version": "1.1",
                "company_query": "宁德时代",
                "market": "CN",
                "document_kind": "annual_report",
                "fiscal_year": 2024,
                "as_of_date": "2026-07-31",
            }
        )
        self.assertEqual(rc, 2, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "upstream_error")
        self.assertIn("snapshot_sha256", payload["error"])


class TestIdentityUnavailable(MutatingE2E):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.wiki = IsolatedWiki(Path(self._temporary.name), with_security_master=False)

    def test_e2e_identity_unavailable_without_snapshots(self) -> None:
        """No security_master snapshots: identify exits 1 with
        SecurityMasterUnavailableError, which filing-fetch maps to fatal
        (fail-closed).  Pinned mapping documented here."""
        rc, out, err = self.wiki.run_fetch(
            {
                "schema_version": "1.1",
                "company_query": "AMD",
                "market": "US",
                "document_kind": "annual_report",
                "as_of_date": "2026-07-31",
            }
        )
        self.assertEqual(rc, 2, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "fatal")
        self.assertIn("SecurityMasterUnavailableError", payload["error"])


class TestCatalogLockContention(MutatingE2E):
    def _fetch_existing_cn_annual(self, timeout: float) -> tuple[int, str, str]:
        # ensure --allow-download on an existing filing: resolution REUSED,
        # then the acquisition journal record takes the catalog lock.
        return self.wiki.run_fetch(
            {
                "schema_version": "1.1",
                "company_query": "宁德时代",
                "market": "CN",
                "document_kind": "annual_report",
                "fiscal_year": 2024,
                "as_of_date": "2026-07-31",
            },
            allow_download=True,
            timeout=timeout,
        )

    def test_e2e_catalog_lock_retry_then_success(self) -> None:
        """Lock held ~7s: filing-fetch backs off and succeeds after release."""
        self.wiki.seed_market("CN")
        self.wiki.scan()
        acquired = threading.Event()
        # The lock is released after 7s *during* the fetch; the final attempt
        # then succeeds.  (resolve itself takes no lock — the contention the
        # retry loop observes is the acquisition-journal record inside ensure.)
        thread = _hold_lock_for(self.wiki.catalog_dir, 7.0, acquired)
        try:
            self.assertTrue(acquired.wait(10), "test thread never acquired the lock")
            started = time.monotonic()
            rc, out, err = self._fetch_existing_cn_annual(timeout=30)
        finally:
            thread.join(10)
        elapsed = time.monotonic() - started
        self.assertEqual(rc, 0, out + err)
        self.assertEqual(json.loads(out)["status"], "capture_ready")
        self.assertIn("blocked by a running catalog operation", err)
        self.assertGreaterEqual(elapsed, 5.0)  # at least one 5s backoff round

    def test_e2e_catalog_lock_until_deadline(self) -> None:
        """Lock held past the deadline: the retry loop exhausts it and the
        fetch surfaces upstream_error instead of hanging."""
        self.wiki.seed_market("CN")
        self.wiki.scan()
        release = threading.Event()
        acquired = threading.Event()
        thread = _hold_lock_until_release(self.wiki.catalog_dir, release, acquired)
        try:
            self.assertTrue(acquired.wait(10), "test thread never acquired the lock")
            rc, out, err = self._fetch_existing_cn_annual(timeout=8)
        finally:
            release.set()
            thread.join(10)
        self.assertEqual(rc, 2, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "upstream_error")
        self.assertTrue(payload["retryable"])


class TestWorkerPaused(MutatingE2E):
    def test_e2e_worker_paused_blocks_download(self) -> None:
        """paused + --allow-download -> worker_paused (retryable); after
        re-enabling, the same request resolves MISSING -> not_found with no
        network traffic (no-op adapters prove the gate passed)."""
        self.wiki.seed_market("CN")
        self.wiki.set_worker_state("paused")
        self.wiki.scan()
        request = {
            "schema_version": "1.1",
            "company_query": "宁德时代",
            "market": "CN",
            "document_kind": "quarterly_report",
            "as_of_date": "2026-07-31",
        }
        rc, out, err = self.wiki.run_fetch(request, allow_download=True, timeout=30)
        self.assertEqual(rc, 2, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "worker_paused")
        self.assertTrue(payload["retryable"])

        self.wiki.set_worker_state("enabled")
        rc, out, err = self.wiki.run_fetch(request, allow_download=True, timeout=30)
        self.assertEqual(rc, 2, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "not_found")
        self.assertFalse(payload["retryable"])


if __name__ == "__main__":
    unittest.main()
