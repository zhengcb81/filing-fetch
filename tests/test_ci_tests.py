"""The push hook and CI share an isolated behavior runner and real failures."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def _load(name, relative):
    path = ROOT / relative
    assert path.is_file(), f"shared behavior runner missing: {relative}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hook_and_ci_use_the_same_behavior_runner():
    workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["verify"]["steps"]
    behavior = next(step["run"] for step in steps
                    if step.get("name") == "Run focused regression suite once")
    assert behavior.strip() == "python tools/ci_tests.py"
    hook = (ROOT / ".githooks/pre-push").read_text(encoding="utf-8")
    assert '--ci-tests' in hook
    runner = _load("ff_ci_list", "tools/ci_tests.py")
    assert len(runner.CI_TESTS) == len(set(runner.CI_TESTS))
    for name in ("tests/test_provider_cause_contract.py", "tests/test_acquisition_failure_consumer.py",
                 "tests/test_transcript_companion_transport.py", "tests/test_ci_tests.py"):
        assert name in runner.CI_TESTS
    assert all((ROOT / relative).is_file() for relative in runner.CI_TESTS)


def test_failure_keeps_full_node_output_exit_code_and_cleans_scratch(monkeypatch, tmp_path, capsys):
    runner = _load("ff_ci_failure", "tools/ci_tests.py")
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    scratch = []
    calls = []
    for key in runner.GIT_REPOSITORY_CONTEXT:
        monkeypatch.setenv(key, "parent-hook-context")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "safe-context-must-remain")

    def fail(command, **kwargs):
        calls.append(command)
        owned = Path(command[command.index("--basetemp") + 1])
        scratch.append(owned)
        (owned / "child-proof.txt").write_text("owned", encoding="utf-8")
        assert not any(key in kwargs["env"] for key in runner.GIT_REPOSITORY_CONTEXT)
        assert kwargs["env"]["GIT_CONFIG_PARAMETERS"] == "safe-context-must-remain"
        return subprocess.CompletedProcess(command, 7, "first_failure_node\n" + "x" * 5000,
                                           "last_failure_node\n")

    monkeypatch.setattr(runner.subprocess, "run", fail)
    assert runner.run_tests() == 7
    assert len(calls) == 1
    assert [item for item in calls[0] if item in runner.CI_TESTS] == list(runner.CI_TESTS)
    assert scratch and all(not path.exists() for path in scratch)
    output = capsys.readouterr()
    assert "first_failure_node" in output.out
    assert "last_failure_node" in output.err
    assert list(tmp_path.iterdir()) == []


def test_real_pytest_failure_reports_node_and_restores_owned_temp(monkeypatch, tmp_path, capsys):
    runner = _load("ff_ci_real_failure", "tools/ci_tests.py")
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "CI_TESTS", ("test_owned_failure.py",))
    (tmp_path / "test_owned_failure.py").write_text(
        "def test_specific_ci_failure():\n    assert False, 'specific-ci-failure'\n", encoding="utf-8")
    before = set(tmp_path.iterdir())
    allocated = []
    original = runner.tempfile.TemporaryDirectory

    def owned_temp(*args, **kwargs):
        directory = original(*args, **kwargs)
        allocated.append(Path(directory.name))
        return directory

    monkeypatch.setattr(runner.tempfile, "TemporaryDirectory", owned_temp)
    assert runner.run_tests() == 1
    output = capsys.readouterr()
    assert "test_specific_ci_failure" in output.out
    assert "specific-ci-failure" in output.out
    assert allocated and all(not path.exists() for path in allocated)
    assert set(tmp_path.iterdir()) == before


def test_timeout_also_cleans_owned_scratch(monkeypatch):
    runner = _load("ff_ci_timeout", "tools/ci_tests.py")
    scratch = []

    def timeout(command, **kwargs):
        owned = Path(command[command.index("--basetemp") + 1])
        scratch.append(owned)
        (owned / "partial-result.txt").write_text("partial", encoding="utf-8")
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(runner.subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        runner.run_tests()
    assert scratch and all(not path.exists() for path in scratch)


def test_local_gate_runs_shared_ci_tests_once_and_propagates_failure(monkeypatch):
    gate = _load("ff_gate_ci_failure", "tools/pre_push_gate.py")
    monkeypatch.setattr(gate, "_run", lambda *args, **kwargs: 0)
    monkeypatch.setattr(gate, "_unique_test_symbols", lambda: 0)
    monkeypatch.setattr(gate, "_config_doctor_gate", lambda: 0)
    monkeypatch.setattr(gate, "_no_bom_check", lambda: 0)
    calls = []
    monkeypatch.setitem(sys.modules, "ci_tests", SimpleNamespace(run_tests=lambda: calls.append(1) or 7))
    assert gate.main(["--ci-tests", "--skip-install-sync"]) == 7
    assert calls == [1]
