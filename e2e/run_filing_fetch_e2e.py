"""Repeatable, self-validating filing-fetch full-chain E2E harness.

Builds a HERMETIC company-wiki instance (synthetic seed documents, no
dependency on production wiki files), then exercises the real filing-fetch
CLI: identify -> resolve reuse (CN/US/HK) -> resolve missing -> ensure
missing -> handle validation, compares deterministic handle outputs against
a golden, and verifies double-run reproducibility.

Usage:
    python e2e/run_filing_fetch_e2e.py [--update-golden] [--keep-runs]

Exit codes:
    0 = all green
    1 = a step assertion failed (regression or environment)
    2 = input/contract error (missing fixture, import failure, golden key)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
EXPECTED_DIR = HERE / "expected"
RUNS_DIR = HERE / ".runs"

FIXTURE_VERSION = "biren-e2e-v1"  # bump when synthetic seed content changes

SYNTHETIC_SEEDS = {
    "CN": {
        "entity": "宁德时代", "company_query": "宁德时代", "market": "CN",
        "security_id": "300750", "fiscal_year": 2024, "as_of": "2026-07-31",
        "bytes": b"%PDF-1.4 synthetic cn annual fixture 0123456789",
        "title": "宁德时代2024年年度报告",
        "provider": "cninfo", "provider_document_id": "syn-cn-0001",
        "source_url": "https://www.cninfo.com.cn/new/disclosure/detail?stockCode=300750",
        "published": "2025-03-14",
    },
    "US": {
        "entity": "Apple Inc", "company_query": "Apple Inc", "market": "US",
        "security_id": "AAPL", "fiscal_year": 2025, "as_of": "2026-07-31",
        "bytes": b"%PDF-1.4 synthetic us 10k fixture 9876543210",
        "title": "Apple Inc. 10-K FY2025",
        "provider": "sec", "provider_document_id": "syn-us-0001",
        "source_url": "https://www.sec.gov/Archives/edgar/data/0000320193/syn-10k.htm",
        "published": "2025-10-31",
    },
    "HK": {
        "entity": "騰訊控股", "company_query": "腾讯控股", "market": "HK",
        "security_id": "00700", "fiscal_year": 2024, "as_of": "2026-07-31",
        "bytes": b"%PDF-1.4 synthetic hk annual fixture abcdef",
        "title": "腾讯控股2024年年度報告",
        "provider": "hkexnews", "provider_document_id": "syn-hk-0001",
        "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/syn-annual.pdf",
        "published": "2025-04-10",
    },
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def seed_fingerprint() -> str:
    return sha256_bytes(json.dumps(
        {m: (s["entity"], sha256_bytes(s["bytes"])) for m, s in SYNTHETIC_SEEDS.items()},
        sort_keys=True, ensure_ascii=False,
    ).encode("utf-8"))


def _report(msg: str) -> None:
    print(f"[e2e] {msg}", flush=True)


class StepCollector:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, step: str, condition: bool, message: str) -> None:
        if not condition:
            self.failures.append(f"STEP {step}: {message}")
            _report(f"  FAIL {step}: {message}")
        else:
            _report(f"  ok   {step}")


def build_wiki(root: Path) -> object:
    sys.path.insert(0, str(REPO / "tests"))
    sys.path.insert(0, str(REPO / "tests" / "e2e_support"))
    from isolated_wiki import IsolatedWiki  # noqa: E402

    wiki = IsolatedWiki(root)
    for market, spec in SYNTHETIC_SEEDS.items():
        kind_dir = "annual"
        target = root / "companies" / spec["entity"] / "raw" / "financial_reports" / kind_dir
        target.mkdir(parents=True, exist_ok=True)
        pdf = target / f"synthetic_{spec['fiscal_year']}_annual.pdf"
        pdf.write_bytes(spec["bytes"])
        sidecar = target / (pdf.name + ".source.json")
        sidecar.write_text(json.dumps({
            "market": spec["market"], "security_id": spec["security_id"],
            "source_title": spec["title"], "provider": spec["provider"],
            "provider_document_id": spec["provider_document_id"],
            "source_url": spec["source_url"], "published_date": spec["published"],
            "fiscal_year": spec["fiscal_year"], "form_type": "FY",
        }, ensure_ascii=False), encoding="utf-8")
    wiki.scan()
    return wiki


def fetch(wiki, spec: dict) -> dict:
    rc, out, err = wiki.run_fetch({
        "schema_version": "1.1", "company_query": spec["company_query"],
        "market": spec["market"], "document_kind": "annual_report",
        "fiscal_year": spec["fiscal_year"], "as_of_date": spec["as_of"],
    })
    return {"rc": rc, "payload": json.loads(out) if out else None, "err": err}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update-golden", action="store_true")
    parser.add_argument("--keep-runs", action="store_true")
    args = parser.parse_args()

    golden_key = f"{FIXTURE_VERSION}-{seed_fingerprint()[:12]}"
    golden_path = EXPECTED_DIR / f"expected-{golden_key}.json"

    run_root = RUNS_DIR / golden_key
    run_root.mkdir(parents=True, exist_ok=True)
    existing = [int(p.name.split("-")[1]) for p in run_root.iterdir()
                if p.is_dir() and p.name.startswith("run-")]
    seq = max(existing, default=0)

    c = StepCollector()
    collected: dict = {"golden_key": golden_key}
    # ---- build a fresh hermetic wiki per run ----
    for attempt in (1, 2):
        wiki_root = run_root / f"run-{seq + attempt}"
        wiki = build_wiki(wiki_root)
        market_results = {}
        for market, spec in SYNTHETIC_SEEDS.items():
            r = fetch(wiki, spec)
            market_results[market] = r
        collected[f"run{attempt}_market_results"] = {
            m: {
                "status": r["payload"].get("status") if r["payload"] else None,
                "request_id": (r["payload"].get("handle") or {}).get("request_id"),
                "snapshot_sha256": (r["payload"].get("handle") or {}).get("snapshot_sha256"),
                "https_url": (r["payload"].get("handle") or {}).get("https_url"),
                "canonical_tail": (r["payload"].get("handle") or {}).get("canonical_path", "")[-30:],
                "missing": (r["payload"].get("handle") or {}).get("missing_capture_fields"),
            }
            for m, r in market_results.items()
        }
        _report(f"  run {attempt}: CN={market_results['CN']['payload'].get('status')} "
                f"US={market_results['US']['payload'].get('status')} "
                f"HK={market_results['HK']['payload'].get('status')}")

    r1 = collected["run1_market_results"]
    r2 = collected["run2_market_results"]
    # ---- STEP 9: determinism ----
    for m in SYNTHETIC_SEEDS:
        h1 = (r1[m].get("snapshot_sha256"), r1[m].get("request_id"))
        h2 = (r2[m].get("snapshot_sha256"), r2[m].get("request_id"))
        c.check(f"9-{m}", h1 == h2, f"double-run handle drift for {m}: {h1} vs {h2}")

    # ---- STEPS 3-8 on run 1 ----
    for m, spec in SYNTHETIC_SEEDS.items():
        res = r1[m]
        c.check(f"3-{m}", res["status"] == "capture_ready",
                f"{m}: expected capture_ready, got {res['status']}")
        c.check(f"4-{m}", res["missing"] == [],
                f"{m}: missing_capture_fields should be empty: {res['missing']}")
        c.check(f"5-{m}", bool(res["request_id"]) and res["request_id"].startswith("urn:"),
                f"{m}: request_id missing/invalid")
        c.check(f"6-{m}", bool(res["snapshot_sha256"]) and len(res["snapshot_sha256"]) == 64,
                f"{m}: snapshot_sha256 invalid")
        c.check(f"7-{m}", bool(res["https_url"]) and res["https_url"].startswith("https://"),
                f"{m}: https_url invalid")

    # ---- STEP 5: resolve missing (fiscal year not in the synthetic wiki) ----
    missing_spec = dict(SYNTHETIC_SEEDS["CN"]); missing_spec["fiscal_year"] = 2023
    wiki_root = run_root / f"run-{seq + 1}"
    missing_wiki = build_wiki(wiki_root)
    r_missing = fetch(missing_wiki, missing_spec)
    c.check("5-missing", r_missing["rc"] == 2 and (r_missing["payload"] or {}).get("status") == "not_found",
            f"missing-year request should be not_found: rc={r_missing['rc']} status={(r_missing['payload'] or {}).get('status')}")

    if not golden_path.is_file() and not args.update_golden:
        print(f"ERROR: no golden for key {golden_key} (seed changed? run --update-golden)", file=sys.stderr)
        return 2

    # ---- STEP 8/10: golden ----
    golden_data = {"golden_key": golden_key, "market_results": r1}
    try:
        golden_data["repo_head"] = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
    except Exception:
        golden_data["repo_head"] = None
    if args.update_golden:
        EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
        golden_path.write_text(json.dumps(golden_data, ensure_ascii=False, indent=2), encoding="utf-8")
        _report(f"golden updated: {golden_path.name}")
    else:
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        diffs = []
        for m in SYNTHETIC_SEEDS:
            for k in ("status", "request_id", "snapshot_sha256", "https_url", "canonical_tail", "missing"):
                a = r1[m].get(k); g = (golden.get("market_results") or {}).get(m, {}).get(k)
                if a != g:
                    diffs.append(f"{m}.{k}: expected {g} got {a}")
        if diffs:
            print("ERROR: STEP 10 FAILED — golden mismatch:", file=sys.stderr)
            for d in diffs:
                print(f"  {d}", file=sys.stderr)
            return 1
        _report("  ok   STEP 10: golden comparison identical")

    if c.failures:
        print("ERROR: " + "; ".join(c.failures), file=sys.stderr)
        return 1
    _report(f"E2E PASS: golden={golden_key} repo_head={(golden_data.get('repo_head') or '?')[:8]}")
    if not args.keep_runs:
        runs = sorted(run_root.glob("run-*"))
        for old in runs[:-2]:
            try:
                for f in old.rglob("*"):
                    if f.is_file():
                        f.unlink()
                for d in sorted(old.rglob("*"), reverse=True):
                    if d.is_dir():
                        d.rmdir()
                old.rmdir()
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
