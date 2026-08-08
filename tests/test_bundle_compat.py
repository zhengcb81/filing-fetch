"""WU-5.3: filing-fetch bundle compatibility (consumer side).

- A capture-ready handle MAY carry an optional ``source_bundle`` field
  (source + valid_handles + invalid + bundle_hash). Filing-fetch must not
  choke on it (forward compat: newer company-wiki → older filing-fetch).
- A handle WITHOUT the field still validates (backward compat: older
  company-wiki → newer filing-fetch): the bundle is optional.
- validate_handle's deep checks (required fields, capture_ready, path
  containment) keep working in both directions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


FILING_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FILING_ROOT / "scripts"))

from filing_contracts import FilingFetchError, validate_handle  # noqa: E402


def _make_canonical_file(tmp_path: Path) -> tuple[Path, int, str]:
    """validate_handle deep-checks is_file + byte_size + snapshot hash; create
    a real file under a temp companies/ root; return (path, size, sha256)."""
    import hashlib

    root = tmp_path / "companies"
    acme = root / "ACME"
    acme.mkdir(parents=True)
    path = acme / "1.pdf"
    body = b"%PDF-1.4 " + b"x" * 90
    path.write_bytes(body)
    return path, len(body), hashlib.sha256(body).hexdigest()


def _base_handle(tmp_path: Path, **overrides):
    path, size, sha = _make_canonical_file(tmp_path)
    handle = {
        "request_id": "req-1",
        "document_id": "doc-1",
        "source_id": "src-1",
        "title": "ACME 2025 annual",
        "published_date": "2026-04-15",
        "https_url": "https://www.sec.gov/x/2025.pdf",
        "canonical_path": str(path),
        "snapshot_sha256": sha,
        "retrieved_at": "2026-08-08T12:00:00Z",
        "provider": "sec",
        "provider_document_id": "acc-2025",
        "collector_name": "test",
        "collector_version": "1.0.0",
        "byte_size": size,
        "mime_type": "application/pdf",
        "capture_ready": True,
    }
    handle.update(overrides)
    return handle


def _request():
    return {
        "schema_version": "1.2",
        "company_query": "ACME",
        "market": "US",
        "document_kind": "annual_report",
        "mode": "exact",
        "fiscal_year": 2025,
        "as_of_date": "2026-07-31",
    }


def _wiki_root(tmp_path: Path):
    return tmp_path


def test_handle_with_bundle_validates(tmp_path):
    """Forward compat: a handle carrying source_bundle still passes deep
    validation (bundle is optional metadata, not required)."""
    handle = _base_handle(
        tmp_path,
        source_bundle={
            "schema_version": "1.0",
            "source": {"document_id": "doc-1"},
            "valid_handles": {
                "normalized": {"artifact_role": "normalized", "reusable": True}
            },
            "invalid": {},
            "bundle_hash": "b" * 64,
        },
    )
    validate_handle(handle, _request(), _wiki_root(tmp_path))  # must not raise


def test_handle_without_bundle_validates(tmp_path):
    """Backward compat: legacy company-wiki handles (no bundle) are accepted."""
    validate_handle(_base_handle(tmp_path), _request(), _wiki_root(tmp_path))


def test_bundle_is_optional_never_required(tmp_path):
    """No code path should require source_bundle — its absence is normal."""
    try:
        validate_handle(_base_handle(tmp_path), _request(), _wiki_root(tmp_path))
    except FilingFetchError as exc:
        if "bundle" in str(exc).lower():
            pytest.fail(f"bundle wrongly required: {exc}")


def test_forged_bundle_does_not_relax_deep_checks(tmp_path):
    """Reviewer finding: a forged/malformed source_bundle must NEVER relax the
    handle deep checks — an out-of-allowance or bad-hash handle is rejected
    regardless of what the bundle claims."""
    # forged bundle claiming a valid normalized handle
    forged = _base_handle(
        tmp_path,
        source_bundle={
            "schema_version": "1.0",
            "source": {"document_id": "doc-1"},
            "valid_handles": {
                "normalized": {
                    "artifact_role": "normalized",
                    "reusable": True,
                    "path": "/unrelated",
                    "content_sha256": "c" * 64,
                }
            },
            "invalid": {},
            "bundle_hash": "d" * 64,
        },
    )
    # but the canonical file itself is tampered: snapshot hash no longer matches
    forged["snapshot_sha256"] = "e" * 64
    with pytest.raises(FilingFetchError):
        validate_handle(forged, _request(), _wiki_root(tmp_path))
