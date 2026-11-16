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
- bounded requests use a 50 MiB response limit, a 180s wall deadline,
  and zero provider fee with the configured raw-only adapters
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "tests"))

from e2e_support.isolated_wiki import IsolatedWiki, cleanup_temporary  # noqa: E402

# Resolve the production tools from the sibling layout (…/Projects/<repo>), not
# from Path.home(): the weekly T3 scheduled task runs as SYSTEM, where
# Path.home() is the system profile and every ~/Projects lookup would fail and
# silently skip the suite (GP-009, 2026-09-08).  Fall back to ~/Projects for
# installed skill copies.
_SIBLING_PROJECTS = SKILL_ROOT.parent
_PROJECTS_ROOT = (
    _SIBLING_PROJECTS
    if (_SIBLING_PROJECTS / "StockInfoDLSimple").is_dir()
    else Path.home() / "Projects"
)
_TOOL_PATHS = (
    _PROJECTS_ROOT
    / "StockInfoDLSimple"
    / "v2-clean-rewrite"
    / "src"
    / "company_wiki_adapter_cli.py",
    _PROJECTS_ROOT / "dayu-agent" / "dayu-agent" / ".venv" / "Scripts" / "python.exe",
)

_DOWNLOAD_GATE = os.environ.get("FILING_FETCH_E2E_DOWNLOAD") == "1"
_TOOLS_PRESENT = all(path.exists() for path in _TOOL_PATHS)
_T3_TIMEOUT_SECONDS = 180
_T3_DOWNLOAD_LIMITS = {
    "max_bytes": 50 * 1024 * 1024,
    "timeout_seconds": _T3_TIMEOUT_SECONDS,
    "max_cost_usd": "0",
}


