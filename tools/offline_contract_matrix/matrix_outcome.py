"""Shared typed observations; missing evidence is never measured zero."""
from dataclasses import dataclass
from typing import Any, Mapping


def count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def source_ref(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    required = ("document_id", "source_id", "content_sha256", "byte_size", "mime_type")
    if not all(k in value for k in required):
        return None
    if not all(isinstance(value[k], str) and value[k] for k in required if k != "byte_size"):
        return None
    if len(value["content_sha256"]) != 64 or count(value["byte_size"]) is None:
        return None
    return value


@dataclass(frozen=True)
class Outcome:
    status: str | None
    reason: str | None
    reference: dict | None
    requests: int | None
    usage_complete: bool | None
    fiscal_year: Any
    fiscal_quarter: Any
    raw: Mapping[str, Any]

    @classmethod
    def observe(cls, value: Mapping[str, Any]):
        return cls(value.get("status"), value.get("reason"), source_ref(value.get("source_ref")),
            count(value.get("provider_requests")), value.get("provider_usage_complete"),
            value.get("fiscal_year"), value.get("fiscal_quarter"), value)

    def rejected_quarter(self) -> bool:
        return self.status not in {None, "downloaded", "reused", "unknown_publication"} and (
            self.reason in {"quarter_mismatch", "fiscal_quarter_mismatch", "period_mismatch"})

    def rejected_cutoff(self) -> bool:
        return self.status not in {None, "downloaded", "reused"} and self.reason in {
            "after_as_of", "after_as_of_date", "past_cutoff", "call_after_as_of",
            "published_after_as_of", "publication_after_as_of", "cutoff_exceeded"}

    def preserves_unknown_usage(self) -> bool:
        return (self.raw.get("provider_requests") is None
            and self.usage_complete is False and self.status in {
                "upstream_error", "provider_unavailable", "failed", "timeout"}
            and isinstance(self.reason, str) and bool(self.reason))


def filing_reused(first: Mapping[str, Any], second: Mapping[str, Any], kind: str) -> bool:
    ref1, ref2 = source_ref(first.get("source_ref")), source_ref(second.get("source_ref"))
    return bool(ref1 and ref1 == ref2 and first.get("document_kind") == kind
        and second.get("document_kind") == kind
        and first.get("resolution_outcome") in {"downloaded_new", "reused_after_discovery"}
        and second.get("resolution_outcome") == "reused_existing"
        and count(first.get("download_events")) is not None
        and count(first.get("download_events")) >= 1
        and count(second.get("download_events")) == 0)
