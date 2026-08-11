"""FC-803: minimal download + second-request zero fetch/write (T1).

Real cross-process spies: the IsolatedWiki acquisition config points at
tests/e2e_support/spy_adapter.py (a real subprocess json_command_v1
adapter) whose every invocation lands in a spy log.  Scenarios:
LT-09/DL-04 (second identical request: fetch=0, write=0), LT-02 (reuse
the old period, download only the missing new one), LT-01 (local is
latest: discover ok, fetch=0, local handle), LT-05 (provider unavailable:
retryable plan, local reuse preserved, fetch=0), LT-07 (not-yet-published
never leaks into the gap).
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from e2e_support.isolated_wiki import IsolatedWiki, cleanup_temporary

_SPY = Path(__file__).resolve().parent / "e2e_support" / "spy_adapter.py"


def _spy_acquisition_yaml(log: Path, fixture: Path) -> str:
    from e2e_support.isolated_wiki import _NOOP_ADAPTER

    command = json.dumps(
        [os.environ.get("PYTHON_EXECUTABLE", "python"), str(_SPY)],
        ensure_ascii=False,
    )
    noop = json.dumps(_NOOP_ADAPTER, ensure_ascii=False)
    return f"""schema_version: "1.1"
staging_root: "${{PROJECT_ROOT}}/.source_catalog/staging"
timeout_seconds: 120
adapters:
  cn:
    name: "spy-provider"
    version: "1.0.0"
    interface: "json_command_v1"
    project_root: "${{PROJECT_ROOT}}"
    config_root: null
    command: {command}
  hk:
    name: "e2e-noop-hk"
    version: "1.0.0"
    interface: "dayu_cli_v1"
    project_root: "${{PROJECT_ROOT}}"
    config_root: "${{PROJECT_ROOT}}/config"
    command: {noop}
  us:
    name: "e2e-noop-us"
    version: "1.0.0"
    interface: "dayu_cli_v1"
    project_root: "${{PROJECT_ROOT}}"
    config_root: "${{PROJECT_ROOT}}/config"
    command: {noop}
