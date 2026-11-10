"""Behavioral regressions for the shared FF configuration/source boundary."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import fetch_filing
from ff_source_candidate import validate_source_candidate
from filing_contracts import FilingFetchError, validate_handle_metadata, validate_request
from support import bounded_side_effect
from test_source_ref_v2_db_query import (
    _candidate,
    _completed,
    _identity,
    _operation_v2,
    _query,
    _request,
    _v2_request,
    _wiki,
)


@pytest.mark.parametrize("date", ["2026-02-30", "2025-02-29", "2026-13-01", "0000-01-01"])
@pytest.mark.parametrize("schema", ["1.1", "1.2", "2.0"])
def test_invalid_calendar_request_is_rejected_before_any_transport(tmp_path, date, schema):
    request = {**_request(), "schema_version": schema, "as_of_date": date}
    if schema == "2.0":
        request["filing_intent"] = "reuse_only"
    with patch("fetch_filing._run_bounded_json") as transport:
        with pytest.raises(FilingFetchError) as caught:
            fetch_filing.resolve_filing(
                request=request, company_wiki_root=_wiki(tmp_path), source_ref_v2=schema == "2.0"
            )
    assert caught.value.code == "request_error"
    transport.assert_not_called()


def test_valid_leap_day_is_accepted():
    validate_request({**_request(), "as_of_date": "2024-02-29"})


@pytest.mark.parametrize("date", ["2026-02-30", "2025-02-29", "2026-13-01", "0000-01-01"])
def test_invalid_producer_publication_is_an_upstream_error(date):
    candidate = {**_candidate(), "request_id": "test-request", "published_date": date}
    with pytest.raises(FilingFetchError) as caught:
        validate_handle_metadata(candidate, {**_request(), "as_of_date": "9999-12-31"})
    assert caught.value.code == "upstream_error"


@pytest.mark.parametrize("token", ["${unknown}", "${BROKEN", "${}"])
def test_literal_unknown_token_directory_cannot_make_runtime_green(tmp_path, token):
    root = _wiki(tmp_path / token)
    config = tmp_path / "connection.json"
    config.write_text(
        json.dumps({"schema_version": "1.0", "company_wiki_root": str(root)}), encoding="utf-8"
    )
    with pytest.raises(FilingFetchError) as caught:
        fetch_filing.load_company_wiki_root(config_path=config)
    assert caught.value.code == "config_error"


def test_invalid_utf8_config_is_a_named_error(tmp_path):
    config = tmp_path / "connection.json"
    config.write_bytes(b"{\xff}")
    with pytest.raises(FilingFetchError) as caught:
        fetch_filing.load_company_wiki_root(config_path=config)
    assert caught.value.code == "config_error"


@pytest.mark.parametrize("route", ["query", "ensure"])
def test_nested_physical_candidate_fields_never_escape(tmp_path, route):
    candidate = _candidate()
    candidate["metadata"] = {"nested": [{"canonical_path": "fixture-private/original.pdf"}]}
    payload = _query(candidate=candidate) if route == "query" else _operation_v2()
    if route == "ensure":
        payload["candidate"] = candidate
    request = _request() if route == "query" else _v2_request()
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect(
            [
                _completed(_identity()),
                _completed(payload),
            ]
        ),
    ):
        with pytest.raises(FilingFetchError) as caught:
            fetch_filing.resolve_filing(
                request=request, company_wiki_root=_wiki(tmp_path), source_ref_v2=True
            )
    assert caught.value.code == "upstream_error"


@pytest.mark.parametrize("route", ["query", "ensure"])
def test_business_path_label_is_not_a_storage_location(tmp_path, route):
    candidate = _candidate()
    candidate["growth_path"] = "store expansion"
    payload = _query(candidate=candidate) if route == "query" else _operation_v2()
    if route == "ensure":
        payload["candidate"] = candidate
    request = _request() if route == "query" else _v2_request()
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect(
            [
                _completed(_identity()),
                _completed(payload),
            ]
        ),
    ):
        handle = fetch_filing.resolve_filing(
            request=request, company_wiki_root=_wiki(tmp_path), source_ref_v2=True
        )
    assert handle["source_ref"] == candidate["source_ref"]
    assert "growth_path" not in handle
    assert handle["byte_verified"] is False


@pytest.mark.parametrize("route", ["query", "ensure"])
def test_candidate_projection_discards_unknown_metadata_consistently(tmp_path, route):
    candidate = _candidate()
    candidate["unowned_metadata"] = {"internal": "fixture-only"}
    payload = _query(candidate=candidate) if route == "query" else _operation_v2()
    if route == "ensure":
        payload["candidate"] = candidate
    request = _request() if route == "query" else _v2_request()
    with patch(
        "fetch_filing._run_bounded_json",
        side_effect=bounded_side_effect(
            [
                _completed(_identity()),
                _completed(payload),
            ]
        ),
    ):
        handle = fetch_filing.resolve_filing(
            request=request, company_wiki_root=_wiki(tmp_path), source_ref_v2=True
        )
    assert "unowned_metadata" not in handle
    assert "fixture-only" not in json.dumps(handle)


def test_source_candidate_must_match_verified_cross_market_link():
    link_id = "issuer-link-v1:" + "a" * 64
    other_link_id = "issuer-link-v1:" + "b" * 64
    request = {
        **_v2_request(intent="reuse_only"),
        "source_market": "HK", "form_type": "20-F", "fiscal_period": "FY",
    }
    company_identity = {
        **_identity()["resolved"], "issuer_link_id": link_id,
    }
    source_identity = {
        "canonical_name": "Alibaba Group Holding Limited", "market": "HK",
        "security_id": None, "issuer_link_id": link_id,
    }
    candidate = {
        **_candidate(), "market": "HK", "security_id": "09988",
        "issuer_link_id": link_id, "form_type": "20-F", "fiscal_period": "FY",
    }
    handle = validate_source_candidate(
        candidate, candidate["source_ref"], request_id="request", request=request,
        company_identity=company_identity, source_identity=source_identity,
        context="source query",
    )
    assert handle["issuer_link_id"] == link_id
    with pytest.raises(FilingFetchError, match="issuer_link_id mismatch"):
        validate_source_candidate(
            {**candidate, "issuer_link_id": other_link_id}, candidate["source_ref"],
            request_id="request", request=request, company_identity=company_identity,
            source_identity=source_identity, context="source query",
        )


def test_large_valid_config_is_read_completely_before_root_use(tmp_path):
    root = _wiki(tmp_path)
    config = tmp_path / "connection.json"
    data = json.dumps({"schema_version": "1.0", "company_wiki_root": str(root)}).encode()
    complete = data + b" " * 70000
    config.write_bytes(complete)
    assert fetch_filing.load_company_wiki_root(config_path=config) == root
    assert config.read_bytes() == complete
    config.write_bytes(complete + b"\xff")
    with pytest.raises(FilingFetchError) as caught:
        fetch_filing.load_company_wiki_root(config_path=config)
    assert caught.value.code == "config_error"


def test_complete_config_tail_is_not_rejected_by_an_implicit_read_limit(tmp_path, monkeypatch):
    from io import BytesIO
    from pathlib import Path

    root = _wiki(tmp_path)
    config = tmp_path / "connection.json"
    data = b" " * 70000 + json.dumps({"schema_version": "1.0", "company_wiki_root": str(root)}).encode()
    config.write_bytes(data)
    reads = []
    original_open = Path.open

    class CompleteStream(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def open_path(self, *args, **kwargs):
        if self == config:
            return CompleteStream(data)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_path)
    assert fetch_filing.load_company_wiki_root(config_path=config) == root
    assert reads  # Full JSON value lies beyond the retired64KiB boundary.


def test_doctor_uses_runtime_rejection_for_invalid_utf8_and_literals(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "quality_config_doctor", Path(__file__).resolve().parents[1] / "tools" / "config_doctor.py"
    )
    doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(doctor)
    config = tmp_path / "connection.json"
    root = _wiki(tmp_path / "${unknown}")
    for raw in [
        b"{\xff}",
        json.dumps({"schema_version": "1.0", "company_wiki_root": str(root)}).encode(),
    ]:
        config.write_bytes(raw)
        problems, notes = [], []
        assert doctor._check_filing_config(config, problems, notes) is None
        assert len(problems) == 1
        assert notes == []


@pytest.mark.parametrize("field", ["document_id", "source_id", "mime_type"])
def test_et_and_filing_reference_validation_reject_the_same_blank_fields(field):
    from ff_v2_envelope import _reference
    from transcript_tool_transport import EarningsTranscriptsTransport

    candidate = _candidate()["source_ref"]
    candidate[field] = " "
    with pytest.raises(FilingFetchError):
        _reference(candidate)
    with pytest.raises(ValueError):
        EarningsTranscriptsTransport._valid_ref(candidate)


def test_tracked_pre_commit_hook_has_no_machine_specific_python_path():
    from pathlib import Path

    hook = (Path(__file__).resolve().parents[1] / ".githooks" / "pre-commit").read_text(
        encoding="utf-8"
    )
    assert "Miniconda" not in hook
    assert "-m pre_commit" in hook
    assert "ARGS=(" not in hook


def test_portable_hook_executes_existing_check_module_in_active_path(tmp_path):
    import os
    import shutil
    import subprocess
    from pathlib import Path

    shell = shutil.which("sh")
    if shell is None:
        git = shutil.which("git")
        candidates = (
            []
            if git is None
            else [Path(git).parent / "sh.exe", Path(git).parent.parent / "bin" / "sh.exe"]
        )
        shell = next((str(path) for path in candidates if path.is_file()), None)
    if shell is None:
        pytest.skip("POSIX shell is unavailable for the portable Git hook replay")
    executable = tmp_path / "python"
    executable.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$FF_HOOK_ARGV"\nexit 7\n', encoding="utf-8"
    )
    executable.chmod(0o755)
    log = tmp_path / "argv.txt"
    environment = dict(os.environ)
    environment["PATH"] = (
        str(tmp_path) + os.pathsep + str(Path(shell).parent) + os.pathsep + os.defpath
    )
    environment["FF_HOOK_ARGV"] = str(log)
    hook = Path(__file__).resolve().parents[1] / ".githooks" / "pre-commit"
    result = subprocess.run(
        [shell, str(hook), "fixture-argument"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert result.returncode == 7, result.stderr
    arguments = log.read_text(encoding="utf-8").splitlines()
    assert arguments[:3] == ["-m", "pre_commit", "hook-impl"]
    assert "--config=.pre-commit-config.yaml" in arguments
    assert "--hook-type=pre-commit" in arguments
    assert arguments[-2:] == ["--", "fixture-argument"]
    assert not (tmp_path / ".pre-commit-config.yaml").exists()


def test_invalid_physical_root_is_a_named_config_error(tmp_path):
    config = tmp_path / "connection.json"
    config.write_text(
        json.dumps({"schema_version": "1.0", "company_wiki_root": str(tmp_path) + "\0"}),
        encoding="utf-8",
    )
    with pytest.raises(FilingFetchError) as caught:
        fetch_filing.load_company_wiki_root(config_path=config)
    assert caught.value.code == "config_error"


@pytest.mark.parametrize("failure", [OSError, ValueError])
def test_root_resolution_failure_is_consistently_a_config_error(tmp_path, failure):
    from pathlib import Path

    with patch.object(Path, "resolve", side_effect=failure("synthetic invalid physical root")):
        with pytest.raises(FilingFetchError) as caught:
            fetch_filing._validate_company_wiki_root(tmp_path)
    assert caught.value.code == "config_error"
