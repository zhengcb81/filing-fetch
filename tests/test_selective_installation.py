"""Installer behavior: user state survives, scope is explicit, retries converge."""

from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import sync_installs_b3 as installer  # noqa: E402

SELECTED = ["SKILL.md", "scripts/fetch_filing.py", "scripts/filing_contracts.py"]


@pytest.fixture
def canonical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "canonical"
    contents = {
        "SKILL.md": b"new skill\n",
        "CHANGELOG.md": b"changes\n",
        "config/company_wiki.json": b'{"template": true}\n',
        "scripts/fetch_filing.py": b"print('fetch')\n",
        "scripts/filing_contracts.py": b"CONTRACT = 2\n",
        "references/identity.md": b"identity\n",
    }
    for relative, content in contents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    monkeypatch.setattr(installer, "CANONICAL", root)
    return root


def _snapshot(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def _directory_link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as error:
        if os.name != "nt":
            pytest.skip(f"directory links unavailable on this filesystem: {error}")
        # Junction creation needs no symlink privilege. This creates a link
        # between two test-owned paths; no shell deletion/move is involved.
        result = subprocess.run(
            ["cmd", "/d", "/c", "mklink", "/J", str(link), str(target)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip(f"directory links unavailable on this filesystem: {result.stderr!r}")


def _remove_directory_link(link: Path) -> None:
    if getattr(link, "is_junction", lambda: False)():
        link.rmdir()  # Removes only the owned junction, without following it.
    else:
        link.unlink()


def _seed_user_state(parent: Path) -> dict[str, tuple[bytes, int]]:
    root = parent / installer.SKILL
    for relative in [
        "config/company_wiki.json",
        "config/FMP_API_KEY.txt",
        ".env",
        "output/result.json",
        "scripts/local_helper.py",
        "references/my-notes.md",
        "tests/local-test.py",
        "scripts/__pycache__/old.pyc",
    ]:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"USER_OR_FAKE_TEST_DATA_ONLY\n")
    return _snapshot(root)


def test_full_install_preserves_existing_config_and_all_unowned_files(
    canonical: Path,
    tmp_path: Path,
) -> None:
    parent = tmp_path / "skills"
    before = _seed_user_state(parent)
    installer.sync(parent)
    after = _snapshot(parent / installer.SKILL)
    assert all(after[name] == value for name, value in before.items())
    assert (parent / installer.SKILL / "SKILL.md").read_bytes() == (
        canonical / "SKILL.md"
    ).read_bytes()


def test_drift_reports_missing_installation_and_ignores_unowned_residue(
    canonical: Path,
    tmp_path: Path,
) -> None:
    parent = tmp_path / "skills"
    assert set(installer.installation_diff(parent)) == set(installer.manifest(canonical))
    assert not parent.exists()
    installer.sync(parent)
    target = parent / installer.SKILL
    extra = target / "references" / "my-note.md"
    extra.write_bytes(b"user note")
    assert installer.installation_diff(parent) == []


def test_selected_install_changes_only_requested_files_and_repeats_without_writes(
    canonical: Path,
    tmp_path: Path,
) -> None:
    parent = tmp_path / "skills"
    before = _seed_user_state(parent)
    result = installer.sync(parent, files=SELECTED)
    assert result["status"] == "completed"
    assert result["targets"][0]["written"] == SELECTED
    assert set(_snapshot(parent / installer.SKILL)) == set(before) | set(SELECTED)
    assert all(_snapshot(parent / installer.SKILL)[name] == value for name, value in before.items())
    after = _snapshot(parent / installer.SKILL)
    repeated = installer.sync(parent, files=SELECTED)
    assert repeated["targets"][0]["written"] == []
    assert _snapshot(parent / installer.SKILL) == after


def test_plan_is_one_json_value_and_does_not_create_missing_destination(
    canonical: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parent = tmp_path / "not-created"
    args = ["--plan", "--json", "--dest", str(parent)]
    for name in SELECTED:
        args += ["--file", name]
    assert installer.main(args) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["schema_version"] == "ff-install-plan/1"
    assert value["scope"] == SELECTED
    assert value["targets"][0]["needs_update"] == SELECTED
    assert not parent.exists()


@pytest.mark.parametrize(
    "relative",
    [
        ".",
        "../outside.txt",
        "/absolute.txt",
        PureWindowsPath("Q:", "/invalid-file").as_posix(),
        "scripts//fetch_filing.py",
        "scripts\\fetch_filing.py",
        "tools/pre_push_gate.py",
        "config/FMP_API_KEY.txt",
        "",
    ],
)
def test_invalid_scope_rejects_whole_request_before_any_write(
    canonical: Path,
    tmp_path: Path,
    relative: str,
) -> None:
    parent = tmp_path / "absent"
    with pytest.raises(SystemExit) as error:
        installer.main(
            ["--install", "--dest", str(parent), "--file", "SKILL.md", "--file", relative]
        )
    assert error.value.code == 2
    assert not parent.exists()


def test_mid_batch_failure_reports_partial_and_retry_only_writes_remainder(
    canonical: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "skills"
    before = _seed_user_state(parent)
    replace = installer.os.replace
    names = SELECTED[1:]

    def fail_second(source, destination):
        if Path(destination).name == "filing_contracts.py":
            raise OSError("injected disk error")
        return replace(source, destination)

    monkeypatch.setattr(installer.os, "replace", fail_second)
    failed = installer.sync(parent, files=names)
    row = failed["targets"][0]
    assert failed["status"] == "partial"
    assert row["written"] == [names[0]]
    assert row["not_written"] == [names[1]]
    assert row["errors"]
    target = parent / installer.SKILL
    assert not list(target.rglob(".ff-install-*"))
    first_stat = (target / names[0]).stat().st_mtime_ns
    monkeypatch.setattr(installer.os, "replace", replace)
    repeated = installer.sync(parent, files=names)
    assert repeated["status"] == "completed"
    assert repeated["targets"][0]["written"] == [names[1]]
    assert (target / names[0]).stat().st_mtime_ns == first_stat
    assert all(_snapshot(target)[name] == value for name, value in before.items())


def test_source_change_after_first_write_does_not_install_a_different_source_version(
    canonical: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "skills"
    replace = installer.os.replace
    names = SELECTED[1:]

    def change_remaining(source, destination):
        result = replace(source, destination)
        if Path(destination).name == "fetch_filing.py":
            (canonical / names[1]).write_bytes(b"concurrent source edit")
        return result

    monkeypatch.setattr(installer.os, "replace", change_remaining)
    result = installer.sync(parent, files=names)
    assert result["status"] == "partial"
    assert result["targets"][0]["written"] == [names[0]]
    assert result["targets"][0]["not_written"] == [names[1]]
    assert not (parent / installer.SKILL / names[1]).exists()
    assert not list((parent / installer.SKILL).rglob(".ff-install-*"))


def test_concurrent_target_edit_survives_with_conflict_diagnostic(
    canonical: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "skills"
    target = parent / installer.SKILL / SELECTED[1]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old bytes")
    mkstemp = installer.tempfile.mkstemp

    def target_edit(*args, **kwargs):
        target.write_bytes(b"concurrent owner edit")
        return mkstemp(*args, **kwargs)

    monkeypatch.setattr(installer.tempfile, "mkstemp", target_edit)
    result = installer.sync(parent, files=[SELECTED[1]])
    assert result["status"] == "failed"
    assert result["targets"][0]["conflicts"] == [SELECTED[1]]
    assert result["targets"][0]["written"] == []
    assert target.read_bytes() == b"concurrent owner edit"
    assert not list((parent / installer.SKILL).rglob(".ff-install-*"))


def test_destination_aliases_are_one_physical_target(
    canonical: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parent = tmp_path / "primary"
    parent.mkdir()
    alias = tmp_path / "alias"
    _directory_link(alias, parent)
    try:
        assert (
            installer.main(
                [
                    "--install",
                    "--json",
                    "--dest",
                    str(parent),
                    "--dest",
                    str(alias),
                    "--file",
                    "SKILL.md",
                ]
            )
            == 0
        )
        result = json.loads(capsys.readouterr().out)
        assert len(result["targets"]) == 1
        assert set(result["targets"][0]["destinations"]) == {str(parent), str(alias)}
        assert result["targets"][0]["written"] == ["SKILL.md"]
    finally:
        _remove_directory_link(alias)


def test_selected_child_symlink_does_not_write_outside_target(
    canonical: Path,
    tmp_path: Path,
) -> None:
    parent = tmp_path / "skills"
    root = parent / installer.SKILL
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "fetch_filing.py"
    marker.write_bytes(b"outside original")
    link = root / "scripts"
    _directory_link(link, outside)
    try:
        result = installer.sync(parent, files=[SELECTED[1]])
        assert result["status"] == "failed"
        assert result["targets"][0]["written"] == []
        assert marker.read_bytes() == b"outside original"
    finally:
        _remove_directory_link(link)


def test_physical_root_retargeted_during_staging_is_not_used_for_final_write(
    canonical: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "skills"
    root = parent / installer.SKILL
    path = root / SELECTED[1]
    path.parent.mkdir(parents=True)
    path.write_bytes(b"old bytes")
    outside = tmp_path / "other-owner"
    marker = outside / SELECTED[1]
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"old bytes")  # Equal bytes alone must not prove path ownership.
    moved = tmp_path / "original-root"
    mkstemp = installer.tempfile.mkstemp

    def retarget(*args, **kwargs):
        root.rename(moved)
        _directory_link(root, outside)
        return mkstemp(*args, **kwargs)

    monkeypatch.setattr(installer.tempfile, "mkstemp", retarget)
    try:
        result = installer.sync(parent, files=[SELECTED[1]])
        assert result["status"] == "failed"
        assert result["targets"][0]["written"] == []
        assert marker.read_bytes() == b"old bytes"
        assert (moved / SELECTED[1]).read_bytes() == b"old bytes"
        assert not list(outside.rglob(".ff-install-*"))
    finally:
        if root.is_symlink() or getattr(root, "is_junction", lambda: False)():
            _remove_directory_link(root)
            moved.rename(root)


def test_literal_cli_three_temporary_targets_preserves_state_and_works_on_repeat(
    tmp_path: Path,
) -> None:
    """Actual installer and installed fetch CLI, no HTTP/provider/model calls."""
    command = [sys.executable, "-B", str(REPO / "tools" / "sync_installs_b3.py")]
    parents = [tmp_path / name / "skills" for name in ["agents", "claude", "codex"]]
    for parent in parents:
        completed = subprocess.run(
            command + ["--install", "--dest", str(parent), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout)["status"] == "completed"
        _seed_user_state(parent)
        for name in SELECTED:
            (parent / installer.SKILL / name).write_bytes(b"old selected bytes")
    before = [_snapshot(parent / installer.SKILL) for parent in parents]
    arguments = ["--json"]
    for parent in parents:
        arguments += ["--dest", str(parent)]
    for name in SELECTED:
        arguments += ["--file", name]
    planned = subprocess.run(
        command + ["--plan", *arguments], capture_output=True, text=True, timeout=30, check=False
    )
    assert planned.returncode == 0, planned.stderr
    assert [_snapshot(parent / installer.SKILL) for parent in parents] == before
    applied = subprocess.run(
        command + ["--install", *arguments], capture_output=True, text=True, timeout=30, check=False
    )
    assert applied.returncode == 0, applied.stderr
    rows = json.loads(applied.stdout)["targets"]
    assert len(rows) == 3
    assert all(row["written"] == SELECTED for row in rows)
    for parent, snapshot in zip(parents, before):
        after = _snapshot(parent / installer.SKILL)
        assert all(after[name] == value for name, value in snapshot.items() if name not in SELECTED)
        help_result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(parent / installer.SKILL / "scripts/fetch_filing.py"),
                "--help",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert help_result.returncode == 0, help_result.stderr
    after = [_snapshot(parent / installer.SKILL) for parent in parents]
    repeated = subprocess.run(
        command + ["--install", *arguments], capture_output=True, text=True, timeout=30, check=False
    )
    assert repeated.returncode == 0, repeated.stderr
    assert all(not row["written"] for row in json.loads(repeated.stdout)["targets"])
    assert [_snapshot(parent / installer.SKILL) for parent in parents] == after
