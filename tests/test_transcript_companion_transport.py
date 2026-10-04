from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any

import pytest

from transcript_companion import resolve_companion_transcript
import transcript_tool_transport
from transcript_tool_transport import EarningsTranscriptsTransport

_FIXTURE = Path(__file__).parent / "fixtures" / "et_s0b" / "fmp_v2.fetched.json"
_FIL_REF = {
    "schema_version": "2.0",
    "document_id": "urn:company-wiki:document:sha256:" + "a" * 64,
    "source_id": "urn:company-wiki:source:sha256:" + "a" * 64,
    "content_sha256": "a" * 64,
    "byte_size": 100,
    "mime_type": "application/pdf",
}


def _request() -> dict[str, Any]:
    return {
        "as_of_date": "2026-09-30",
        "companion_transcript": {
            "intent": "fetch_if_missing",
            "fiscal_year": 2026,
            "fiscal_quarter": 3,
            "provider": "fmp",
            "acquisition_limits": {
                "max_bytes": 1_000_000,
                "timeout_seconds": 10,
                "max_cost_usd": "1.00",
            },
        },
    }


def _filing() -> dict[str, Any]:
    return {
        "source_ref": _FIL_REF,
        "company_identity": {
            "canonical_name": "Microsoft Corporation",
            "market": "US",
            "security_id": "MSFT",
            "ticker": "MSFT",
            "exchange": "NASDAQ",
            "verified": True,
            "active": True,
        },
    }


def _completed(command: list[str], *, stdout: bytes = b"", stderr: bytes = b""):
    return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=stderr)


def test_fmp_tool_result_is_imported_and_verified_through_cwp(tmp_path, monkeypatch) -> None:
    wiki_root = tmp_path / "company-wiki"
    (wiki_root / "config").mkdir(parents=True)
    (wiki_root / "config" / "source_catalog.yaml").write_text("fixture", encoding="utf-8")
    tool = tmp_path / "transcript_tool.py"
    tool.write_text("# fixture path; process is injected", encoding="utf-8")
    producer = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    original = base64.b64decode(producer["provider_payload_base64"], validate=True)
    digest = producer["provider_payload_sha256"]
    ref = {
        "schema_version": "2.0",
        "document_id": f"urn:company-wiki:document:sha256:{digest}",
        "source_id": f"urn:company-wiki:source:sha256:{digest}",
        "content_sha256": digest,
        "byte_size": len(original),
        "mime_type": "application/json",
    }
    request_id = "urn:company-wiki:source-request:sha256:" + "c" * 64
    calls: list[tuple[list[str], bytes]] = []

    def fake_run(command, *, input, **kwargs):
        calls.append((list(command), input))
        joined = " ".join(command)
        if "source_query_cli" in joined:
            payload = {
                "schema_version": "2.0",
                "status": "not_found",
                "reason": "no_local_match",
                "request_id": request_id,
                "matches": [],
                "candidates": [],
                "source_read_policy_sha256": "d" * 64,
            }
            return _completed(list(command), stdout=json.dumps(payload).encode())
        if str(tool) in command:
            et_request = json.loads(input.decode("utf-8"))
            assert et_request["download_authorized"] is True
            assert et_request["request_id"] == request_id
            assert et_request["provider"] == "fmp"
            assert et_request["fiscal_year"] == 2026
            assert et_request["fiscal_quarter"] == 3
            assert "api_key" not in et_request
            result = dict(producer, request_id=et_request["request_id"])
            return _completed(list(command), stdout=json.dumps(result).encode())
        if "transcript_import_cli" in joined:
            envelope = json.loads(input.decode("utf-8"))
            assert envelope["schema_version"] == "company-wiki-transcript-import-request/2"
            assert "request_id" not in envelope["source_request"]
            assert envelope["source_request"]["allow_download"] is True
            assert envelope["candidate"]["filing_date"] is None
            assert envelope["candidate"]["language"] is None
            assert envelope["candidate"]["document_kind"] == "investor_call_transcript"
            result = {
                "schema_version": "company-wiki-transcript-import-response/3",
                "status": "imported",
                "canonical_status": "imported_new",
                "source_id": ref["source_id"],
                "content_sha256": digest,
                "provider_payload_sha256": digest,
                "source_ref": ref,
            }
            return _completed(list(command), stdout=json.dumps(result).encode())
        if "source_reader_cli" in joined:
            receipt = {
                "schema_version": "2.1",
                "status": "ok",
                "document_id": ref["document_id"],
                "source_id": ref["source_id"],
                "content_sha256": digest,
                "byte_size": len(original),
            }
            return _completed(
                list(command),
                stdout=original,
                stderr=json.dumps(receipt).encode(),
            )
        raise AssertionError(f"unexpected subprocess: {joined}")

    monkeypatch.setattr("transcript_tool_transport.subprocess.run", fake_run)
    transport = EarningsTranscriptsTransport(
        wiki_root=wiki_root,
        transcript_tool=tool,
        deadline=time.monotonic() + 30,
    )

    result = resolve_companion_transcript(
        request=_request(),
        filing_handle=_filing(),
        transport=transport,
    )

    assert result["status"] == "downloaded", result
    assert result["source_ref"] == ref
    assert result["publication_date"] is None
    assert result["as_of_cutoff_verified"] is False
    assert result["provider_calls"] == 1
    assert [
        name
        for command, _ in calls
        for name in ("source_query_cli", "transcript_import_cli", "source_reader_cli")
        if name in " ".join(command)
    ] == [
        "source_query_cli",
        "transcript_import_cli",
        "source_reader_cli",
    ]
    et_command = next(command for command, _ in calls if str(tool) in command)
    assert "--include-source-payload" in et_command
    assert "--allow-download" not in et_command


