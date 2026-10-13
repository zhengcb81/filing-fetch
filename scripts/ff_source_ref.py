"""Pure SourceRef wire validation; no storage policy, original reads or serialization.

All filing, transcript and local-intake boundaries use this one contract.
"""

from __future__ import annotations

import re
from typing import Any

from filing_contracts import FilingFetchError

_REF_KEYS = frozenset(
    {
        "schema_version",
        "document_id",
        "source_id",
        "content_sha256",
        "byte_size",
        "mime_type",
    }
)


def _ref_shape(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _REF_KEYS:
        raise FilingFetchError("v2 SourceRef shape is invalid", code="upstream_error")
    if value.get("schema_version") != "2.0":
        raise FilingFetchError("v2 SourceRef version is unsupported", code="upstream_error")
    return value


def _ref_sha(value: dict[str, Any]) -> str:
    sha = value.get("content_sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise FilingFetchError("v2 SourceRef SHA is invalid", code="upstream_error")
    return sha


def _ref_ids(value: dict[str, Any], sha: str) -> None:
    for field, kind in (("document_id", "document"), ("source_id", "source")):
        identifier = value[field]
        prefix = f"urn:company-wiki:{kind}:sha256:"
        if identifier.startswith("urn:company-wiki:"):
            if not identifier.startswith(prefix) or identifier[len(prefix) :] != sha:
                raise FilingFetchError(
                    f"v2 SourceRef {field} does not match content SHA",
                    code="upstream_error",
                )


def _ref_size(value: dict[str, Any]) -> None:
    size = value.get("byte_size")
    if type(size) is not int or size < 0:
        raise FilingFetchError("v2 SourceRef byte size is invalid", code="upstream_error")


def validate_source_ref(value: object) -> dict[str, Any]:
    ref = _ref_shape(value)
    for field in ("document_id", "source_id", "mime_type"):
        text = ref.get(field)
        if not isinstance(text, str) or not text.strip():
            raise FilingFetchError(f"v2 SourceRef {field} is invalid", code="upstream_error")
    _ref_ids(ref, _ref_sha(ref))
    _ref_size(ref)
    return dict(ref)
