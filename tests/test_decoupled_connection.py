"""A configured CWP connection is opaque to all FF domain operations."""
import json
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ff_configuration import load_connection_root  # noqa: E402
from ff_company_wiki_connection import command_for, connection_cwd  # noqa: E402


def test_external_connection_has_no_catalog_layout_requirement(tmp_path):
    config = tmp_path / "connection.json"
    operations = ["catalog", "query", "local_prepare", "open", "transcript_import", "financial_statements"]
    commands = {name: [sys.executable, "independent-service.py", name] for name in operations}
    config.write_text(json.dumps({"schema_version": "1.0", "connection": {
        "cwd": str(tmp_path), "commands": commands}}), encoding="utf-8")
    endpoint = load_connection_root(config, skill_root=ROOT)
    assert connection_cwd(endpoint) == tmp_path
    for name in operations:
        assert command_for(endpoint, name) == commands[name]
    assert not (tmp_path / "config/source_catalog.yaml").exists()


def test_missing_operation_never_falls_back_to_an_unconfigured_producer(tmp_path):
    config = tmp_path / "connection.json"
    config.write_text(json.dumps({"schema_version": "1.0", "connection": {
        "cwd": str(tmp_path), "commands": {"query": ["external-query"]}}}), encoding="utf-8")
    endpoint = load_connection_root(config, skill_root=ROOT)
    with pytest.raises(ValueError, match="operation"):
        command_for(endpoint, "transcript_import")


def test_transcript_and_statements_use_same_connection(tmp_path, monkeypatch):
    from ff_company_wiki_connection import WikiConnection
    from transcript_tool_transport import EarningsTranscriptsTransport
    from ff_financial_statements import build_cwp_command
    endpoint = WikiConnection(tmp_path, {"query": ("external-query",),
        "open": ("external-open",), "transcript_import": ("external-import",),
        "financial_statements": ("external-statements",)})
    transport = EarningsTranscriptsTransport(wiki_root=endpoint, deadline=time.monotonic()+30)
    def response(command, payload, **kw):
        assert command == ["external-query"]
        assert kw["cwd"] == tmp_path
        return {"schema_version": "2.0"}, 0
    monkeypatch.setattr(transport, "_run_json", response)
    transport._query_local({})
    assert build_cwp_command(endpoint) == ["external-statements"]
