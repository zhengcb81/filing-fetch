"""DU11: pure reading of the public local-query wires (reuse vs acquisition).

Every case is a wire shape the frozen company-wiki CLI can actually emit; the
module under test performs no I/O, so each case is a pure decision.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from transcript_reuse_selection import (
    GAP_PUBLICATION_AFTER_AS_OF,
    GAP_PUBLICATION_INVALID,
    GAP_PUBLICATION_UNKNOWN,
    LocalQueryContractError,
    excluded_candidates,
    select_local_outcome,
)

AS_OF = "2026-09-30"


def ref(*, raw: bytes = b"transcript bytes", sha: str | None = None) -> dict[str, Any]:
    digest = sha or hashlib.sha256(raw).hexdigest()
    return {
        "schema_version": "2.0",
        "document_id": f"urn:company-wiki:document:sha256:{digest}",
        "source_id": f"urn:company-wiki:source:sha256:{digest}",
        "content_sha256": digest,
        "byte_size": max(len(raw), 1),
        "mime_type": "text/plain",
    }


def qualification(
    status: str,
    *,
    local_bytes_status: str = "not_checked",
    as_of_date: str | None = AS_OF,
) -> dict[str, Any]:
    eligible = None if status == "unknown" else status == "eligible"
    return {
        "publication_status": status,
        "as_of_date": as_of_date,
        "local_bytes_status": local_bytes_status,
        "historical_date_eligible": eligible,
        "historical_reuse_eligible": eligible,
        "schema_version": "source-qualification/1",
    }


def excluded(status: str, **kwargs: Any) -> dict[str, Any]:
    return {"source_ref": ref(raw=status.encode()), "qualification": qualification(status, **kwargs)}


def result(payload: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "2.0", "request_id": "urn:request", **payload}


def candidate(source_ref: dict[str, Any], published_date: str | None) -> dict[str, Any]:
    return {"source_ref": source_ref, "published_date": published_date}


def test_one_qualified_candidate_is_a_match_with_its_published_date() -> None:
    source_ref = ref()
    selection = select_local_outcome(
        result({
            "status": "found",
            "reason": "one_local_match",
            "candidates": [candidate(source_ref, "2026-07-22")],
        })
    )
    assert selection.kind == "match"
    assert selection.source_ref is not None
    assert selection.source_ref.to_dict() == source_ref
    assert selection.published_date == "2026-07-22"
    assert selection.exclusions() == {}


def test_found_candidate_without_publication_date_is_unknown_not_reusable() -> None:
    selection = select_local_outcome(
        result({
            "status": "found",
            "reason": "one_local_match",
            "candidates": [candidate(ref(), None)],
        })
    )
    assert selection.kind == "unknown_publication"
    assert selection.published_date is None


def test_explicit_unknown_publication_status_keeps_the_observation() -> None:
    selection = select_local_outcome(
        result({
            "status": "unknown_publication",
            "reason": "publication_date_unknown",
            "candidates": [candidate(ref(), None)],
        })
    )
    assert selection.kind == "unknown_publication"


@pytest.mark.parametrize("count", [0, 2])
def test_a_found_status_must_carry_exactly_one_candidate(count: int) -> None:
    with pytest.raises(LocalQueryContractError):
        select_local_outcome(
            result({
                "status": "found",
                "reason": "one_local_match",
                "candidates": [candidate(ref(), "2026-07-22")] * count,
            })
        )


def test_no_candidate_and_no_exclusion_is_a_true_miss() -> None:
    selection = select_local_outcome(
        result({"status": "not_found", "reason": "no_local_match", "candidates": []})
    )
    assert selection.kind == "missing"


def test_one_unknown_excluded_candidate_keeps_ref_and_qualification() -> None:
    item = excluded("unknown")
    selection = select_local_outcome(
        result({"status": "not_found", "reason": "no_local_match", "excluded_candidates": [item]})
    )
    assert selection.kind == "unknown_publication"
    assert selection.source_ref is not None
    assert selection.source_ref.to_dict() == item["source_ref"]
    assert selection.qualification == item["qualification"]
    diagnostics = selection.exclusions()
    assert diagnostics["excluded_publication_statuses"] == {"unknown": 1}
    assert diagnostics["excluded_candidates"] == [item]


def test_several_unknown_exclusions_are_a_named_unknown_publication_gap() -> None:
    selection = select_local_outcome(
        result({
            "status": "not_found",
            "reason": "no_local_match",
            "excluded_candidates": [excluded("unknown"), excluded("unknown")],
        })
    )
    assert selection.kind == "gap"
    assert selection.reason == GAP_PUBLICATION_UNKNOWN
    assert len(selection.exclusions()["excluded_candidates"]) == 2


@pytest.mark.parametrize("other", ["after_as_of", "invalid"])
def test_unknown_mixed_with_a_restricted_observation_stays_the_unknown_gap(other: str) -> None:
    selection = select_local_outcome(
        result({
            "status": "not_found",
            "reason": "no_local_match",
            "excluded_candidates": [excluded("unknown"), excluded(other)],
        })
    )
    assert selection.kind == "gap"
    assert selection.reason == GAP_PUBLICATION_UNKNOWN


@pytest.mark.parametrize(
    "exclusions,reason",
    [
        (["after_as_of"], GAP_PUBLICATION_AFTER_AS_OF),
        (["invalid"], GAP_PUBLICATION_INVALID),
        (["after_as_of", "invalid"], GAP_PUBLICATION_INVALID),
    ],
)
def test_restricted_only_exclusions_become_their_own_named_gap(
    exclusions: list[str], reason: str
) -> None:
    selection = select_local_outcome(
        result({
            "status": "not_found",
            "reason": "no_local_match",
            "excluded_candidates": [excluded(status) for status in exclusions],
        })
    )
    assert selection.kind == "gap"
    assert selection.reason == reason
    assert "excluded_candidates" in selection.exclusions()


@pytest.mark.parametrize(
    "status,reason",
    [
        ("ambiguous", "multiple_local_matches"),
        ("blocked", "source_not_active"),
        ("unavailable", "catalog_unavailable"),
        ("not_indexed", "source_version_not_indexed"),
    ],
)
def test_non_reuse_statuses_are_reported_not_converted_to_a_miss(status: str, reason: str) -> None:
    selection = select_local_outcome(result({"status": status, "reason": reason}))
    assert selection.kind == "status"
    assert selection.provider_status == status
    assert selection.reason == reason


def test_non_reuse_status_falls_back_to_the_documented_reason() -> None:
    selection = select_local_outcome(result({"status": "blocked", "reason": ""}))
    assert selection.kind == "status"
    assert selection.reason == "transcript_lookup_unavailable"


@pytest.mark.parametrize("status", ["", "bogus", "FOUND", None, 7])
def test_an_unknown_status_is_a_contract_error(status: object) -> None:
    with pytest.raises(LocalQueryContractError):
        select_local_outcome(result({"status": status, "reason": "no_local_match"}))


@pytest.mark.parametrize("version", ["1.0", "3.0", None, 2.0])
def test_an_unsupported_result_schema_is_a_contract_error(version: object) -> None:
    with pytest.raises(LocalQueryContractError):
        select_local_outcome({"schema_version": version, "status": "not_found"})


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "not_found", "reason": "no_local_match", "excluded_candidates": "x"},
        {"status": "not_found", "reason": "no_local_match", "excluded_candidates": [["x"]]},
        {"status": "not_found", "reason": "no_local_match", "excluded_candidates": [{}]},
        {
            "status": "not_found",
            "reason": "no_local_match",
            "excluded_candidates": [{"source_ref": ref(), "qualification": []}],
        },
        {
            "status": "not_found",
            "reason": "no_local_match",
            "excluded_candidates": [
                {"source_ref": ref(), "qualification": {**qualification("unknown"), "extra": 1}}
            ],
        },
        {
            "status": "not_found",
            "reason": "no_local_match",
            "excluded_candidates": [
                {"source_ref": ref(), "qualification": {**qualification("unknown"), "schema_version": "9"}}
            ],
        },
        {
            "status": "not_found",
            "reason": "no_local_match",
            "excluded_candidates": [
                {"source_ref": ref(), "qualification": {**qualification("unknown"), "publication_status": "?"}}
            ],
        },
        {
            "status": "not_found",
            "reason": "no_local_match",
            "excluded_candidates": [
                {
                    "source_ref": ref(),
                    "qualification": {**qualification("unknown"), "local_bytes_status": "trusted"},
                }
            ],
        },
        {
            "status": "not_found",
            "reason": "no_local_match",
            "excluded_candidates": [
                {"source_ref": ref(), "qualification": {**qualification("unknown"), "historical_date_eligible": "yes"}}
            ],
        },
        {
            "status": "not_found",
            "reason": "no_local_match",
            "excluded_candidates": [
                {"source_ref": ref(), "qualification": {**qualification("unknown"), "as_of_date": 20260930}}
            ],
        },
    ],
)
def test_malformed_exclusions_are_a_contract_error(payload: dict[str, Any]) -> None:
    with pytest.raises(LocalQueryContractError):
        select_local_outcome(result(payload))


@pytest.mark.parametrize(
    "bad_ref",
    [
        {},
        {**ref(), "extra": 1},
        {key: value for key, value in ref().items() if key != "mime_type"},
        {**ref(), "schema_version": "1.0"},
        {**ref(), "content_sha256": "abc"},
        {**ref(), "byte_size": -1},
        {**ref(), "byte_size": True},
        {**ref(), "document_id": ""},
        {**ref(), "mime_type": 7},
    ],
)
def test_malformed_source_refs_are_a_contract_error(bad_ref: dict[str, Any]) -> None:
    with pytest.raises(LocalQueryContractError):
        select_local_outcome(
            result({"status": "found", "reason": "one_local_match",
                    "candidates": [candidate(bad_ref, "2026-07-22")]})
        )


def test_excluded_candidates_can_be_read_directly() -> None:
    items = excluded_candidates(result({
        "status": "not_found",
        "reason": "no_local_match",
        "excluded_candidates": [excluded("after_as_of", local_bytes_status="verified")],
    }))
    assert len(items) == 1
    assert items[0].publication_status == "after_as_of"
    assert items[0].local_bytes_status == "verified"
    assert excluded_candidates(result({"status": "not_found"})) == ()
