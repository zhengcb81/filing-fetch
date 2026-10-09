"""Explicit reuse misses can prepare existing local originals through CWP."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import fetch_filing
from filing_contracts import FilingFetchError
from support import bounded_side_effect
from test_source_ref_v2_db_query import _completed, _identity, _query, _ref, _v2_request, _wiki


def _reuse_request():
    request = _v2_request(intent="reuse_only")
    request.pop("acquisition_limits")
    return request


def _prepared(status="ready", **changes):
    return {
        "schema_version": "local-source-prepare/1", "status": status,
        "reason": "verified_local_original" if status == "ready" else "no_local_original",
        "source_ref": _ref() if status == "ready" else None,
        "blocks_download": status in {"blocked", "unavailable", "ambiguous"},
        "operations": [], "diagnostics": [], "download_events": 0, **changes,
    }


def test_reuse_only_missing_index_prepares_local_then_queries_same_request(tmp_path):
    stats = {"calls": 0, "downloads": 0}
    responses = [_identity(), _query("not_found"), _prepared(), _query()]
    with patch("fetch_filing._run_bounded_json",
               side_effect=bounded_side_effect([_completed(r) for r in responses])) as run:
        result = fetch_filing.resolve_filing(
            request=_reuse_request(), company_wiki_root=_wiki(tmp_path),
            source_ref_v2=True, stats=stats,
        )
    commands = [c.args[0] for c in run.call_args_list]
    assert len(commands) == stats["calls"] == 4
    assert "company_wiki.source_catalog.local_prepare_cli" in commands[2]
    assert commands[2][-2:] == ["--request", "-"]
    assert "company_wiki.source_catalog.source_query_cli" in commands[3]
    assert result["source_ref"] == _ref()
    assert result["download_events"] == stats["downloads"] == 0
    local_request = json.loads(run.call_args_list[2].kwargs["input_bytes"])
    assert local_request["schema_version"] == "local-source-prepare-request/1"
    assert local_request["source_request"]["entity"] == "Advanced Micro Devices, Inc."
    assert local_request["source_request"]["allow_download"] is False
    assert local_request["limits"]["max_candidates"] == 64
    assert local_request["limits"]["max_bytes"] == 128 * 1024 * 1024
    assert 0 < local_request["limits"]["timeout_seconds"] <= 600
    assert all("fetch" not in c and "ensure" not in c for c in commands)


def test_active_reuse_only_hit_has_no_extra_local_preparation(tmp_path):
    with patch("fetch_filing._run_bounded_json", side_effect=bounded_side_effect([
        _completed(_identity()), _completed(_query()),
    ])) as run:
        fetch_filing.resolve_filing(request=_reuse_request(),
                                   company_wiki_root=_wiki(tmp_path), source_ref_v2=True)
    assert len(run.call_args_list) == 2


@pytest.mark.parametrize("status,code", [
    ("not_found", "not_found"), ("blocked", "source_blocked"),
    ("unavailable", "upstream_error"), ("ambiguous", "ambiguous"),
])
def test_local_gap_does_not_download_or_repeat_query(tmp_path, status, code):
    with patch("fetch_filing._run_bounded_json", side_effect=bounded_side_effect([
        _completed(_identity()), _completed(_query("not_found")), _completed(_prepared(status)),
    ])) as run:
        with pytest.raises(FilingFetchError) as caught:
            fetch_filing.resolve_filing(request=_reuse_request(),
                                       company_wiki_root=_wiki(tmp_path), source_ref_v2=True)
    assert caught.value.code == code
    assert len(run.call_args_list) == 3


@pytest.mark.parametrize("change", [
    {"schema_version": "unknown"}, {"download_events": 1},
    {"diagnostics": [{"canonical_path": "unwanted/file.txt"}]},
    {"source_ref": {"schema_version": "2.0", "content_sha256": "bad"}},
])
def test_invalid_prepare_receipt_does_not_become_a_candidate(tmp_path, change):
    with patch("fetch_filing._run_bounded_json", side_effect=bounded_side_effect([
        _completed(_identity()), _completed(_query("not_found")), _completed(_prepared(**change)),
    ])) as run:
        with pytest.raises(FilingFetchError) as caught:
            fetch_filing.resolve_filing(request=_reuse_request(),
                                       company_wiki_root=_wiki(tmp_path), source_ref_v2=True)
    assert caught.value.code == "upstream_error"
    assert len(run.call_args_list) == 3