@unittest.skipUnless(_DOWNLOAD_GATE, "set FILING_FETCH_E2E_DOWNLOAD=1 to run real downloads")
@unittest.skipUnless(_TOOLS_PRESENT, "production download tools not found")
class DownloadE2E(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory(prefix="ff-t3-")
        self.addCleanup(self._cleanup_wiki)
        self.wiki = IsolatedWiki(Path(self._temporary.name))
        self.wiki.use_production_adapters()

    def _cleanup_wiki(self) -> None:
        path = Path(self._temporary.name)
        cleanup_temporary(self._temporary)
        self.assertFalse(path.exists(), f"temporary wiki was not removed: {path}")

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

    def _assert_capture_ready_layout(self, payload: dict) -> tuple[Path, str]:
        """The downloaded file sits under companies/<entity>/raw/financial_reports/<kind>/
        with a complete sidecar (https url, published_date, content hash)."""
        self.assertEqual(payload["status"], "capture_ready")
        self.assertEqual(payload["downloads"], 1)
        handle = payload["handle"]
        self.assertTrue(handle["capture_ready"], handle)
        canonical = Path(handle["canonical_path"]).resolve(strict=True)
        self.assertTrue(canonical.is_file(), canonical)
        self.assertTrue(canonical.is_relative_to(self.wiki.root.resolve() / "companies"))
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
        with canonical.open("rb") as original:
            digest = hashlib.file_digest(original, "sha256").hexdigest()
        self.assertEqual(digest, meta["content_sha256"])
        self.assertEqual(digest, handle["snapshot_sha256"])
        self.assertTrue(meta.get("retrieved_at"), meta)
        return canonical, digest

    def _assert_idempotent_reuse(
        self, request: dict, canonical: Path, digest: str, deadline: float
    ) -> None:
        """A second run must reuse: same bytes (mtime unchanged) and no new
        downloaded_new journal outcome."""
        before_mtime = canonical.stat().st_mtime_ns
        before_outcomes = self.wiki.journal_outcomes()
        rc, out, err = self.wiki.run_fetch(request, allow_download=True, timeout=deadline)
        self.assertEqual(rc, 0, out + err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "capture_ready")
        self.assertEqual(payload["downloads"], 0)
        self.assertEqual(Path(payload["handle"]["canonical_path"]).resolve(), canonical)
        self.assertEqual(payload["handle"]["snapshot_sha256"], digest)
        self.assertEqual(canonical.stat().st_mtime_ns, before_mtime)
        with canonical.open("rb") as original:
            self.assertEqual(hashlib.file_digest(original, "sha256").hexdigest(), digest)
        after_outcomes = self.wiki.journal_outcomes()
        self.assertEqual(
            after_outcomes.count("downloaded_new"), before_outcomes.count("downloaded_new"),
            "second run must not download again",
        )
        self.assertIn("reused_before_download", after_outcomes)
        self._assert_no_residue()

    # -- scenarios --------------------------------------------------------

    def test_download_cn_annual_report(self) -> None:
        """宁德时代 FY2024 annual via StockInfoDLSimple/cninfo, then reuse.

        (贵州茅台 FY2024 yields TWO cninfo candidates — Chinese + English
        annual — so the coordinator legitimately returns AMBIGUOUS and
        filing-fetch maps it to not_found; CATL yields exactly one.)"""
        deadline = _T3_TIMEOUT_SECONDS
        request = {
            "schema_version": "1.1",
            "company_query": "宁德时代",
            "market": "CN",
            "document_kind": "annual_report",
            "fiscal_year": 2024,
            "as_of_date": "2026-07-31",
            "acquisition_limits": _T3_DOWNLOAD_LIMITS,
        }
        rc, out, err = self.wiki.run_fetch(request, allow_download=True, timeout=deadline)
        self.assertEqual(rc, 0, out + err)
        canonical, digest = self._assert_capture_ready_layout(json.loads(out))
        self.assertIn("annual", canonical.parts)
        self.assertIn("downloaded_new", self.wiki.journal_outcomes())
        self._assert_no_residue()
        self._assert_idempotent_reuse(request, canonical, digest, deadline)

    def test_download_us_annual_report(self) -> None:
        """AMD 10-K via dayu-sec, then reuse."""
        deadline = _T3_TIMEOUT_SECONDS
        request = {
            "schema_version": "1.1",
            "company_query": "AMD",
            "market": "US",
            "document_kind": "annual_report",
            "fiscal_year": 2025,
            "as_of_date": "2026-07-31",
            "acquisition_limits": _T3_DOWNLOAD_LIMITS,
        }
        rc, out, err = self.wiki.run_fetch(request, allow_download=True, timeout=deadline)
        self.assertEqual(rc, 0, out + err)
        canonical, digest = self._assert_capture_ready_layout(json.loads(out))
        self.assertIn("downloaded_new", self.wiki.journal_outcomes())
        self._assert_no_residue()
        self._assert_idempotent_reuse(request, canonical, digest, deadline)

    def test_download_hk_annual_report(self) -> None:
        """腾讯 annual via dayu-hkex, then reuse.

        fiscal_year is mandatory for the dayu adapter; the year must match
        dayu's title inference — the latest annual in range is the FY2025
        report ("2025 年報", filed 2026-04-09).  A pinned 2024 was the root
        cause of the original hang: the adapter downloaded the 2025 report
        and ``_candidate_from_meta`` rejected it on the year filter."""
        deadline = _T3_TIMEOUT_SECONDS
        request = {
            "schema_version": "1.1",
            "company_query": "腾讯",
            "market": "HK",
            "document_kind": "annual_report",
            "fiscal_year": 2025,
            "as_of_date": "2026-07-31",
            "acquisition_limits": _T3_DOWNLOAD_LIMITS,
        }
        rc, out, err = self.wiki.run_fetch(request, allow_download=True, timeout=deadline)
        self.assertEqual(rc, 0, out + err)
        canonical, digest = self._assert_capture_ready_layout(json.loads(out))
        self.assertIn("downloaded_new", self.wiki.journal_outcomes())
        self._assert_no_residue()
        self._assert_idempotent_reuse(request, canonical, digest, deadline)

    def test_download_rejects_corrupted_local_copy(self) -> None:
        """A corrupt original is unavailable on reuse and on bounded ensure."""
        self.wiki.seed_market("CN")
        self.wiki.scan()
        target = self.wiki.root / "companies" / "宁德时代" / "raw" / "financial_reports" / "annual"
        # Discover the seeded PDF instead of pinning the provider's 2026-XX
        # filename: the seed is `synthetic_cn_2024_annual.pdf`, and a hardcoded
        # `2025-03-14_cninfo_..._2024年年度报告.pdf` made this test fail with
        # FileNotFoundError regardless of the code under test.
        candidates = sorted(target.glob("*.pdf"))
        self.assertEqual(len(candidates), 1, f"expected one seeded PDF, got {candidates}")
        source = candidates[0]
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
        rc, out, err = self.wiki.run_fetch(request, timeout=_T3_TIMEOUT_SECONDS)
        self.assertEqual(rc, 2, out + err)
        self.assertEqual(json.loads(out)["status"], "upstream_error")
        rc, out, err = self.wiki.run_fetch(
            {**request, "acquisition_limits": _T3_DOWNLOAD_LIMITS},
            allow_download=True,
            timeout=_T3_TIMEOUT_SECONDS,
        )
        self.assertEqual(rc, 2, out + err)
        result = json.loads(out)
        self.assertNotIn("handle", result)
        self.assertEqual(result["upstream_cause"]["operation"], "ensure")
        self.assertIs(result["upstream_cause"]["provider_started"], False)
        self.assertEqual(result["downloads"], 0)
        self.assertEqual(source.read_bytes(), bytes(raw))
        self.assertNotIn("downloaded_new", self.wiki.journal_outcomes())
        self._assert_no_residue()


if __name__ == "__main__":
    unittest.main()
