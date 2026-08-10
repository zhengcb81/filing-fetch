"""FC-501 RED/acceptance tests: filing-fetch consumes the policy snapshot.

filing-fetch must NOT keep an independent root allowlist
(``allowed_handle_roots``).  Handle validation verifies: (1) the policy
snapshot hash from company-wiki is consistent, and (2) the canonical path
is contained within a root the snapshot marks reusable_for_filing —
nothing else (DBX-01..06, architecture_target section 7).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from filing_contracts import FilingFetchError, validate_handle  # noqa: E402


def _policy_snapshot(roots=None):
    roots = roots or [
        {
            "root_id": "dropbox_stock",
            "path_ref": "${PROJECT_ROOT}/Dropbox/Stock",
            "read_only": True,
            "reusable_for_filing": True,
            "canonical_write_target": None,
        },
        {
            "root_id": "company_raw",
            "path_ref": "${PROJECT_ROOT}/companies",
            "read_only": False,
            "reusable_for_filing": True,
            "canonical_write_target": "companies",
        },
    ]
    return {
        "schema_version": "2.0",
        "reusable_root_kinds": ["company_raw", "dayu_portfolio", "directory"],
        "roots": roots,
    }


def _request(**overrides):
    request = {
        "schema_version": "1.1",
        "company_query": "Acme",
        "market": "CN",
        "document_kind": "annual",
        "fiscal_year": 2024,
        "as_of_date": "2026-08-10",
    }
    request.update(overrides)
    return request


def _base_handle(tmp_path, *, request_id="req-1", canonical_path=None):
    import hashlib

    pdf = tmp_path / "Dropbox" / "Stock" / "2025.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"pdf")
    digest = hashlib.sha256(b"pdf").hexdigest()
    return {
        "schema_version": "1.1",
        "request_id": request_id,
        "capture_ready": True,
        "canonical_path": str(canonical_path or pdf),
        "byte_size": 3,
        "content_sha256": digest,
        "snapshot_sha256": digest,
        "https_url": "https://example.com/2025.pdf",
        "published_date": "2025-03-21",
        "source_id": "src-1",
        "document_id": "doc-1",
        "location_id": "loc-1",
        "collector_name": "company-wiki",
        "collector_version": "1.0.0",
        "retrieved_at": "2026-08-10T00:00:00Z",
        "market": "CN",
        "security_id": "000001",
        "fiscal_year": 2024,
        "title": "Acme 2024 annual",
        "mime_type": "application/pdf",
        "provider": "cninfo",
        "provider_document_id": "doc-1",
    }


# --- policy hash binding -----------------------------------------------------


def test_validate_handle_requires_policy_hash(tmp_path):
    """FC-501: validate_handle must consume a policy snapshot (no
    independent allowlist path)."""
    handle = _base_handle(tmp_path)
    snapshot = _policy_snapshot()
    with pytest.raises(FilingFetchError):
        validate_handle(
            handle, _request(), tmp_path,
            policy_snapshot=snapshot,
            expected_policy_hash="b" * 64,  # mismatched hash -> fail closed
        )


def test_validate_handle_accepts_matching_policy_hash(tmp_path):
    import hashlib

    handle = _base_handle(tmp_path)
    snapshot = _policy_snapshot()
    payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    policy_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    validate_handle(
        handle, _request(), tmp_path,
        policy_snapshot=snapshot,
        expected_policy_hash=policy_hash,
    )  # must not raise


# --- canonical containment via the snapshot, not a local allowlist ----------


def test_handle_inside_reusable_root_accepted(tmp_path):
    import hashlib

    handle = _base_handle(tmp_path)  # canonical path under Dropbox/Stock
    snapshot = _policy_snapshot()
    payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    policy_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    validate_handle(
        handle, _request(), tmp_path,
        policy_snapshot=snapshot,
        expected_policy_hash=policy_hash,
    )  # Dropbox root is reusable_for_filing


def test_handle_outside_any_reusable_root_rejected(tmp_path):
    import hashlib

    outside = tmp_path / "other" / "leak.pdf"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"pdf")
    handle = _base_handle(tmp_path, canonical_path=outside)
    snapshot = _policy_snapshot()
    payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    policy_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    with pytest.raises(FilingFetchError):
        validate_handle(
            handle, _request(), tmp_path,
            policy_snapshot=snapshot,
            expected_policy_hash=policy_hash,
        )


def test_handle_inside_non_reusable_root_rejected(tmp_path):
    """A root marked reusable_for_filing=False must not serve handles."""
    import hashlib

    handle = _base_handle(tmp_path)
    snapshot = _policy_snapshot(roots=[
        {
            "root_id": "dropbox_stock",
            "path_ref": "${PROJECT_ROOT}/Dropbox/Stock",
            "read_only": True,
            "reusable_for_filing": False,  # not reusable
            "canonical_write_target": None,
        },
    ])
    payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False)
    policy_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    with pytest.raises(FilingFetchError):
        validate_handle(
            handle, _request(), tmp_path,
            policy_snapshot=snapshot,
            expected_policy_hash=policy_hash,
        )


def test_no_independent_allowlist_in_config_schema(tmp_path):
    """The config loader must reject allowed_handle_roots (no independent
    allowlist in the config schema)."""
    import json as _json

    from fetch_filing import load_company_wiki_root
    from filing_contracts import FilingFetchError

    # a REAL temp wiki root so only the schema rejection can fire
    root = tmp_path / "company-wiki"
    (root / "config").mkdir(parents=True)
    (root / "config" / "source_catalog.yaml").write_text(
        "schema_version: '1.0'\n"
        "catalog_dir: x\n"
        "roots: []\n",
        encoding="utf-8",
    )
    cfg = tmp_path / "company_wiki.json"
    cfg.write_text(
        _json.dumps({
            "schema_version": "1.0",
            "company_wiki_root": str(root),
            "allowed_handle_roots": ["/tmp"],
        }),
        encoding="utf-8",
    )
    with pytest.raises(FilingFetchError, match="exactly schema_version"):
        load_company_wiki_root(config_path=cfg)
