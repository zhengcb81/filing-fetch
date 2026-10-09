"""W07 safe configured credential launch contracts; no live provider calls."""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import transcript_tool_transport as transport_module  # noqa: E402

SENTINEL = "w07-synthetic-credential-never-public"


@pytest.fixture(autouse=True)
def isolated_launch_environment(monkeypatch, tmp_path):
    # A failing mock must never expose the host process environment.
    safe = {name: transport_module.os.environ[name] for name in ("SYSTEMROOT", "PATH", "TEMP", "TMP", "PYTHONUTF8", "W07_ET_TOOL") if name in transport_module.os.environ}
    safe["USERPROFILE"] = str(tmp_path / "synthetic-profile")
    safe["HOME"] = str(tmp_path / "synthetic-profile")
    monkeypatch.setattr(transport_module.os, "environ", safe)


def _request():
    return {"request_id": "w07", "security_id": "MSFT", "exchange": "NASDAQ",
            "fiscal_year": 2026, "fiscal_quarter": 4, "as_of_date": "2026-10-08"}


def _limits():
    return {"timeout_seconds": 10, "max_bytes": 1000000, "max_cost_usd": "0.00"}


def _transport(tmp_path):
    tool = tmp_path / "transcript_tool.py"
    tool.write_text("# injected fixture", encoding="utf-8")
    return transport_module.EarningsTranscriptsTransport(
        wiki_root=tmp_path, transcript_tool=tool, deadline=time.monotonic() + 30)


def _failure(error_code="provider_entitlement_required"):
    result = {"schema_version": "earnings-transcript-result/2", "request_id": "w07",
              "status": "unavailable", "provider": "fmp", "error_code": error_code}
    usage = {"schema_version": "earnings-retrieval-usage/1", "request_id": "w07",
             "usage_complete": True, "usage": {"requests_used": 1, "response_bytes_used": 12}}
    return json.dumps(result).encode(), json.dumps(usage).encode(), 0


def test_explicit_key_file_reaches_only_et_environment(tmp_path, monkeypatch):
    key_file = tmp_path / "sentinel.key"
    key_file.write_text(SENTINEL + "\n", encoding="utf-8")
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("FMP_API_KEY_FILE", str(key_file))
    seen = []
    def run(command, *, env, input_bytes, **kwargs):
        seen.append((command, env, input_bytes))
        assert bool(env.get("FMP_API_KEY") == SENTINEL)
        assert "FMP_API_KEY_FILE" not in env
        assert SENTINEL.encode() not in input_bytes
        assert SENTINEL not in " ".join(command)
        return _failure()
    monkeypatch.setattr(transport_module, "_run_bounded_json", run)
    transport = _transport(tmp_path)
    result = transport._et_result(request=_request(), limits=_limits())
    assert result["reason"] == "provider_entitlement_required"
    assert result["provider_requests"] == 1
    assert SENTINEL not in json.dumps(result)
    assert len(seen) == 1
    wiki_env = transport._wiki_env()
    assert "FMP_API_KEY" not in wiki_env
    assert "FMP_API_KEY_FILE" not in wiki_env
    assert key_file.read_text(encoding="utf-8").strip() == SENTINEL


@pytest.mark.parametrize("kind,reason", [("absent", "provider_credentials_file_unavailable"),
    ("empty", "provider_credentials_file_empty"), ("invalid", "provider_credentials_file_invalid")])
def test_bad_explicit_source_does_not_fall_back_or_start_et(tmp_path, monkeypatch, kind, reason):
    key_file = tmp_path / "configured.key"
    if kind == "empty":
        key_file.write_text(" \n", encoding="utf-8")
    if kind == "invalid":
        key_file.write_bytes(b"first\nsecond")
    monkeypatch.setenv("FMP_API_KEY_FILE", str(key_file))
    monkeypatch.setenv("FMP_API_KEY", "unused-synthetic-fallback")
    def forbidden(*args, **kwargs):
        pytest.fail("invalid explicit credentials must not launch a child")
    monkeypatch.setattr(transport_module, "_run_bounded_json", forbidden)
    result = _transport(tmp_path)._et_result(request=_request(), limits=_limits())
    assert result["reason"] == reason
    assert result["provider_requests"] == 0 and result["provider_response_bytes"] == 0
    assert result["provider_usage_complete"] is True
    assert str(key_file) not in json.dumps(result)


