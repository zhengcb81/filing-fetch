"""ZR-405 acceptance tests: policy-root containment, no legacy companies
default in production, no widening, containment/symlink negatives,
envelope policy_hash cross-check, and policy-export fail-closed.

The tests drive validate_handle and _handle_from_resolution directly
with a policy snapshot whose roots use ${PROJECT_ROOT}-tokenized
path_refs — the exact shape the wiki ``policy-export`` endpoint emits.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from filing_contracts import FilingFetchError, validate_handle  # noqa: E402
from fetch_filing import (  # noqa: E402
    _handle_from_resolution,
    resolve_filing,
)


def _policy(*, root_ids: tuple[str, ...], wiki_root: Path) -> dict:
    """A policy snapshot in the wiki policy-export shape: ${PROJECT_ROOT}
    tokens in path_ref, reusable_for_filing only on the listed roots.
    policy_hash is the canonical hash of the policy DOCUMENT (the
    ``policy_hash`` key itself excluded — the ZR-405 discipline)."""
    templates = {
        "company_raw": "${PROJECT_ROOT}/companies",
        "dropbox_stock": "${PROJECT_ROOT}/Dropbox/Stock",
        "dayu_portfolio": "${PROJECT_ROOT}/portfolio",
        "future_lake": "${PROJECT_ROOT}/future_lake",
    }
    roots = []
    for root_id in templates:
        entry = {
            "root_id": root_id,
            "path_ref": templates[root_id],
            "adapter_id": "sidecar_filing_v1",
            "read_only": True,
            "reusable_for_filing": root_id in root_ids,
            "priority": 10,
        }
        roots.append(entry)
    document = {
        "schema_version": "1.0",
        "reusable_root_kinds": list(root_ids),
        "roots": roots,
    }
    payload = json.dumps(document, sort_keys=True, ensure_ascii=False)
    return {
        "schema_version": "1.0",
        "policy_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "reusable_root_kinds": list(root_ids),
        "roots": roots,
    }


def _wiki_root(tmp_path: Path) -> Path:
    root = tmp_path / "wiki"
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "source_catalog.yaml").write_text(
        "schema_version: '1.0'\n", encoding="utf-8"
    )
    for rel in (
        "companies/Acme/raw/financial_reports/annual",
        "Dropbox/Stock",
        "portfolio/ACME/filings/fil_x",
        "future_lake",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
    return root


def _canonical(wiki_root: Path, rel: str) -> Path:
    path = wiki_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 zr405")
    return path


def _request() -> dict:
    return {
        "schema_version": "1.2",
        "company_query": "Acme",
        "market": "US",
        "security_id": "ACME",
        "document_kind": "annual_report",
        "form_type": "10-K",
        "fiscal_year": 2025,
        "as_of_date": "2026-08-11",
    }


def _handle(wiki_root: Path, rel: str) -> dict:
    canonical = _canonical(wiki_root, rel)
    return {
        "request_id": "urn:test:zr405",
        "document_id": "doc-1",
        "source_id": "src:sha256:" + "0" * 64,
        "title": "Acme 2025",
        "source_type": "regulatory_filing",
        "document_kind": "annual_report",
        "published_date": "2026-02-20",
        "fiscal_year": 2025,
        "form_type": "10-K",
        "language": "en",
        "provider": "sec",
        "provider_document_id": "doc-1",
        "https_url": "https://sec.gov/x/2025",
        "canonical_path": str(canonical),
        "canonical_location_id": "loc-1",
        "content_sha256": hashlib.sha256(b"%PDF-1.4 zr405").hexdigest(),
        "snapshot_sha256": hashlib.sha256(b"%PDF-1.4 zr405").hexdigest(),
        "mime_type": "application/pdf",
        "byte_size": len(b"%PDF-1.4 zr405"),
        "retrieved_at": "2026-08-10T00:00:00Z",
        "collector_name": "test",
        "collector_version": "1.0.0",
        "source_status": "active",
        "capture_ready": True,
        "missing_capture_fields": [],
        "exact_duplicate_group_id": "",
        "exact_duplicate_location_count": 0,
    }


def _envelope(*, policy_hash: str | None, outcome: str = "reused_existing") -> dict:
    return {
        "envelope_schema_version": "1.0",
        "outcome": outcome,
        "download_events": 0,
        "policy_hash": policy_hash,
        "activation_epoch": "epoch-7",
        "bundle_status": "unavailable",
        "bundle_hash": None,
        "bundle": None,
        "prompt_injection_status": "not_reviewed",
        "parser_calls": None,
        "llm_calls": None,
    }


def _resolution(
    handle: dict, *, envelope: dict | None = None, policy_export: dict | None = None
) -> dict:
    resolution = {
        "schema_version": "1.0",
        "request_id": "urn:test:zr405",
        "status": "reused_exact",
        "reason": "one_existing_source_matches_provider_identity",
        "download_required": False,
        "download_allowed": False,
        "matches": [handle],
        "debug_trace": ["matched"],
    }
    if envelope is not None:
        resolution["resolution_envelope"] = envelope
    if policy_export is not None:
        resolution["policy_export"] = policy_export
    return resolution


class PolicyRootsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="zr405-"))
        self.wiki_root = _wiki_root(self._tmp)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    # --- C3: any policy-allowed root succeeds --------------------------------

    def test_dropbox_only_policy_allows_dropbox_handle(self) -> None:
        policy = _policy(root_ids=("dropbox_stock",), wiki_root=self.wiki_root)
        handle = _handle(self.wiki_root, "Dropbox/Stock/2025.pdf")
        validate_handle(
            handle,
            _request(),
            self.wiki_root,
            policy_snapshot=policy,
            expected_policy_hash=policy["policy_hash"],
        )

    def test_dayu_only_policy_allows_dayu_handle(self) -> None:
        policy = _policy(root_ids=("dayu_portfolio",), wiki_root=self.wiki_root)
        handle = _handle(self.wiki_root, "portfolio/ACME/filings/fil_x/fil_x.pdf")
        validate_handle(
            handle,
            _request(),
            self.wiki_root,
            policy_snapshot=policy,
            expected_policy_hash=policy["policy_hash"],
        )

    def test_future_lake_policy_allows_future_root_handle(self) -> None:
        policy = _policy(root_ids=("future_lake",), wiki_root=self.wiki_root)
        handle = _handle(self.wiki_root, "future_lake/2025.pdf")
        validate_handle(
            handle,
            _request(),
            self.wiki_root,
            policy_snapshot=policy,
            expected_policy_hash=policy["policy_hash"],
        )

    # --- C4: no widening, no legacy default under a policy -------------------

    def test_companies_handle_rejected_when_not_in_policy(self) -> None:
        """Dropbox-only policy: a companies handle is REJECTED — the legacy
        <wiki_root>/companies default never applies when a policy is
        supplied."""
        policy = _policy(root_ids=("dropbox_stock",), wiki_root=self.wiki_root)
        handle = _handle(self.wiki_root, "companies/Acme/raw/financial_reports/annual/2025.pdf")
        with self.assertRaises(FilingFetchError) as ctx:
            validate_handle(
                handle,
                _request(),
                self.wiki_root,
                policy_snapshot=policy,
                expected_policy_hash=policy["policy_hash"],
            )
        self.assertIn("outside the policy snapshot", str(ctx.exception))

    def test_allowed_roots_param_cannot_widen_policy(self) -> None:
        """filing cannot enlarge policy: even with allowed_roots listing
        companies, a policy that does not allow companies rejects it."""
        policy = _policy(root_ids=("dropbox_stock",), wiki_root=self.wiki_root)
        handle = _handle(self.wiki_root, "companies/Acme/raw/financial_reports/annual/2025.pdf")
        with self.assertRaises(FilingFetchError):
            validate_handle(
                handle,
                _request(),
                self.wiki_root,
                allowed_roots=(self.wiki_root / "companies",),
                policy_snapshot=policy,
                expected_policy_hash=policy["policy_hash"],
            )

    def test_policy_hash_mismatch_fails_closed(self) -> None:
        policy = _policy(root_ids=("dropbox_stock",), wiki_root=self.wiki_root)
        handle = _handle(self.wiki_root, "Dropbox/Stock/2025.pdf")
        with self.assertRaises(FilingFetchError) as ctx:
            validate_handle(
                handle,
                _request(),
                self.wiki_root,
                policy_snapshot=policy,
                expected_policy_hash="0" * 64,
            )
        self.assertIn("policy snapshot hash mismatch", str(ctx.exception))

    # --- C5: containment / symlink negatives ---------------------------------

    def test_dotdot_escape_rejected(self) -> None:
        policy = _policy(root_ids=("dropbox_stock",), wiki_root=self.wiki_root)
        outside = self._tmp / "outside.pdf"
        outside.write_bytes(b"%PDF-1.4 zr405")
        handle = _handle(self.wiki_root, "Dropbox/Stock/2025.pdf")
        handle["canonical_path"] = str(
            self.wiki_root / "Dropbox" / "Stock" / ".." / ".." / "outside.pdf"
        )
        handle["byte_size"] = outside.stat().st_size
        handle["content_sha256"] = hashlib.sha256(b"%PDF-1.4 zr405").hexdigest()
        handle["snapshot_sha256"] = hashlib.sha256(b"%PDF-1.4 zr405").hexdigest()
        with self.assertRaises(FilingFetchError) as ctx:
            validate_handle(
                handle,
                _request(),
                self.wiki_root,
                policy_snapshot=policy,
                expected_policy_hash=policy["policy_hash"],
            )
        self.assertIn("outside the policy snapshot", str(ctx.exception))

    def test_symlink_escape_rejected(self) -> None:
        """A symlink inside the policy root pointing outside resolves
        outside and fails containment.  Skipped where symlinks cannot be
        created (Windows non-privileged)."""
        outside = self._tmp / "secret.pdf"
        outside.write_bytes(b"%PDF-1.4 zr405")
        link = self.wiki_root / "Dropbox" / "Stock" / "linked.pdf"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:  # pragma: no cover
            self.skipTest(f"cannot create symlink: {exc}")
        policy = _policy(root_ids=("dropbox_stock",), wiki_root=self.wiki_root)
        handle = _handle(self.wiki_root, "Dropbox/Stock/2025.pdf")
        handle["canonical_path"] = str(link)
        handle["byte_size"] = outside.stat().st_size
        handle["content_sha256"] = hashlib.sha256(b"%PDF-1.4 zr405").hexdigest()
        handle["snapshot_sha256"] = hashlib.sha256(b"%PDF-1.4 zr405").hexdigest()
        with self.assertRaises(FilingFetchError) as ctx:
            validate_handle(
                handle,
                _request(),
                self.wiki_root,
                policy_snapshot=policy,
                expected_policy_hash=policy["policy_hash"],
            )
        self.assertIn("outside the policy snapshot", str(ctx.exception))

    # --- C6: envelope policy_hash cross-check in the production seam ---------

    def test_envelope_policy_hash_mismatch_fails_closed(self) -> None:
        policy = _policy(root_ids=("dropbox_stock",), wiki_root=self.wiki_root)
        handle = _handle(self.wiki_root, "Dropbox/Stock/2025.pdf")
        resolution = _resolution(
            handle,
            envelope=_envelope(policy_hash="1" * 64),
            policy_export=policy,
        )
        with self.assertRaises(FilingFetchError) as ctx:
            _handle_from_resolution(resolution, _request(), self.wiki_root)
        self.assertIn("does not match the exported root policy", str(ctx.exception))

    def test_envelope_policy_hash_match_forwards_envelope(self) -> None:
        policy = _policy(root_ids=("dropbox_stock",), wiki_root=self.wiki_root)
        handle = _handle(self.wiki_root, "Dropbox/Stock/2025.pdf")
        envelope = _envelope(policy_hash=policy["policy_hash"])
        result = _handle_from_resolution(
            _resolution(handle, envelope=envelope, policy_export=policy),
            _request(),
            self.wiki_root,
        )
        self.assertEqual(result["resolution_envelope"]["policy_hash"], policy["policy_hash"])

    def test_envelope_without_policy_hash_still_forwards(self) -> None:
        """N/N-1: an envelope without policy_hash (pre-ZR-404 wiki) forwards
        when the export is available — no fabricated hash, no false
        conflict."""
        policy = _policy(root_ids=("dropbox_stock",), wiki_root=self.wiki_root)
        handle = _handle(self.wiki_root, "Dropbox/Stock/2025.pdf")
        result = _handle_from_resolution(
            _resolution(handle, envelope=_envelope(policy_hash=None), policy_export=policy),
            _request(),
            self.wiki_root,
        )
        self.assertIsNone(result["resolution_envelope"].get("policy_hash"))

    # --- C2: response without policy_export keeps the N-1 bridge ------------

    def test_response_without_policy_export_keeps_legacy_bridge(self) -> None:
        """An N-1 company-wiki response (no policy_export) keeps the legacy
        companies containment bridge — the production CURRENT triplet
        always sends policy_export, so the bridge is unreachable there."""
        handle = _handle(self.wiki_root, "companies/Acme/raw/financial_reports/annual/2025.pdf")
        result = _handle_from_resolution(_resolution(handle), _request(), self.wiki_root)
        self.assertEqual(result["canonical_path"], handle["canonical_path"])


class ResolveFilingPolicyWiringTests(unittest.TestCase):
    """End-to-end wiring: resolve_filing loads the policy export and the
    handle containment uses it (the legacy companies default is never
    reachable in production)."""

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="zr405e2e-"))
        self.wiki_root = _wiki_root(self._tmp)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_resolve_filing_passes_policy_export(self) -> None:
        """resolve_filing forwards the response-embedded policy export: the
        final handle passes containment under a dropbox-only policy with NO
        extra subprocess call (the wiki response carries policy_export)."""
        import fetch_filing

        policy = _policy(root_ids=("dropbox_stock",), wiki_root=self.wiki_root)
        handle = _handle(self.wiki_root, "Dropbox/Stock/2025.pdf")
        resolution = _resolution(
            handle,
            envelope=_envelope(policy_hash=policy["policy_hash"]),
            policy_export=policy,
        )

        calls: list[str] = []

        def _fake_run(*, command, root, action, deadline, stats):
            calls.append(action)
            if action == "identify":
                return {
                    "schema_version": "1.0",
                    "status": "resolved",
                    "reason": "uniquely_resolved",
                    "resolved": {
                        "canonical_name": "Acme",
                        "market": "US",
                        "exchange": "NYSE",
                        "ticker": "ACME",
                        "security_id": "ACME",
                        "match_basis": "exact",
                        "matched_value": "Acme",
                        "source_name": "test",
                        "source_url": "https://example.test/acme",
                        "source_record_id": "rec-1",
                        "verified": True,
                        "active": True,
                    },
                }
            if action == "resolve":
                return resolution
            raise AssertionError(f"unexpected action {action}")

        original = fetch_filing._run_company_wiki_json_retry
        fetch_filing._run_company_wiki_json_retry = _fake_run
        try:
            result = resolve_filing(
                request={
                    "schema_version": "1.2",
                    "company_query": "Acme",
                    "market": "US",
                    "document_kind": "annual_report",
                    "fiscal_year": 2025,
                    "as_of_date": "2026-08-11",
                },
                company_wiki_root=self.wiki_root,
                stats={},
            )
        finally:
            fetch_filing._run_company_wiki_json_retry = original
        self.assertEqual(calls, ["identify", "resolve"])
        self.assertEqual(result["canonical_path"], handle["canonical_path"])
        self.assertEqual(result["resolution_envelope"]["policy_hash"], policy["policy_hash"])

    def test_resolve_filing_companies_handle_rejected_under_policy(self) -> None:
        """End-to-end fail closed: a response whose policy_export does NOT
        allow the handle's root is rejected — the legacy companies default
        never applies when the response carries the policy."""
        import fetch_filing

        policy = _policy(root_ids=("dropbox_stock",), wiki_root=self.wiki_root)
        handle = _handle(self.wiki_root, "companies/Acme/raw/financial_reports/annual/2025.pdf")
        resolution = _resolution(
            handle,
            envelope=_envelope(policy_hash=policy["policy_hash"]),
            policy_export=policy,
        )

        def _fake_run(*, command, root, action, deadline, stats):
            if action == "identify":
                return {
                    "schema_version": "1.0",
                    "status": "resolved",
                    "reason": "uniquely_resolved",
                    "resolved": {
                        "canonical_name": "Acme",
                        "market": "US",
                        "exchange": "NYSE",
                        "ticker": "ACME",
                        "security_id": "ACME",
                        "match_basis": "exact",
                        "matched_value": "Acme",
                        "source_name": "test",
                        "source_url": "https://example.test/acme",
                        "source_record_id": "rec-1",
                        "verified": True,
                        "active": True,
                    },
                }
            if action == "resolve":
                return resolution
            raise AssertionError(f"unexpected action {action}")

        original = fetch_filing._run_company_wiki_json_retry
        fetch_filing._run_company_wiki_json_retry = _fake_run
        try:
            with self.assertRaises(FilingFetchError) as ctx:
                resolve_filing(
                    request={
                        "schema_version": "1.2",
                        "company_query": "Acme",
                        "market": "US",
                        "document_kind": "annual_report",
                        "fiscal_year": 2025,
                        "as_of_date": "2026-08-11",
                    },
                    company_wiki_root=self.wiki_root,
                    stats={},
                )
        finally:
            fetch_filing._run_company_wiki_json_retry = original
        self.assertIn("outside the policy snapshot", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
