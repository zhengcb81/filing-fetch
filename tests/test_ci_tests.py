"""The push hook and CI share an isolated behavior runner and real failures."""

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


def test_runner_resolves_absent_ci_override_with_public_config_loader(monkeypatch, tmp_path):
    runner = _load("ff_ci_config_runtime", "tools/ci_tests.py")
    project, wiki, config = _configured_runtime(tmp_path)
    source = wiki / "src"
    cli = source / "company_wiki" / "source_catalog" / "cli.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("pass\n", encoding="utf-8")
    monkeypatch.delenv("FILING_FETCH_V2_WIKI_SRC", raising=False)
    monkeypatch.setattr(runner, "PROJECT_ROOT", project)
    original = fetch_filing.load_company_wiki_root
    loaded = []

    def public_loader(**kwargs):
        loaded.append(kwargs["config_path"])
        return original(**kwargs)

    monkeypatch.setattr(fetch_filing, "load_company_wiki_root", public_loader)
    child = []

    def successful_child(command, **kwargs):
        child.append(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.subprocess, "run", successful_child)
    assert runner.run_tests() == 0
    assert loaded == [config]
    assert child[0]["FILING_FETCH_V2_WIKI_SRC"] == str(source.resolve())


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


def test_missing_configured_runtime_is_failure_before_pytest(monkeypatch, tmp_path, capsys):
    runner = _load("ff_ci_missing_runtime", "tools/ci_tests.py")
    project, _wiki, _config = _configured_runtime(tmp_path)
    monkeypatch.delenv("FILING_FETCH_V2_WIKI_SRC", raising=False)
    monkeypatch.setattr(runner, "PROJECT_ROOT", project)
    child = []
    monkeypatch.setattr(runner.subprocess, "run",
                        lambda *args, **kwargs: child.append(1) or subprocess.CompletedProcess([], 0))
    assert runner.run_tests() == 2
    assert child == []
    assert "company-wiki runtime" in capsys.readouterr().err.lower()


def test_v2_e2e_uses_public_loader_without_an_opt_in_environment(monkeypatch, tmp_path):
    e2e = _load("ff_v2_public_root", "e2e/test_source_ref_v2_cli.py")
    _project, wiki, _config = _configured_runtime(tmp_path)
    cli = wiki / "src" / "company_wiki" / "source_catalog" / "cli.py"
    cli.parent.mkdir(parents=True)
    cli.write_text("pass\n", encoding="utf-8")
    monkeypatch.delenv("FILING_FETCH_V2_WIKI_SRC", raising=False)
    loaded = []
    monkeypatch.setattr(fetch_filing, "load_company_wiki_root", lambda: loaded.append(1) or wiki)
    try:
        environment = e2e._environment()
    except pytest.skip.Exception:
        pytest.fail("configured offline v2 E2E was silently skipped")
    assert loaded == [1]
    assert environment["PYTHONPATH"] == str((wiki / "src").resolve())