@pytest.mark.parametrize("stream", ["stdout", "stderr", "payload"])
def test_child_secret_echo_is_rejected_without_exposing_or_rewriting_bytes(tmp_path, monkeypatch, stream):
    monkeypatch.delenv("FMP_API_KEY_FILE", raising=False)
    monkeypatch.setenv("FMP_API_KEY", SENTINEL)
    def run(*args, **kwargs):
        out, err, code = _failure()
        if stream == "stdout":
            out = out[:-1] + b',"detail":"' + SENTINEL.encode() + b'"}'
        elif stream == "payload":
            out = json.dumps({"status": "fetched", "provider_payload_base64":
                base64.b64encode(SENTINEL.encode()).decode()}).encode()
        else:
            err += SENTINEL.encode()
        return out, err, code
    monkeypatch.setattr(transport_module, "_run_bounded_json", run)
    result = _transport(tmp_path)._et_result(request=_request(), limits=_limits())
    assert result["reason"] == "provider_credentials_leaked"
    assert SENTINEL not in json.dumps(result)
    assert result["retryable"] is False
    assert result["provider_started"] is (None if stream == "stderr" else True)
    assert result["provider_requests"] == (None if stream == "stderr" else 1)


def test_no_configured_key_remains_et_measured_missing_not_fabricated_auth(tmp_path, monkeypatch):
    monkeypatch.delenv("FMP_API_KEY_FILE", raising=False)
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    def run(command, *, env, **kwargs):
        assert "FMP_API_KEY" not in env
        out, _, code = _failure("provider_credentials_missing")
        usage = {"schema_version": "earnings-retrieval-usage/1", "request_id": "w07",
                 "usage_complete": True, "usage": {"requests_used": 0, "response_bytes_used": 0}}
        return out, json.dumps(usage).encode(), code
    monkeypatch.setattr(transport_module, "_run_bounded_json", run)
    result = _transport(tmp_path)._et_result(request=_request(), limits=_limits())
    assert result["reason"] == "provider_credentials_missing"
    assert result["provider_requests"] == 0


def test_selected_ff_config_reuses_the_previously_configured_known_file(tmp_path, monkeypatch):
    config_dir = tmp_path / "configuration"
    config_dir.mkdir()
    config = config_dir / "company_wiki.json"
    config.write_text('{"schema_version":"1.0"}', encoding="utf-8")
    key = config_dir / "FMP_API_KEY.txt"
    key.write_text(SENTINEL, encoding="utf-8")
    transport = _transport(tmp_path)
    transport.config_path = config
    def run(command, *, env, input_bytes, **kwargs):
        assert bool(env.get("FMP_API_KEY") == SENTINEL)
        assert SENTINEL.encode() not in input_bytes
        return _failure()
    monkeypatch.setattr(transport_module, "_run_bounded_json", run)
    result = transport._et_result(request=_request(), limits=_limits())
    assert result["reason"] == "provider_entitlement_required"
    assert result["provider_started"] is True


def test_configured_relative_file_resolves_against_selected_config_not_cwd(tmp_path, monkeypatch):
    directory = tmp_path / "configured"
    directory.mkdir()
    config = directory / "company_wiki.json"
    config.write_text('{"fmp_api_key_file":"keys/test.key"}', encoding="utf-8")
    key = directory / "keys" / "test.key"
    key.parent.mkdir()
    key.write_text(SENTINEL, encoding="utf-8")
    transport = _transport(tmp_path)
    transport.config_path = config
    env, credential = transport._et_environment()
    assert bool(credential == SENTINEL)
    assert bool(env.get("FMP_API_KEY") == SENTINEL)
    assert "FMP_API_KEY_FILE" not in env


@pytest.mark.parametrize("started", [None, False, True])
def test_usage_started_survives_companion_and_public_v2_serializer(started):
    from transcript_companion import resolve_companion_transcript
    from ff_v2_envelope import success_envelope
    from test_transcript_companion_transport import _request as companion_request, _filing
    class Port:
        def lookup_exact(self, **kwargs):
            return None
        def acquire_exact(self, **kwargs):
            return {"status": "provider_unavailable", "reason": "unsupported_market",
                    "provider_calls": 0, "provider_requests": None if started is None else int(started),
                    "provider_response_bytes": None if started is None else 0,
                    "provider_usage_complete": started is not None, "provider_started": started}
    filing = _filing()
    filing["download_events"] = 0
    result = resolve_companion_transcript(request=companion_request(), filing_handle=filing, transport=Port())
    assert result["provider_started"] is started
    envelope = success_envelope(companion_request(), filing, result, {"calls": 1, "downloads": 0})
    assert envelope["status"] == "source_candidate"
    assert envelope["transcript"]["provider_started"] is started
    assert envelope["filing"]["source_ref"] == filing["source_ref"]


@pytest.mark.parametrize("exchange,reason", [("HKEX", "unsupported_market"),
    ("NASDAQ", "provider_credentials_missing"), ("TOKYO", "unsupported_exchange")])
