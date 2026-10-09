"""Complexity is observable maintenance data, not a source-code permit."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "complexity_diagnostics.py"
SIMPLE = "def decide(value):\n    return value\n"
BRANCHED = "def decide(value):\n" + "    if value:\n        pass\n" * 12 + "    return value\n"


def _tool():
    assert TOOL.is_file(), "runnable diagnostic missing"
    spec = importlib.util.spec_from_file_location("ff_complexity_diagnostics", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(*paths):
    return subprocess.run([sys.executable, "-B", str(TOOL), *map(str, paths)],
                          capture_output=True, text=True, encoding="utf-8", timeout=20)


def test_scores_measure_changes_without_a_numeric_permission():
    tool = _tool()
    low = tool.max_function_score(SIMPLE)
    high = tool.max_function_score(BRANCHED)
    assert low == 1
    assert high > 10
    assert high > low


def test_invalid_syntax_is_not_a_zero_complexity_score():
    tool = _tool()
    with pytest.raises(SyntaxError):
        tool.max_function_score("def broken(:\n    pass\n")


@pytest.mark.parametrize("source", [SIMPLE, BRANCHED], ids=["low", "above-reference"])
def test_valid_source_exit_is_independent_of_score(source, tmp_path):
    tool = _tool()
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    result = _run(path)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["diagnostic_only"] is True
    assert report["metric"] == "legacy_ast_branch_count"
    assert report["errors"] == []
    assert report["files"][0]["max_score"] == tool.max_function_score(source)
    assert report["files"][0]["above_reference"] is (source == BRANCHED)


def test_syntax_error_has_nonzero_exit_and_does_not_hide_other_measurements(tmp_path):
    _tool()
    valid = tmp_path / "valid.py"
    invalid = tmp_path / "broken.py"
    valid.write_text(BRANCHED, encoding="utf-8")
    invalid.write_text("def broken(:\n    pass\n", encoding="utf-8")
    result = _run(valid, invalid)
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["files"][0]["path"] == str(valid.resolve())
    assert report["files"][0]["above_reference"] is True
    assert report["errors"][0]["path"] == str(invalid.resolve())
    assert report["errors"][0]["error"] == "SyntaxError"
    assert report["errors"][0]["line"] == 1
    assert all(row["path"] != str(invalid.resolve()) for row in report["files"])


def test_missing_input_fails_instead_of_silently_reporting_zero(tmp_path):
    _tool()
    result = _run(tmp_path / "missing.py")
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["files"] == []
    assert report["errors"][0]["error"] == "FileNotFoundError"


def test_current_sources_are_measurable_without_score_thresholds():
    report = _tool().measure([ROOT / "scripts"])
    assert report["diagnostic_only"] is True
    assert report["errors"] == []
    assert report["files"]
    assert all(isinstance(row["max_score"], int) for row in report["files"])
