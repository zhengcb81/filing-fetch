"""Offline consumer boundary for frozen earnings-transcript-result/2 producer JSON.

This validates the ET wire result before an eventual CWP importer call. It
does not turn ET's unverified publication cutoff into verified provenance.
"""

from __future__ import annotations

import base64
import binascii
from datetime import date
import hashlib
import re
from typing import Any, NoReturn
from urllib.parse import parse_qs, urlsplit


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FMP_SUCCESS_KEYS = frozenset({
    "schema_version", "request_id", "status", "provider", "ticker",
    "exchange", "fiscal_period", "as_of_date", "title", "source_url",
    "provider_document_id", "call_date", "publication_date",
    "as_of_cutoff_verified", "extraction_version",
    "provider_payload_sha256", "canonical_content_sha256",
    "content_bytes", "provider_payload_encoding",
    "provider_payload_base64", "provider_payload_mime_type",
    "effective_url", "http_status", "retrieved_at",
    "adapter_name", "adapter_version",
})
_FAILURE_KEYS = frozenset({
    "schema_version", "request_id", "status", "provider", "error_code",
})
_FAILURES = {
    ("unavailable", "provider_credentials_missing"): "provider_unavailable",
    ("unavailable", "provider_entitlement_required"): "provider_unavailable",
    ("unavailable", "provider_credentials_rejected"): "provider_unavailable",
    ("unavailable", "provider_credentials_file_unavailable"): "provider_unavailable",
    ("unavailable", "provider_credentials_file_empty"): "provider_unavailable",
    ("unavailable", "provider_credentials_file_invalid"): "provider_unavailable",
    ("unsupported", "unsupported_market"): "provider_unavailable",
    ("unsupported", "unsupported_exchange"): "provider_unavailable",
    ("provider_error", "provider_credentials_leaked"): "provider_unavailable",
    ("provenance_rejected", "provider_identity_or_host"): "provenance_rejected",
    ("invalid_request", "request_schema"): "request_error",
}


class ETContractError(ValueError):
    """ET /2 wire result is not safe to forward to the CWP importer."""


def _fail(reason: str) -> NoReturn:
    raise ETContractError(reason)


def _date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        _fail(field)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        _fail(field)
    if parsed.isoformat() != value:
        _fail(field)
    return parsed


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(field)
    return value


def _hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(field)
    return value


