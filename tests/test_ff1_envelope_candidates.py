"""FF-1 envelope candidates: CWP operation candidate detail through to envelopes.

All evidence here is mock/unit level (no CWP checkout, no network, no real
provider): the operation payloads are hand-built fixtures shaped like the
shared CWP producer contract.
"""

from __future__ import annotations

import pytest

import fetch_filing as ff
from filing_contracts import FilingFetchError
from test_source_ref_v2_db_query import _operation_v2


def _candidate(n: int = 1, **overrides) -> dict:
    sha = f"{n:064x}"
    item = {
        "document_id": f"urn:company-wiki:document:sha256:{sha}",
        "title": f"Fixture Co 2025 Semi-Annual Report {n}",
        "document_kind": "semi_annual_report",
        "provider": "fmp",
        "provider_document_id": f"0001032-{n:04d}",
        "form_type": "6-K",
        "fiscal_year": 2025,
        "fiscal_period": "H1",
        "language": "en",
        "content_sha256": sha,
        "byte_size": 1024 * n,
        "publication_status": "known",
        "exclusion_reason": "published_date_unknown",
    }
    item.update(overrides)
    return item


def _operation_with_candidates(status: str = "ambiguous", count: int = 2,
                               reason: str | None = "multiple_candidates") -> dict:
    payload = _operation_v2(status=status, outcome=None)
    payload["candidates"] = [_candidate(n) for n in range(1, count + 1)]
    if reason is not None:
        payload["reason"] = reason
    return payload


def _request() -> dict:
    return {
        "schema_version": "2.0",
        "company_query": "Fixture Co",
        "market": "HK",
        "document_kind": "semi_annual_report",
        "fiscal_year": 2025,
        "fiscal_period": "H1",
        "as_of_date": "2026-10-21",
        "filing_intent": "reuse_only",
    }


