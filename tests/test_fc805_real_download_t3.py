"""FC-805: real-provider isolated E2E (T3) — CN/HK/US minimal samples.
SCENARIO: UJ-03 UJ-05 DL-01 DL-05 DL-06 DL-10

Runs the REAL chain (filing-fetch CLI -> company-wiki CLI -> REAL
provider adapters: cninfo/dayu) against an ISOLATED temp wiki — the
production catalog and real roots are never written.  Per market:
1) latest_as_of returns the structured gap (provider metadata hash =
   gap_plan.gap_hash recorded);
2) an authorized close-gap downloads the missing period into the TEMP
   wiki (downloaded bytes hash = handle.snapshot_sha256 recorded);
3) the SECOND identical request reports the gap closed with zero
   downloads (journal: reused, no downloaded_new).

Explicit environment authorization: the tests SKIP (blocked, never
counted as pass) unless FC805_REAL_DOWNLOAD=1 — per scenario_matrix T3
authorization rules.
"""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from e2e_support.isolated_wiki import IsolatedWiki, cleanup_temporary

_REAL_DOWNLOAD_AUTHORIZED = os.environ.get("FC805_REAL_DOWNLOAD") == "1"

SAMPLES = [
    {"market": "CN", "company_query": "紫金矿业",
     "expected_provider": "cninfo"},
    {"market": "HK", "company_query": "腾讯控股",
     "expected_provider": "hkexnews"},
    {"market": "US", "company_query": "Apple Inc",
     "expected_provider": "sec"},
]


def _policy_file(wiki: IsolatedWiki) -> None:
    import sys

    sys.path.insert(
        0, str(Path(__file__).resolve().parents[1] / ".." / "company-wiki" / "src"))
    from company_wiki.source_catalog.runtime_policy import snapshot_hash

    policy = {
        "schema_version": "1.0",
        "policy_hash": "c" * 64,
        "flags": {"v2_resolve_active": False, "legacy_bridge_enabled": True,
                  "v2_bundle_active": False, "v2_persist_assertions": False,
                  "v2_resolve_shadow": False, "v2_scan_shadow": False},
        "current_epoch": "epoch-1",
        "active_cohorts": ["cohort-1"],
        "updated_at": "2026-08-11T00:00:00Z",
    }
    policy["snapshot_sha256"] = snapshot_hash(policy)
    wiki.catalog_dir.mkdir(parents=True, exist_ok=True)
    (wiki.catalog_dir / "runtime_policy.json").write_text(
        json.dumps(policy, ensure_ascii=False), encoding="utf-8")


def _latest_request(company_query: str, market: str) -> dict:
    return {
        "schema_version": "1.2",
        "company_query": company_query,
        "market": market,
        "document_kind": "annual_report",
        "mode": "latest_as_of",
        "as_of_date": "2026-08-11",
    }


def _authorized_request(company_query: str, market: str,
                        plan: dict) -> dict:
    missing = plan.get("missing") or []
    assert missing, f"no missing period to download: {plan}"
    candidate = missing[0]
    return {
        "schema_version": "1.2",
        "company_query": company_query,
        "market": market,
        "document_kind": "annual_report",
        "mode": "latest_as_of",
        "as_of_date": "2026-08-11",
        "authorization": {
            "provider": candidate.get("provider"),
            "allowed_accessions": [candidate.get("provider_document_id")],
            "max_items": 3,
            "max_bytes": 200_000_000,
            "expires_at": "2099-01-01T00:00:00Z",
        },
    }


