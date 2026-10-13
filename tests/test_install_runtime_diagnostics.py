"""Partial-copy success must not claim full installed runtime readiness."""

from __future__ import annotations

import json
from pathlib import Path

from test_selective_installation import canonical as canonical, _snapshot, _seed_user_state
import sync_installs_b3 as installer

DEPENDENCY = "scripts/ff_provider_cause.py"
SELECTED = "scripts/fetch_filing.py"


def _dependency(canonical):
    (canonical / DEPENDENCY).write_bytes(b"def build_request_diagnostic(): return {}\n")


def _installed(canonical, tmp_path):
    _dependency(canonical)
    parent = tmp_path / "skills"
    installer.sync(parent)
    return parent, parent / installer.SKILL


def test_matching_subset_reports_older_owned_dependency_as_outside_drift(canonical, tmp_path):
    parent, target = _installed(canonical, tmp_path)
    (target / DEPENDENCY).write_bytes(b"# old missing public symbol\n")
    before = _snapshot(target)
    row = installer.plan_installations((parent,), [SELECTED])["targets"][0]
    assert row["needs_update"] == []
    assert row["full_runtime_drift"] == [DEPENDENCY]
    assert row["outside_scope_runtime_drift"] == [DEPENDENCY]
    assert row["runtime_byte_complete"] is False
    assert row["runtime_execution_validation"] == "NOT_EVALUATED"
    assert _snapshot(target) == before


def test_apply_remains_scoped_and_reports_actual_remaining_runtime_drift(canonical, tmp_path):
    parent, target = _installed(canonical, tmp_path)
    protected = _seed_user_state(parent)
    (target / SELECTED).write_bytes(b"# previous fetch\n")
    (target / DEPENDENCY).write_bytes(b"# old dependency\n")
    outside_before = (target / DEPENDENCY).read_bytes(), (target / DEPENDENCY).stat().st_mtime_ns
    result = installer.sync(parent, files=[SELECTED])
    row = result["targets"][0]
    assert result["status"] == "completed"
    assert row["written"] == [SELECTED]
    assert row["full_runtime_drift"] == [DEPENDENCY]
    assert row["outside_scope_runtime_drift"] == [DEPENDENCY]
    assert row["runtime_byte_complete"] is False
    assert row["runtime_execution_validation"] == "NOT_EVALUATED"
    assert outside_before == (
        (target / DEPENDENCY).read_bytes(),
        (target / DEPENDENCY).stat().st_mtime_ns,
    )
    assert all(
        _snapshot(target)[name] == content
        for name, content in protected.items()
        if name not in {SELECTED, DEPENDENCY}
    )


def test_full_scope_can_complete_bytes_without_claiming_execution(canonical, tmp_path, monkeypatch):
    _dependency(canonical)
    parent = tmp_path / "skills"
    protected = _seed_user_state(parent)
    target = parent / installer.SKILL
    original_sha = installer._sha
    allowed = set(installer.manifest(canonical)) - set(installer.CONFIG_FILES)

    def only_owned_runtime(path):
        if path.is_relative_to(target):
            assert path.relative_to(target).as_posix() in allowed or path.name.startswith(
                ".ff-install-"
            ), "config/keys/unknown must not be read"
        return original_sha(path)

    monkeypatch.setattr(installer, "_sha", only_owned_runtime)
    original_rglob = Path.rglob

    def no_target_scan(self, *args, **kwargs):
        assert not self.is_relative_to(target), "installed unknown tree must not be scanned"
        return original_rglob(self, *args, **kwargs)

    with monkeypatch.context() as no_scan:
        no_scan.setattr(Path, "rglob", no_target_scan)
        result = installer.sync(parent)
    row = result["targets"][0]
    assert result["status"] == "completed"
    assert row["full_runtime_drift"] == []
    assert row["outside_scope_runtime_drift"] == []
    assert row["runtime_byte_complete"] is True
    assert row["runtime_execution_validation"] == "NOT_EVALUATED"
    assert all(_snapshot(target)[name] == content for name, content in protected.items())


def test_post_apply_recomputes_drift_after_outside_target_changes(canonical, tmp_path, monkeypatch):
    parent, target = _installed(canonical, tmp_path)
    (target / SELECTED).write_bytes(b"# old selected\n")
    plan = installer.plan_installations((parent,), [SELECTED])
    assert plan["targets"][0]["outside_scope_runtime_drift"] == []
    replace = installer.os.replace

    def introduce_drift(source, destination):
        result = replace(source, destination)
        (target / DEPENDENCY).write_bytes(b"# changed after plan\n")
        return result

    monkeypatch.setattr(installer.os, "replace", introduce_drift)
    row = installer._apply(plan)["targets"][0]
    assert row["outside_scope_runtime_drift"] == [DEPENDENCY]
    assert row["runtime_byte_complete"] is False


def test_outside_runtime_read_error_is_diagnostic_not_a_new_copy_gate(
    canonical, tmp_path, monkeypatch
):
    parent, target = _installed(canonical, tmp_path)
    (target / SELECTED).write_bytes(b"# old selected\n")
    sha = installer._sha

    def inaccessible(path):
        if path == target / DEPENDENCY:
            raise PermissionError("fixture outside-scope unreadable")
        return sha(path)

    monkeypatch.setattr(installer, "_sha", inaccessible)
    result = installer.sync(parent, files=[SELECTED])
    row = result["targets"][0]
    assert result["status"] == "completed"
    assert row["written"] == [SELECTED]
    assert row["errors"] == []
    assert row["runtime_byte_complete"] is False
    assert row["runtime_diagnostic_errors"][0]["path"] == DEPENDENCY
    assert row["runtime_execution_validation"] == "NOT_EVALUATED"


def test_check_exit_stays_subset_specific_while_json_exposes_runtime_gap(
    canonical, tmp_path, capsys
):
    parent, target = _installed(canonical, tmp_path)
    (target / DEPENDENCY).write_bytes(b"# old dependency\n")
    assert installer.main(["--check", "--json", "--dest", str(parent), "--file", SELECTED]) == 0
    row = json.loads(capsys.readouterr().out)["targets"][0]
    assert row["needs_update"] == []
    assert row["runtime_byte_complete"] is False
    assert row["outside_scope_runtime_drift"] == [DEPENDENCY]
