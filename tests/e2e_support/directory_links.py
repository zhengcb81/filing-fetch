"""Native directory links for owned scratch fixtures."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from e2e_support.cwp_runtime import WINDOW_FLAGS


def make_directory_link(link: Path, target: Path) -> None:
    if os.name != "nt":
        try:
            link.symlink_to(target, target_is_directory=True)
        except NotImplementedError:
            pytest.skip("filesystem does not implement directory symlinks")
        return
    result = subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "mklink", "/J", str(link), str(target)],
        creationflags=WINDOW_FLAGS, stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
    )
    if result.returncode:
        raise AssertionError(f"could not create test junction: {result.stderr!r}")
