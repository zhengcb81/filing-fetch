"""Manual fixed-SHA annual filing through real FF and CWP public CLIs.

Original bytes are read/copied only. Metadata/identity are labelled fixtures.
No provider/network/model call. All copies and SQLite state are finally removed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))
from e2e_support.isolated_wiki import IsolatedWiki, _synthetic_security_master  # noqa: E402
from ff_process_transport import run_bounded  # noqa: E402

SHA = "d64c410832f22f5127277bad6dc357c664aede523561af99150c494857fd3aa5"


def _digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _pathless(value):
    if isinstance(value, dict):
        for key, child in value.items():
            assert not any(word in key for word in ("path", "root", "location")), key
            _pathless(child)
    elif isinstance(value, list):
        for child in value:
            _pathless(child)


def run(raw, scratch):
    assert _digest(raw) == SHA
    before = sorted(path.name for path in scratch.iterdir())
    with tempfile.TemporaryDirectory(prefix="real-", dir=scratch) as temporary:
        root = Path(temporary)
        wiki = IsolatedWiki(root)
        master = _synthetic_security_master("cn")
        record = master["records"][0]
        record.update(canonical_name="中微公司", aliases=["AMEC"], market="CN",
                      exchange="SSE", ticker="688012", security_id="688012",
                      identifiers={"org_id": "fixture-amec"})
        (wiki.catalog_dir / "security_master" / "cn.json").write_text(
            json.dumps(master, ensure_ascii=False), encoding="utf-8"
        )
        copy = root / "companies/中微公司/raw/financial_reports/annual/2025.pdf"
        copy.parent.mkdir(parents=True)
        shutil.copy2(raw, copy)
        sidecar = dict(schema_version="1.0", market="CN", security_id="688012",
                       source_title="中微公司2025年年度报告", company_name="中微公司",
                       published_date="2026-03-30", fiscal_year=2025, form_type="FY",
                       provider="cninfo", provider_document_id="fixture-amec-2025",
                       source_url="https://www.cninfo.com.cn/fixture-amec-2025")
        copy.with_name(copy.name + ".source.json").write_text(
            json.dumps(sidecar, ensure_ascii=False), encoding="utf-8"
        )
        wiki.scan()
        request = dict(schema_version="2.0", company_query="中微公司", market="CN",
                       document_kind="annual_report", mode="exact", fiscal_year=2025,
                       as_of_date="2026-10-05", filing_intent="reuse_only")
        bodies = []
        for _ in range(2):
            code, stdout, stderr = wiki.run_fetch(request, timeout=30)
            assert code == 0, stdout + stderr
            envelope = json.loads(stdout)
            assert envelope["status"] == "source_candidate", envelope
            assert envelope["downloads"] == 0
            assert envelope["request_period"]["fiscal_year"] == 2025
            assert envelope["filing"]["byte_verification"] == "pending_verified_open"
            ref = envelope["filing"]["source_ref"]
            assert ref["content_sha256"] == SHA
            assert ref["byte_size"] == raw.stat().st_size
            _pathless(envelope["filing"])
            bodies.append(ref)
        assert bodies[0] == bodies[1]
        ref = bodies[0]
        result = run_bounded([
            sys.executable, "-B", "-m", "company_wiki.source_catalog.source_reader_cli",
            "--config", str(wiki.config_path), "--document-id", ref["document_id"],
            "--source-id", ref["source_id"], "--content-sha256", SHA, "--purpose", "preview"
        ], timeout_seconds=30, cwd=str(root), env=dict(os.environ))
        assert result["stdout"] == raw.read_bytes() == copy.read_bytes()
        receipt = json.loads(result["stderr"])
        assert receipt["status"] == "ok"
        assert receipt["content_sha256"] == SHA
        assert receipt["byte_size"] == raw.stat().st_size
        assert not list(root.rglob("filing_fetch_pause.*"))
        journal = root / ".source_catalog/acquisition_attempts.jsonl"
        assert not journal.exists(), "reuse_only must not acquire"
    assert not Path(temporary).exists()
    assert sorted(path.name for path in scratch.iterdir()) == before
    assert _digest(raw) == SHA
    print(json.dumps(dict(status="ok", original_sha256=SHA, byte_size=raw.stat().st_size,
                          raw_equal=True, repeat_provider_calls=0, legacy_pause_files=0,
                          scratch_restored=True, identity_metadata="synthetic fixture",
                          provider_http_calls=0, model_calls=0), ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-file", type=Path, required=True)
    parser.add_argument("--scratch-root", type=Path, required=True)
    args = parser.parse_args()
    run(args.raw_file.resolve(strict=True), args.scratch_root.resolve(strict=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