"""


def _policy_file(wiki: IsolatedWiki) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".." / "company-wiki" / "src"))
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


def _candidate(accession: str, year: int, *, form_type: str = "annual_report",
               filing_date: str = "2026-04-15") -> dict:
    return {
        "candidate_id": f"c-{accession}",
        "provider": "spy",
        "provider_document_id": accession,
        "title": f"ACME {year} annual",
        "form_type": form_type,
        "filing_date": filing_date,
        "fiscal_year": year,
    }


class Fc803MinimalDownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.wiki = IsolatedWiki(self.root)
        _policy_file(self.wiki)
        self.spy_log = self.root / "spy_log.jsonl"
        self.fixture = self.root / "spy_fixture.json"
        self.fixture.write_text(json.dumps({}), encoding="utf-8")
        self._write_acquisition()

    def tearDown(self) -> None:
        cleanup_temporary(self._temporary)

    def _write_acquisition(self) -> None:
        # The spy env flows through os.environ: the filing-fetch CLI and the
        # company-wiki CLI subprocesses inherit it down to the adapter.
        os.environ["SPY_ADAPTER_LOG"] = str(self.spy_log)
        os.environ["SPY_ADAPTER_FIXTURE"] = str(self.fixture)
        # never leak a fault from a previous test into this one
        os.environ.pop("SPY_ADAPTER_FAULT", None)
        (self.root / "config" / "source_acquisition.yaml").write_text(
            _spy_acquisition_yaml(self.spy_log, self.fixture), encoding="utf-8")

    def _write_acquisition_fault(self) -> None:
        os.environ["SPY_ADAPTER_FAULT"] = "provider_unavailable"
        (self.root / "config" / "source_acquisition.yaml").write_text(
            _spy_acquisition_yaml(self.spy_log, self.fixture), encoding="utf-8")

    def _spy_actions(self) -> list[str]:
        if not self.spy_log.is_file():
            return []
        return [
            str(json.loads(line).get("action"))
            for line in self.spy_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def _spy_fetches(self) -> list[dict]:
        if not self.spy_log.is_file():
            return []
        return [
            json.loads(line)
            for line in self.spy_log.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("action") == "fetch"
        ]

    def _companies_files(self) -> set[str]:
        companies = self.root / "companies"
        return {
            str(p.relative_to(companies))
            for p in companies.rglob("*")
            if p.is_file()
        } if companies.exists() else set()

    def _authorized_latest(self) -> dict:
        return {
            "schema_version": "1.2",
            "company_query": "宁德时代",
            "market": "CN",
            "document_kind": "annual_report",
            "mode": "latest_as_of",
            "as_of_date": "2026-07-31",
            "authorization": {
                "provider": "spy",
                "allowed_accessions": ["acc-2025"],
                "max_items": 2,
                "max_bytes": 5_000_000,
                "expires_at": "2099-01-01T00:00:00Z",
            },
        }

    def test_lt09_second_request_zero_fetch_write(self) -> None:
        """DL-04/LT-09: after the first authorized close-gap, the second
        identical request reuses — provider fetch=0 and canonical write=0."""
        self.wiki.seed_market("CN")
        self.wiki.scan()
        self.fixture.write_text(json.dumps({
            "CN": [_candidate("acc-2025", 2025)],
        }), encoding="utf-8")
        request = self._authorized_latest()
        rc, out, err = self.wiki.run_fetch(request, allow_download=True)
        self.assertEqual(rc, 0, err)
        first = json.loads(out)
        self.assertEqual(first["status"], "capture_ready", out[:300])
        self.assertEqual(self._spy_actions().count("fetch"), 1)
        files_after_first = self._companies_files()
        self.assertTrue(files_after_first, "first download wrote nothing")

        # second identical request: the plan is now empty -> structured
        # gap (gap closed), zero fetch, zero write
        rc2, out2, err2 = self.wiki.run_fetch(request, allow_download=True)
        self.assertEqual(rc2, 0, err2)
        second = json.loads(out2)
        self.assertEqual(second["status"], "gap", out2[:300])
        self.assertEqual(second["gap_plan"]["missing"], [],
                         "gap not reported closed")
        self.assertEqual(self._spy_actions().count("fetch"), 1,
                         "second request fetched again")
        self.assertEqual(self._companies_files(), files_after_first,
                         "second request wrote to companies")

    def test_lt02_reuse_old_download_missing_new_only(self) -> None:
        """LT-02: Dropbox/companies has the old period; the provider has a
        NEWER period — the old handle is reused and ONLY the missing new
        period is downloaded (one fetch, for the new year)."""
        self.wiki.seed_market("CN")  # FY2024 local
        self.fixture.write_text(json.dumps({
            "CN": [_candidate("acc-2025", 2025)],
        }), encoding="utf-8")
        request = self._authorized_latest()
        rc, out, err = self.wiki.run_fetch(request, allow_download=True)
        self.assertEqual(rc, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "capture_ready", out[:300])
        fetches = self._spy_fetches()
        self.assertEqual(len(fetches), 1)
        self.assertEqual(fetches[0]["payload"].get("fiscal_year"), 2025,
                         "downloaded the wrong period")
        # the old-period document remains (reused, not re-downloaded)
        self.assertTrue(any("2024" in f for f in self._companies_files()),
                        f"old period vanished: {self._companies_files()}")

    def test_lt01_local_is_latest_fetch_zero(self) -> None:
        """LT-01: the provider confirms local is latest — discover may
        run, fetch=0, and the local handle is returned."""
        self.wiki.seed_market("CN")  # FY2024 local
        self.wiki.scan()
        self.fixture.write_text(json.dumps({
            "CN": [_candidate("syn-cn-0001", 2024)],
        }), encoding="utf-8")
        rc, out, err = self.wiki.run_fetch(self._authorized_latest(),
                                           allow_download=True)
        self.assertEqual(rc, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "gap", out[:300])
        self.assertEqual(payload["gap_plan"]["missing"], [])
        self.assertTrue(payload["gap_plan"]["reuse"],
                        "local reuse handle not surfaced")
        self.assertEqual(self._spy_actions().count("fetch"), 0)
        self.assertEqual(self._spy_actions().count("discover"), 1)

    def test_lt05_provider_unavailable_keeps_local_reuse(self) -> None:
        """LT-05: a provider outage must NOT claim 'no gap' — the plan is
        retryable, the local reuse is preserved, and fetch=0."""
        self.wiki.seed_market("CN")
        self._write_acquisition_fault()
        rc, out, err = self.wiki.run_fetch(self._authorized_latest(),
                                           allow_download=True)
        self.assertEqual(rc, 0, err + " OUT:" + out[:400])
        payload = json.loads(out)
        self.assertEqual(payload["status"], "gap", out[:300])
        self.assertTrue(payload["gap_plan"]["provider_unavailable"])
        self.assertEqual(self._spy_actions().count("fetch"), 0)

    def test_lt07_future_filing_never_leaks_into_gap(self) -> None:
        """LT-07: a candidate filed after as_of is excluded from the gap —
        nothing to fetch, nothing downloaded."""
        self.wiki.seed_market("CN")
        # FY2026 filed 2027-03-15 is after as_of 2026-07-31 -> future
        self.fixture.write_text(json.dumps({
            "CN": [_candidate("acc-2026", 2026, filing_date="2027-03-15")],
        }), encoding="utf-8")
        rc, out, err = self.wiki.run_fetch(self._authorized_latest(),
                                           allow_download=True)
        self.assertEqual(rc, 0, err + " OUT:" + out[:400])
        payload = json.loads(out)
        self.assertEqual(payload["status"], "gap", out[:300])
        plan = payload["gap_plan"]
        self.assertEqual(plan["missing"], [])
        self.assertTrue(plan["future"], "future candidate not surfaced")
        self.assertEqual(self._spy_actions().count("fetch"), 0)


if __name__ == "__main__":
    unittest.main()
