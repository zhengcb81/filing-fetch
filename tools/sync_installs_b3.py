"""Explicit, minimal install surface for the filing-fetch skill (.agents/.claude/.codex).

The manifest is an allowlist, not a sweep: the runtime ``scripts/``, the skill
docs, the reference notes and the one public config template.  Credentials,
local ``.env`` files, the test suite, caches and run logs are structurally
outside it - and a name-based fence catches a credential dropped into an
included directory.

Installing writes to shared user directories, so it is an explicit action::

    python tools/sync_installs_b3.py --install [--dest DIR]

``--check`` is the read-only drift report used by CI and by the pre-push gate
(FF-S3: the gate reports drift, it never performs the install).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

HOME = Path.home()
SKILL = "filing-fetch"
CANONICAL = Path(__file__).resolve().parents[1]
ROOT_FILES = ("SKILL.md", "CHANGELOG.md")
ROOT_DIRS = ("references", "scripts")
# The only config file the skill reads at runtime.  Anything else that lands
# in config/ (a downloaded key, a local override) has to be named here before
# it can ever reach an install.
CONFIG_FILES = ("config/company_wiki.json",)
IGNORED_DIRS = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".codegraph", ".codex", ".git", ".runs", ".env",
}
CREDENTIAL_MARKERS = (
    "api_key", "apikey", "secret", "token", "credential",
    "private_key", "passphrase", "password",
)
CREDENTIAL_SUFFIXES = (".env", ".pem", ".key", ".p12", ".pfx", ".log")


def _excluded(relative: Path) -> bool:
    """True for anything that must never be installed."""
    name = relative.name.lower()
    if name.startswith(".env"):
        return True
    if any(marker in name for marker in CREDENTIAL_MARKERS):
        return True
    if name.endswith(CREDENTIAL_SUFFIXES):
        return True
    if set(relative.parts) & IGNORED_DIRS:
        return True
    return relative.suffix in {".pyc", ".pyo"}


def installable(canonical: Path) -> list[Path]:
    files = [canonical / name for name in ROOT_FILES]
    files += [canonical / name for name in CONFIG_FILES]
    for directory in ROOT_DIRS:
        base = canonical / directory
        if base.is_dir():
            files.extend(
                p
                for p in base.rglob("*")
                if p.is_file() and not _excluded(p.relative_to(canonical))
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
        if any(part in IGNORED_DIRS for part in p.relative_to(target).parts):
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check or install the filing-fetch skill surface"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="read-only drift check; exit 1 on drift",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="copy the manifest into the install roots (the only writing mode)",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        action="append",
        default=None,
        help=(
            "install parent directory holding the filing-fetch folder; "
            "repeatable, defaults to the three global skill roots"
        ),
    )
    args = parser.parse_args(argv)
    if args.check == args.install:
        parser.error("pass exactly one of --check or --install (install is explicit)")
    destinations = tuple(args.dest) if args.dest else DESTINATIONS
    if args.check:
        failed = False
        for destination in destinations:
            diffs = installation_diff(destination)
            if diffs:
                failed = True
                print(f"DIFF {destination}: {len(diffs)} drift")
                for key in diffs[:20]:
                    print(f"  {key}")
            else:
                print(f"MATCH {destination}: {len(manifest(CANONICAL))} files")
        return 1 if failed else 0
    for destination in destinations:
        sync(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
