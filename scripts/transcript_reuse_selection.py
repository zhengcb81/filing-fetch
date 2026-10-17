"""Pure selection between an existing local transcript and provider acquisition.

This module interprets only the *public* company-wiki wires:

* the ``2.0`` local source-query result (``status``/``reason``/``candidates``/
  ``excluded_candidates``), and
* one ``source-qualification/1`` observation per excluded candidate.

It performs no I/O, owns no storage and caches nothing: bytes still have to be
verified by the public source reader before anything is reused.  The decision
below is only "is there exactly one qualified local source, is there local
evidence that a source exists but is not as-of usable, or is there truly no
candidate" — never a second identity or provenance database.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from typing import Any

RESULT_SCHEMA_VERSION = "2.0"
QUALIFICATION_SCHEMA_VERSION = "source-qualification/1"

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

#: Statuses the public exact local query may report.
QUERY_STATUSES = frozenset(
    {
        "found",
        "not_found",
        "unknown_publication",
        "ambiguous",
        "blocked",
        "unavailable",
        "not_indexed",
    }
)
#: Statuses that carry a usable local observation and must never become a download.
_NON_REUSE_STATUSES = frozenset({"ambiguous", "blocked", "unavailable", "not_indexed"})

PUBLICATION_STATUSES = frozenset(
    {"unknown", "invalid", "known", "eligible", "after_as_of"}
)
LOCAL_BYTES_STATUSES = frozenset({"not_checked", "verified", "unavailable"})

_REF_FIELDS = {
    "schema_version": str,
    "document_id": str,
    "source_id": str,
    "content_sha256": str,
    "byte_size": int,
    "mime_type": str,
}
_QUALIFICATION_FIELDS = {
    "publication_status": str,
    "as_of_date": (str, type(None)),
    "local_bytes_status": str,
    "historical_date_eligible": (bool, type(None)),
    "historical_reuse_eligible": (bool, type(None)),
    "schema_version": str,
}
_EXCLUDED_FIELDS = frozenset({"source_ref", "qualification"})

#: Named reasons for "local evidence exists but is not as-of reusable".
GAP_PUBLICATION_UNKNOWN = "publication_date_unknown"
GAP_PUBLICATION_INVALID = "publication_date_invalid"
GAP_PUBLICATION_AFTER_AS_OF = "publication_after_as_of"


class LocalQueryContractError(ValueError):
    """The public local-query result cannot be interpreted faithfully."""


@dataclass(frozen=True)
class SourceRefObservation:
    """One pathless ``SourceRef`` exactly as the public wire reported it."""

    document_id: str
    source_id: str
    content_sha256: str
    byte_size: int
    mime_type: str
    schema_version: str = RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "document_id": self.document_id,
            "source_id": self.source_id,
            "content_sha256": self.content_sha256,
            "byte_size": self.byte_size,
            "mime_type": self.mime_type,
        }


@dataclass(frozen=True)
class ExcludedCandidate:
    """A local observation that exists but is not a qualified as-of match."""

    source_ref: SourceRefObservation
    publication_status: str
    as_of_date: str | None
    local_bytes_status: str
    historical_date_eligible: bool | None
    historical_reuse_eligible: bool | None

    def qualification(self) -> dict[str, Any]:
        return {
            "publication_status": self.publication_status,
            "as_of_date": self.as_of_date,
            "local_bytes_status": self.local_bytes_status,
            "historical_date_eligible": self.historical_date_eligible,
            "historical_reuse_eligible": self.historical_reuse_eligible,
            "schema_version": QUALIFICATION_SCHEMA_VERSION,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_ref": self.source_ref.to_dict(),
            "qualification": self.qualification(),
        }


@dataclass(frozen=True)
class Selection:
    """One faithful reading of a local query result.

    ``kind`` is ``match`` (one qualified source, bytes still unverified),
    ``unknown_publication`` (one local observation whose publication date is
    unknown), ``gap`` (local evidence that cannot be reused as-of),
    ``missing`` (no candidate at all) or ``status`` (a named non-reuse status).
    """

    kind: str
    source_ref: SourceRefObservation | None = None
    published_date: str | None = None
    qualification: dict[str, Any] | None = None
    provider_status: str | None = None
    reason: str | None = None
    excluded: tuple[ExcludedCandidate, ...] = field(default=())

    def exclusions(self) -> dict[str, Any]:
        """Compact, pathless duplicate-suppression diagnostics."""
        if not self.excluded:
            return {}
        counts: dict[str, int] = {}
        for item in self.excluded:
            counts[item.publication_status] = counts.get(item.publication_status, 0) + 1
        return {
            "excluded_candidates": [item.to_dict() for item in self.excluded],
            "excluded_publication_statuses": counts,
        }


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LocalQueryContractError(f"{label} is not an object")
    return value


def _require_list(value: object, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise LocalQueryContractError(f"{label} is not a list")
    return value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise LocalQueryContractError(f"{label} is not non-empty text")
    return value


def _observed_ref(value: object) -> SourceRefObservation:
    ref = _require_mapping(value, "source_ref")
    if set(ref) != set(_REF_FIELDS):
        raise LocalQueryContractError("source_ref fields differ from the 2.0 contract")
    for name, expected in _REF_FIELDS.items():
        item = ref[name]
        if expected is int:
            if type(item) is not int or item < 0:
                raise LocalQueryContractError("source_ref byte_size is not a byte count")
        elif not isinstance(item, str):
            raise LocalQueryContractError("source_ref field is not text")
    if ref["schema_version"] != RESULT_SCHEMA_VERSION:
        raise LocalQueryContractError("source_ref schema is unsupported")
    for name in ("document_id", "source_id", "content_sha256", "mime_type"):
        _require_text(ref[name], f"source_ref.{name}")
    if not _SHA256.match(ref["content_sha256"]):
        raise LocalQueryContractError("source_ref content_sha256 is not a lowercase SHA-256")
    return SourceRefObservation(
        document_id=ref["document_id"],
        source_id=ref["source_id"],
        content_sha256=ref["content_sha256"],
        byte_size=ref["byte_size"],
        mime_type=ref["mime_type"],
        schema_version=ref["schema_version"],
    )


def _excluded_candidate(value: object) -> ExcludedCandidate:
    item = _require_mapping(value, "excluded candidate")
    if set(item) != _EXCLUDED_FIELDS:
        raise LocalQueryContractError("excluded candidate fields differ from the contract")
    qualification = _require_mapping(item["qualification"], "excluded qualification")
    if set(qualification) != set(_QUALIFICATION_FIELDS):
        raise LocalQueryContractError("excluded qualification fields differ from the contract")
    for name, expected in _QUALIFICATION_FIELDS.items():
        entry = qualification[name]
        if not isinstance(entry, expected):
            raise LocalQueryContractError(f"excluded qualification {name} has the wrong type")
    if qualification["schema_version"] != QUALIFICATION_SCHEMA_VERSION:
        raise LocalQueryContractError("excluded qualification schema is unsupported")
    status = qualification["publication_status"]
    if status not in PUBLICATION_STATUSES:
        raise LocalQueryContractError("excluded publication_status is not a known value")
    if qualification["local_bytes_status"] not in LOCAL_BYTES_STATUSES:
        raise LocalQueryContractError("excluded local_bytes_status is not a known value")
    return ExcludedCandidate(
        source_ref=_observed_ref(item["source_ref"]),
        publication_status=status,
        as_of_date=qualification["as_of_date"],
        local_bytes_status=qualification["local_bytes_status"],
        historical_date_eligible=qualification["historical_date_eligible"],
        historical_reuse_eligible=qualification["historical_reuse_eligible"],
    )


def excluded_candidates(result: Mapping[str, Any]) -> tuple[ExcludedCandidate, ...]:
    """Parse the optional ``excluded_candidates`` observation list."""
    value = result.get("excluded_candidates")
    if value is None:
        return ()
    return tuple(_excluded_candidate(item) for item in _require_list(value, "excluded_candidates"))


def _gap_reason(excluded: tuple[ExcludedCandidate, ...]) -> str:
    statuses = {item.publication_status for item in excluded}
    if "unknown" in statuses:
        # Several or mixed unknown observations cannot honestly be expressed as
        # one reusable record: keep the documented unknown-publication gap.
        return GAP_PUBLICATION_UNKNOWN
    if "invalid" in statuses:
        return GAP_PUBLICATION_INVALID
    return GAP_PUBLICATION_AFTER_AS_OF


def select_local_outcome(result: object) -> Selection:
    """Read one public exact local-query result without inventing a source."""
    payload = _require_mapping(result, "source query result")
    if payload.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise LocalQueryContractError("source query schema is unsupported")
    status = payload.get("status")
    if not isinstance(status, str) or status not in QUERY_STATUSES:
        raise LocalQueryContractError("source query status is not a known value")
    reason = payload.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise LocalQueryContractError("source query reason is not text")

    if status in {"found", "unknown_publication"}:
        candidates = _require_list(payload.get("candidates"), "candidates")
        if len(candidates) != 1:
            raise LocalQueryContractError("exact local query did not return one candidate")
        candidate = _require_mapping(candidates[0], "candidate")
        published = candidate.get("published_date")
        if published is not None and not isinstance(published, str):
            raise LocalQueryContractError("candidate published_date is not text")
        unknown = status == "unknown_publication" or published is None
        return Selection(
            "unknown_publication" if unknown else "match",
            source_ref=_observed_ref(candidate.get("source_ref")),
            published_date=published,
        )
    if status in _NON_REUSE_STATUSES:
        return Selection(
            "status", provider_status=status, reason=reason or "transcript_lookup_unavailable"
        )
    excluded = excluded_candidates(payload)
    if not excluded:
        return Selection("missing", reason=reason)
    if len(excluded) == 1 and excluded[0].publication_status == "unknown":
        return Selection(
            "unknown_publication",
            source_ref=excluded[0].source_ref,
            published_date=None,
            qualification=excluded[0].qualification(),
            excluded=excluded,
        )
    return Selection("gap", reason=_gap_reason(excluded), excluded=excluded)


__all__ = [
    "ExcludedCandidate",
    "GAP_PUBLICATION_AFTER_AS_OF",
    "GAP_PUBLICATION_INVALID",
    "GAP_PUBLICATION_UNKNOWN",
    "LocalQueryContractError",
    "QUALIFICATION_SCHEMA_VERSION",
    "RESULT_SCHEMA_VERSION",
    "Selection",
    "SourceRefObservation",
    "excluded_candidates",
    "select_local_outcome",
]
