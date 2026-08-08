"""One-off B3 sync for filing-fetch installs (.agents/.codex).

Mirrors revenue-forecast's installable surface: ROOT_FILES + config/
references/scripts/tests, ignoring working docs, pycache, codegraph, coverage.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

HOME = Path.home()
SKILL = "filing-fetch"
CANONICAL = Path(__file__).resolve().parents[1]
ROOT_FILES = (".gitignore", "CHANGELOG.md", "SKILL.md")
ROOT_DIRS = ("config", "references", "scripts", "tests")
IGNORED = {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".codegraph", ".codex"}


def installable(canonical: Path) -> list[Path]:
    files = [canonical / name for name in ROOT_FILES]
    for directory in ROOT_DIRS:
        base = canonical / directory
        if base.is_dir():
            files.extend(
                p
                for p in base.rglob("*")
                if p.is_file()
                and not (set(p.relative_to(canonical).parts) & IGNORED)
                and p.suffix not in {".pyc", ".pyo"}
            )
    return sorted(set(files))


def manifest(canonical: Path) -> dict[str, str]:
    return {
        p.relative_to(canonical).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in installable(canonical)
    }


def sync(destination: Path) -> None:
    expected = manifest(CANONICAL)
    target = destination / SKILL
    target.mkdir(parents=True, exist_ok=True)
    for relative, digest in expected.items():
        out = target / relative
        src = CANONICAL / relative
        if out.is_file() and hashlib.sha256(out.read_bytes()).hexdigest() == digest:
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
    # Remove stale files not in the canonical manifest.
    for p in target.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix in {".pyc", ".pyo"}:
            p.unlink()
            continue
        if any(part in IGNORED for part in p.relative_to(target).parts):
            continue
        if p.relative_to(target).as_posix() not in expected:
            p.unlink()
    actual = manifest(target)
    diffs = [k for k in sorted(set(expected) | set(actual)) if expected.get(k) != actual.get(k)]
    print(
        f"{'MATCH' if not diffs else 'DIFF'} {destination}: {len(expected)} files"
        + (f" ({len(diffs)} drift)" if diffs else "")
    )


if __name__ == "__main__":
    for dest in (
        HOME / ".agents" / "skills",
        HOME / ".claude" / "skills",
        HOME / ".codex" / "skills",
    ):
        sync(dest)