def _run_real_flow(company_query: str, market: str, tmp: Path) -> dict:
    """The full T3 flow; returns the recorded evidence."""
    wiki = IsolatedWiki(tmp)
    _policy_file(wiki)
    wiki.use_production_adapters()
    # step 1: structured gap from the REAL provider (metadata only)
    rc, out, err = wiki.run_fetch(_latest_request(company_query, market),
                                  timeout=300)
    assert rc == 0, f"step-1 failed ({market}): {out[:400]} {err[:200]}"
    first = json.loads(out)
    assert first["status"] == "gap", f"expected gap, got {first.get('status')}"
    plan = first["gap_plan"]
    provider_metadata_hash = plan.get("gap_hash")
    # step 2: authorized close-gap downloads the missing period
    rc2, out2, err2 = wiki.run_fetch(
        _authorized_request(company_query, market, plan),
        allow_download=True, timeout=600)
    assert rc2 == 0, f"step-2 failed ({market}): {out2[:400]} {err2[:200]}"
    second = json.loads(out2)
    assert second["status"] == "capture_ready", (
        f"expected capture_ready, got {second.get('status')}: {out2[:400]}")
    handle = second["handle"]
    downloaded_bytes_hash = handle.get("snapshot_sha256")
    canonical = Path(handle["canonical_path"])
    assert canonical.is_file(), "downloaded file missing"
    assert hashlib.sha256(canonical.read_bytes()).hexdigest() == (
        downloaded_bytes_hash), "bytes hash mismatch"
    files_after_first = {
        str(p.relative_to(tmp)) for p in (tmp / "companies").rglob("*")
        if p.is_file()
    }
    # step 3: the SECOND identical request — gap closed, zero downloads
    rc3, out3, err3 = wiki.run_fetch(
        _authorized_request(company_query, market, plan),
        allow_download=True, timeout=300)
    assert rc3 == 0, f"step-3 failed ({market}): {out3[:400]} {err3[:200]}"
    third = json.loads(out3)
    assert third["status"] == "gap", (
        f"expected gap closed, got {third.get('status')}: {out3[:300]}")
    assert third["gap_plan"]["missing"] == [], "gap not reported closed"
    files_after_second = {
        str(p.relative_to(tmp)) for p in (tmp / "companies").rglob("*")
        if p.is_file()
    }
    assert files_after_first == files_after_second, (
        "second request wrote to companies")
    outcomes = wiki.journal_outcomes()
    assert outcomes.count("downloaded_new") == 1, (
        f"expected exactly one downloaded_new, got {outcomes}")
    return {
        "market": market,
        "provider_metadata_hash": provider_metadata_hash,
        "downloaded_bytes_hash": downloaded_bytes_hash,
        "journal_outcomes": outcomes,
        "first_handle": {
            "provider": handle.get("provider"),
            "provider_document_id": handle.get("provider_document_id"),
            "fiscal_year": handle.get("fiscal_year"),
        },
    }


@unittest.skipUnless(
    _REAL_DOWNLOAD_AUTHORIZED,
    "T3 real-provider download requires FC805_REAL_DOWNLOAD=1 "
    "(explicit authorization; blocked otherwise, never counted as pass)")
class Fc805RealDownloadT3(unittest.TestCase):
    """CN/HK/US minimal samples against the REAL providers (isolated wiki)."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.tmp = Path(self._temporary.name)

    def tearDown(self) -> None:
        cleanup_temporary(self._temporary)

    def test_cn_real_provider_download(self) -> None:
        evidence = _run_real_flow("紫金矿业", "CN", self.tmp)
        self.assertEqual(evidence["first_handle"]["provider"], "cninfo")
        self.assertTrue(evidence["provider_metadata_hash"])
        self.assertTrue(evidence["downloaded_bytes_hash"])

    def test_hk_real_provider_download(self) -> None:
        evidence = _run_real_flow("腾讯控股", "HK", self.tmp)
        self.assertEqual(evidence["first_handle"]["provider"], "hkexnews")

    def test_us_real_provider_download(self) -> None:
        evidence = _run_real_flow("Apple Inc", "US", self.tmp)
        self.assertEqual(evidence["first_handle"]["provider"], "sec")


if __name__ == "__main__":
    unittest.main()
