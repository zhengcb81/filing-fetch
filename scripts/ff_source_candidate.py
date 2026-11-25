"""Pure logical candidate binding/projection shared by query and ensure.

This boundary never opens original bytes or reinterprets CWP storage policy.
The consumer's verified-open remains responsible for actual byte validation.
"""

from __future__ import annotations

from typing import Any

from ff_errors import FilingFetchError
from filing_contracts import validate_handle_metadata
from ff_pathless_payload import contains_physical_field
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
        "issuer_link_id",
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
        "issuer_link_id",
        "identity_scope",
        "verified",
        "active",
    }
)

# FF-1: the candidate-detail field set the CWP producer lane emits on
# ambiguous/not_found operations (shared consumer contract; fetch_filing
# enforces it strictly at operation intake, projections reuse it here).
CANDIDATE_DETAIL_FIELDS = frozenset(
    {
        "document_id",
        "title",
        "document_kind",
        "provider",
        "provider_document_id",
        "form_type",
        "fiscal_year",
        "fiscal_period",
        "language",
        "content_sha256",
        "byte_size",
        "publication_status",
        "exclusion_reason",
    }
)
CANDIDATE_DETAIL_LIMIT = 5
_ERROR_CANDIDATE_FIELDS = CANDIDATE_DETAIL_FIELDS | COMPANY_IDENTITY_FIELDS
# The error codes whose responses may carry candidate details (shared by the
# v2 error envelope and the job error view so the two faces cannot drift).
ERROR_CANDIDATE_CODES = frozenset({"ambiguous", "identity_error", "not_found"})


def projected_error_candidates(value: object) -> list[dict[str, Any]] | None:
    """Safety projection for candidate details riding error envelopes.

    Accepts either producer shape — operation candidate detail (closed field
    set, already validated strictly at operation intake) or company-identity
    candidates from an ambiguous resolve — and returns only closed, pathless
    copies. Any non-dict item, physical-location key, or item with no
    recognized field removes the whole block (fail closed against leaks,
    never a partial guess). Returns None for an absent/empty/unsafe list.
    """
    if not isinstance(value, list) or not value:
        return None
    projected: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or contains_physical_field(item):
            return None
        cleaned = {key: child for key, child in item.items() if key in _ERROR_CANDIDATE_FIELDS}
        if not cleaned:
            return None
        projected.append(cleaned)
    return projected


def project_source_candidate_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    """Project known source fields and omit unknown capture diagnostics."""
    return {
        key: value for key, value in candidate.items()
        if key in SOURCE_CANDIDATE_FIELDS and (key != "capture_ready" or type(value) is bool)
    }


def validate_source_candidate(
    candidate: object,
    source_ref: object,
    *,
    request_id: object,
    request: dict[str, Any],
    company_identity: dict[str, Any],
    source_identity: dict[str, Any] | None = None,
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
    handle = project_source_candidate_fields(candidate)
    handle["source_ref"] = ref
    handle["request_id"] = request_id
    # Unknown publication is metadata, not availability authority. Keep it
    # explicit for the consumer's verified-open; never invent it from retrieval.
    validate_handle_metadata(handle, request, allow_unknown_publication_date=True)
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
    for field in ("form_type", "fiscal_period", "provider", "provider_document_id"):
        expected = request.get(field)
        if expected is not None and handle.get(field) != expected:
            raise FilingFetchError(
                f"company-wiki {context} {field} mismatch", code="upstream_error"
            )
    source_identity = source_identity or company_identity
    expected_market = request.get("source_market") or source_identity.get("market")
    expected_security_id = source_identity.get("security_id")
    if source_identity.get("market") != expected_market:
        raise FilingFetchError(
            f"company-wiki {context} source identity market mismatch", code="upstream_error"
        )
    for field, expected in (("market", expected_market), ("security_id", expected_security_id)):
        if expected is not None and handle.get(field) != expected:
            raise FilingFetchError(
                f"company-wiki {context} source {field} mismatch", code="upstream_error"
            )
    expected_link_id = source_identity.get("issuer_link_id")
    if expected_link_id is not None and handle.get("issuer_link_id") != expected_link_id:
        raise FilingFetchError(
            f"company-wiki {context} source issuer_link_id mismatch", code="upstream_error"
        )
    handle["company_identity"] = {
        key: value for key, value in company_identity.items() if key in COMPANY_IDENTITY_FIELDS
    }
    if (
        source_identity.get("market") != company_identity.get("market")
        or source_identity.get("security_id") != company_identity.get("security_id")
        or source_identity.get("issuer_link_id") != company_identity.get("issuer_link_id")
    ):
        handle["source_identity"] = {
            key: value for key, value in source_identity.items() if key in COMPANY_IDENTITY_FIELDS
        }
    handle["prompt_injection_status"] = candidate.get("prompt_injection_status")
    handle["byte_verified"] = False
    return handle
