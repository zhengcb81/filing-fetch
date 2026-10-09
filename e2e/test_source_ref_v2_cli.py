"""Offline, real-process filing-fetch SourceRef v2 candidate handoff.

CI may select a pinned ``src`` with FILING_FETCH_V2_WIKI_SRC; local runs use
filing-fetch's configured company-wiki project when no override is provided.
All state lives under pytest's temporary directory. No acquisition is enabled.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import fetch_filing


REPO = Path(__file__).resolve().parents[1]
BODY = b"%PDF-1.4\nApple annual filing\x00\xff\n"
SHA = hashlib.sha256(BODY).hexdigest()


def _environment() -> dict[str, str]:
    source = os.environ.get("FILING_FETCH_V2_WIKI_SRC")
    if not source:
        source = str(fetch_filing.load_company_wiki_root() / "src")
    try:
        source_dir = Path(source).resolve(strict=True)
    except OSError as exc:
        pytest.fail(f"company-wiki source runtime unavailable: {exc}", pytrace=False)
    if not (source_dir / "company_wiki" / "source_catalog" / "cli.py").is_file():
        pytest.fail("FILING_FETCH_V2_WIKI_SRC lacks source catalog CLI")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(source_dir)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    environment["HTTP_PROXY"] = "http://127.0.0.1:9"
    environment["HTTPS_PROXY"] = "http://127.0.0.1:9"
    environment["NO_PROXY"] = ""
    return environment


def _sidecar() -> dict:
    return {
        "schema_version": "1.0",
        "canonical_entity_id": "ent-apple",
        "display_name": "Apple Inc.",
        "market": "US",
        "security_id": "AAPL",
        "document_kind": "annual_report",
        "fiscal_year": 2025,
        "period_end": "2025-12-31",
        "filing_date": "2026-02-20",
        "form_type": "10-K",
        "provider": "sec",
        "provider_document_id": "doc-v2-e2e-1",
        "source_url": "https://sec.gov/x/2025",
        "content_sha256": SHA,
        "retrieved_at": "2026-02-21T00:00:00Z",
        "collector_name": "sec_edgar",
        "collector_version": "1.0",
    }


def _write_copy(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / "2025.pdf"
    pdf.write_bytes(BODY)
    (folder / "2025.pdf.source.json").write_text(
        json.dumps(_sidecar()), encoding="utf-8"
    )
    return pdf


def _setup_wiki(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    wiki = tmp_path / "wiki"
    config = wiki / "config"
    config.mkdir(parents=True)
    primary = _write_copy(
        wiki / "companies" / "Apple Inc." / "raw" / "financial_reports" / "annual"
    )
    _write_copy(wiki / "future_lake")
    catalog_config = config / "source_catalog.yaml"
    catalog_config.write_text(
        'schema_version: "1.0"\n'
        'catalog_dir: "${PROJECT_ROOT}/.source_catalog"\n'
        'reusable_root_kinds: [company_raw, directory]\n'
        'roots:\n'
        '  - root_id: company_raw\n'
        '    kind: company_raw\n'
        '    path: "${PROJECT_ROOT}/companies"\n'
        '    priority: 10\n'
        '    adapter_id: company_raw_v1\n'
        '    read_only: false\n'
        '  - root_id: future_lake\n'
        '    kind: directory\n'
        '    path: "${PROJECT_ROOT}/future_lake"\n'
        '    priority: 20\n'
        '    adapter_id: sidecar_filing_v1\n'
        '    read_only: true\n'
        '    reusable_for_filing: true\n',
        encoding="utf-8",
    )
    master = wiki / ".source_catalog" / "security_master"
    master.mkdir(parents=True)
    (master / "us.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "market": "US",
                "retrieved_at": "2000-01-01T00:00:00Z",
                "sources": ["https://sec.gov"],
                "record_count": 1,
                "records": [
                    {
                        "schema_version": "1.0",
                        "active": True,
                        "canonical_name": "Apple Inc.",
                        "market": "US",
                        "exchange": "NASDAQ",
                        "ticker": "AAPL",
                        "security_id": "AAPL",
                        "aliases": ["APPLE"],
                        "identifiers": {"cik": "0000320193"},
                        "source_name": "sec",
                        "source_url": "https://sec.gov",
                        "source_record_id": "synthetic-aapl",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    launcher = tmp_path / "company_wiki.json"
    launcher.write_text(
        json.dumps({"schema_version": "1.0", "company_wiki_root": str(wiki)}),
        encoding="utf-8",
    )
    return wiki, catalog_config, launcher, primary


def _wiki_cli(
    wiki: Path,
    catalog_config: Path,
    environment: dict[str, str],
    command: str,
    *arguments: str,
) -> dict:
    proc = subprocess.run(
        [
            sys.executable, "-B", "-m", "company_wiki.source_catalog.cli",
            "--config", str(catalog_config), command, *arguments,
        ],
        cwd=wiki, env=environment, capture_output=True, text=True,
        encoding="utf-8", timeout=60, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)



def _record_clean_review(config_path: Path, environment: dict[str, str]) -> None:
    source_dir = environment["PYTHONPATH"]
    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)
    from company_wiki.source_catalog import SourceCatalog
    from company_wiki.source_catalog.config import load_catalog_config
    from company_wiki.source_catalog.policy_2x import export_policy_2x
    from company_wiki.source_catalog.prompt_injection import record_prompt_injection_review

    catalog = SourceCatalog(load_catalog_config(config_path))
    try:
        row = catalog.reader.fetchone(
            "SELECT document_id FROM documents d JOIN sources s "
            "ON s.source_id=d.primary_source_id "
            "WHERE d.source_status='active' AND s.content_sha256=? LIMIT 1",
            (SHA,),
        )
        assert row is not None
        policy_hash, _ = export_policy_2x(catalog.config)
        with catalog.store.transaction() as connection:
            record_prompt_injection_review(
                connection, str(row["document_id"]), status="not_detected",
                reviewer="ff-source-ref-v2-e2e", evidence_sha256=SHA,
                evidence_payload=BODY, source_sha256=SHA,
                policy_hash=policy_hash, now="2026-09-27T00:00:00Z",
            )
    finally:
        catalog.close()


def _activate_policy(wiki: Path, policy_hash: str) -> None:
    payload = {
        "schema_version": "1.0",
        "policy_hash": policy_hash,
        "current_epoch": "reader-e2e-1",
        "active_cohorts": [],
        "flags": {
            "v2_scan_shadow": False,
            "v2_persist_assertions": False,
            "v2_resolve_shadow": False,
            "v2_resolve_active": False,
            "v2_bundle_active": False,
            "legacy_bridge_enabled": True,
        },
        "updated_at": "2026-09-27T00:00:00Z",
    }
    payload["snapshot_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    (wiki / ".source_catalog" / "runtime_policy.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _fetch(launcher: Path, environment: dict[str, str]) -> dict:
    request = {
        "schema_version": "1.1",
        "company_query": "AAPL",
        "market": "US",
        "document_kind": "annual_report",
        "fiscal_year": 2025,
        "as_of_date": "2026-09-27",
    }
    proc = subprocess.run(
        [
            sys.executable, "-B", str(REPO / "scripts" / "fetch_filing.py"),
            "--config", str(launcher), "--source-ref-v2",
            "--timeout-seconds", "60",
        ],
        cwd=REPO, env=environment,
        input=json.dumps(request), capture_output=True, text=True,
        encoding="utf-8", timeout=75, check=False,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    return json.loads(proc.stdout)


def _assert_pathless(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            assert not any(word in key for word in ("path", "location", "root"))
            _assert_pathless(child)
    elif isinstance(value, list):
        for child in value:
            _assert_pathless(child)


def test_same_sha_duplicate_returns_pathless_candidate_without_reading_pdf(tmp_path):
    environment = _environment()
    wiki, config, launcher, primary = _setup_wiki(tmp_path)
    duplicate = wiki / "future_lake" / "2025.pdf"
    _wiki_cli(wiki, config, environment, "scan")
    policy = _wiki_cli(wiki, config, environment, "policy-export")
    _activate_policy(wiki, policy["policy_hash"])
    _record_clean_review(config, environment)
    original_mtimes = (primary.stat().st_mtime_ns, duplicate.stat().st_mtime_ns)
    journal = wiki / ".source_catalog" / "acquisition_attempts.jsonl"
    journal_before = journal.read_bytes() if journal.exists() else b""

    first = _fetch(launcher, environment)
    assert first["status"] == "capture_ready"
    assert first["downloads"] == 0
    assert first["calls"] == 2
    first_handle = first["handle"]
    assert first_handle["download_events"] == 0
    assert first_handle["resolution_outcome"] == "reused_existing"
    assert first_handle["source_ref"]["content_sha256"] == SHA
    assert first_handle["document_kind"] == "annual_report"
    assert first_handle["fiscal_year"] == 2025
    assert first_handle["provider"] == "sec"
    assert first_handle["capture_ready"] is True
    assert first_handle["company_identity"]["security_id"] == "AAPL"
    assert "source_read_receipt" not in first_handle
    _assert_pathless(first_handle)
    assert primary.read_bytes() == duplicate.read_bytes() == BODY
    assert (primary.stat().st_mtime_ns, duplicate.stat().st_mtime_ns) == original_mtimes
    assert (journal.read_bytes() if journal.exists() else b"") == journal_before

    primary.unlink()
    second = _fetch(launcher, environment)
    second_handle = second["handle"]
    assert second["downloads"] == 0
    assert second["calls"] == 2
    assert second_handle["source_ref"] == first_handle["source_ref"]
    assert second_handle["download_events"] == 0
    _assert_pathless(second_handle)
    assert duplicate.read_bytes() == BODY
    assert duplicate.stat().st_mtime_ns == original_mtimes[1]
    assert (journal.read_bytes() if journal.exists() else b"") == journal_before

