"""Daily pushes run Ruff once and one fixed local smoke; CI stays explicit.

``--push-checks`` never repeats commit type checks, the full40-file CI list,
three-repository doctors, plan/BOM scans or global install checks. The existing
manual ``--ci-tests``/``--run-tests`` modes retain their complete checks.
A local_fast_pass is only the fixed smoke, not complete CI acceptance.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PY_DIRS = ("scripts", "tests", "tools", "e2e")
# The same engineering owner supplies child isolation to static and pytest runs.
sys.path.insert(0, str(PROJECT_ROOT / "tools"))


def _safe_console() -> None:
    """Windows consoles default to GBK; any non-GBK byte in a captured tool
    output would crash the gate while *reporting* a failure.  Reconfigure to
    UTF-8 with replacement so reporting can never mask the real result."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _run(
    cmd: list[str], label: str, timeout: int = 900, *, blocking: bool = True
) -> int:
    print(f"\n=== {label} ===")
    import ci_tests

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=ci_tests.subprocess_environment(),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"FAILED: {label} (timeout after {timeout}s)")
        return 124
    except OSError as exc:
        print(f"FAILED: {label} ({type(exc).__name__})")
        return 1
    tail = (proc.stdout or "")[-2000:] + (proc.stderr or "")[-1000:]
    if proc.returncode != 0:
        print(tail)
        if blocking:
            print(f"FAILED: {label}")
    else:
        print("ok")
    return proc.returncode


def _unique_test_symbols() -> int:
    """Mirror CI WU-7.1: no duplicate test function names in a scope."""
    problems: list[str] = []
    for path in sorted((PROJECT_ROOT / "tests").rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))

        def visit(scope: ast.AST) -> None:
            seen: dict[str, int] = {}
            for node in ast.iter_child_nodes(scope):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("test_"):
                        if node.name in seen:
                            problems.append(
                                f"DUPLICATE {path.relative_to(PROJECT_ROOT)}:"
                                f"{node.lineno} {node.name}"
                            )
                        else:
                            seen[node.name] = node.lineno
                elif isinstance(node, ast.ClassDef):
                    visit(node)

        visit(tree)
    if problems:
        print("FAILED: duplicate test symbols (CI WU-7.1):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("ok")
    return 0


def _no_bom_check() -> int:
    """CA-304/final_ratchet require ZERO UTF-8 BOM python files."""
    bad: list[str] = []
    for directory in PY_DIRS:
        base = PROJECT_ROOT / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if path.read_bytes().startswith(b"\xef\xbb\xbf"):
                bad.append(str(path.relative_to(PROJECT_ROOT)))
    if bad:
        print("FAILED: UTF-8 BOM python files must be zero:")
        for name in bad:
            print(f"  {name}")
        return 1
    print("ok")
    return 0


def _config_doctor_gate() -> int:
    """CI FC-1202.  CI materializes ${USER_PROFILE}/Projects/filing-fetch and
    requires revenue's config; locally the sibling revenue checkout stands in
    for it.  A missing sibling is reported loudly instead of pretending the
    check ran."""
    sibling = PROJECT_ROOT.parent / "revenue-forecast"
    if not sibling.is_dir():
        print("\n=== config doctor (FC-1202) ===")
        print(
            f"SKIP: no revenue sibling at {sibling} — cannot mirror CI's "
            f"three-repo check locally (CI clones the manifest pin)."
        )
        return 0
    return _run(
        [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "config_doctor.py"),
            "--revenue-root",
            str(sibling),
            "--require-revenue-config",
        ],
        "config doctor (FC-1202 three-repo contract)",
    )


