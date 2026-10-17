"""DU11: real offline contract E2E against the frozen company-wiki commit.

Layering (recorded so the chain cannot be mistaken for a helper shortcut):

    test -> transcript_companion.resolve_companion_transcript  (real code)
          -> EarningsTranscriptsTransport                      (real code)
             -> python -m company_wiki...source_query_cli      (real frozen CWP)
             -> python -m company_wiki...source_reader_cli     (real frozen CWP)
             -> python -m company_wiki...transcript_import_cli (real frozen CWP)
             -> offline ET fixture process                     (the only fake boundary)

Only the ET supplier boundary and the FIFO of its recorded calls are synthetic:
the FF transport, the companion orchestration, the company-wiki CLI processes,
the catalog SQLite state, the scanner and the canonical import are all real.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

import pytest

from test_du11_transcript_reuse_support import (
    AFTER_AS_OF_BODY,
    AS_OF,
    ENTITY,
    KNOWN_TRANSCRIPT_BODY,
    MARKET,
    MOTLEY_SIDECAR,
    OTHER_TRANSCRIPT_BODY,
    SECURITY_ID,
    UNKNOWN_TRANSCRIPT_BODY,
    OwnedWiki,
    frozen_archive,
)

from transcript_companion import resolve_companion_transcript
from transcript_tool_transport import EarningsTranscriptsTransport

FF_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = FF_ROOT / "tests" / "fixtures" / "du11_transcript_reuse"
KNOWN_FIXTURE = FIXTURES / "fmp_known_publication.fetched.json"
UNKNOWN_FIXTURE = FF_ROOT / "tests" / "fixtures" / "et_s0b" / "fmp_v2.fetched.json"


@pytest.fixture(scope="session")
def frozen_source_tar() -> Any:
    with frozen_archive() as archive:
        yield archive


@pytest.fixture
def owned_wiki(frozen_source_tar: Path) -> Any:
    wiki = OwnedWiki(frozen_source_tar).build()
    try:
        yield wiki
    finally:
        # The restore receipt is evidence; it must never leave a temp tree behind.
        try:
            wiki.assert_restored()
        finally:
            wiki.cleanup()


def filing_handle() -> dict[str, Any]:
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
            "canonical_name": ENTITY,
            "market": MARKET,
            "security_id": SECURITY_ID,
            "ticker": SECURITY_ID,
            "exchange": "NASDAQ",
            "verified": True,
            "active": True,
        },
    }


def companion_request(*, provider: str | None = None, intent: str = "fetch_if_missing") -> dict:
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


def transport(wiki: OwnedWiki, fixture: Path) -> EarningsTranscriptsTransport:
    return EarningsTranscriptsTransport(
        wiki_root=wiki.root,
        transcript_tool=wiki.et_tool(),
        fmp_api_key_file=wiki.key_file(),
        deadline=time.monotonic() + 180,
    )


def et_calls(wiki: OwnedWiki) -> list[dict[str, Any]]:
    log = wiki.call_log()
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture(autouse=True)
def et_boundary(monkeypatch: pytest.MonkeyPatch, owned_wiki: OwnedWiki):
    """Point the offline ET fixture process at its fixture and its call log."""
    monkeypatch.setenv("ET_FIXTURE_PATH", str(KNOWN_FIXTURE))
    monkeypatch.setenv("ET_CALL_LOG", str(owned_wiki.call_log()))
    # The frozen source tree must stay byte-identical: no __pycache__ residue.
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    return owned_wiki


def test_real_cwp_reuses_a_motley_fool_transcript_without_any_download(
    owned_wiki: OwnedWiki,
) -> None:
    original = owned_wiki.seed_transcript(
        "msft_2026_q3_call.txt", KNOWN_TRANSCRIPT_BODY, MOTLEY_SIDECAR
    )
    owned_wiki.run_scan()
    before = owned_wiki.query_local({
        "entity": ENTITY, "document_kind": "investor_call_transcript",
        "as_of_date": AS_OF, "market": MARKET, "security_id": SECURITY_ID,
        "form_type": None, "fiscal_year": 2026, "fiscal_period": "Q3",
        "language": None, "provider": None, "provider_document_id": None,
        "mode": "exact", "allow_download": False, "schema_version": "1.0",
    })
    assert before["status"] == "found", before
    source_ref = before["candidates"][0]["source_ref"]

    resolved = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing_handle(),
        transport=transport(owned_wiki, KNOWN_FIXTURE),
    )

    assert resolved["status"] == "reused", resolved
    assert resolved["source_ref"] == source_ref
    assert resolved["provider"] == "motley_fool"
    assert resolved["as_of_cutoff_verified"] is True
    assert resolved["provider_calls"] == 0
    assert resolved["publication_date"] == "2026-07-22"
    assert et_calls(owned_wiki) == []
    assert source_ref["content_sha256"] == hashlib.sha256(
        original.read_bytes()
    ).hexdigest()
    assert original.read_bytes() == KNOWN_TRANSCRIPT_BODY


def test_real_cwp_unknown_publication_observation_costs_zero_provider_and_zero_read(
    owned_wiki: OwnedWiki,
) -> None:
    sidecar = {
        key: value for key, value in MOTLEY_SIDECAR.items()
        if key not in {"published_date"}
    }
    owned_wiki.seed_transcript("msft_2026_q3_unknown.txt", UNKNOWN_TRANSCRIPT_BODY, sidecar)
    owned_wiki.run_scan()

    probe = owned_wiki.query_local({
        "entity": ENTITY, "document_kind": "investor_call_transcript",
        "as_of_date": AS_OF, "market": MARKET, "security_id": SECURITY_ID,
        "form_type": None, "fiscal_year": 2026, "fiscal_period": "Q3",
        "language": None, "provider": None, "provider_document_id": None,
        "mode": "exact", "allow_download": False, "schema_version": "1.0",
    })
    assert probe["status"] == "not_found", probe
    excluded = probe["excluded_candidates"]
    assert [item["qualification"]["publication_status"] for item in excluded] == ["unknown"]
    assert excluded[0]["qualification"]["schema_version"] == "source-qualification/1"

    held = transport(owned_wiki, KNOWN_FIXTURE)
    resolved = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing_handle(), transport=held,
    )

    assert resolved["status"] == "unknown_publication", resolved
    assert resolved["reason"] == "publication_date_unknown"
    assert resolved["source_ref"] == excluded[0]["source_ref"]
    assert resolved["as_of_cutoff_verified"] is False
    assert resolved["provider_calls"] == 0
    assert resolved["qualification"] == excluded[0]["qualification"]
    assert "provider" not in resolved
    assert et_calls(owned_wiki) == []
    # One bounded query process and no source read at all.
    assert held.company_wiki_calls == 1


def test_real_cwp_qualified_match_wins_over_an_unknown_observation(
    owned_wiki: OwnedWiki,
) -> None:
    unknown_sidecar = {
        key: value for key, value in MOTLEY_SIDECAR.items()
        if key not in {"published_date"}
    }
    owned_wiki.seed_transcript("msft_2026_q3_unknown.txt", UNKNOWN_TRANSCRIPT_BODY,
                               unknown_sidecar)
    owned_wiki.seed_transcript("msft_2026_q3_call.txt", KNOWN_TRANSCRIPT_BODY,
                               MOTLEY_SIDECAR)
    owned_wiki.run_scan()

    held = transport(owned_wiki, KNOWN_FIXTURE)
    resolved = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing_handle(), transport=held,
    )

    assert resolved["status"] == "reused", resolved
    assert resolved["provider"] == "motley_fool"
    assert resolved["source_ref"]["content_sha256"] == hashlib.sha256(
        KNOWN_TRANSCRIPT_BODY
    ).hexdigest()
    assert et_calls(owned_wiki) == []
    assert held.company_wiki_calls == 2


def test_real_cwp_two_real_providers_for_one_period_are_ambiguous_and_never_download(
    owned_wiki: OwnedWiki,
) -> None:
    owned_wiki.seed_transcript("msft_2026_q3_call.txt", KNOWN_TRANSCRIPT_BODY,
                               MOTLEY_SIDECAR)
    owned_wiki.seed_transcript(
        "msft_2026_q3_call_alt.txt",
        OTHER_TRANSCRIPT_BODY,
        dict(
            MOTLEY_SIDECAR,
            provider="seeking_alpha",
            provider_document_id="sa:MSFT:2026:Q3",
            source_url="https://seekingalpha.com/article/synthetic-msft-q3-2026",
        ),
    )
    owned_wiki.run_scan()

    held = transport(owned_wiki, KNOWN_FIXTURE)
    resolved = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing_handle(), transport=held,
    )

    assert resolved["status"] == "ambiguous", resolved
    assert resolved["reason"] == "multiple_local_matches"
    assert "source_ref" not in resolved
    assert et_calls(owned_wiki) == []
    assert held.company_wiki_calls == 1


def test_real_cwp_mixed_unknown_and_after_as_of_observations_are_a_named_gap(
    owned_wiki: OwnedWiki,
) -> None:
    unknown_sidecar = {
        key: value for key, value in MOTLEY_SIDECAR.items()
        if key not in {"published_date"}
    }
    after_sidecar = dict(MOTLEY_SIDECAR, published_date="2026-10-10")
    owned_wiki.seed_transcript("msft_2026_q3_unknown.txt", UNKNOWN_TRANSCRIPT_BODY,
                               unknown_sidecar)
    owned_wiki.seed_transcript("msft_2026_q3_late.txt", AFTER_AS_OF_BODY, after_sidecar)
    owned_wiki.run_scan()

    probe = owned_wiki.query_local({
        "entity": ENTITY, "document_kind": "investor_call_transcript",
        "as_of_date": AS_OF, "market": MARKET, "security_id": SECURITY_ID,
        "form_type": None, "fiscal_year": 2026, "fiscal_period": "Q3",
        "language": None, "provider": None, "provider_document_id": None,
        "mode": "exact", "allow_download": False, "schema_version": "1.0",
    })
    assert probe["status"] == "not_found", probe
    statuses = sorted(
        item["qualification"]["publication_status"] for item in probe["excluded_candidates"]
    )
    assert statuses == ["after_as_of", "unknown"]

    held = transport(owned_wiki, KNOWN_FIXTURE)
    resolved = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing_handle(), transport=held,
    )

    assert resolved["status"] == "upstream_error", resolved
    assert resolved["reason"] == "publication_date_unknown"
    assert resolved["retryable"] is False
    assert resolved["provider_calls"] == 0
    assert sorted(
        item["qualification"]["publication_status"]
        for item in resolved["excluded_candidates"]
    ) == ["after_as_of", "unknown"]
    assert et_calls(owned_wiki) == []
    assert held.company_wiki_calls == 1


def test_real_cwp_after_as_of_only_observation_is_its_own_named_gap(
    owned_wiki: OwnedWiki,
) -> None:
    owned_wiki.seed_transcript("msft_2026_q3_late.txt", AFTER_AS_OF_BODY,
                               dict(MOTLEY_SIDECAR, published_date="2026-10-10"))
    owned_wiki.run_scan()

    held = transport(owned_wiki, KNOWN_FIXTURE)
    resolved = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing_handle(), transport=held,
    )

    assert resolved["status"] == "upstream_error", resolved
    assert resolved["reason"] == "publication_after_as_of"
    assert resolved["provider_calls"] == 0
    assert et_calls(owned_wiki) == []
    assert held.company_wiki_calls == 1


def test_real_cwp_missing_then_one_download_then_replay_is_pure_reuse(
    owned_wiki: OwnedWiki,
) -> None:
    owned_wiki.run_scan()
    first_transport = transport(owned_wiki, KNOWN_FIXTURE)

    first = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing_handle(),
        transport=first_transport,
    )

    assert first["status"] == "downloaded", first
    assert first["provider"] == "fmp"
    assert first["provider_calls"] == 1
    assert first["publication_date"] == "2026-07-22"
    assert first["as_of_cutoff_verified"] is True
    calls = et_calls(owned_wiki)
    assert len(calls) == 1
    assert calls[0]["provider"] == "fmp"
    assert calls[0]["ticker"] == SECURITY_ID
    assert calls[0]["fiscal_year"] == 2026 and calls[0]["fiscal_quarter"] == 3
    originals = [
        path for path in (owned_wiki.root / "companies").rglob("*")
        if path.is_file() and not path.name.endswith(".source.json")
    ]
    assert len(originals) == 1

    replay_transport = transport(owned_wiki, KNOWN_FIXTURE)
    replay = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing_handle(),
        transport=replay_transport,
    )

    assert replay["status"] == "reused", replay
    assert replay["source_ref"] == first["source_ref"]
    assert replay["provider"] == "fmp"
    assert replay["provider_calls"] == 0
    assert len(et_calls(owned_wiki)) == 1
    assert replay_transport.company_wiki_calls == 2
    assert [
        path for path in (owned_wiki.root / "companies").rglob("*")
        if path.is_file() and not path.name.endswith(".source.json")
    ] == originals


def test_real_cwp_explicit_fmp_does_not_reuse_another_providers_source(
    owned_wiki: OwnedWiki, monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned_wiki.seed_transcript("msft_2026_q3_call.txt", KNOWN_TRANSCRIPT_BODY,
                               MOTLEY_SIDECAR)
    owned_wiki.run_scan()
    monkeypatch.setenv("ET_FIXTURE_PATH", str(UNKNOWN_FIXTURE))

    held = transport(owned_wiki, UNKNOWN_FIXTURE)
    resolved = resolve_companion_transcript(
        request=companion_request(provider="fmp"), filing_handle=filing_handle(),
        transport=held,
    )

    # The explicit constraint is honoured: the motley_fool source is not reused,
    # and the one acquisition is still the configured FMP provider.
    assert resolved["status"] == "downloaded", resolved
    assert resolved["provider"] == "fmp"
    assert len(et_calls(owned_wiki)) == 1
    assert resolved["source_ref"]["content_sha256"] != (
        hashlib.sha256(KNOWN_TRANSCRIPT_BODY).hexdigest()
    )

    replay_transport = transport(owned_wiki, UNKNOWN_FIXTURE)
    replay = resolve_companion_transcript(
        request=companion_request(provider="fmp"), filing_handle=filing_handle(),
        transport=replay_transport,
    )
    assert replay["status"] == "unknown_publication", replay
    assert replay["source_ref"] == resolved["source_ref"]
    assert replay["as_of_cutoff_verified"] is False
    assert replay["provider_calls"] == 0
    assert len(et_calls(owned_wiki)) == 1


def test_real_ff_cli_reuses_the_registered_transcript_end_to_end(
    owned_wiki: OwnedWiki, monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned_wiki.seed_filing("msft_fy2025_10k.htm", b"<html>synthetic 10-K</html>")
    owned_wiki.seed_transcript("msft_2026_q3_call.txt", KNOWN_TRANSCRIPT_BODY,
                               MOTLEY_SIDECAR)
    owned_wiki.run_scan()
    config = owned_wiki.launcher_config(
        earnings_transcripts_tool=str(owned_wiki.et_tool()),
        fmp_api_key_file=str(owned_wiki.key_file()),
    )
    owner = owned_wiki

    def run(request: dict) -> tuple[int, dict, str]:
        process = subprocess.run(
            [
                sys.executable, str(FF_ROOT / "scripts" / "fetch_filing.py"),
                "--config", str(config),
                "--timeout-seconds", "180",
            ],
            input=json.dumps(request).encode("utf-8"),
            cwd=FF_ROOT,
            capture_output=True,
            timeout=300,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        assert process.stdout, process.stderr.decode("utf-8", "replace")
        return (
            process.returncode,
            json.loads(process.stdout.decode("utf-8")),
            process.stderr.decode("utf-8", "replace"),
        )

    request = {
        "schema_version": "2.0",
        "company_query": ENTITY,
        "market": MARKET,
        "document_kind": "annual_report",
        "fiscal_year": 2025,
        "as_of_date": AS_OF,
        "filing_intent": "reuse_only",
        "companion_transcript": companion_request()["companion_transcript"],
    }
    code, payload, stderr = run(request)

    assert code == 0, (payload, stderr)
    assert payload["status"] == "source_candidate", payload
    assert payload["filing"]["status"] == "source_candidate", payload
    transcript = payload.get("transcript") or {}
    assert transcript.get("status") == "reused", payload
    assert transcript.get("provider") == "motley_fool"
    assert transcript.get("provider_calls") == 0
    assert transcript.get("as_of_cutoff_verified") is True
    assert transcript.get("fiscal_year") == 2026
    assert transcript.get("fiscal_quarter") == 3
    assert et_calls(owner) == []
    assert owner.call_log().exists() is False
    # The public envelope exposes the verified source identity, never a path.
    assert transcript["source_ref"]["content_sha256"] == hashlib.sha256(
        KNOWN_TRANSCRIPT_BODY
    ).hexdigest()
    assert str(owner.root) not in json.dumps(payload)
    assert payload["downloads"] == 0

