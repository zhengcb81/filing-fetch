"""Daily/CI inventories share isolation while preserving their actual scope."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml
import fetch_filing


ROOT = Path(__file__).resolve().parents[1]


def _load(name, relative):
    path = ROOT / relative
    assert path.is_file(), f"shared behavior runner missing: {relative}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def wiki_source(monkeypatch, tmp_path):
    source = tmp_path / "runtime-src"
    cli = source / "company_wiki" / "source_catalog" / "cli.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("pass\n", encoding="utf-8")
    monkeypatch.setenv("FILING_FETCH_V2_WIKI_SRC", str(source))
    return source


def _configured_runtime(tmp_path):
    wiki = tmp_path / "configured-wiki"
    (wiki / "config").mkdir(parents=True)
    (wiki / "config" / "source_catalog.yaml").write_text("schema_version: '1.0'\n", encoding="utf-8")
    project = tmp_path / "filing-project"
    (project / "config").mkdir(parents=True)
    config = project / "config" / "company_wiki.json"
    config.write_text(json.dumps({"schema_version": "1.0", "company_wiki_root": str(wiki)}),
                      encoding="utf-8")
    return project, wiki, config


def test_hook_uses_fixed_local_smoke_and_ci_retains_complete_inventory():
    workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["verify"]["steps"]
    behavior = next(step["run"] for step in steps
                    if step.get("name") == "Run focused regression suite once")
    assert behavior.strip() == "python tools/ci_tests.py"
    hook = (ROOT / ".githooks/pre-push").read_text(encoding="utf-8")
    assert '--push-checks' in hook
    assert '--ci-tests' not in hook
    runner = _load("ff_ci_list", "tools/ci_tests.py")
    assert len(runner.CI_TESTS) == len(set(runner.CI_TESTS))
    for name in ("tests/test_provider_cause_contract.py", "tests/test_acquisition_failure_consumer.py",
                 "tests/test_transcript_companion_transport.py", "tests/test_transcript_launch_contract.py",
                 "tests/test_ci_tests.py", "tests/test_local_preparation_observation.py"):
        assert name in runner.CI_TESTS
    assert all((ROOT / relative).is_file() for relative in runner.CI_TESTS)


def test_shared_ci_table_covers_pure_local_reuse_and_current_reader_regressions():
    runner = _load("ff_ci_du11_regressions", "tools/ci_tests.py")
    for name in ("tests/test_du11_transcript_reuse_selection.py",
                 "tests/test_du11_transcript_reuse_contract.py",
                 "tests/test_du11_verified_reader_revalidation.py"):
        assert name in runner.CI_TESTS
    assert len(runner.CI_TESTS) == len(set(runner.CI_TESTS))
    # The frozen-CWP archive/real CLI matrix remains a large-node exercise.
    assert "tests/test_du11_transcript_reuse_e2e.py" not in runner.CI_TESTS


def test_failure_keeps_full_node_output_exit_code_and_cleans_scratch(
    monkeypatch, tmp_path, capsys, wiki_source,
):
    runner = _load("ff_ci_failure", "tools/ci_tests.py")
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    scratch = []
    calls = []
    before = set(tmp_path.iterdir())
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
    assert "-rs" in calls[0]
    assert [item for item in calls[0] if item in runner.CI_TESTS] == list(runner.CI_TESTS)
    assert scratch and all(not path.exists() for path in scratch)
    output = capsys.readouterr()
    assert "first_failure_node" in output.out
    assert "last_failure_node" in output.err
    assert set(tmp_path.iterdir()) == before


def test_real_pytest_failure_reports_node_and_restores_owned_temp(
    monkeypatch, tmp_path, capsys, wiki_source,
):
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


def test_timeout_also_cleans_owned_scratch(monkeypatch, wiki_source):
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


def test_consumer_ci_does_not_load_producer_configuration(monkeypatch, tmp_path):
    runner = _load("ff_ci_opaque_runtime", "tools/ci_tests.py")
    monkeypatch.delenv("FILING_FETCH_V2_WIKI_SRC", raising=False)
    monkeypatch.setattr(fetch_filing, "load_company_wiki_root",
        lambda **kwargs: pytest.fail("consumer CI must not load upstream configuration"))
    seen = []
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **kw:
        seen.append(kw["env"]) or subprocess.CompletedProcess([],0,"",""))
    assert runner.run_tests() == 0
    assert len(seen) == 1 and "FILING_FETCH_V2_WIKI_SRC" not in seen[0]


def test_explicit_ci_runtime_keeps_priority_over_owner_config(monkeypatch, wiki_source):
    runner = _load("ff_ci_explicit_runtime", "tools/ci_tests.py")
    monkeypatch.setattr(fetch_filing, "load_company_wiki_root",
                        lambda **kwargs: pytest.fail("explicit CI runtime read owner config"))
    child = []

    def successful_child(command, **kwargs):
        child.append(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.subprocess, "run", successful_child)
    assert runner.run_tests() == 0
    assert child[0]["FILING_FETCH_V2_WIKI_SRC"] == str(wiki_source.resolve())


def test_missing_producer_does_not_prevent_consumer_tests(monkeypatch, tmp_path):
    runner = _load("ff_ci_without_runtime", "tools/ci_tests.py")
    monkeypatch.delenv("FILING_FETCH_V2_WIKI_SRC", raising=False)
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    seen = []
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **kw:
        seen.append(a) or subprocess.CompletedProcess([],0,"",""))
    assert runner.run_tests() == 0
    assert len(seen) == 1



def test_daily_gate_only_runs_ruff_and_fixed_smoke(monkeypatch):
    gate = _load("ff_gate_daily", "tools/pre_push_gate.py")
    calls = []
    monkeypatch.setattr(gate, "_run", lambda command, label, **kwargs:
                        calls.append((command, kwargs)) or 0)
    for name in ("_unique_test_symbols", "_no_bom_check", "_config_doctor_gate", "_install_check"):
        monkeypatch.setattr(gate, name, lambda: pytest.fail("daily push repeated a CI/manual phase"))
    smoke = []
    monkeypatch.setitem(sys.modules, "ci_tests", SimpleNamespace(run_local_smoke=lambda: smoke.append(1) or 0))
    assert gate.main(["--push-checks"]) == 0
    assert len(calls) == 1 and calls[0][0][1:4] == ["-m", "ruff", "check"]
    assert calls[0][1]["timeout"] == 180
    assert smoke == [1]


@pytest.mark.parametrize("ruff_code,smoke_code,expected", [(7,0,7),(0,9,9)])
def test_daily_gate_propagates_real_failed_phase_once(monkeypatch, ruff_code, smoke_code, expected):
    gate = _load("ff_gate_daily_failure", "tools/pre_push_gate.py")
    monkeypatch.setattr(gate, "_run", lambda *args, **kwargs: ruff_code)
    calls = []
    monkeypatch.setitem(sys.modules, "ci_tests", SimpleNamespace(
        run_local_smoke=lambda: calls.append(1) or smoke_code))
    assert gate.main(["--push-checks"]) == expected
    assert calls == ([] if ruff_code else [1])


def test_local_smoke_has_fixed_nodes_no_runtime_config_or_parent_git(monkeypatch, tmp_path):
    runner = _load("ff_local_smoke_schedule", "tools/ci_tests.py")
    assert 0 < len(runner.LOCAL_SMOKE_TESTS) <= 12
    assert len(runner.LOCAL_SMOKE_TESTS) == len(set(runner.LOCAL_SMOKE_TESTS))
    assert all("::test_" in node and node.split("::")[0] in runner.CI_TESTS
               for node in runner.LOCAL_SMOKE_TESTS)
    monkeypatch.setattr(runner, "_wiki_source_directory", lambda: pytest.fail("local smoke loaded another repo"))
    calls, scratch = [], []
    for key in runner.GIT_REPOSITORY_CONTEXT:
        monkeypatch.setenv(key, "parent-hook-context")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "keep-this-context")
    def child(command, **kwargs):
        calls.append(command)
        owned = Path(command[command.index("--basetemp")+1])
        scratch.append(owned)
        (owned/"child.txt").write_text("owned", encoding="utf-8")
        assert kwargs["timeout"] == 180
        assert not any(key in kwargs["env"] for key in runner.GIT_REPOSITORY_CONTEXT)
        assert kwargs["env"]["GIT_CONFIG_PARAMETERS"] == "keep-this-context"
        assert [x for x in command if x in runner.LOCAL_SMOKE_TESTS] == list(runner.LOCAL_SMOKE_TESTS)
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(runner.subprocess,"run",child)
    assert runner.run_local_smoke() == 0
    assert len(calls) == 1 and all(not p.exists() for p in scratch)


def test_real_local_smoke_failure_keeps_node_exit_and_cleans_scratch(monkeypatch, tmp_path, capsys):
    runner = _load("ff_local_smoke_failure", "tools/ci_tests.py")
    monkeypatch.setattr(runner,"PROJECT_ROOT",tmp_path)
    monkeypatch.setattr(runner,"LOCAL_SMOKE_TESTS",("test_local_red.py::test_actual_local_failure",))
    (tmp_path/"test_local_red.py").write_text(
        "def test_actual_local_failure():\n    assert False, 'actual-local-node'\n",encoding="utf-8")
    before = set(tmp_path.iterdir())
    assert runner.run_local_smoke() == 1
    assert "test_actual_local_failure" in capsys.readouterr().out
    assert set(tmp_path.iterdir()) == before


def test_local_smoke_timeout_cleans_scratch_without_hiding_failure(monkeypatch):
    runner = _load("ff_local_smoke_timeout", "tools/ci_tests.py")
    scratch = []
    def timeout(command, **kwargs):
        owned = Path(command[command.index("--basetemp")+1])
        scratch.append(owned)
        (owned/"partial.txt").write_text("pending",encoding="utf-8")
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
    monkeypatch.setattr(runner.subprocess,"run",timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        runner.run_local_smoke()
    assert scratch and all(not p.exists() for p in scratch)