def test_real_cwp_cli_import_and_unknown_publication_replay(tmp_path, monkeypatch) -> None:
    source_root = Path(
        os.environ.get(
            "COMPANY_WIKI_SOURCE_ROOT", str(Path.home() / "Projects" / "company-wiki" / "src")
        )
    )
    if not source_root.is_dir():
        pytest.skip("company-wiki source checkout is not available for cross-project E2E")
    monkeypatch.setenv("PYTHONPATH", str(source_root))
    wiki_root = tmp_path / "company-wiki"
    (wiki_root / "companies").mkdir(parents=True)
    config = wiki_root / "config"
    config.mkdir()
    (config / "source_catalog.yaml").write_text(
        "schema_version: '1.0'\n"
        "catalog_dir: .source_catalog\n"
        "roots:\n"
        "  - root_id: company_raw\n"
        "    path: companies\n"
        "    kind: company_raw\n"
        "    priority: 10\n"
        "    adapter_id: company_raw_v1\n"
        "    read_only: false\n",
        encoding="utf-8",
    )
    tool = tmp_path / "transcript_tool.py"
    tool.write_text(
        "import json, os, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "assert request['provider'] == 'fmp' and request['download_authorized'] is True\n"
        "assert request['fiscal_year'] == 2026 and request['fiscal_quarter'] == 3\n"
        "assert '--include-source-payload' in sys.argv\n"
        "assert '--allow-download' not in sys.argv\n"
        "with open(os.environ['ET_CALL_LOG'], 'a', encoding='utf-8') as stream: stream.write('call\\n')\n"
        "with open(os.environ['ET_FIXTURE_PATH'], encoding='utf-8') as stream: result = json.load(stream)\n"
        "result['request_id'] = request['request_id']\n"
        "print(json.dumps(result, separators=(',', ':')))\n",
        encoding="utf-8",
    )
    call_log = tmp_path / "et-calls.log"
    monkeypatch.setenv("ET_CALL_LOG", str(call_log))
    monkeypatch.setenv("ET_FIXTURE_PATH", str(_FIXTURE))
    bootstrap = subprocess.run(
        [
            sys.executable,
            "-m",
            "company_wiki.source_catalog.cli",
            "--config",
            str(config / "source_catalog.yaml"),
            "scan",
            "--root-id",
            "company_raw",
        ],
        cwd=wiki_root,
        env=dict(os.environ),
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert bootstrap.returncode == 0, bootstrap.stderr.decode("utf-8", errors="replace")
    filing = _filing()
    request = _request()
    first_transport = EarningsTranscriptsTransport(
        wiki_root=wiki_root,
        transcript_tool=tool,
        deadline=time.monotonic() + 60,
    )
    first = resolve_companion_transcript(
        request=request,
        filing_handle=filing,
        transport=first_transport,
    )
    assert first["status"] == "downloaded", first
    assert first["publication_date"] is None
    assert first["as_of_cutoff_verified"] is False
    assert first["provider_calls"] == 1
    original = base64.b64decode(
        json.loads(_FIXTURE.read_text(encoding="utf-8"))["provider_payload_base64"],
        validate=True,
    )
    originals = [
        path
        for path in (wiki_root / "companies").rglob("*")
        if path.is_file() and not path.name.endswith(".source.json")
    ]
    assert len(originals) == 1
    assert originals[0].read_bytes() == original
    assert str(wiki_root) not in json.dumps(first)

    second_transport = EarningsTranscriptsTransport(
        wiki_root=wiki_root,
        transcript_tool=tool,
        deadline=time.monotonic() + 60,
    )
    second = resolve_companion_transcript(
        request=request,
        filing_handle=filing,
        transport=second_transport,
    )
    assert second["status"] == "unknown_publication", second
    assert second["source_ref"] == first["source_ref"]
    assert second["as_of_cutoff_verified"] is False
    assert second["provider_calls"] == 0
    assert call_log.read_text(encoding="utf-8").splitlines() == ["call"]
    originals_after = [
        path
        for path in (wiki_root / "companies").rglob("*")
        if path.is_file() and not path.name.endswith(".source.json")
    ]
    assert originals_after == originals


def test_unknown_publication_lookup_suppresses_second_provider_call(tmp_path, monkeypatch) -> None:
    wiki_root = tmp_path / "company-wiki"
    (wiki_root / "config").mkdir(parents=True)
    (wiki_root / "config" / "source_catalog.yaml").write_text("fixture", encoding="utf-8")
    tool = tmp_path / "transcript_tool.py"
    tool.write_text("# fixture path; process is injected", encoding="utf-8")
    raw = b"unknown publication raw"
    digest = hashlib.sha256(raw).hexdigest()
    ref = {
        "schema_version": "2.0",
        "document_id": f"urn:company-wiki:document:sha256:{digest}",
        "source_id": f"urn:company-wiki:source:sha256:{digest}",
        "content_sha256": digest,
        "byte_size": len(raw),
        "mime_type": "application/json",
    }
    calls: list[list[str]] = []

    def fake_run(command, *, input=None, **kwargs):
        calls.append(list(command))
        joined = " ".join(command)
        if "source_reader_cli" in joined:
            receipt = {
                "status": "ok",
                "document_id": ref["document_id"],
                "source_id": ref["source_id"],
                "content_sha256": digest,
                "byte_size": len(raw),
            }
            return _completed(list(command), stdout=raw, stderr=json.dumps(receipt).encode())
        payload = {
            "schema_version": "2.0",
            "status": "unknown_publication",
            "reason": "publication_date_unknown",
            "request_id": "urn:company-wiki:source-request:sha256:" + "c" * 64,
            "matches": [ref],
            "candidates": [
                {
                    "source_ref": ref,
                    "published_date": None,
                    "document_kind": "investor_call_transcript",
                    "fiscal_year": 2026,
                    "fiscal_period": "Q3",
                    "provider": "fmp",
                    "market": "US",
                    "security_id": "MSFT",
                }
            ],
            "source_read_policy_sha256": "d" * 64,
        }
        return _completed(list(command), stdout=json.dumps(payload).encode())

    monkeypatch.setattr("transcript_tool_transport.subprocess.run", fake_run)
    transport = EarningsTranscriptsTransport(
        wiki_root=wiki_root,
        transcript_tool=tool,
        deadline=time.monotonic() + 30,
    )

    result = resolve_companion_transcript(
        request=_request(),
        filing_handle=_filing(),
        transport=transport,
    )

    assert result["status"] == "unknown_publication", result
    assert result["source_ref"] == ref
    assert result["as_of_cutoff_verified"] is False
    assert result["provider_calls"] == 0
    assert len(calls) == 2
    assert "source_query_cli" in " ".join(calls[0])
    assert "source_reader_cli" in " ".join(calls[1])

def test_creationflags_handles_a_missing_windows_constant(monkeypatch) -> None:
    monkeypatch.setattr(transcript_tool_transport, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(transcript_tool_transport, "subprocess", SimpleNamespace())

    assert EarningsTranscriptsTransport._creationflags() == 0
