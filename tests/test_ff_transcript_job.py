from __future__ import annotations

import pytest

import fetch_filing
from ff_job_contracts import FFJobError, validate_submit_body
from ff_job_runner import act, run_job
from ff_job_store import JobStore
import transcript_tool_transport


_REF = {"schema_version": "2.0", "document_id": "call-doc", "source_id": "call-src",
        "content_sha256": "a" * 64, "byte_size": 400, "mime_type": "text/plain"}


def body():
    return {
        "schema_version": "ff-job/1", "command_id": "schedule-run", "kind": "transcript.acquire",
        "idempotency_key": "scheduled-transcript-job",
        "request": {
            "schema_version": "ff-transcript-request/1",
            "identity": {"entity_id": "company", "listing_id": "listing", "market": "US", "ticker": "SYN"},
            "fiscal_year": 2026, "fiscal_quarter": 3, "as_of_date": "2026-11-10",
            "intent": "fetch_if_missing",
            "acquisition_limits": {"max_bytes": 20000, "timeout_seconds": 9, "max_cost_usd": "0.00"},
        },
    }


def fake_transport(monkeypatch, root, *, lose_reply=False):
    monkeypatch.setattr(fetch_filing, "load_company_wiki_root", lambda **_: root)
    monkeypatch.setattr(fetch_filing, "identify_company", lambda **_: {
        "market": "US", "ticker": "SYN", "verified": True, "active": True,
        "security_id": "SYN:US",
    })

    class Transport:
        company_wiki_calls = 0
        acquired = 0
        found = False

        def lookup_exact(self, **scope):
            assert scope["fiscal_quarter"] == 3 and scope["filing_source_ref"] is None
            if self.found:
                return {"status": "found", "source_ref": _REF}
            return None

        def acquire_exact(self, **scope):
            self.acquired += 1
            self.found = True
            assert scope["fiscal_year"] == 2026 and scope["filing_source_ref"] is None
            if lose_reply:
                return {"status": "upstream_error", "reason": "provider_timeout",
                        "provider_started": True, "provider_usage_complete": False}
            return {"status": "downloaded", "source_ref": _REF, "provider_started": True,
                    "provider_usage_complete": True, "provider_requests": 1,
                    "provider_response_bytes": 500}

    transport = Transport()
    monkeypatch.setattr(transcript_tool_transport, "EarningsTranscriptsTransport", lambda **_: transport)
    return transport


def test_transcript_job_downloads_a_call_without_a_filing(tmp_path, monkeypatch):
    transport = fake_transport(monkeypatch, tmp_path)
    store = JobStore(tmp_path / "jobs")
    record, _ = store.create_job(validate_submit_body(body()), command_id="schedule-run")
    job, executed = run_job(store, record["owner_job_id"], config_path=None, timeout_seconds=12)
    assert executed and job["status"] == "succeeded"
    assert job["result"]["source_ref"] == _REF and job["result"]["downloads"] == 1
    assert job["result"]["provider_requests"] == 1 and job["cost_state"] == "unknown"
    assert not run_job(store, record["owner_job_id"], config_path=None, timeout_seconds=12)[1]
    assert transport.acquired == 1


def test_transcript_job_reuses_existing_txt_without_contacting_provider(tmp_path, monkeypatch):
    transport = fake_transport(monkeypatch, tmp_path)
    transport.found = True
    store = JobStore(tmp_path / "jobs")
    record, _ = store.create_job(validate_submit_body(body()), command_id="schedule-run")
    job, executed = run_job(store, record["owner_job_id"], config_path=None, timeout_seconds=12)
    assert executed and job["status"] == "succeeded"
    assert job["result"]["source_ref"] == _REF and job["result"]["downloads"] == 0
    assert job["cost_state"] == "known" and job["cost"]["value"] == "0.00"
    assert transport.acquired == 0


def test_transcript_timeout_recovers_by_lookup_without_retry(tmp_path, monkeypatch):
    transport = fake_transport(monkeypatch, tmp_path, lose_reply=True)
    store = JobStore(tmp_path / "jobs")
    record, _ = store.create_job(validate_submit_body(body()), command_id="schedule-run")
    job_id = record["owner_job_id"]
    lost, _ = run_job(store, job_id, config_path=None, timeout_seconds=12)
    assert lost["status"] == "unknown" and lost["cost_state"] == "unknown"
    restored, _ = act(store, job_id, action="reconcile", idempotency_key="restore-call")
    assert restored["status"] == "succeeded" and restored["result"]["source_ref"] == _REF
    assert restored["cost_state"] == "unknown"
    assert transport.acquired == 1


def test_annual_disclosure_does_not_supply_a_transcript_quarter():
    request = body()
    del request["request"]["fiscal_quarter"]
    with pytest.raises(FFJobError, match="fiscal"):
        validate_submit_body(request)
