"""FF-1 envelope candidates: CWP operation candidate detail through to envelopes.

All evidence here is mock/unit level (no CWP checkout, no network, no real
provider): the operation payloads are hand-built fixtures shaped like the
shared CWP producer contract.
"""

from __future__ import annotations

import io
import json

import pytest

import fetch_filing as ff
from filing_contracts import FilingFetchError
from ff_job_contracts import FFJobError, build_job_view, error_view_from_exception
from ff_v2_envelope import error_envelope
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


_IDENTITY_CANDIDATES = [
    {
        "ticker": "GOOGL",
        "canonical_name": "Alphabet Inc.",
        "market": "US",
        "exchange": "NASDAQ",
    },
    {
        "ticker": "GOOG",
        "canonical_name": "Alphabet Inc.",
        "market": "US",
        "exchange": "NASDAQ",
    },
]


class TestC2V2ErrorEnvelope:
    def test_ambiguous_code_writes_candidates_and_hint(self):
        result = error_envelope(
            "ambiguous", "company-wiki ensure ambiguous", retryable=False,
            candidates=[_candidate(1), _candidate(2)],
        )
        assert result["filing"]["candidates"] == [_candidate(1), _candidate(2)]
        assert result["filing"]["hint"] == (
            "select one candidate from filing.candidates and resubmit "
            "with disambiguation fields"
        )

    def test_identity_error_writes_identity_candidates_and_v1_hint(self):
        result = error_envelope(
            "identity_error", "company identity is not uniquely resolved: ambiguous / fuzzy",
            retryable=False, candidates=list(_IDENTITY_CANDIDATES),
        )
        assert result["filing"]["candidates"] == _IDENTITY_CANDIDATES
        assert result["filing"]["hint"] == (
            "identity is ambiguous; disambiguate by adding market/exchange "
            "or by using a specific ticker in company_query"
        )

    def test_not_found_writes_candidates_without_hint(self):
        result = error_envelope(
            "not_found", "company-wiki ensure not_found", retryable=False,
            candidates=[_candidate(1)],
        )
        assert result["filing"]["candidates"] == [_candidate(1)]
        assert "hint" not in result["filing"]

    @pytest.mark.parametrize(
        "code", ["upstream_error", "request_error", "source_blocked", "fatal", "gap"],
    )
    def test_other_codes_never_carry_candidates(self, code):
        result = error_envelope(
            code, "failed", retryable=False, candidates=[_candidate(1)],
        )
        assert "candidates" not in result["filing"]
        assert "hint" not in result["filing"]

    def test_absent_or_empty_candidates_leave_shape_unchanged(self):
        legacy = error_envelope("ambiguous", "failed", retryable=False)
        empty = error_envelope("ambiguous", "failed", retryable=False, candidates=[])
        none_value = error_envelope("ambiguous", "failed", retryable=False, candidates=None)
        assert legacy == empty == none_value
        assert set(legacy["filing"]) == {"status", "reason", "retryable"}

    @pytest.mark.parametrize(
        "unsafe",
        [
            [{"ticker": "GOOGL", "path": "hidden/original.pdf"}],
            ["not-a-dict"],
            [{"unknown_only": "junk"}],
            [{"ticker": "GOOGL"}, {"bundle": "originals.bundle"}],
        ],
    )
    def test_unsafe_candidates_are_dropped_not_leaked(self, unsafe):
        result = error_envelope(
            "identity_error", "ambiguous", retryable=False, candidates=unsafe,
        )
        assert "candidates" not in result["filing"]
        assert "hint" not in result["filing"]

    def test_unknown_keys_are_projected_out_of_identity_candidates(self):
        raw = [dict(item, credentials="api-key", collector="x") for item in _IDENTITY_CANDIDATES]
        result = error_envelope(
            "identity_error", "ambiguous", retryable=False, candidates=raw,
        )
        assert result["filing"]["candidates"] == _IDENTITY_CANDIDATES

    def test_main_v2_identity_error_carries_candidates_and_hint(self, monkeypatch, capsys):
        def boom(**kwargs):
            raise FilingFetchError(
                "company identity is not uniquely resolved: ambiguous / fuzzy",
                code="identity_error",
                candidates=list(_IDENTITY_CANDIDATES),
            )

        monkeypatch.setattr(ff, "resolve_filing", boom)
        monkeypatch.setattr(
            "sys.stdin", io.StringIO(json.dumps(_v2_cli_request())),
        )
        rc = ff.main([])
        out = json.loads(capsys.readouterr().out)
        assert rc == 2
        assert out["filing"]["candidates"] == _IDENTITY_CANDIDATES
        assert "market/exchange" in out["filing"]["hint"]

    def test_main_v2_operation_ambiguous_error_carries_candidates(self, monkeypatch, capsys):
        def boom(**kwargs):
            raise FilingFetchError(
                "company-wiki ensure ambiguous: multiple_candidates",
                code="ambiguous",
                candidates=[_candidate(1), _candidate(2)],
            )

        monkeypatch.setattr(ff, "resolve_filing", boom)
        monkeypatch.setattr(
            "sys.stdin", io.StringIO(json.dumps(_v2_cli_request())),
        )
        rc = ff.main([])
        out = json.loads(capsys.readouterr().out)
        assert rc == 2
        assert out["filing"]["candidates"] == [_candidate(1), _candidate(2)]
        assert "hint" in out["filing"]

    def test_main_v2_error_without_candidates_keeps_legacy_filing_shape(
            self, monkeypatch, capsys):
        def boom(**kwargs):
            raise FilingFetchError("company-wiki ensure not_found", code="not_found")

        monkeypatch.setattr(ff, "resolve_filing", boom)
        monkeypatch.setattr(
            "sys.stdin", io.StringIO(json.dumps(_v2_cli_request())),
        )
        rc = ff.main([])
        out = json.loads(capsys.readouterr().out)
        assert rc == 2
        assert set(out["filing"]) == {"status", "reason", "retryable"}


