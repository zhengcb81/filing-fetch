"""A legacy scope narrows one ensure request; no second discovery/receipt."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from support import bounded_side_effect


@pytest.mark.parametrize("expiry", [None, "2000-01-01T00:00:00Z"])
@pytest.mark.parametrize("producer_gap", [False, True])
def test_legacy_scope_uses_one_ensure_and_cleans_scope_file(tmp_path, expiry, producer_gap):
    from fetch_filing import resolve_filing
    from test_fc802_gap_orchestration import Fc802GapTests

    fixture = Fc802GapTests()
    fixture.parent = tmp_path
    root = fixture._wiki_root(tmp_path, "wiki")
    request = fixture._latest_request()
    request["authorization"] = {"provider": "sec", "allowed_accessions": ["acc-2025"],
                               "max_items": 1, "max_bytes": 5000}
    if expiry is not None:
        request["authorization"]["expires_at"] = expiry
    request["acquisition_limits"] = {"max_bytes": 9000, "timeout_seconds": 30, "max_cost_usd": "0"}
    ensured = fixture._gap_ensure() if producer_gap else {
        "schema_version": "1.0", "status": "imported",
        "resolution": {"schema_version": "1.0", "status": "reused_exact", "request_id": "urn:req:one",
                       "matches": [fixture._handle(root)],
                       "resolution_envelope": {"envelope_schema_version": "1.0", "outcome": "downloaded_new",
                           "download_events": 1, "policy_hash": "b" * 64,
                           "activation_epoch": "epoch-1", "bundle_status": "unavailable"}}}
    responses = [subprocess.CompletedProcess([], 0, json.dumps(fixture._identity_response()), ""),
                 subprocess.CompletedProcess([], 0, json.dumps(ensured), "")]
    commands, scopes = [], []

    def run(argv, **kwargs):
        commands.append(argv)
        if "--binding-file" in argv:
            scope_path = Path(argv[argv.index("--binding-file") + 1])
            scopes.append((scope_path, json.loads(scope_path.read_text(encoding="utf-8"))))
        return bounded_side_effect([responses.pop(0)])[0]

    with patch("fetch_filing._run_bounded_json", side_effect=run):
        result = resolve_filing(request=request, company_wiki_root=root, allow_download=True)
    assert len(commands) == 2
    assert "ensure" in commands[1] and "close-gap" not in commands[1]
    assert "--allow-download" in commands[1]
    assert len(scopes) == 1
    scope_path, scope = scopes[0]
    assert not scope_path.exists()
    assert scope == {"provider": "sec", "allowed_accessions": ["acc-2025"], "max_items": 1, "max_bytes": 5000}
    assert result["status"] == "gap" if producer_gap else result["request_id"] == "urn:req:one"
