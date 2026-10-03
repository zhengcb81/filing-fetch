"""FF-S3: the filing-fetch install surface is explicit, minimal and clean.

The manifest must contain only what the skill needs to run - scripts, the
skill docs and the one public config template - and must never sweep in a
credential, a local ``.env``, the test suite, a cache or a run log.  Writing
to the shared ``.agents`` / ``.claude`` / ``.codex`` roots is an explicit
action; neither a bare invocation nor the pre-push gate may do it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[1]
TOOLS = SKILL_ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import pre_push_gate  # noqa: E402
import sync_installs_b3  # noqa: E402

PUBLIC_CONFIG = {"config/company_wiki.json"}
RUNTIME_PREFIXES = ("scripts/", "references/")
RUNTIME_FILES = {"SKILL.md", "CHANGELOG.md"}


def _keys(canonical: Path) -> list[str]:
    return sorted(sync_installs_b3.manifest(canonical))


def test_manifest_is_only_runtime_scripts_docs_and_public_config_templates() -> None:
    keys = _keys(sync_installs_b3.CANONICAL)
    assert keys, "an empty manifest would install nothing"
    assert set(keys) <= RUNTIME_FILES | set(PUBLIC_CONFIG) | {
        key for key in keys if key.startswith(RUNTIME_PREFIXES)
    }
    assert set(key for key in keys if key.startswith("config/")) == PUBLIC_CONFIG
    assert not any(key.startswith("tests/") for key in keys)
    assert not any(key.endswith((".pyc", ".pyo", ".log", ".env")) for key in keys)


def test_manifest_excludes_a_fake_fmp_api_key_file() -> None:
    """A locally dropped key must never reach an install, even though it sits
    inside ``config/``.  Only a fake value is ever written or read."""
    key = sync_installs_b3.CANONICAL / "config" / "FMP_API_KEY.txt"
    assert not key.exists(), "test precondition: this worktree carries no key"
    try:
        key.write_text("FAKE_KEY_FOR_FF_S3_TEST_ONLY", encoding="utf-8")
        assert "config/FMP_API_KEY.txt" not in sync_installs_b3.manifest(
            sync_installs_b3.CANONICAL
        )
    finally:
        key.unlink(missing_ok=True)
    assert not key.exists(), "the fake key must be removed on exit"


def test_synthetic_tree_excludes_credentials_env_tests_and_run_logs(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical"
    (canonical / "scripts").mkdir(parents=True)
    (canonical / "references").mkdir()
    (canonical / "config").mkdir()
    (canonical / "tests").mkdir()
    (canonical / "SKILL.md").write_text("# skill\n", encoding="utf-8")
    (canonical / "CHANGELOG.md").write_text("# changelog\n", encoding="utf-8")
    (canonical / "scripts" / "fetch_filing.py").write_text("pass\n", encoding="utf-8")
    (canonical / "references" / "identity.md").write_text("id\n", encoding="utf-8")
    (canonical / "config" / "company_wiki.json").write_text("{}", encoding="utf-8")
    for relative in (
        "scripts/FMP_API_KEY.txt",
        "scripts/.env",
        "scripts/run.log",
        "scripts/fetch_filing.pyc",
        "references/notes.env",
        "config/dayu_secret_token.json",
    ):
        (canonical / relative).parent.mkdir(parents=True, exist_ok=True)
        (canonical / relative).write_text("do not install\n", encoding="utf-8")
    (canonical / "tests" / "test_thing.py").write_text("pass\n", encoding="utf-8")

    assert _keys(canonical) == [
        "CHANGELOG.md",
        "SKILL.md",
        "config/company_wiki.json",
        "references/identity.md",
        "scripts/fetch_filing.py",
    ]


def test_explicit_install_copies_only_the_manifest_to_a_repo_local_target(
    tmp_path: Path,
) -> None:
    assert sync_installs_b3.main(["--install", "--dest", str(tmp_path)]) == 0
    target = tmp_path / sync_installs_b3.SKILL
    assert target.is_dir()
    installed = {
        path.relative_to(target).as_posix()
        for path in target.rglob("*")
        if path.is_file()
    }
    assert installed == set(sync_installs_b3.manifest(sync_installs_b3.CANONICAL))
    assert not (target / "tests").exists()
    assert not (target / "config" / "FMP_API_KEY.txt").exists()
    assert sync_installs_b3.installation_diff(tmp_path) == []


def test_installing_without_an_explicit_flag_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sync_installs_b3, "sync",
        lambda destination: pytest.fail("a bare invocation must not write installs"),
    )
    with pytest.raises(SystemExit) as exit_info:
        sync_installs_b3.main([])
    assert exit_info.value.code == 2


def test_pre_push_only_runs_the_read_only_install_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(cmd, label, *args, **kwargs):
        commands.append(cmd)
        return 1  # simulate stale installs so the reporting path is exercised

    monkeypatch.setattr(pre_push_gate, "_run", fake_run)
    assert pre_push_gate._install_check() == 0, "the gate must never block on installs"
    assert commands, "the drift report should still run"
    for cmd in commands:
        assert "--check" in cmd
        assert "--install" not in cmd


def test_git_pre_push_hook_uses_fast_checks_without_the_full_suite() -> None:
    hook = (SKILL_ROOT / ".githooks" / "pre-push").read_text(encoding="utf-8")
    assert "--skip-install-sync" in hook
    assert "--run-tests" not in hook
