"""Binary, pathless company-wiki SourceReader transport contract."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from filing_contracts import FilingFetchError
from source_reader_transport import read_source_version


BODY = b"%PDF-1.4\nraw\x00\xff\n"
SHA = hashlib.sha256(BODY).hexdigest()
POLICY = "a" * 64
DOCUMENT = "urn:company-wiki:document:sha256:" + "b" * 64
SOURCE = "urn:company-wiki:source:sha256:" + SHA


def _receipt(**overrides: object) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": "2.0",
        "status": "ok",
        "document_id": DOCUMENT,
        "source_id": SOURCE,
        "content_sha256": SHA,
        "byte_size": len(BODY),
        "policy_sha256": POLICY,
        "read_at": "2026-09-27T00:00:00+00:00",
    }
    receipt.update(overrides)
    return receipt


def _call(root: Path) -> dict[str, object]:
    return read_source_version(
        wiki_root=root,
        document_id=DOCUMENT,
        source_id=SOURCE,
        content_sha256=SHA,
        byte_size=len(BODY),
        policy_sha256=POLICY,
        timeout_seconds=5,
    )


def test_binary_read_requires_verified_bytes_and_pathless_receipt(tmp_path, monkeypatch):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command, 0, BODY, (json.dumps(_receipt()) + "\n").encode("utf-8")
        )

    monkeypatch.setattr("source_reader_transport.subprocess.run", fake_run)
    receipt = _call(tmp_path)
    assert receipt == _receipt()
    assert captured["kwargs"]["cwd"] == tmp_path
    assert captured["kwargs"].get("text") is not True
    assert captured["kwargs"]["stdout"] == subprocess.PIPE
    assert captured["kwargs"]["stderr"] == subprocess.PIPE
    command = captured["command"]
    assert "company_wiki.source_catalog.source_reader_cli" in command
    assert command[command.index("--document-id") + 1] == DOCUMENT
    assert command[command.index("--source-id") + 1] == SOURCE
    assert command[command.index("--content-sha256") + 1] == SHA
    assert "--path" not in command
    assert not any("path" in key or "location" in key or "root" in key for key in receipt)


@pytest.mark.parametrize(
    ("returncode", "body", "stderr", "message"),
    [
        (2, BODY, b'{"schema_version":"2.0","status":"blocked","reason":"no_reusable_root_location"}\n', "refused"),
        (0, BODY, b"", "receipt"),
        (0, BODY, b"{}\n{}\n", "receipt"),
        (0, BODY[:-1] + b"X", None, "SHA-256"),
        (0, BODY, None, "policy"),
    ],
)
def test_binary_read_fails_closed(
    tmp_path, monkeypatch, returncode, body, stderr, message
):
    if stderr is None:
        receipt = (
            _receipt(policy_sha256="c" * 64)
            if message == "policy"
            else _receipt()
        )
        stderr = (json.dumps(receipt) + "\n").encode("utf-8")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, returncode, body, stderr)

    monkeypatch.setattr("source_reader_transport.subprocess.run", fake_run)
    with pytest.raises(FilingFetchError, match=message) as error:
        _call(tmp_path)
    assert error.value.code == "upstream_error"
    assert error.value.stage == "source_read"


@pytest.mark.parametrize(
    "changed",
    [
        {"document_id": "other"},
        {"source_id": "other"},
        {"content_sha256": "c" * 64},
        {"byte_size": len(BODY) + 1},
        {"schema_version": "1.0"},
        {"status": "blocked"},
    ],
)
def test_binary_read_rejects_receipt_identity_mismatch(tmp_path, monkeypatch, changed):
    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0, BODY, (json.dumps(_receipt(**changed)) + "\n").encode("utf-8")
        )

    monkeypatch.setattr("source_reader_transport.subprocess.run", fake_run)
    with pytest.raises(FilingFetchError) as error:
        _call(tmp_path)
    assert error.value.code == "upstream_error"


def test_binary_read_timeout_is_structured_upstream_error(tmp_path, monkeypatch):
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 5)

    monkeypatch.setattr("source_reader_transport.subprocess.run", fake_run)
    with pytest.raises(FilingFetchError) as error:
        _call(tmp_path)
    assert error.value.code == "upstream_error"
    assert error.value.stage == "source_read"