def _install_check() -> int:
    """Report install drift READ-ONLY (FF-S3).

    Installing touches the shared ``~/.agents`` / ``~/.claude`` /
    ``~/.codex`` skill roots, so it is an explicit action performed by the
    owner - never a side effect of pushing.  This step surfaces the drift and
    returns success regardless, so the gate can neither write global state nor
    block a push on it.
    """
    tool = PROJECT_ROOT / "tools" / "sync_installs_b3.py"
    rc = _run(
        [sys.executable, str(tool), "--check"],
        "installed-skill drift check (read-only)",
        blocking=False,
    )
    if rc != 0:
        print("installed skill copies differ from this repo.")
        print("  installing is explicit: python tools/sync_installs_b3.py --install")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    behavior = parser.add_mutually_exclusive_group()
    behavior.add_argument("--push-checks", action="store_true",
                          help="run only Ruff and the fixed local pure-unit smoke")
    behavior.add_argument("--run-tests", action="store_true")
    behavior.add_argument("--ci-tests", action="store_true",
                          help="run the shared focused offline CI behavior suite")
    parser.add_argument("--skip-mypy", action="store_true")
    parser.add_argument("--skip-install-sync", action="store_true")
    args = parser.parse_args(argv)
    _safe_console()
    if args.push_checks:
        rc = _run([sys.executable, "-m", "ruff", "check", *PY_DIRS],
                  "daily Ruff", timeout=180)
        if rc:
            return rc
        import ci_tests
        try:
            rc = ci_tests.run_local_smoke()
        except subprocess.TimeoutExpired:
            print("FAILED: daily local smoke (timeout after180s)")
            return 124
        except OSError as exc:
            print(f"FAILED: daily local smoke ({type(exc).__name__})")
            return 1
        if rc == 0:
            print("local_fast_pass: fixed smoke GREEN; complete CI validation remains pending.")
        return rc

    gates: list[tuple[list[str], str]] = [
        (
            [sys.executable, "-m", "ruff", "check", *PY_DIRS],
            "ruff (CI WU-1.2 full scope)",
        ),
        (
            [sys.executable, "-m", "compileall", "-q", *PY_DIRS],
            "compileall",
        ),
        (
            [
                sys.executable,
                "-c",
                "import sys; sys.path.insert(0, 'scripts'); "
                "import fetch_filing, filing_contracts; print('ok')",
            ],
            "import smoke (scripts.fetch_filing, scripts.filing_contracts)",
        ),
    ]
    if not args.skip_mypy:
        gates.append(
            (
                [
                    sys.executable,
                    "-m",
                    "mypy",
                    "scripts/filing_contracts.py",
                    "scripts/fetch_filing.py",
                ],
                "mypy public contracts (CI FC-1204-c set)",
            )
        )
    if args.run_tests:
        gates.append(
            (
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests",
                    "-q",
                    "--tb=short",
                    "--ignore=tests/test_real_tool_conformance.py",
                    "--ignore=tests/test_e2e_download.py",
                ],
                "hermetic test suite (CI)",
            )
        )

    for cmd, label in gates:
        rc = _run(cmd, label)
        if rc != 0:
            print(
                f"\nGATE RED at: {label}\nFix the root cause (see "
                f"revenue-forecast/assurance/runs/2026-09-02_remaining-gap-"
                f"closure/ci_root_fix.md), do not bypass."
            )
            return rc

    print("\n=== unique test symbols (CI WU-7.1) ===")
    if _unique_test_symbols() != 0:
        return 1

    # FC-1307-a (vendored from company-wiki): host assumptions - a test path or a
    # frozen value that is host-dependent, green here and red on Linux CI.  That is
    # the class that broke revenue-forecast's CI on 2026-09-13; this repository's
    # symlink test was the false-positive case that had to be fixed first.
    rc = _run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "host_assumption_guard.py"),
         "--roots", *PY_DIRS],
        "host assumption guard (FC-1307-a)",
    )
    if rc != 0:
        return rc

    rc = _config_doctor_gate()
    if rc != 0:
        return rc

    if not args.skip_install_sync:
        # Read-only (FF-S3): reports drift, never writes an install root and
        # never blocks the push.
        _install_check()

    rc = _run(
        [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "verify_plan_claims.py"),
            "--plan-dir",
            ".",
        ],
        "plan claim verifier (CI WU-8.3)",
    )
    if rc != 0:
        return rc

    print("\n=== UTF-8 BOM scan (CA-304/final_ratchet surface) ===")
    if _no_bom_check() != 0:
        return 1

    if args.ci_tests:
        import ci_tests

        print("\n=== shared focused CI behavior tests ===")
        rc = ci_tests.run_tests()
        if rc != 0:
            return rc

    print("\npre-push gate GREEN — safe to push (then self-monitor CI).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
