"""ROOT regression: a replay owns only its exclusive staging/output files."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("du6_portable_helpers", REPO / "tests/test_du6_portable_matrix_evidence.py")
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


@pytest.fixture()
def replay_input(tmp_path):
    report, artifacts = helpers.build_controlled_matrix(tmp_path / "controlled")
    source = tmp_path / "controlled/report.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    return source, artifacts


def invoke(replay_input, output):
    source, artifacts = replay_input
    return helpers.cli_main.main(["replay", "--report", str(source), "--evidence-root", str(artifacts), "--output", str(output)])


def test_preexisting_partial_file_is_not_owned_by_replay(replay_input, tmp_path):
    output = tmp_path / "replay.json"
    existing = output.with_name(output.name + ".partial")
    existing.write_bytes(b"another-writer-staging")
    assert invoke(replay_input, output) == 0
    assert existing.read_bytes() == b"another-writer-staging"
    assert json.loads(output.read_text(encoding="utf-8"))["certified"] is True
    assert sorted(p.name for p in tmp_path.iterdir()) == ["controlled", "replay.json", "replay.json.partial"]


def test_output_created_during_audit_is_never_replaced(replay_input, tmp_path):
    output = tmp_path / "racing-output.json"
    original_audit = helpers.cli_main.oracle_mod.audit
    def concurrent_output(*args, **kwargs):
        findings = original_audit(*args, **kwargs)
        output.write_bytes(b"another-writer-result")
        return findings
    with patch.object(helpers.cli_main.oracle_mod, "audit", side_effect=concurrent_output):
        assert invoke(replay_input, output) == 2
    assert output.read_bytes() == b"another-writer-result"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["controlled", "racing-output.json"]


def test_publish_failure_cleans_only_its_unique_staging(replay_input, tmp_path):
    output = tmp_path / "failed-output.json"
    existing = output.with_name(output.name + ".partial")
    existing.write_bytes(b"another-writer-staging")
    with patch("os.link", side_effect=OSError("synthetic publish failure")):
        assert invoke(replay_input, output) == 2
    assert not output.exists()
    assert existing.read_bytes() == b"another-writer-staging"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["controlled", "failed-output.json.partial"]


def test_serialization_failure_cleans_only_its_unique_staging(replay_input, tmp_path):
    output = tmp_path / "invalid-output.json"
    existing = output.with_name(output.name + ".partial")
    existing.write_bytes(b"another-writer-staging")
    def partial_write(record, stream, **kwargs):
        stream.write("{partial")
        raise OSError("synthetic interrupted write")
    with patch.object(helpers.cli_main.json, "dump", side_effect=partial_write):
        assert invoke(replay_input, output) == 2
    assert not output.exists()
    assert existing.read_bytes() == b"another-writer-staging"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["controlled", "invalid-output.json.partial"]