def _v2_cli_request() -> dict:
    return {
        "schema_version": "2.0",
        "company_query": "Fixture Co",
        "market": "HK",
        "document_kind": "semi_annual_report",
        "mode": "exact",
        "fiscal_year": 2025,
        "fiscal_period": "H1",
        "as_of_date": "2026-10-21",
        "filing_intent": "reuse_only",
    }


_LEGACY_ERROR_VIEW = {
    "code": "not_found",
    "message": "company-wiki ensure not_found",
    "owner": "filing-fetch",
    "retryable": False,
    "next_actions": ["correct_scope_and_resubmit"],
    "correlation_id": "ffjob-000000000001",
}


def _record(error):
    return {
        "command_id": "cmd-1",
        "owner_job_id": "ffjob-000000000001",
        "status": "failed",
        "status_known": True,
        "allowed_actions": [],
        "started_at": "2026-11-15T00:00:00Z",
        "updated_at": "2026-11-15T00:00:01Z",
        "cost": None,
        "cost_state": "unknown",
        "error": error,
        "recovery_capability": "durable_owner_job",
        "kind": "filing.acquire",
        "intent": "reuse_only",
        "idempotency_key": "k-1",
        "attempts": 1,
        "execution_count": 1,
        "result": None,
    }


class TestC3JobErrorView:
    def test_error_view_passes_validated_candidates_for_ambiguous(self):
        exc = FilingFetchError(
            "company-wiki ensure ambiguous: multiple_candidates",
            code="ambiguous", candidates=[_candidate(1), _candidate(2)],
        )
        view = error_view_from_exception(exc, "ffjob-000000000001")
        assert view["candidates"] == [_candidate(1), _candidate(2)]
        assert set(view) == set(_LEGACY_ERROR_VIEW) | {"candidates"}
        assert view["next_actions"] == ["resubmit_with_disambiguation"]

    def test_error_view_passes_identity_candidates_for_identity_error(self):
        exc = FilingFetchError(
            "company identity is not uniquely resolved: ambiguous / fuzzy",
            code="identity_error", candidates=list(_IDENTITY_CANDIDATES),
        )
        view = error_view_from_exception(exc, "ffjob-000000000001")
        assert view["candidates"] == _IDENTITY_CANDIDATES

    def test_error_view_drops_candidates_for_non_disambiguation_code(self):
        exc = FilingFetchError(
            "producer failed", code="upstream_error", candidates=[_candidate(1)],
        )
        view = error_view_from_exception(exc, "ffjob-000000000001")
        assert set(view) == set(_LEGACY_ERROR_VIEW)
        assert "candidates" not in view

    def test_error_view_without_candidates_keeps_legacy_six_keys(self):
        exc = FilingFetchError("company-wiki ensure not_found", code="not_found")
        view = error_view_from_exception(exc, "ffjob-000000000001")
        assert set(view) == set(_LEGACY_ERROR_VIEW)

    @pytest.mark.parametrize(
        "unsafe", [[{"ticker": "A", "path": "x.pdf"}], ["junk"], [{"nope": 1}]],
    )
    def test_error_view_drops_unsafe_candidates(self, unsafe):
        exc = FilingFetchError("ambiguous", code="ambiguous", candidates=unsafe)
        view = error_view_from_exception(exc, "ffjob-000000000001")
        assert "candidates" not in view

    def test_build_job_view_accepts_legacy_six_field_error(self):
        view = build_job_view(_record(dict(_LEGACY_ERROR_VIEW)))
        assert view["error"] == _LEGACY_ERROR_VIEW

    def test_build_job_view_accepts_seven_field_error_with_candidates(self):
        error = dict(_LEGACY_ERROR_VIEW, candidates=[_candidate(1)])
        view = build_job_view(_record(error))
        assert view["error"]["candidates"] == [_candidate(1)]

    def test_build_job_view_rejects_unknown_error_field(self):
        error = dict(_LEGACY_ERROR_VIEW, extra="nope")
        with pytest.raises(FFJobError, match="stored error shape"):
            build_job_view(_record(error))

    def test_build_job_view_rejects_physical_leak_inside_error(self):
        error = dict(_LEGACY_ERROR_VIEW, candidates=[
            dict(_candidate(1), canonical_path="hidden/original.pdf"),
        ])
        with pytest.raises(FFJobError, match="leaked a physical location"):
            build_job_view(_record(error))

    def test_build_job_view_rejects_invalid_stored_candidates(self):
        error = dict(_LEGACY_ERROR_VIEW, candidates="junk")
        with pytest.raises(FFJobError, match="stored error candidates"):
            build_job_view(_record(error))

    def test_runner_lands_failed_job_with_candidates_in_error(self, tmp_path):
        from unittest.mock import patch

        from ff_job_runner import run_job
        from ff_job_store import JobStore

        store = JobStore(tmp_path / "jobs")
        record, _created = store.create_job(
            {
                "schema_version": "ff-job/1",
                "command_id": "cmd-1",
                "kind": "filing.acquire",
                "idempotency_key": "k-1",
                "request": dict(_v2_cli_request()),
            },
            command_id="cmd-1",
        )
        with patch("fetch_filing.resolve_filing") as engine:
            engine.side_effect = FilingFetchError(
                "company-wiki ensure ambiguous: multiple_candidates",
                code="ambiguous", candidates=[_candidate(1), _candidate(2)],
            )
            final, _executed = run_job(
                store, record["owner_job_id"], config_path=None, timeout_seconds=60,
            )
        assert final["status"] == "failed"
        assert final["error"]["candidates"] == [_candidate(1), _candidate(2)]
        view = build_job_view(final)
        assert view["error"]["candidates"] == [_candidate(1), _candidate(2)]
