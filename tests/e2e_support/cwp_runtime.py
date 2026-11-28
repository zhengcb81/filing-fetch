"""Run FF and explicitly pinned CWP entrypoints with isolated test state."""

from __future__ import annotations

from functools import cache
import os
from pathlib import Path
import subprocess


CWP_REVISION = "1a62edf1d0d89567a5a552709d7027880ea3b857"
WINDOW_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_OS = {"COMSPEC", "PATH", "PATHEXT", "SYSTEMDRIVE", "SYSTEMROOT", "WINDIR"}


def isolated_environment(root: Path, src: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if key.upper() in _OS}
    home = root / "test-home"
    temp = root / "test-tmp"
    appdata = home / "AppData" / "Roaming"
    local = home / "AppData" / "Local"
    for path in (home, temp, appdata, local):
        path.mkdir(parents=True, exist_ok=True)
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(appdata),
               LOCALAPPDATA=str(local), TMP=str(temp), TEMP=str(temp), TMPDIR=str(temp),
               PYTHONPATH=str(src), PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               PYTHONDONTWRITEBYTECODE="1",
               RESEARCH_FEEDBACK_DIR=str(root / "feedback"),
               RESEARCH_FEEDBACK_STATE_ROOT=str(root / "feedback-state"))
    return env


def run_quiet(command: list[str], *, cwd: Path, env: dict[str, str] | None = None,
              input: bytes | None = None, timeout: float = 75) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command, cwd=cwd, env=env, input=input,
        stdin=subprocess.DEVNULL if input is None else None,
        capture_output=True, creationflags=WINDOW_FLAGS, timeout=timeout,
    )


@cache
def _checked_release(raw: str) -> Path:
    root = Path(raw).resolve(strict=True)
    if not root.is_dir() or not (root / "src" / "company_wiki").is_dir():
        raise ValueError("COMPANY_WIKI_REPO must point to the explicit CWP release checkout")
    git = run_quiet(["git", "rev-parse", "HEAD"], cwd=root)
    if git.returncode != 0 or git.stdout.decode("ascii").strip() != CWP_REVISION:
        raise ValueError(f"COMPANY_WIKI_REPO must be at the pinned CWP revision {CWP_REVISION}")
    return root


def cwp_checkout() -> Path:
    raw = os.environ.get("COMPANY_WIKI_REPO")
    if not raw:
        raise ValueError("COMPANY_WIKI_REPO must identify the CI's pinned CWP release checkout")
    return _checked_release(raw)
