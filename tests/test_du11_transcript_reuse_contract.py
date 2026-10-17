"""DU11: reuse scope and acquisition provider are separate decisions.

Every company-wiki/ET child is an offline stand-in, so the tests count actual
child calls: a path that must not download proves it with zero ET/import/reader
calls, never from a label.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any

import pytest

from transcript_companion import resolve_companion_transcript
import transcript_tool_transport
from transcript_tool_transport import EarningsTranscriptsTransport

AS_OF = "2026-09-30"
REQUEST_ID = "urn:company-wiki:source-request:sha256:" + "c" * 64
FMP_PAYLOAD = b'[{"symbol":"MSFT","period":"Q3","year":2026,"date":"2026-07-22","content":"synthetic"}]'


def ref_for(raw: bytes, mime: str = "text/plain") -> dict[str, Any]:
    digest = hashlib.sha256(raw).hexdigest()
    return {
        "schema_version": "2.0",
        "document_id": f"urn:company-wiki:document:sha256:{digest}",
        "source_id": f"urn:company-wiki:source:sha256:{digest}",
        "content_sha256": digest,
        "byte_size": len(raw),
        "mime_type": mime,
    }


def qualification(status: str) -> dict[str, Any]:
    eligible = None if status == "unknown" else status == "eligible"
    return {
        "publication_status": status,
        "as_of_date": AS_OF,
        "local_bytes_status": "not_checked",
        "historical_date_eligible": eligible,
        "historical_reuse_eligible": eligible,
        "schema_version": "source-qualification/1",
    }


def excluded(status: str, raw: bytes) -> dict[str, Any]:
    return {"source_ref": ref_for(raw), "qualification": qualification(status)}


def query_found(raw: bytes, published: str | None = "2026-07-22") -> dict[str, Any]:
    source_ref = ref_for(raw)
    return {
        "schema_version": "2.0",
        "status": "found",
        "reason": "one_local_match",
        "request_id": REQUEST_ID,
        "matches": [source_ref],
        "candidates": [
            {
                "source_ref": source_ref,
                "published_date": published,
                "document_kind": "investor_call_transcript",
                "fiscal_year": 2026,
                "fiscal_period": "Q3",
                "provider": "motley_fool",
                "market": "US",
                "security_id": "MSFT",
            }
        ],
        "source_read_policy_sha256": "d" * 64,
    }


def query_not_found(*exclusions: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "2.0",
        "status": "not_found",
        "reason": "no_local_match",
        "request_id": REQUEST_ID,
        "matches": [],
        "candidates": [],
        "source_read_policy_sha256": "d" * 64,
    }
    if exclusions:
        payload["excluded_candidates"] = list(exclusions)
    return payload


def query_status(status: str, reason: str = "reader_unavailable") -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "status": status,
        "reason": reason,
        "request_id": REQUEST_ID,
        "matches": [],
        "candidates": [],
        "source_read_policy_sha256": "d" * 64,
    }


def reader_entry(
    raw: bytes,
    *,
    provider: str | None = "motley_fool",
    published: str | None = "2026-07-22",
    fiscal_period: str = "Q3",
    fiscal_year: int = 2026,
    market: str = "US",
    security_id: str = "MSFT",
    code: int = 0,
    manifest: bool = True,
) -> dict[str, Any]:
    source_ref = ref_for(raw)
    receipt: dict[str, Any] = {
        "schema_version": "2.1",
        "status": "ok",
        "document_id": source_ref["document_id"],
        "source_id": source_ref["source_id"],
        "content_sha256": source_ref["content_sha256"],
        "byte_size": source_ref["byte_size"],
    }
    if manifest:
        receipt["manifest"] = {
            "provider": provider,
            "published_date": published,
            "fiscal_period": fiscal_period,
            "fiscal_year": fiscal_year,
            "market": market,
            "security_id": security_id,
        }
    return {"raw": raw, "receipt": receipt, "code": code}


class FakeCWP:
    """Offline stand-in for the source query, reader, import and ET children."""

    def __init__(
        self,
        *,
        queries: list[dict[str, Any]],
        reader: list[dict[str, Any]] | None = None,
        imported: dict[str, Any] | None = None,
        fetched: dict[str, Any] | None = None,
        tool: Path | None = None,
        usage: bool = True,
        raise_at_et: BaseException | None = None,
    ) -> None:
        self.queries = queries
        self.reader = reader or []
        self.imported = imported
        self.fetched = fetched
        self.tool = tool
        self.usage = usage
        self.raise_at_et = raise_at_et
        self.calls: list[tuple[str, list[str], bytes | None]] = []

    def kinds(self) -> list[str]:
        return [kind for kind, _, _ in self.calls]

    def count(self, kind: str) -> int:
        return self.kinds().count(kind)

    def payload(self, index: int = 0) -> dict[str, Any]:
        raw = self.calls[index][2]
        assert raw is not None
        return json.loads(raw.decode("utf-8"))

    def __call__(self, command, *, input_bytes=None, timeout_seconds=None, **kwargs):
        joined = " ".join(command)
        if "source_query_cli" in joined:
            self.calls.append(("query", list(command), input_bytes))
            payload = self.queries.pop(0) if len(self.queries) > 1 else self.queries[0]
            return json.dumps(payload).encode(), b"", 0
        if "source_reader_cli" in joined:
            self.calls.append(("reader", list(command), input_bytes))
            entry = self.reader.pop(0) if len(self.reader) > 1 else self.reader[0]
            return entry["raw"], json.dumps(entry["receipt"]).encode(), entry.get("code", 0)
        if "transcript_import_cli" in joined:
            self.calls.append(("import", list(command), input_bytes))
            assert self.imported is not None
            return json.dumps(self.imported).encode(), b"", 0
        if self.tool is not None and str(self.tool) in command:
            self.calls.append(("et", list(command), input_bytes))
            if self.raise_at_et is not None:
                raise self.raise_at_et
            assert self.fetched is not None
            usage = {
                "schema_version": "earnings-retrieval-usage/1",
                "request_id": REQUEST_ID,
                "usage_complete": True,
                "usage": {"requests_used": 1, "response_bytes_used": 512},
            }
            return (
                json.dumps(self.fetched).encode(),
                json.dumps(usage).encode() if self.usage else b"",
                0,
            )
        raise AssertionError(f"unexpected child process: {joined}")


def fetched_result(published: str | None = "2026-07-22") -> dict[str, Any]:
    return {
        "schema_version": "earnings-transcript-result/2",
        "request_id": REQUEST_ID,
        "status": "fetched",
        "provider": "fmp",
        "ticker": "MSFT",
        "exchange": "nasdaq",
        "fiscal_period": "2026-Q3",
        "as_of_date": AS_OF,
        "title": "MSFT 2026 Q3 Earnings Call Transcript",
        "source_url": (
            "https://financialmodelingprep.com/stable/earning-call-transcript"
            "?symbol=MSFT&year=2026&quarter=3"
        ),
        "provider_document_id": "fmp:MSFT:2026:Q3:2026-07-22",
        "call_date": "2026-07-22",
        "publication_date": published,
        "as_of_cutoff_verified": published is not None,
        "provider_payload_sha256": hashlib.sha256(FMP_PAYLOAD).hexdigest(),
    }


def imported_result() -> dict[str, Any]:
    source_ref = ref_for(FMP_PAYLOAD, "application/json")
    return {
        "schema_version": "company-wiki-transcript-import-response/3",
        "status": "imported",
        "canonical_status": "imported_new",
        "request_id": REQUEST_ID,
        "source_id": source_ref["source_id"],
        "content_sha256": source_ref["content_sha256"],
        "provider_payload_sha256": source_ref["content_sha256"],
        "source_ref": source_ref,
    }


def companion_request(*, provider: str | None = None, intent: str = "fetch_if_missing") -> dict[str, Any]:
    option: dict[str, Any] = {"intent": intent, "fiscal_year": 2026, "fiscal_quarter": 3}
    if provider is not None:
        option["provider"] = provider
    if intent == "fetch_if_missing":
        option["acquisition_limits"] = {
            "max_bytes": 1_000_000,
            "timeout_seconds": 10,
            "max_cost_usd": "0.00",
        }
    return {"as_of_date": AS_OF, "companion_transcript": option}


def filing() -> dict[str, Any]:
    return {
        "source_ref": {
            "schema_version": "2.0",
            "document_id": "urn:company-wiki:document:sha256:" + "a" * 64,
            "source_id": "urn:company-wiki:source:sha256:" + "a" * 64,
            "content_sha256": "a" * 64,
            "byte_size": 100,
            "mime_type": "application/pdf",
        },
        "company_identity": {
            "canonical_name": "Microsoft Corporation",
            "market": "US",
            "security_id": "MSFT",
            "ticker": "MSFT",
            "exchange": "NASDAQ",
            "verified": True,
            "active": True,
        },
    }


@pytest.fixture
def tool(tmp_path: Path) -> Path:
    path = tmp_path / "transcript_tool.py"
    path.write_text("# offline fixture; the process is injected\n", encoding="utf-8")
    return path


def build(
    monkeypatch: pytest.MonkeyPatch, fake: FakeCWP, tool: Path | None
) -> EarningsTranscriptsTransport:
    monkeypatch.setattr(transcript_tool_transport, "_run_bounded_json", fake)
    return EarningsTranscriptsTransport(
        wiki_root=_wiki_root(tool),
        transcript_tool=tool,
        deadline=time.monotonic() + 60,
    )


def _wiki_root(tool: Path | None) -> Path:
    root = (tool.parent if tool is not None else Path.cwd())
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "source_catalog.yaml").write_text("fixture", encoding="utf-8")
    return root


LOCAL_RAW = b"motley fool transcript original bytes"


def test_omitted_provider_queries_without_a_provider_and_reuses_the_local_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(queries=[query_found(LOCAL_RAW)], reader=[reader_entry(LOCAL_RAW)])
    transport = build(monkeypatch, fake, tool)

    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )

    assert result["status"] == "reused", result
    assert result["provider"] == "motley_fool"
    assert result["source_ref"] == ref_for(LOCAL_RAW)
    assert result["publication_date"] == "2026-07-22"
    assert result["as_of_cutoff_verified"] is True
    assert result["provider_calls"] == 0
    assert result["fiscal_year"] == 2026 and result["fiscal_quarter"] == 3
    assert fake.kinds() == ["query", "reader"]
    sent = fake.payload(0)
    assert sent["provider"] is None
    assert sent["document_kind"] == "investor_call_transcript"
    assert sent["mode"] == "exact"
    assert sent["allow_download"] is False
    assert "source_request" not in sent
    assert sent["schema_version"] == "1.0"
    assert transport.company_wiki_calls == 2


def test_explicit_fmp_keeps_the_provider_scoped_lookup_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(
        queries=[query_found(LOCAL_RAW)],
        reader=[reader_entry(LOCAL_RAW, provider="fmp")],
    )
    transport = build(monkeypatch, fake, tool)

    result = resolve_companion_transcript(
        request=companion_request(provider="fmp"), filing_handle=filing(),
        transport=transport,
    )

    assert result["status"] == "reused", result
    assert result["provider"] == "fmp"
    assert fake.count("et") == 0
    sent = fake.payload(0)
    assert sent["schema_version"] == "company-wiki-transcript-import-lookup-request/1"
    assert set(sent) == {"schema_version", "source_request"}
    assert sent["source_request"]["provider"] == "fmp"


def test_reused_provider_comes_from_the_verified_reader_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(
        queries=[query_found(LOCAL_RAW)],
        reader=[reader_entry(LOCAL_RAW, provider="motley_fool")],
    )
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "reused"
    assert result["provider"] == "motley_fool"
    # The manifest wins over the query candidate's own label.
    assert fake.payload(0)["provider"] is None


def test_a_missing_manifest_provider_stays_unknown_and_is_never_relabelled_fmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(
        queries=[query_found(LOCAL_RAW)],
        reader=[reader_entry(LOCAL_RAW, manifest=False)],
    )
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "reused", result
    assert "provider" not in result
    assert fake.count("et") == 0


def test_a_manifest_provider_disagreeing_with_the_explicit_constraint_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(
        queries=[query_found(LOCAL_RAW)],
        reader=[reader_entry(LOCAL_RAW, provider="motley_fool")],
    )
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(provider="fmp"), filing_handle=filing(),
        transport=transport,
    )
    assert result["status"] == "upstream_error"
    assert result["reason"] == "transcript_provider_mismatch"
    assert fake.count("et") == 0


@pytest.mark.parametrize(
    "manifest",
    [
        {"security_id": "AAPL"},
        {"fiscal_period": "Q2"},
        {"fiscal_year": 2025},
        {"market": "HK"},
    ],
)
def test_a_manifest_contradicting_the_exact_request_is_never_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path, manifest: dict[str, Any]
) -> None:
    entry = reader_entry(LOCAL_RAW)
    entry["receipt"]["manifest"].update(manifest)
    fake = FakeCWP(queries=[query_found(LOCAL_RAW)], reader=[entry])
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "upstream_error", result
    assert result["reason"] == "transcript_lookup_identity_mismatch"
    assert fake.count("et") == 0


def test_a_single_unknown_publication_exclusion_keeps_the_observation_without_a_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    observed = excluded("unknown", b"unknown publication local bytes")
    fake = FakeCWP(queries=[query_not_found(observed)])
    transport = build(monkeypatch, fake, tool)

    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )

    assert result["status"] == "unknown_publication", result
    assert result["reason"] == "publication_date_unknown"
    assert result["source_ref"] == observed["source_ref"]
    assert result["as_of_cutoff_verified"] is False
    assert result["provider_calls"] == 0
    assert result["qualification"] == observed["qualification"]
    assert fake.kinds() == ["query"]
    assert fake.count("et") == 0


def test_several_unknown_exclusions_become_the_named_gap_without_any_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    first = excluded("unknown", b"first unknown observation")
    second = excluded("unknown", b"second unknown observation")
    fake = FakeCWP(queries=[query_not_found(first, second)])
    transport = build(monkeypatch, fake, tool)

    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )

    assert result["status"] == "upstream_error", result
    assert result["reason"] == "publication_date_unknown"
    assert result["retryable"] is False
    assert result["provider_calls"] == 0
    assert [item["source_ref"] for item in result["excluded_candidates"]] == [
        first["source_ref"], second["source_ref"],
    ]
    assert fake.kinds() == ["query"]


def test_a_qualified_match_wins_over_an_unknown_exclusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    payload = query_found(LOCAL_RAW)
    payload["excluded_candidates"] = [excluded("unknown", b"unknown but same period")]
    fake = FakeCWP(queries=[payload], reader=[reader_entry(LOCAL_RAW)])
    transport = build(monkeypatch, fake, tool)

    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )

    assert result["status"] == "reused", result
    assert result["source_ref"] == ref_for(LOCAL_RAW)
    assert fake.count("et") == 0


@pytest.mark.parametrize(
    "statuses,reason",
    [
        (["after_as_of"], "publication_after_as_of"),
        (["invalid"], "publication_date_invalid"),
        (["after_as_of", "invalid"], "publication_date_invalid"),
        (["unknown", "after_as_of"], "publication_date_unknown"),
    ],
)
def test_restricted_exclusions_are_reported_with_their_own_qualification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path,
    statuses: list[str], reason: str,
) -> None:
    items = [excluded(status, status.encode() + b" local bytes") for status in statuses]
    fake = FakeCWP(queries=[query_not_found(*items)])
    transport = build(monkeypatch, fake, tool)

    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )

    assert result["status"] == "upstream_error", result
    assert result["reason"] == reason
    assert [item["qualification"]["publication_status"] for item in result["excluded_candidates"]] == statuses
    assert fake.count("et") == 0
    assert fake.count("reader") == 0


@pytest.mark.parametrize("status", ["ambiguous", "blocked", "unavailable", "not_indexed"])
def test_non_reuse_query_statuses_stay_named_and_never_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path, status: str
) -> None:
    fake = FakeCWP(queries=[query_status(status, "named_cause")])
    transport = build(monkeypatch, fake, tool)

    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )

    expected = "ambiguous" if status == "ambiguous" else "upstream_error"
    assert result["status"] == expected, result
    assert result["reason"] == "named_cause"
    assert fake.kinds() == ["query"]


def test_illegal_query_status_is_a_named_contract_error_without_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(queries=[{"schema_version": "2.0", "status": "weird", "reason": "?"}])
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "upstream_error"
    assert result["reason"] == "transcript_lookup_contract"
    assert fake.count("et") == 0


def test_malformed_excluded_qualification_is_a_named_contract_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    observed = excluded("unknown", b"malformed qualification bytes")
    observed["qualification"]["publication_status"] = "probably_unknown"
    fake = FakeCWP(queries=[query_not_found(observed)])
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "upstream_error"
    assert result["reason"] == "transcript_lookup_contract"
    assert fake.kinds() == ["query"]


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda ref: {**ref, "content_sha256": "b" * 64}, "transcript_lookup_source_ref"),
        (lambda ref: {key: value for key, value in ref.items() if key != "mime_type"},
         "transcript_lookup_contract"),
    ],
)
def test_a_broken_source_ref_never_reuses_or_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path, mutate, reason: str
) -> None:
    payload = query_found(LOCAL_RAW)
    payload["candidates"][0]["source_ref"] = mutate(payload["candidates"][0]["source_ref"])
    fake = FakeCWP(queries=[payload], reader=[reader_entry(LOCAL_RAW)])
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "upstream_error", result
    assert result["reason"] == reason
    assert fake.count("et") == 0


@pytest.mark.parametrize("damage", ["sha", "size", "code"])
def test_damaged_or_unreadable_local_bytes_never_reuse_or_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path, damage: str
) -> None:
    entry = reader_entry(b"same length"[: len(LOCAL_RAW)].ljust(len(LOCAL_RAW), b"x"))
    if damage == "code":
        entry["code"] = 2
    fake = FakeCWP(queries=[query_found(LOCAL_RAW)], reader=[entry])
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "upstream_error", result
    assert result["reason"] == "transcript_lookup_failed"
    assert fake.count("et") == 0


def test_explicit_fmp_without_a_local_match_acquires_once_then_replays_without_a_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(
        queries=[query_not_found()],
        fetched=fetched_result(),
        imported=imported_result(),
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp", manifest=True)],
        tool=tool,
    )
    transport = build(monkeypatch, fake, tool)

    first = resolve_companion_transcript(
        request=companion_request(provider="fmp"), filing_handle=filing(),
        transport=transport,
    )

    assert first["status"] == "downloaded", first
    assert first["provider"] == "fmp"
    assert first["source_ref"] == ref_for(FMP_PAYLOAD, "application/json")
    assert first["provider_calls"] == 1
    assert fake.kinds() == ["query", "et", "import", "reader"]
    et_request = json.loads(fake.calls[1][2].decode("utf-8"))
    assert et_request["provider"] == "fmp"
    assert fake.payload(0)["source_request"]["provider"] == "fmp"

    replay = FakeCWP(
        queries=[query_found(FMP_PAYLOAD)],
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
    )
    monkeypatch.setattr(transcript_tool_transport, "_run_bounded_json", replay)
    replay_transport = build(monkeypatch, replay, tool)
    second = resolve_companion_transcript(
        request=companion_request(provider="fmp"), filing_handle=filing(),
        transport=replay_transport,
    )
    assert second["status"] == "reused", second
    assert second["provider_calls"] == 0
    assert replay.count("et") == 0
    assert replay.count("import") == 0


def test_omitted_provider_acquisition_still_uses_only_fmp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(
        queries=[query_not_found()],
        fetched=fetched_result(),
        imported=imported_result(),
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
    )
    transport = build(monkeypatch, fake, tool)

    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )

    assert result["status"] == "downloaded", result
    # The neutral local query stayed source-neutral ...
    assert fake.payload(0)["provider"] is None
    # ... while the acquisition request is still the configured FMP provider.
    assert json.loads(fake.calls[1][2].decode("utf-8"))["provider"] == "fmp"
    assert fake.count("et") == 1
    assert result["provider"] == "fmp"


def test_omitted_provider_truly_missing_then_replay_reuses_the_imported_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(
        queries=[query_not_found()],
        fetched=fetched_result(),
        imported=imported_result(),
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
    )
    transport = build(monkeypatch, fake, tool)
    first = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )
    assert first["status"] == "downloaded", first

    replay = FakeCWP(
        queries=[query_found(FMP_PAYLOAD)],
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
    )
    monkeypatch.setattr(transcript_tool_transport, "_run_bounded_json", replay)
    second = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(),
        transport=build(monkeypatch, replay, tool),
    )
    assert second["status"] == "reused", second
    assert second["provider"] == "fmp"
    assert second["provider_calls"] == 0
    assert replay.count("et") == 0


def test_reuse_only_intent_never_downloads_after_a_named_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(queries=[query_not_found(excluded("after_as_of", b"after as-of bytes"))])
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(intent="reuse_only"), filing_handle=filing(),
        transport=transport,
    )
    assert result["status"] == "upstream_error", result
    assert result["reason"] == "publication_after_as_of"
    assert fake.kinds() == ["query"]


def test_reuse_only_intent_true_miss_is_not_found_with_zero_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(queries=[query_not_found()])
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(intent="reuse_only"), filing_handle=filing(),
        transport=transport,
    )
    assert result["status"] == "not_found"
    assert result["reason"] == "exact_transcript_missing"
    assert fake.kinds() == ["query"]


@pytest.mark.parametrize(
    "exclusions,key",
    [
        ([excluded("unknown", b"single unknown after requery")], "qualification"),
        (
            [excluded("unknown", b"first unknown after requery"),
             excluded("after_as_of", b"after as-of after requery")],
            "excluded_candidates",
        ),
    ],
)
def test_acquire_requery_with_local_evidence_never_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path,
    exclusions: list[dict[str, Any]], key: str,
) -> None:
    fake = FakeCWP(
        queries=[query_not_found(*exclusions)],
        fetched=fetched_result(),
        imported=imported_result(),
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
    )
    transport = build(monkeypatch, fake, tool)
    result = transport.acquire_exact(
        identity=filing()["company_identity"],
        filing_source_ref=filing()["source_ref"],
        fiscal_year=2026,
        fiscal_quarter=3,
        as_of_date=AS_OF,
        provider=None,
        acquisition_limits={"max_bytes": 1_000_000, "timeout_seconds": 10, "max_cost_usd": "0.00"},
    )
    assert result["status"] == "upstream_error"
    assert result["reason"] == "transcript_lookup_changed"
    assert fake.kinds() == ["query"]
    assert key in result
    reported = (
        [result["qualification"]["publication_status"]]
        if key == "qualification"
        else [item["qualification"]["publication_status"]
              for item in result["excluded_candidates"]]
    )
    assert reported == [item["qualification"]["publication_status"] for item in exclusions]


def test_acquire_requery_with_a_contract_violation_never_downloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(
        queries=[{"schema_version": "2.0", "status": "weird"}],
        fetched=fetched_result(),
        imported=imported_result(),
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
    )
    transport = build(monkeypatch, fake, tool)
    result = transport.acquire_exact(
        identity=filing()["company_identity"],
        filing_source_ref=filing()["source_ref"],
        fiscal_year=2026,
        fiscal_quarter=3,
        as_of_date=AS_OF,
        provider=None,
        acquisition_limits={"max_bytes": 1_000_000, "timeout_seconds": 10, "max_cost_usd": "0.00"},
    )
    assert result["status"] == "upstream_error"
    assert result["reason"] == "transcript_lookup_contract"
    assert fake.kinds() == ["query"]


@pytest.mark.parametrize("provider", ["motley_fool", "sec"])
def test_an_unsupported_provider_option_is_named_and_calls_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path, provider: str
) -> None:
    fake = FakeCWP(queries=[query_not_found()], tool=tool)
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(provider=provider), filing_handle=filing(),
        transport=transport,
    )
    assert result["status"] == "request_error"
    assert result["reason"] == "unsupported_transcript_provider"
    assert fake.calls == []


def test_the_transport_itself_refuses_an_unlisted_provider_without_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(queries=[query_found(LOCAL_RAW)], tool=tool)
    transport = build(monkeypatch, fake, tool)
    result = transport.lookup_exact(
        identity=filing()["company_identity"],
        fiscal_year=2026,
        fiscal_quarter=3,
        as_of_date=AS_OF,
        provider="motley_fool",
    )
    assert result == {
        "status": "upstream_error",
        "reason": "unsupported_transcript_provider",
        "provider_calls": 0,
    }
    assert fake.calls == []


def test_the_public_v2_envelope_keeps_the_real_provider_and_measured_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    from ff_v2_envelope import _transcript_result

    fake = FakeCWP(queries=[query_found(LOCAL_RAW)], reader=[reader_entry(LOCAL_RAW)])
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )
    public = _transcript_result(result)
    assert public["status"] == "reused"
    assert public["provider"] == "motley_fool"
    assert public["provider_calls"] == 0
    assert public["source_ref"] == ref_for(LOCAL_RAW)


def test_a_bad_response_sha_keeps_one_download_and_never_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    imported = imported_result()
    imported["content_sha256"] = "e" * 64
    imported["provider_payload_sha256"] = "e" * 64
    imported["source_ref"] = {**imported["source_ref"], "content_sha256": "e" * 64,
                              "document_id": "urn:company-wiki:document:sha256:" + "e" * 64,
                              "source_id": "urn:company-wiki:source:sha256:" + "e" * 64}
    fake = FakeCWP(
        queries=[query_not_found()],
        fetched=fetched_result(),
        imported=imported,
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
    )
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "upstream_error", result
    assert result["reason"] == "transcript_import_hash_mismatch"
    assert result["provider_calls"] == 1
    assert fake.kinds() == ["query", "et", "import"]
    assert fake.count("et") == 1


@pytest.mark.parametrize(
    "failure,reason",
    [
        ("child_timeout", "provider_result_oversized"),
        ("subprocess_timeout", "provider_deadline"),
    ],
)
def test_an_et_timeout_never_triggers_a_second_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path,
    failure: str, reason: str,
) -> None:
    from ff_process_transport import ChildTimeout
    import subprocess

    raised = (
        ChildTimeout("deadline expired")
        if failure == "child_timeout"
        else subprocess.TimeoutExpired("owned tool", 10)
    )
    fake = FakeCWP(
        queries=[query_not_found()],
        fetched=fetched_result(),
        imported=imported_result(),
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
        raise_at_et=raised,
    )
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "provider_unavailable", result
    assert result["reason"] == reason
    assert result["provider_calls"] == 1
    assert fake.count("et") == 1
    assert fake.count("import") == 0


def test_absent_usage_keeps_unknown_counts_as_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FakeCWP(
        queries=[query_not_found()],
        fetched=fetched_result(),
        imported=imported_result(),
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
        usage=False,
    )
    transport = build(monkeypatch, fake, tool)
    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )
    assert result["status"] == "downloaded", result
    assert result["provider_requests"] is None
    assert result["provider_response_bytes"] is None
    assert result["provider_usage_complete"] is False
    assert result["provider_calls"] == 1
    assert fake.count("et") == 1
