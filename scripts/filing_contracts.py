"""Schema contracts and validation for filing-fetch request/response/handle."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

SKILL_VERSION = "1.2.0"
FILING_REQUEST_SCHEMA_VERSION = "1.1"
FILING_RESPONSE_SCHEMA_VERSION = "1.1"
GAP_RECEIPT_SCHEMA_VERSION = "1.0"
DOWNLOAD_AUTHORIZATION_SCHEMA_VERSION = "1.0"

COMPANY_WIKI_CONFIG_SCHEMA_VERSION = "1.0"
COMPANY_WIKI_IDENTITY_SCHEMA_VERSION = "1.0"

CONFIG_TOKEN_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

SUPPORTED_COMPANY_WIKI_CONTRACTS = frozenset({
    "resolve_schema_version": "1.0",
    "ensure_schema_version": "1.0",
    "identity_schema_version": COMPANY_WIKI_IDENTITY_SCHEMA_VERSION,
    "config_schema_version": COMPANY_WIKI_CONFIG_SCHEMA_VERSION,
})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FilingFetchError(RuntimeError):
    """Raised when a capture-ready filing cannot be resolved or downloaded."""

    def __init__(self, message: str, code: str = "fatal") -> None:
        super().__init__(message)
        self.code = code
        self.retryable = code in {"upstream_error", "worker_paused", "catalog_locked"}


# ---------------------------------------------------------------------------
# Request schema (1.1)
# ---------------------------------------------------------------------------

_REQUEST_SCHEMA_1_1_FIELDS = frozenset({
    "schema_version",
    "company_query",
    "market",
    "exchange",
    "document_kind",
    "fiscal_year",
    "as_of_date",
    "form_type",
    "fiscal_period",
    "language",
    "provider",
    "provider_document_id",
})


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise FilingFetchError(f"{field_name} must be non-empty trimmed text", code="request_error")
    return value


def validate_request(request: dict[str, Any]) -> None:
    """Validate a filing-fetch request against the 1.1 schema."""
    version = request.get("schema_version")
    if version != FILING_REQUEST_SCHEMA_VERSION:
        raise FilingFetchError(
            f"unsupported request schema_version: {version} (expected {FILING_REQUEST_SCHEMA_VERSION})",
            code="request_error",
        )
    unknown = set(request) - _REQUEST_SCHEMA_1_1_FIELDS
    if unknown:
        raise FilingFetchError(
            f"unknown request field(s): {', '.join(sorted(unknown))}",
            code="request_error",
        )
    _required_text(request.get("document_kind"), "document_kind")
    _required_text(request.get("as_of_date"), "as_of_date")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", request["as_of_date"]):
        raise FilingFetchError("as_of_date must use YYYY-MM-DD format", code="request_error")
    fiscal_year = request.get("fiscal_year")
    if fiscal_year is not None:
        if isinstance(fiscal_year, bool) or not isinstance(fiscal_year, int):
            raise FilingFetchError("fiscal_year must be an integer", code="request_error")
        if fiscal_year < 1900:
            raise FilingFetchError(f"fiscal_year is out of range: {fiscal_year}", code="request_error")


# ---------------------------------------------------------------------------
# Handle validation
# ---------------------------------------------------------------------------

_HANDLE_REQUIRED_FIELDS = frozenset({
    "request_id", "document_id", "source_id", "title", "published_date",
    "https_url", "canonical_path", "snapshot_sha256", "retrieved_at",
    "provider", "provider_document_id", "collector_name", "collector_version",
    "byte_size", "mime_type", "capture_ready",
})


def validate_handle(handle: dict[str, Any], request: dict[str, Any], wiki_root: Path) -> None:
    """Deep-validate a capture-ready handle returned by company-wiki."""
    missing = _HANDLE_REQUIRED_FIELDS - set(handle)
    if missing:
        raise FilingFetchError(f"handle missing required field(s): {', '.join(sorted(missing))}", code="upstream_error")
    if handle.get("capture_ready") is not True:
        raise FilingFetchError("handle capture_ready is not True", code="upstream_error")
    canonical = Path(handle["canonical_path"])
    if not canonical.is_absolute():
        canonical = wiki_root / canonical
    try:
        canonical.resolve(strict=False)
    except (OSError, ValueError) as exc:
        raise FilingFetchError(f"handle canonical_path is invalid: {canonical}", code="upstream_error") from exc
    companies = (wiki_root / "companies").resolve()
    resolved = canonical.resolve()
    if not str(resolved).startswith(str(companies) + os.sep):
        raise FilingFetchError(
            "handle canonical_path is outside the company-wiki companies/ subtree",
            code="upstream_error",
        )
    digest = handle.get("snapshot_sha256", "")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise FilingFetchError("handle snapshot_sha256 is not a valid lowercase SHA-256", code="upstream_error")
    url = handle.get("https_url", "")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise FilingFetchError("handle https_url must use HTTPS", code="upstream_error")
    if not canonical.is_file():
        raise FilingFetchError("handle canonical_path is not a regular file", code="upstream_error")
    size = handle.get("byte_size")
    if isinstance(size, bool) or not isinstance(size, int) or size != canonical.stat().st_size:
        raise FilingFetchError("handle byte_size does not match the canonical file", code="upstream_error")
    content = canonical.read_bytes()
    content_digest = hashlib.sha256(content).hexdigest()
    if content_digest != digest:
        raise FilingFetchError("handle snapshot_sha256 does not match the canonical file bytes", code="upstream_error")
    published = handle.get("published_date", "")
    if not isinstance(published, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published):
        raise FilingFetchError("handle published_date must use YYYY-MM-DD format", code="upstream_error")
    as_of = request.get("as_of_date", "")
    if isinstance(as_of, str) and as_of and published > as_of:
        raise FilingFetchError("handle published_date is after the request as_of_date", code="upstream_error")
