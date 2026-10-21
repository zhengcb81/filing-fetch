"""Closed failure DTO recognition at the CWP bounded process boundary.

This validates the published request fingerprint, not company identity or raw
bytes. An exception without a request ID remains bound to its one child call;
only the small producer error shape (no matches or candidates) is admissible.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from filing_contracts import FilingFetchError
from ff_provider_cause import source_condition
from ff_source_candidate import contains_physical_field

_REQUEST_FIELDS = (
    "entity",
    "market",
    "security_id",
    "document_kind",
    "form_type",
    "fiscal_year",
    "fiscal_period",
    "language",
    "provider",
    "provider_document_id",
    "as_of_date",
    "mode",
)
_QUERY_FAILURE_FIELDS = {"schema_version", "status", "reason", "matches", "candidates"}


def source_request_id(request: dict[str, Any]) -> str:
    """The source-request/1 public canonical JSON fingerprint, without IO."""
    identity: dict[str, Any] = {key: request.get(key) for key in _REQUEST_FIELDS}
    identity["schema_version"] = "1.0"
    for key in _REQUEST_FIELDS:
        if isinstance(identity[key], str):
            identity[key] = identity[key].strip() or None
    for key in ("document_kind", "provider", "mode"):
        if identity[key] is not None:
            identity[key] = identity[key].lower()
    if identity["market"] is not None:
        identity["market"] = identity["market"].upper()
    data = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "urn:company-wiki:source-request:sha256:" + hashlib.sha256(data).hexdigest()


def invalid_result(action: str, returncode: int | None = None) -> FilingFetchError:
    return FilingFetchError(
        "company-wiki business failure contract is invalid",
        code="upstream_error",
        stage=action,
        producer_exit_code=returncode,
        upstream_cause=source_condition(action, "invalid_producer_schema"),
    )


def decode_failure(stdout: bytes, *, action: str, returncode: int) -> dict[str, Any]:
    try:
        result = json.loads(stdout.decode("utf-8", errors="strict"))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise invalid_result(action, returncode) from exc
    if not isinstance(result, dict) or returncode not in (1, 2):
        raise invalid_result(action, returncode)
    return result


def validate_query_failure(
    payload: dict[str, Any], request: dict[str, Any], *, returncode: int
) -> None:
    keys = set(payload)
    if (
        returncode not in (1, 2)
        or not _QUERY_FAILURE_FIELDS <= keys
        or not keys
        <= _QUERY_FAILURE_FIELDS
        | {"request_id", "source_read_policy_sha256", "excluded_candidates"}
        or payload.get("schema_version") != "2.0"
        or not isinstance(payload.get("status"), str)
        or payload["status"] not in {"blocked", "unavailable", "not_found", "ambiguous"}
        or payload.get("matches") != []
        or payload.get("candidates") != []
        or contains_physical_field(payload)
        or not isinstance(payload.get("reason"), str)
        or ("request_id" in payload and payload["request_id"] != source_request_id(request))
    ):
        raise invalid_result("query", returncode)
    # Unknown reasons remain a bounded named 'unknown'; never copy arbitrary
    # producer text. Nonzero exception shapes cannot carry excluded bodies.
    if payload.get("excluded_candidates") not in (None, []):
        raise invalid_result("query", returncode)
