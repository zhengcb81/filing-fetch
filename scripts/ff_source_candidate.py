"""Pure logical candidate binding/projection shared by query and ensure.

This boundary never opens original bytes or reinterprets CWP storage policy.
The consumer's verified-open remains responsible for actual byte validation.
"""

from __future__ import annotations

from typing import Any

from filing_contracts import FilingFetchError, validate_handle_metadata
from ff_source_ref import validate_source_ref

SOURCE_CANDIDATE_FIELDS = frozenset(
    {
        "request_id",
        "document_id",
        "source_id",
        "title",
        "document_kind",
        "fiscal_year",
        "fiscal_period",
        "period_end",
        "form_type",
        "market",
        "security_id",
        "language",
        "published_date",
        "https_url",
        "snapshot_sha256",
        "content_sha256",
        "retrieved_at",
        "provider",
        "provider_document_id",
        "collector_name",
        "collector_version",
        "byte_size",
        "mime_type",
        "capture_ready",
    }
)

COMPANY_IDENTITY_FIELDS = frozenset(
    {
        "canonical_name",
        "market",
        "exchange",
        "ticker",
        "security_id",
        "match_basis",
        "matched_value",
        "source_name",
        "source_url",
        "source_record_id",
        "verified",
        "active",
    }
)

# Exact storage contract names: a business field such as growth_path is not
# a physical location. Unknown non-storage metadata is omitted by projection.
_PHYSICAL_FIELDS = frozenset(
    {
        "path",
        "paths",
        "path_ref",
        "canonical_path",
        "physical_path",
        "file_path",
        "absolute_path",
        "resolved_path",
        "storage_path",
        "document_path",
        "root",
        "roots",
        "root_id",
        "root_path",
        "root_kind",
        "physical_root",
        "company_wiki_root",
        "allowed_handle_roots",
        "location",
        "locations",
        "location_id",
        "canonical_location_id",
        "selected_location",
        "bundle",
        "source_bundle",
        "bundle_path",
        "bundle_status",
    }
)


def contains_physical_field(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower() in _PHYSICAL_FIELDS or contains_physical_field(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(contains_physical_field(child) for child in value)
    return False


def validate_source_candidate(
    candidate: object,
    source_ref: object,
    *,
    request_id: object,
    request: dict[str, Any],
    company_identity: dict[str, Any],
    context: str,
) -> dict[str, Any]:
    """Validate once, project one owned shape, and bind the known logical identity."""
    ref = validate_source_ref(source_ref)
    if not isinstance(candidate, dict) or candidate.get("source_ref") != ref:
        raise FilingFetchError(f"company-wiki {context} SourceRef mismatch", code="upstream_error")
    if contains_physical_field(candidate):
        raise FilingFetchError(
            f"company-wiki {context} leaked a physical location", code="upstream_error"
        )
    handle = {key: value for key, value in candidate.items() if key in SOURCE_CANDIDATE_FIELDS}
    handle["source_ref"] = ref
    handle["request_id"] = request_id
    validate_handle_metadata(handle, request)
    bindings = {
        "document_id": "document_id",
        "source_id": "source_id",
        "snapshot_sha256": "content_sha256",
        "byte_size": "byte_size",
        "mime_type": "mime_type",
    }
    if any(handle.get(field) != ref[ref_field] for field, ref_field in bindings.items()):
        raise FilingFetchError(
            f"company-wiki {context} candidate identity mismatch", code="upstream_error"
        )
    if handle.get("document_kind") != request.get("document_kind"):
        raise FilingFetchError(
            f"company-wiki {context} document_kind mismatch", code="upstream_error"
        )
    if (
        request.get("fiscal_year") is not None
        and handle.get("fiscal_year") != request["fiscal_year"]
    ):
        raise FilingFetchError(
            f"company-wiki {context} fiscal_year mismatch", code="upstream_error"
        )
    for field in ("market", "security_id"):
        if field in handle and handle[field] != company_identity[field]:
            raise FilingFetchError(
                f"company-wiki {context} {field} mismatch", code="upstream_error"
            )
    handle["company_identity"] = {
        key: value for key, value in company_identity.items() if key in COMPANY_IDENTITY_FIELDS
    }
    handle["prompt_injection_status"] = candidate.get("prompt_injection_status")
    handle["byte_verified"] = False
    return handle
