"""W20 replay: FF fault classification at the ET boundary (offline unit).

These prove the product-side behaviour the matrix fault cases rely on, using
the established offline child-process seam (``_run_bounded_json`` stand-in):
a truncated ET result stream, a nonzero tool exit after a complete result, a
usage receipt that belongs to another request, a truncated usage receipt and a
lying payload digest are each classified as named failures or preserved
unknowns — never a fake success, never a swallowed call, never a blind retry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

import sys

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
MATRIX = Path(__file__).resolve().parents[1] / "tools" / "offline_contract_matrix"
if str(MATRIX) not in sys.path:
    sys.path.insert(0, str(MATRIX))

from transcript_companion import resolve_companion_transcript  # noqa: E402

from test_du11_transcript_reuse_contract import (  # noqa: E402
    FMP_PAYLOAD,
    FakeCWP,
    REQUEST_ID,
    build,
    companion_request,
    fetched_result,
    filing,
    imported_result,
    query_not_found,
    reader_entry,
)


@pytest.fixture
def tool(tmp_path: Path) -> Path:
    path = tmp_path / "transcript_tool.py"
    path.write_text("# offline fixture; the process is injected\n", encoding="utf-8")
    return path


class FaultyET(FakeCWP):
    """The established offline child seam plus ET stream-level faults."""

    def __init__(
        self,
        *,
        et_stdout: Callable[[bytes], bytes] | None = None,
        et_usage: Callable[[bytes], bytes] | None = None,
        et_rc: int = 0,
        fetched: dict[str, Any] | None = None,
        imported: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(fetched=fetched or fetched_result(),
                         imported=imported or imported_result(), **kwargs)
        self.et_stdout = et_stdout
        self.et_usage = et_usage
        self.et_rc = et_rc

    def __call__(self, command, *, input_bytes=None, timeout_seconds=None, **kwargs):
        if self.tool is not None and str(self.tool) in command:
            self.calls.append(("et", list(command), input_bytes))
            stdout = json.dumps(self.fetched).encode("utf-8")
            if self.et_stdout is not None:
                stdout = self.et_stdout(stdout)
            usage = json.dumps({
                "schema_version": "earnings-retrieval-usage/1",
                "request_id": REQUEST_ID,
                "usage_complete": True,
                "usage": {"requests_used": 1, "response_bytes_used": 512},
            }).encode("utf-8")
            if self.et_usage is not None:
                usage = self.et_usage(usage)
            return stdout, usage, self.et_rc
        return super().__call__(command, input_bytes=input_bytes,
                                timeout_seconds=timeout_seconds, **kwargs)


def _acquire(monkeypatch: pytest.MonkeyPatch, fake: FaultyET, tool: Path) -> dict[str, Any]:
    transport = build(monkeypatch, fake, tool)
    return resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(), transport=transport,
    )


def test_truncated_et_result_is_a_named_invalid_and_never_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FaultyET(
        queries=[query_not_found()],
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
        et_stdout=lambda raw: raw[: max(1, len(raw) // 2)],
    )
    result = _acquire(monkeypatch, fake, tool)
    assert result["status"] == "provider_unavailable", result
    assert result["reason"] == "provider_result_invalid"
    assert result["provider_calls"] == 1
    assert "source_ref" not in result
    assert fake.count("et") == 1
    assert fake.count("import") == 0


def test_nonzero_tool_exit_on_the_seam_path_is_a_named_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    """The offline seam returns the exit code directly, reaching the
    ``code != 0`` projection (``provider_tool_failed``)."""
    fake = FaultyET(
        queries=[query_not_found()],
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
        et_rc=1,
    )
    result = _acquire(monkeypatch, fake, tool)
    assert result["status"] == "provider_unavailable", result
    assert result["reason"] == "provider_tool_failed"
    assert result["provider_calls"] == 1
    assert fake.count("import") == 0


def test_nonzero_tool_exit_on_the_subprocess_path_is_also_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    """A real subprocess raises ChildFailed (a TransportError) with the bytes
    captured; FF projects it onto the shared transport-failure reason
    ``provider_result_oversized`` while preserving the call. A named,
    call-preserving rejection either way — this pins the dual-path
    classification honestly instead of hiding it."""
    import ff_process_transport

    class SubprocessFault(FaultyET):
        def __call__(self, command, *, input_bytes=None, timeout_seconds=None, **kwargs):
            if self.tool is not None and str(self.tool) in command:
                self.calls.append(("et", list(command), input_bytes))
                raise ff_process_transport.ChildFailed(
                    "child exited 1", returncode=1,
                    stdout=json.dumps(fetched_result()).encode("utf-8"),
                    stderr=b"",
                )
            return super().__call__(command, input_bytes=input_bytes,
                                    timeout_seconds=timeout_seconds, **kwargs)

    fake = SubprocessFault(
        queries=[query_not_found()],
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
    )
    result = _acquire(monkeypatch, fake, tool)
    assert result["status"] == "provider_unavailable", result
    assert result["reason"] == "provider_result_oversized"
    assert result["provider_calls"] == 1
    assert fake.count("import") == 0


def test_stale_usage_receipt_stays_unknown_and_never_zeroes_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    def stale(receipt: bytes) -> bytes:
        payload = json.loads(receipt)
        payload["request_id"] = "urn:company-wiki:source-request:sha256:" + "0" * 64
        return json.dumps(payload).encode("utf-8")

    fake = FaultyET(
        queries=[query_not_found()],
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
        et_usage=stale,
    )
    result = _acquire(monkeypatch, fake, tool)
    assert result["status"] == "downloaded", result
    assert result["provider_requests"] is None
    assert result["provider_usage_complete"] is False
    assert result["provider_calls"] == 1
    assert fake.count("import") == 1


def test_truncated_usage_receipt_stays_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    fake = FaultyET(
        queries=[query_not_found()],
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
        et_usage=lambda raw: raw[: max(1, len(raw) // 2)],
    )
    result = _acquire(monkeypatch, fake, tool)
    assert result["status"] == "downloaded", result
    assert result["provider_requests"] is None
    assert result["provider_usage_complete"] is False


def test_lying_payload_digest_is_rejected_after_import_with_no_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: Path
) -> None:
    lying = fetched_result()
    lying["provider_payload_sha256"] = "0" * 64
    fake = FaultyET(
        queries=[query_not_found()],
        reader=[reader_entry(FMP_PAYLOAD, provider="fmp")],
        tool=tool,
        fetched=lying,
    )
    result = _acquire(monkeypatch, fake, tool)
    assert result["status"] == "upstream_error", result
    assert result["reason"] == "transcript_import_hash_mismatch"
    assert result["provider_calls"] == 1
    assert fake.count("et") == 1
    assert fake.count("import") == 1


# ── test-proxy fault shaping (pure functions) ─────────────────────────────


def _proxy():
    from et_transcript_proxy import _apply_result_fault, _apply_usage_fault
    return _apply_result_fault, _apply_usage_fault


def test_proxy_fault_shaping_matches_the_declared_scenarios() -> None:
    result_fault, usage_fault = _proxy()
    result = json.dumps({"status": "fetched", "provider_payload_sha256": "a" * 64,
                         "canonical_content_sha256": "b" * 64})
    truncated, rc = result_fault(result, "truncated_json")
    assert rc is None and len(truncated) == len(result) // 2
    lied, rc = result_fault(result, "hash_lie")
    assert rc is None
    payload = json.loads(lied)
    assert payload["provider_payload_sha256"] == "0" * 64
    assert payload["canonical_content_sha256"] == "0" * 64
    same, forced = result_fault(result, "crash_after_result")
    assert same == result and forced == 1
    untouched, none_rc = result_fault(result, "success")
    assert untouched == result and none_rc is None
    usage = json.dumps({"schema_version": "earnings-retrieval-usage/1",
                        "request_id": "urn:x:1", "usage_complete": True,
                        "usage": {"requests_used": 1, "response_bytes_used": 10}})
    stale = json.loads(usage_fault(usage, "stale_usage"))
    assert stale["request_id"] != "urn:x:1"
    assert usage_fault(usage, "truncated_usage") == usage[: len(usage) // 2]
    assert usage_fault(usage, "success") == usage


def test_proxy_hash_lie_leaves_non_fetched_results_untouched() -> None:
    result_fault, _usage = _proxy()
    not_found = json.dumps({"status": "not_found", "request_id": "r"})
    assert result_fault(not_found, "hash_lie")[0] == not_found
