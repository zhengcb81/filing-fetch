"""Explicit, scoped filing-fetch installation; never sweep an installed tree.

``--check`` reports package drift; ``--plan`` is a zero-write preview;
``--install`` is the only writing action. Repeat ``--file`` to select an
exact subset, and use ``--json`` for one structured stdout value. Existing
configuration, output, credentials and unknown files are user state: they
are never removed. The public config template only initializes a missing
configuration. An interrupted install reports its actual partial writes;
running it again writes only the remaining differences.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile

HOME = Path.home()
SKILL = "filing-fetch"
CANONICAL = Path(__file__).resolve().parents[1]
ROOT_FILES = ("SKILL.md", "CHANGELOG.md")
ROOT_DIRS = ("references", "scripts")
CONFIG_FILES = ("config/company_wiki.json",)
IGNORED_DIRS = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".codegraph",
    ".codex",
    ".git",
    ".runs",
    ".env",
}
CREDENTIAL_MARKERS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "credential",
    "private_key",
    "passphrase",
    "password",
)
CREDENTIAL_SUFFIXES = (".env", ".pem", ".key", ".p12", ".pfx", ".log")
DESTINATIONS = tuple(HOME / name / "skills" for name in (".agents", ".claude", ".codex"))


class TargetConflict(OSError):
    """The requested target changed after observing its original bytes."""


def _excluded(relative: Path) -> bool:
    name = relative.name.lower()
    return (
        name.startswith(".env")
        or any(marker in name for marker in CREDENTIAL_MARKERS)
        or name.endswith(CREDENTIAL_SUFFIXES)
        or bool(set(relative.parts) & IGNORED_DIRS)
        or relative.suffix in {".pyc", ".pyo"}
    )


def installable(canonical: Path) -> list[Path]:
    files = [canonical / name for name in (*ROOT_FILES, *CONFIG_FILES)]
    for directory in ROOT_DIRS:
        base = canonical / directory
        if base.is_dir():
            files.extend(
                path
                for path in base.rglob("*")
                if path.is_file() and not _excluded(path.relative_to(canonical))
            )
    return sorted(set(files))


def _safe_path(root: Path, relative: str) -> Path:
    """Root aliases are supported; links below a selected root are not followed."""
    if root.resolve() != root.absolute():
        raise ValueError("physical install/source root changed")
    current = root
    for part in PurePosixPath(relative).parts:
        current /= part
        try:
            stat = current.lstat()
        except FileNotFoundError:
            continue
        if current.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"linked selected path: {relative}")
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"selected path escaped root: {relative}")
    return current


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target_sha(path: Path) -> str | None:
    return _sha(path) if path.exists() else None


def manifest(canonical: Path) -> dict[str, str]:
    return {
        path.relative_to(canonical).as_posix(): _sha(
            _safe_path(canonical, path.relative_to(canonical).as_posix())
        )
        for path in installable(canonical)
    }


def _scope(files: list[str] | None) -> list[str]:
    available = {path.relative_to(CANONICAL).as_posix() for path in installable(CANONICAL)}
    if files is None:
        return sorted(available)
    for relative in files:
        parsed = PurePosixPath(relative)
        if (
            not relative
            or not parsed.parts
            or "\\" in relative
            or parsed.is_absolute()
            or ".." in parsed.parts
            or str(parsed) != relative
            or ":" in parsed.parts[0]
            or relative not in available
        ):
            raise ValueError(f"not an installable relative file: {relative!r}")
    return sorted(set(files))


def plan_installations(destinations: tuple[Path, ...], files: list[str] | None = None) -> dict:
    scope = _scope(files)
    expected = {name: _sha(_safe_path(CANONICAL, name)) for name in scope}
    targets: dict[str, dict] = {}
    for destination in destinations:
        root = (destination / SKILL).resolve()
        key = os.path.normcase(str(root))
        if key in targets:
            targets[key]["destinations"].append(str(destination))
            continue
        row = {
            "physical_target": str(root),
            "destinations": [str(destination)],
            "needs_update": [],
            "preserved_config": [],
            "before_sha256": {},
            "errors": [],
        }
        for relative in scope:
            path = root / relative
            # Never read or replace existing user configuration, even when a
            # template's bytes differ. Missing configuration is initialized.
            if relative in CONFIG_FILES and (path.exists() or path.is_symlink()):
                row["preserved_config"].append(relative)
                continue
            try:
                actual = _target_sha(_safe_path(root, relative))
                row["before_sha256"][relative] = actual
                if actual != expected[relative]:
                    row["needs_update"].append(relative)
            except (OSError, ValueError) as error:
                row["needs_update"].append(relative)
                row["errors"].append({"path": relative, "reason": str(error)})
        targets[key] = row
    return {
        "schema_version": "ff-install-plan/1",
        "scope": scope,
        "source_sha256": expected,
        "targets": list(targets.values()),
    }


def installation_diff(destination: Path, files: list[str] | None = None) -> list[str]:
    """Compare only package-owned files; user configuration/residue is not drift."""
    plan = plan_installations((destination,), files)
    row = plan["targets"][0]
    if row["errors"]:
        raise ValueError(row["errors"][0]["reason"])
    return row["needs_update"]


def _apply(plan: dict) -> dict:
    rows = []
    for planned in plan["targets"]:
        root = Path(planned["physical_target"])
        row = {
            "physical_target": str(root),
            "destinations": planned["destinations"],
            "written": [],
            "not_written": list(planned["needs_update"]),
            "conflicts": [],
            "preserved_config": planned["preserved_config"],
            "errors": list(planned["errors"]),
        }
        rows.append(row)
        if row["errors"]:
            continue
        for relative in planned["needs_update"]:
            temporary = None
            try:
                source = _safe_path(CANONICAL, relative)
                content = source.read_bytes()
                expected = plan["source_sha256"][relative]
                if hashlib.sha256(content).hexdigest() != expected:
                    raise ValueError(f"source changed: {relative}")
                target = _safe_path(root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                descriptor, name = tempfile.mkstemp(prefix=".ff-install-", dir=target.parent)
                temporary = Path(name)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                shutil.copystat(source, temporary)
                if _sha(temporary) != expected or _sha(_safe_path(CANONICAL, relative)) != expected:
                    raise ValueError(f"source changed during staging: {relative}")
                target = _safe_path(root, relative)
                if _target_sha(target) != planned["before_sha256"][relative]:
                    raise TargetConflict(f"target changed: {relative}")
                os.replace(temporary, target)
                row["written"].append(relative)
                row["not_written"].remove(relative)
            except (OSError, ValueError) as error:
                row["errors"].append({"path": relative, "reason": str(error)})
                if isinstance(error, TargetConflict):
                    row["conflicts"].append(relative)
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError as error:
                        row["errors"].append(
                            {
                                "path": relative,
                                "reason": f"temporary cleanup failed: {error}",
                                "temporary_path": str(temporary),
                            }
                        )
            if row["errors"]:
                break
    failed = any(row["errors"] for row in rows)
    written = any(row["written"] for row in rows)
    status = "partial" if failed and written else "failed" if failed else "completed"
    return {
        "schema_version": "ff-install-result/1",
        "status": status,
        "scope": plan["scope"],
        "targets": rows,
    }


def sync(destination: Path, files: list[str] | None = None) -> dict:
    return _apply(plan_installations((destination,), files))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check, plan or install the filing-fetch skill")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="read-only drift check; exit 1 on drift")
    mode.add_argument(
        "--plan", action="store_true", help="zero-write plan with current byte differences"
    )
    mode.add_argument(
        "--install", action="store_true", help="write only changed selected package files"
    )
    parser.add_argument(
        "--dest", type=Path, action="append", help="skill parent directory; repeatable"
    )
    parser.add_argument("--file", action="append", help="installable relative file; repeatable")
    parser.add_argument("--json", action="store_true", help="exactly one structured stdout value")
    args = parser.parse_args(argv)
    destinations = tuple(args.dest) if args.dest else DESTINATIONS
    try:
        plan = plan_installations(destinations, args.file)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    errors = any(row["errors"] for row in plan["targets"])
    if args.install:
        value = _apply(plan)
        code = 0 if value["status"] == "completed" else 1
    else:
        value = plan
        changed = any(row["needs_update"] for row in plan["targets"])
        code = 2 if errors else 1 if args.check and changed else 0
    if args.json:
        # ASCII JSON is independent of a Windows console's current code page.
        print(json.dumps(value))
    else:
        for row in value["targets"]:
            if args.install:
                print(
                    f"{value['status']} {row['physical_target']}: {len(row['written'])} written, {len(row['not_written'])} not written, {len(row['preserved_config'])} config preserved"
                )
            else:
                print(
                    f"{'DIFF' if row['needs_update'] else 'MATCH'} {row['physical_target']}: {len(row['needs_update'])} drift, {len(row['preserved_config'])} config preserved"
                )
                for relative in row["needs_update"][:20]:
                    print(f"  {relative}")
    for row in value["targets"]:
        for error in row["errors"]:
            print(f"{error['path']}: {error['reason']}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
