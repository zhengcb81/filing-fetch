"""Check or synchronize filing-fetch skill installs (.agents/.claude/.codex).

Mirrors revenue-forecast's installable surface: ROOT_FILES + config/
references/scripts/tests, ignoring working docs, pycache, codegraph, coverage.
``--check`` is read-only (exit 1 on drift) for pre-commit/CI gates.
"""

from __future__ import annotations

import argparse
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


def installation_diff(destination: Path) -> list[str]:
    """Canonical-vs-installed drift keys (read-only); [] when not installed."""
    expected = manifest(CANONICAL)
    target = destination / SKILL
    if not target.is_dir():
        return []
    actual = manifest(target)
    keys = sorted(set(expected) | set(actual))
    return [key for key in keys if expected.get(key) != actual.get(key)]


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
    diffs = installation_diff(destination)
    print(
        f"{'MATCH' if not diffs else 'DIFF'} {destination}: {len(expected)} files"
        + (f" ({len(diffs)} drift)" if diffs else "")
    )


DESTINATIONS = (
    HOME / ".agents" / "skills",
    HOME / ".claude" / "skills",
    HOME / ".codex" / "skills",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check or synchronize filing-fetch skill installs"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="read-only drift check across install roots; exit 1 on drift",
    )
    args = parser.parse_args()
    if args.check:
        failed = False
        for destination in DESTINATIONS:
            diffs = installation_diff(destination)
            if diffs:
                failed = True
                print(f"DIFF {destination}: {len(diffs)} drift")
                for key in diffs[:20]:
                    print(f"  {key}")
            else:
                print(f"MATCH {destination}: {len(manifest(CANONICAL))} files")
        return 1 if failed else 0
    for destination in DESTINATIONS:
        sync(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