def _url(value: Any, request: dict[str, Any], field: str) -> None:
    parsed = urlsplit(_text(value, field))
    if (
        parsed.scheme != "https"
        or parsed.hostname != "financialmodelingprep.com"
        or parsed.path != "/stable/earning-call-transcript"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        _fail(field)
    query = parse_qs(parsed.query, strict_parsing=True)
    expected = {
        "symbol": [request["ticker"]],
        "year": [str(request["fiscal_year"])],
        "quarter": [str(request["fiscal_quarter"])],
    }
    if query != expected:
        _fail(field)


def _check_header(result: dict[str, Any], request: dict[str, Any]) -> None:
    if result.get("schema_version") != "earnings-transcript-result/2":
        _fail("schema_version")
    if result.get("request_id") != request.get("request_id"):
        _fail("request_id")
    if request.get("schema_version") != "earnings-transcript-request/1":
        _fail("request_schema")
    _text(request.get("request_id"), "request_id")


def _failure_result(
    result: dict[str, Any], request: dict[str, Any],
) -> dict[str, Any]:
    if frozenset(result) != _FAILURE_KEYS:
        _fail("failure_keys")
    status = result.get("status")
    error_code = result.get("error_code")
    if not isinstance(status, str) or not isinstance(error_code, str):
        _fail("failure_status")
    pair = (status, error_code)
    if pair not in _FAILURES:
        _fail("failure_status")
    if status != "invalid_request" and result.get("provider") != request.get("provider"):
        _fail("provider")
    return {"status": _FAILURES[pair], "reason": error_code}


def _period(request: dict[str, Any]) -> str:
    year = request.get("fiscal_year")
    quarter = request.get("fiscal_quarter")
    if type(year) is not int or type(quarter) is not int:
        _fail("request_period")
    if quarter not in {1, 2, 3, 4}:
        _fail("request_period")
    return f"{year}-Q{quarter}"


def _success_identity(result: dict[str, Any], request: dict[str, Any]) -> str:
    if frozenset(result) != _FMP_SUCCESS_KEYS:
        _fail("fmp_success_keys")
    if result.get("provider") != "fmp" or request.get("provider") != "fmp":
        _fail("provider")
    if result.get("ticker") != request.get("ticker"):
        _fail("ticker")
    if str(result.get("exchange", "")).lower() != str(request.get("exchange", "")).lower():
        _fail("exchange")
    fiscal_period = _period(request)
    if result.get("fiscal_period") != fiscal_period:
        _fail("fiscal_period")
    if result.get("as_of_date") != request.get("as_of_date"):
        _fail("as_of_date")
    return fiscal_period


def _success_dates(
    result: dict[str, Any], request: dict[str, Any],
) -> tuple[str | None, bool]:
    as_of_date = _date(request.get("as_of_date"), "as_of_date")
    if _date(result.get("call_date"), "call_date") > as_of_date:
        _fail("call_date")
    publication = result.get("publication_date")
    if publication is not None and _date(publication, "publication_date") > as_of_date:
        _fail("publication_date")
    verified = result.get("as_of_cutoff_verified")
    if type(verified) is not bool or (verified and publication is None):
        _fail("as_of_cutoff_verified")
    return publication, verified


def _success_text_fields(result: dict[str, Any], request: dict[str, Any]) -> None:
    for field in (
        "title", "provider_document_id", "extraction_version",
        "adapter_name", "adapter_version", "retrieved_at",
    ):
        _text(result.get(field), field)
    _url(result.get("source_url"), request, "source_url")
    _url(result.get("effective_url"), request, "effective_url")
    if result.get("provider_payload_mime_type") != "application/json":
        _fail("provider_payload_mime_type")
    if result.get("provider_payload_encoding") != "base64":
        _fail("provider_payload_encoding")


def _success_sizes(result: dict[str, Any], request: dict[str, Any]) -> None:
    if type(result.get("http_status")) is not int or result["http_status"] != 200:
        _fail("http_status")
    size = result.get("content_bytes")
    if type(size) is not int or size <= 0:
        _fail("content_bytes")
    maximum = request.get("max_body_bytes")
    if type(maximum) is not int or size > maximum:
        _fail("content_bytes")


def _success_digests(result: dict[str, Any]) -> tuple[str, str]:
    payload_digest = _hash(result.get("provider_payload_sha256"), "provider_payload_sha256")
    canonical_digest = _hash(
        result.get("canonical_content_sha256"), "canonical_content_sha256",
    )
    encoded = _text(result.get("provider_payload_base64"), "provider_payload_base64")
    try:
        original = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        _fail("provider_payload_base64")
    if hashlib.sha256(original).hexdigest() != payload_digest:
        _fail("provider_payload_sha256")
    return payload_digest, canonical_digest


def normalize_et_v2_result(
    result: dict[str, Any], request: dict[str, Any],
) -> dict[str, Any]:
    """Classify one exact ET /2 response; preserve raw producer bytes for CWP."""
    if not isinstance(result, dict) or not isinstance(request, dict):
        _fail("shape")
    _check_header(result, request)
    if result.get("status") != "fetched":
        return _failure_result(result, request)
    fiscal_period = _success_identity(result, request)
    publication, verified = _success_dates(result, request)
    _success_text_fields(result, request)
    _success_sizes(result, request)
    payload_digest, canonical_digest = _success_digests(result)
    return {
        "status": "fetched",
        "producer_result": result,
        "fiscal_period": fiscal_period,
        "publication_date": publication,
        "as_of_cutoff_verified": verified,
        "provider_payload_sha256": payload_digest,
        "canonical_content_sha256": canonical_digest,
    }
