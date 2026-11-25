from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

MATRIX = Path(__file__).resolve().parents[1] / "tools" / "offline_contract_matrix"
if str(MATRIX) not in sys.path:
    sys.path.insert(0, str(MATRIX))

import cwp_readback_probe as proof  # noqa: E402


def test_matrix_readback_and_worker_do_not_import_owner_internals():
    for name in ("cwp_readback_probe.py", "et_transcript_proxy.py", "source_proofs.py", "cli_main.py"):
        source = (MATRIX / name).read_text(encoding="utf-8")
        imports = [
            module
            for node in ast.walk(ast.parse(source))
            for module in (
                [alias.name for alias in node.names] if isinstance(node, ast.Import)
                else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            )
        ]
        assert not any(module.startswith(("company_wiki", "sqlite3", "tests.")) for module in imports)
        assert "tests.test_" not in source  # ET worker launcher is an import string.


@pytest.mark.parametrize(
    ("lookup_change", "open_change", "expected"),
    [
        ({}, {}, "confirmed"),
        ({"status": "not_found", "matches": []}, {}, "not_found"),
        ({"status": "unavailable", "matches": []}, {}, "probe_error"),
        ({"status": "found", "matches": []}, {}, "probe_error"),
        ({"schema_version": "unrecognized"}, {}, "probe_error"),
        ({}, {"document_id": "other"}, "probe_error"),
        ({}, {"status": "unavailable"}, "probe_error"),
        ({}, {"stdout": b"another original"}, "probe_error"),
    ],
)
def test_w20_probe_uses_one_deadline_for_public_query_and_public_read(
    monkeypatch, tmp_path, lookup_change, open_change, expected,
):
    data = b"unicode manuscript \xe4\xb8\xad"
    digest = hashlib.sha256(data).hexdigest()
    ref = {
        "document_id": "document", "source_id": "source", "content_sha256": digest,
        "byte_size": len(data), "mime_type": "text/plain",
    }
    lookup = {"schema_version": "2.0", "status": "found", "matches": [{**ref, "schema_version": "2.0"}], **lookup_change}
    opened = {"schema_version": "2.1", "status": "ok", **ref, **open_change}
    content = opened.pop("stdout", data)
    calls = []

    def process(command, *, env, cwd, deadline, input=None):
        calls.append((command, deadline, input))
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 0, json.dumps(lookup).encode(), b"")
        return subprocess.CompletedProcess(command, 0, content, json.dumps(opened).encode())

    monkeypatch.setattr(proof, "run_process", process)
    result = proof.probe_catalog(
        wiki_root=tmp_path, identity_request={"provider": "fmp"},
        content_sha=digest, cwp_src=str(tmp_path),
    )

    assert result["state"] == expected
    assert "company_wiki.source_catalog.source_query_cli" in calls[0][0]
    assert json.loads(calls[0][2]) == {
        "schema_version": "company-wiki-transcript-import-lookup-request/1",
        "source_request": {"provider": "fmp"},
    }
    if expected == "confirmed":
        assert result["ref"] == ref
    if len(calls) == 2:
        assert "company_wiki.source_catalog.source_reader_cli" in calls[1][0]
        assert "--exact-pair" in calls[1][0]
        assert calls[0][1] is calls[1][1]



def test_fresh_proof_uses_public_export_and_original_language_open(monkeypatch, tmp_path):
    import source_proofs

    text = "Analyst Q&A.\n原语言内容。"
    original = json.dumps([{"content": text}], ensure_ascii=False).encode()
    ref = {
        "document_id": "exact-document", "source_id": "exact-source",
        "content_sha256": hashlib.sha256(original).hexdigest(),
        "byte_size": len(original), "mime_type": "application/json",
    }
    unrelated = {**ref, "document_id": "different-document", "source_id": "other-source"}
    manifest = {**ref, "document_kind": "investor_call_transcript", "provider": "fmp"}
    exports = []
    opens = []

    def export(wiki_root, refs, *, env, deadline):
        exports.append(list(refs))
        return [manifest.copy()]

    def read(wiki_root, ref, *, env, deadline):
        opens.append(ref)
        return original

    monkeypatch.setattr(source_proofs, "export_sources", export)
    monkeypatch.setattr(source_proofs, "read_source", read)
    result = source_proofs.prove_sources(
        tmp_path, [ref, ref, unrelated], env={}, deadline=proof.Deadline(),
    )

    assert exports == [[ref, unrelated]]
    assert opens == [ref]
    assert result["schema_version"] == "w06-fresh-source-proofs/2"
    verified = result["proofs"]["exact-document"]
    assert verified["verified"] is True
    assert verified["reference"] == ref
    assert verified["manifest"] == manifest
    assert verified["original_language_content_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert "physical_originals" not in verified
    assert result["proofs"]["different-document"]["verified"] is False


@pytest.mark.parametrize(("market", "security_id"), [("CN", "300750"), ("HK", "00700"), ("US", "AAPL")])
def test_discovery_fixture_supplies_the_requested_source_identity(market, security_id):
    from fixture_provider_adapter import _discover

    outcome = _discover({
        "market": market, "security_id": security_id,
        "entity": "Synthetic Issuer", "document_kind": "annual_report",
    })
    candidate, = outcome["candidates"]
    assert candidate["market"] == market
    assert candidate["security_id"] == security_id


def test_public_failure_type_is_shared_without_importing_filing_or_candidate_contracts():
    root = MATRIX.parents[1]
    program = """
import sys
sys.path.insert(0, sys.argv[1])
import ff_errors
assert "filing_contracts" not in sys.modules
assert "ff_source_candidate" not in sys.modules
from filing_contracts import FilingFetchError
from fetch_filing import FilingFetchError as cli_error
assert FilingFetchError is cli_error is ff_errors.FilingFetchError
error = FilingFetchError("owner is busy", code="catalog_busy", stage="resolve", attempts=2)
assert (error.code, error.retryable, error.stage, error.attempts) == ("catalog_busy", True, "resolve", 2)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", program, str(root / "scripts")],
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_mid_import_signal_binds_provider_original_and_rejects_a_bad_digest(tmp_path):
    import base64
    from w20_fault_cases import import_receipt_digest

    canonical = b"spoken words"
    provider_original = json.dumps([{"content": canonical.decode()}]).encode()
    provider_sha = hashlib.sha256(provider_original).hexdigest()
    receipt = tmp_path / "owned-result.json"
    value = {
        "status": "fetched",
        "provider_payload_base64": base64.b64encode(provider_original).decode(),
        "provider_payload_sha256": provider_sha,
        "canonical_content_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    assert import_receipt_digest(receipt) is None
    receipt.write_text(json.dumps(value), encoding="utf-8")
    assert import_receipt_digest(receipt) == provider_sha
    value["provider_payload_sha256"] = value["canonical_content_sha256"]
    receipt.write_text(json.dumps(value), encoding="utf-8")
    assert import_receipt_digest(receipt) is None
