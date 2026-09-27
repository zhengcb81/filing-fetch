"""Consume company-wiki's binary SourceReader v2 transport without raw paths."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, NoReturn

from filing_contracts import FilingFetchError


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "document_id",
        "source_id",
        "content_sha256",
        "byte_size",
        "policy_sha256",
        "read_at",
    }
)


def _fail(message: str) -> NoReturn:
    raise FilingFetchError(
        message, code="upstream_error", stage="source_read", attempts=1
    )


def _json_constant(value: str) -> NoReturn:
    _fail(f"source reader receipt contains non-JSON constant: {value}")


def _parse_receipt(raw: bytes) -> dict[str, Any]:
    try:
        decoded = raw.decode("utf-8", errors="strict")
        lines = decoded.splitlines()
        if not decoded.endswith("\n") or len(lines) != 1:
            _fail("source reader receipt must be one JSON line")
        receipt = json.loads(lines[0], parse_constant=_json_constant)
    except (UnicodeError, json.JSONDecodeError):
        _fail("source reader receipt is not valid UTF-8 JSON")
    if not isinstance(receipt, dict):
        _fail("source reader receipt must be an object")
    return receipt


def _validate_receipt_shape(receipt: dict[str, Any]) -> None:
    if set(receipt) != _RECEIPT_FIELDS:
        _fail("source reader receipt fields are unsupported")
    if receipt["schema_version"] != "2.0" or receipt["status"] != "ok":
        _fail("source reader receipt status or schema is unsupported")
    if not isinstance(receipt["read_at"], str) or not receipt["read_at"].strip():
        _fail("source reader receipt read_at is invalid")


def _validate_receipt_identity(
    receipt: dict[str, Any],
    document_id: str,
    source_id: str,
    content_sha256: str,
    byte_size: int,
    policy_sha256: str,
) -> None:
    for name, expected in (
        ("document_id", document_id),
        ("source_id", source_id),
        ("content_sha256", content_sha256),
        ("byte_size", byte_size),
    ):
        if receipt[name] != expected:
            _fail(f"source reader receipt {name} mismatch")
    if receipt["policy_sha256"] != policy_sha256:
        _fail("source reader receipt policy hash mismatch")


def _validate_expected_hashes(content_sha256: str, policy_sha256: str) -> None:
    if not _SHA256.fullmatch(content_sha256) or not _SHA256.fullmatch(policy_sha256):
        _fail("source reader expected SHA-256 or policy hash is invalid")


def _validate_expected_limits(byte_size: int, timeout_seconds: float) -> None:
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) or byte_size < 0:
        _fail("source reader expected byte_size is invalid")
    if timeout_seconds <= 0 or not math.isfinite(timeout_seconds):
        _fail("source reader timeout is invalid")


def _run_binary_cli(
    command: list[str], wiki_root: Path, timeout_seconds: float, stats: dict[str, int] | None
) -> subprocess.CompletedProcess[bytes]:
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0  # type: ignore[attr-defined]
    if stats is not None:
        stats["calls"] += 1
    try:
        opened = subprocess.run(
            command,
            cwd=wiki_root,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
            shell=False,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired):
        _fail("source reader subprocess unavailable or timed out")
    if opened.returncode != 0:
        _fail("source reader refused the pinned source version")
    return opened


def _validate_opened_bytes(data: bytes, content_sha256: str, byte_size: int) -> None:
    if len(data) != byte_size:
        _fail("source reader byte_size does not match verified stdout")
    if hashlib.sha256(data).hexdigest() != content_sha256:
        _fail("source reader SHA-256 does not match verified stdout")


def read_source_version(
    *,
    wiki_root: Path,
    document_id: str,
    source_id: str,
    content_sha256: str,
    byte_size: int,
    policy_sha256: str,
    timeout_seconds: float,
    stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Open pinned source bytes and return only a locally checked v2 receipt.

    The transport's stdout is binary. Even a success receipt is unusable until
    the exact stdout length and SHA-256 have been checked here.
    """
    _validate_expected_hashes(content_sha256, policy_sha256)
    _validate_expected_limits(byte_size, timeout_seconds)
    command = [
        sys.executable,
        "-B",
        "-m",
        "company_wiki.source_catalog.source_reader_cli",
        "--config",
        str(wiki_root / "config" / "source_catalog.yaml"),
        "--document-id",
        document_id,
        "--source-id",
        source_id,
        "--content-sha256",
        content_sha256,
        "--purpose",
        "filing_reuse",
    ]
    opened = _run_binary_cli(command, wiki_root, timeout_seconds, stats)
    receipt = _parse_receipt(opened.stderr)
    _validate_receipt_shape(receipt)
    _validate_receipt_identity(
        receipt,
        document_id,
        source_id,
        content_sha256,
        byte_size,
        policy_sha256,
    )
    _validate_opened_bytes(opened.stdout, content_sha256, byte_size)
    return receipt


__all__ = ["read_source_version"]