def test_ff_real_et_cli_preserves_filing_and_measured_pre_http_zero(tmp_path, exchange, reason):
    from transcript_companion import resolve_companion_transcript
    from ff_v2_envelope import success_envelope
    from test_transcript_companion_transport import _request as companion_request, _filing
    configured = transport_module.os.environ.get("W07_ET_TOOL")
    if not configured:
        pytest.skip("W07 real ET checkout integration requires an explicit test tool path")
    tool = Path(configured)
    assert tool.is_file()
    transport = transport_module.EarningsTranscriptsTransport(wiki_root=tmp_path,
        transcript_tool=tool, deadline=time.monotonic() + 30)
    def empty_cwp_lookup(**kwargs):
        transport._pending = {"request_id": "w07", "kwargs": kwargs,
            "source_request": transport._source_request(identity=kwargs["identity"],
                fiscal_year=kwargs["fiscal_year"], fiscal_quarter=kwargs["fiscal_quarter"],
                as_of_date=kwargs["as_of_date"], allow_download=False)}
        return None
    transport.lookup_exact = empty_cwp_lookup
    filing = _filing()
    filing["company_identity"]["exchange"] = exchange
    if exchange == "HKEX":
        filing["company_identity"].update(market="HK", security_id="00700", ticker="00700")
    result = resolve_companion_transcript(request=companion_request(), filing_handle=filing, transport=transport)
    assert result["status"] == "provider_unavailable", result.get("reason")
    assert result["reason"] == reason
    assert result["provider_calls"] == 0
    assert result["provider_requests"] == 0
    assert result["provider_response_bytes"] == 0
    assert result["provider_usage_complete"] is True
    assert result["provider_started"] is False
    envelope = success_envelope(companion_request(), filing, result, {"calls": 0, "downloads": 0})
    assert envelope["status"] == "source_candidate"
    assert envelope["filing"]["source_ref"] == filing["source_ref"]
    assert envelope["transcript"]["provider_started"] is False


def test_real_ff_config_loader_accepts_only_additive_credential_source_path(tmp_path):
    from fetch_filing import load_company_wiki_root
    wiki = tmp_path / "wiki"
    (wiki / "config").mkdir(parents=True)
    (wiki / "config" / "source_catalog.yaml").write_text("fixture", encoding="utf-8")
    config = tmp_path / "company_wiki.json"
    config.write_text(json.dumps({"schema_version": "1.0", "company_wiki_root": str(wiki),
                                 "fmp_api_key_file": "keys/explicit.key"}), encoding="utf-8")
    assert load_company_wiki_root(config_path=config) == wiki.resolve()


@pytest.mark.parametrize("invalid", [None, {}, "", "  "])
def test_real_ff_config_loader_rejects_malformed_source_without_reading_keys(tmp_path, invalid):
    from fetch_filing import load_company_wiki_root
    from filing_contracts import FilingFetchError
    config = tmp_path / "company_wiki.json"
    config.write_text(json.dumps({"schema_version": "1.0", "company_wiki_root": str(tmp_path),
                                 "fmp_api_key_file": invalid}), encoding="utf-8")
    with pytest.raises(FilingFetchError) as caught:
        load_company_wiki_root(config_path=config)
    assert caught.value.code == "config_error"


def test_config_doctor_and_runtime_accept_the_same_optional_source_field(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("w07_config_doctor",
        Path(__file__).resolve().parents[1] / "tools" / "config_doctor.py")
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    wiki = tmp_path / "wiki"
    (wiki / "config").mkdir(parents=True)
    (wiki / "config" / "source_catalog.yaml").write_text("fixture", encoding="utf-8")
    config = tmp_path / "company_wiki.json"
    payload = {"schema_version": "1.0", "company_wiki_root": str(wiki), "fmp_api_key_file": "keys/explicit.key"}
    config.write_text(json.dumps(payload), encoding="utf-8")
    problems, notes = [], []
    assert doctor._check_filing_config(config, problems, notes) == wiki
    assert problems == []
    payload["fmp_api_key_file"] = {}
    config.write_text(json.dumps(payload), encoding="utf-8")
    problems, notes = [], []
    assert doctor._check_filing_config(config, problems, notes) is None
    assert len(problems) == 1
    assert "fmp_api_key_file" in problems[0]


@pytest.mark.parametrize("status,reason", [("unsupported", "unsupported_market"),
    ("unsupported", "unsupported_exchange"),
    ("unavailable", "provider_credentials_file_unavailable"),
    ("unavailable", "provider_credentials_file_empty"),
    ("unavailable", "provider_credentials_file_invalid"),
    ("unavailable", "provider_credentials_rejected"),
    ("provider_error", "provider_credentials_leaked")])
def test_wire_validator_accepts_typed_capability_and_credential_failures(status, reason):
    from et_v2_contract import normalize_et_v2_result
    result = {"schema_version": "earnings-transcript-result/2", "request_id": "w07",
              "status": status, "error_code": reason, "provider": "fmp"}
    request = {"schema_version": "earnings-transcript-request/1", "request_id": "w07", "provider": "fmp"}
    validated = normalize_et_v2_result(result, request)
    assert validated["status"] == "provider_unavailable"
    assert validated["reason"] == reason
