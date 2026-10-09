"""FF forwards operation raw limits separately from ET canonical text limits."""
from __future__ import annotations

import json
import time

import pytest

import transcript_tool_transport as module


@pytest.mark.parametrize("raw_limit,body_limit", [(1024, 1024), (128 * 1024 * 1024, 10 * 1024 * 1024)])
def test_actual_et_input_keeps_raw_quota_and_body_contract_separate(tmp_path, monkeypatch, raw_limit, body_limit):
    tool = tmp_path / "transcript_tool.py"
    tool.write_text("# no network; bounded subprocess injected", encoding="utf-8")
    observed = []

    def run(command, *, input_bytes, **kwargs):
        request = json.loads(input_bytes)
        observed.append(request)
        receipt = {"schema_version": "earnings-retrieval-usage/1", "request_id": "wire-budget",
                   "usage_complete": True, "usage": {"requests_used": 1,
                   "response_bytes_used": 1400, "exhausted": "response_bytes"}}
        return (json.dumps({"status": "content_too_large", "error_code": "byte_limit"}).encode(),
                json.dumps(receipt).encode(), 2)

    monkeypatch.setattr(module, "_run_bounded_json", run)
    transport = module.EarningsTranscriptsTransport(wiki_root=tmp_path, transcript_tool=tool,
                                                    deadline=time.monotonic() + 90)
    result = transport._et_result(request={"request_id": "wire-budget", "security_id": "OTHER",
        "exchange": "NASDAQ", "fiscal_year": 2026, "fiscal_quarter": 2,
        "as_of_date": "2026-10-09"}, limits={"max_bytes": raw_limit,
        "timeout_seconds": 30, "max_cost_usd": "0.00"})
    assert len(observed) == 1
    assert observed[0]["max_response_bytes"] == raw_limit
    assert observed[0]["max_body_bytes"] == body_limit
    assert result["status"] == "provider_unavailable"
    assert result["reason"] == "byte_limit"
    assert result["retryable"] is False
    assert result["provider_requests"] == 1
    # Actual already-read consumption is not clamped to the requested allowance.
    assert result["provider_response_bytes"] == 1400
    assert result["provider_usage_complete"] is True


@pytest.mark.parametrize("failure", ["child", "rejected", "bad_ref", "open"])
def test_post_fetch_import_failures_keep_measured_usage_and_never_retry(tmp_path, monkeypatch, failure):
    tool = tmp_path / "offline_tool.py"
    tool.write_text("# mocked before provider execution", encoding="utf-8")
    transport = module.EarningsTranscriptsTransport(wiki_root=tmp_path, transcript_tool=tool,
                                                    deadline=time.monotonic() + 90)
    identity = {"canonical_name": "Microsoft Corporation", "market": "US",
                "security_id": "MSFT", "exchange": "NASDAQ"}
    kwargs = {"identity": identity, "fiscal_year": 2026, "fiscal_quarter": 3,
              "as_of_date": "2026-10-09"}
    transport._pending = {"source_request": {}, "request_id": "post-fetch", "kwargs": kwargs}
    usage = {"provider_requests": 1, "provider_response_bytes": 1024,
             "provider_usage_complete": True}

    def et_result(**ignored):
        transport._last_provider_usage = usage
        return {"status": "fetched", "request_id": "post-fetch",
                "provider_payload_sha256": "a" * 64}

    def import_result(*ignored, **ignored_kwargs):
        if failure == "child":
            from ff_process_transport import ChildFailed
            raise ChildFailed("rejected", returncode=2, stdout=b'{"status":"rejected"}')
        if failure == "rejected":
            return {"schema_version": "company-wiki-transcript-import-response/3",
                    "status": "rejected"}, 0
        return {"schema_version": "company-wiki-transcript-import-response/3",
                "status": "imported", "source_ref": {}}, 0

    monkeypatch.setattr(transport, "_et_result", et_result)
    monkeypatch.setattr(transport, "_candidate", lambda *ignored: {})
    monkeypatch.setattr(transport, "_run_json", import_result)
    if failure == "open":
        monkeypatch.setattr(transport, "_valid_ref", lambda ignored: {"content_sha256": "a" * 64})
        def broken_open(ignored):
            raise OSError("owned read failure after provider finished")
        monkeypatch.setattr(transport, "_verified_open", broken_open)
    result = transport.acquire_exact(**kwargs, acquisition_limits={"max_bytes": 4096,
        "timeout_seconds": 30, "max_cost_usd": "0.00"})
    assert result["status"] == "upstream_error"
    assert result["retryable"] is False
    assert result["provider_calls"] == 1
    assert all(result.get(key) == value for key, value in usage.items())