class TestC1OperationContract:
    def test_ambiguous_operation_mounts_validated_candidates(self):
        payload = _operation_with_candidates(status="ambiguous", reason="multiple_candidates")
        with pytest.raises(FilingFetchError) as caught:
            ff._pathless_operation_handle(
                payload, operation="ensure", request=_request(),
                company_identity={}, stats={"calls": 0, "downloads": 0},
            )
        assert caught.value.code == "ambiguous"
        assert caught.value.candidates == payload["candidates"]
        assert caught.value.candidates[0] is not payload["candidates"][0]
        assert "multiple_candidates" in str(caught.value)

    def test_not_found_operation_mounts_validated_candidates(self):
        payload = _operation_with_candidates(
            status="not_found", reason="published_date_unknown")
        with pytest.raises(FilingFetchError) as caught:
            ff._pathless_operation_handle(
                payload, operation="ensure", request=_request(),
                company_identity={}, stats={"calls": 0, "downloads": 0},
            )
        assert caught.value.code == "not_found"
        assert caught.value.candidates == payload["candidates"]

    def test_legacy_payload_without_new_fields_is_unchanged(self):
        payload = _operation_v2(status="not_found", outcome=None)
        assert ff._validated_operation(payload, "ensure") == payload
        with pytest.raises(FilingFetchError) as caught:
            ff._pathless_operation_handle(
                payload, operation="ensure", request=_request(),
                company_identity={}, stats={"calls": 0, "downloads": 0},
            )
        assert caught.value.code == "not_found"
        assert caught.value.candidates is None
        assert str(caught.value) == "company-wiki ensure not_found"

    @pytest.mark.parametrize(
        "status", ["completed", "gap", "unavailable", "blocked"],
    )
    def test_candidates_on_non_ambiguous_status_fail_closed(self, status):
        payload = _operation_with_candidates(status=status, reason=None)
        if status == "completed":
            payload["source_ref"] = _operation_v2(status="completed")["source_ref"]
        with pytest.raises(FilingFetchError) as caught:
            ff._validated_operation(payload, "ensure")
        assert caught.value.code == "upstream_error"
        assert caught.value.upstream_cause["code"] == "invalid_producer_schema"

    def test_reason_on_completed_fails_closed(self):
        payload = _operation_v2(status="completed")
        payload["reason"] = "multiple_candidates"
        with pytest.raises(FilingFetchError) as caught:
            ff._validated_operation(payload, "ensure")
        assert caught.value.code == "upstream_error"

    @pytest.mark.parametrize(
        "bad_reason", ["Not A Token", "multiple candidates", "", "9starts", "x" * 81],
    )
    def test_bad_reason_token_fails_closed(self, bad_reason):
        payload = _operation_with_candidates(status="not_found", reason=bad_reason)
        with pytest.raises(FilingFetchError) as caught:
            ff._validated_operation(payload, "ensure")
        assert caught.value.code == "upstream_error"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"exclusion_reason": "published_date_mismatch"},  # outside the closed set
            {"publication_status": "pending"},
            {"publication_status": None},
            {"content_sha256": "not-hex"},
            {"content_sha256": None},
            {"byte_size": "1024"},
            {"byte_size": -1},
            {"fiscal_year": "2025"},
            {"fiscal_year": True},
            {"document_id": "hidden/original.pdf"},
            {"document_id": 12345},
            {"title": ""},
            {"title": None},
            {"document_kind": None},
            {"provider": 7},
            {"form_type": " spaced "},
        ],
    )
    def test_bad_candidate_shapes_fail_closed(self, overrides):
        payload = _operation_with_candidates(status="ambiguous", reason=None)
        payload["candidates"][0].update(overrides)
        with pytest.raises(FilingFetchError) as caught:
            ff._validated_operation(payload, "ensure")
        assert caught.value.code == "upstream_error"
        assert caught.value.upstream_cause["code"] == "invalid_producer_schema"

    @pytest.mark.parametrize(
        "mutation",
        [
            lambda item: item.update({"path": "hidden/original.pdf"}),
            lambda item: item.update({"extra": "not part of contract"}),
            lambda item: item.pop("exclusion_reason"),
            lambda item: item.update({"publication_status": "future", "extra": 1}),
        ],
    )
    def test_extra_or_missing_candidate_fields_fail_closed(self, mutation):
        payload = _operation_with_candidates(status="ambiguous", reason=None)
        mutation(payload["candidates"][0])
        with pytest.raises(FilingFetchError) as caught:
            ff._validated_operation(payload, "ensure")
        assert caught.value.code == "upstream_error"

    def test_more_than_five_candidates_fail_closed(self):
        payload = _operation_with_candidates(status="ambiguous", count=6, reason=None)
        with pytest.raises(FilingFetchError) as caught:
            ff._validated_operation(payload, "ensure")
        assert caught.value.code == "upstream_error"

    def test_five_candidates_are_accepted(self):
        payload = _operation_with_candidates(status="ambiguous", count=5, reason=None)
        validated = ff._validated_operation(payload, "ensure")
        assert len(validated["candidates"]) == 5

    def test_candidates_not_a_list_fails_closed(self):
        payload = _operation_with_candidates(status="ambiguous", reason=None)
        payload["candidates"] = {"document_id": "urn:x"}
        with pytest.raises(FilingFetchError) as caught:
            ff._validated_operation(payload, "ensure")
        assert caught.value.code == "upstream_error"

    def test_nullable_candidate_fields_accept_null(self):
        payload = _operation_with_candidates(status="ambiguous", reason=None)
        payload["candidates"][0].update({
            "provider": None, "provider_document_id": None, "form_type": None,
            "fiscal_year": None, "fiscal_period": None, "language": None,
        })
        validated = ff._validated_operation(payload, "ensure")
        assert validated["candidates"][0]["provider"] is None
        assert validated["candidates"][0]["fiscal_year"] is None
