"""Host-assumption guard (FC-1307-a): catch the defect classes that passed every
local hook and failed only on CI.

History (phase-B run 2026-09-11, findings F-B01-9): four CI failures got through
the pre-commit hook and the pre-push gate.  One was a test CLASS the local gate
never runs (a taxonomy registry check); the others were host assumptions that are
GREEN on the machine that runs the hook:

  1. an absolute host path baked into a test (``C:\\Windows\\win.ini``) - on
     Linux that is a relative name, so the assertion inverts;
  2. a host CAPABILITY used with no guard in the same function (symlink creation);
  3. a machine-scoped value frozen as a constant (a policy-export payload hash
     that embeds each root's absolute path) - it can only be asserted on the
     machine that produced it.

HONEST SCOPE - what this gate cannot see (B.VR-fc1307a review, 2026-09-13; the
first version of this docstring claimed more, and the claim was false):

  * Rule 2 does NOT cover the F-B01-9 row-3 symlink failure.  That test already
    carried ``pytest.skip`` - which is exactly WHY it was green locally - and its
    real defect was an ASSERTION that assumed the wrong layer (it demanded a
    scanner match where Linux legitimately returns none).  A syntax gate cannot
    see an assertion-layer error; that class is covered by running the contract
    suite before pushing, not by this file.  Rule 2's own value is narrower: a NEW
    file that calls a capability API and never guards it is invisible to both
    local hooks (the pre-push gate runs six contract files) and green on Windows.
  * All three rules are SYNTAX-level.  A path or digest that is CONCATENATED or
    COMPUTED at runtime (``"C:" + "/Windows/win.ini"``, ``os.path.join``,
    ``hashlib.sha256(...).hexdigest()`` compared against a constant) is invisible
    here by construction.  That is the price of a fast, deterministic gate.
  * Rule 1 is a FINITE list of absolute prefixes (``WIN_ABS`` / ``POSIX_ABS``),
    widened on 2026-09-13 with the macOS/container roots the first review found
    missing.  It is deliberately not "anything starting with a slash": tests
    legitimately contain URL paths, route names and repo-relative names.
  * A ``.py`` file under the scanned roots that cannot be READ or cannot be PARSED
    is reported and makes the gate RED (fail-closed).  A deliberately unparseable
    Python fixture therefore does not belong under the scanned roots - that is a
    choice, not an oversight.
  * The ratchet identity is the FULL literal value (``rule|relpath|value``); it
    used to be ``value[:40]``, which let a brand-new path that shared a 40-char
    prefix with a baselined one slip through as "already known".

The guard is AST-based on purpose: comments and docstrings may DISCUSS such paths
(the fix notes do), so only runtime string literals count.  Capability exemption is
per FUNCTION, not per file: see ``_exempt_capability``.

Usage:
    python scripts/host_assumption_guard.py            # report and exit 1 on violations
    python scripts/host_assumption_guard.py --report   # report only (exit 0)
    python scripts/host_assumption_guard.py --emit-baseline   # print the baseline JSON
    python scripts/host_assumption_guard.py --roots tests src

READ-ONLY by design: a checker that rewrites the tree it is checking is a smell, and
`tests/unit/test_writer_freeze.py` requires every writing script CLI in this
directory to carry the legacy-writer freeze - a gate has no business holding that
authorization.  To accept today's offenders as the ratchet baseline, run
`--emit-baseline`, paste the output into
``tests/contract/host_assumption_baseline.json``, and say why in the commit.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ROOTS = ("tests", "src")
REGISTRY = REPO / "tests" / "contract" / "host_assumption_allowlist.json"
BASELINE = REPO / "tests" / "contract" / "host_assumption_baseline.json"

WIN_ABS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\[^\\/]|\\\\\?\\|\\\\\.\\)")
# Finite list of absolute POSIX prefixes.  `/Users`, `/Volumes`, `/srv`, ... were
# added after B.VR1307-04 showed the first list missed them; the same failure mode
# as `C:\\Windows\\win.ini`: not absolute on Windows, absolute on Linux/macOS, so
# the assertion flips.  `//server/share` is the POSIX-side UNC spelling.
POSIX_ABS = re.compile(
    r"^(?:"
    r"/(?:etc|tmp|usr|var|home|Users|users|opt|root|proc|sys|dev|mnt|media|srv|data"
    r"|bin|sbin|lib|lib64|boot|run|nix|snap|Volumes|private|Library|Applications"
    r"|System|Network|workspace|builds|github|go)(?:/|$)"
    r"|//[^/\s]+/"
    r")"
)
URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
# Case-insensitive since B.VR1307-05: many tools print lowercase OR uppercase hex,
# and the URL rule above already used IGNORECASE.  Registry lookups lowercase the
# literal, so registering one case covers both.
HEX64 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
# Exact APIs, matched by full dotted receiver: a helper called `link()` must not be
# mistaken for `os.link` (that false positive is B.VR1307-02's second half).
CAPABILITY_FUNCTIONS = ("os.symlink", "os.link", "os.mkfifo")
CAPABILITY_METHODS = ("symlink_to", "hardlink_to")
# Guard detection is AST-level (B.VR1307-02): the WORD appearing in a comment, a
# docstring or a variable name must not exempt a file, so only real calls and real
# decorators count.  `self.skipTest` is unittest's spelling of the same guard, and
# leaving it out was a measured FALSE POSITIVE of the first version: filing-fetch
# tests/test_zr405_policy_roots.py:290-293 guards its symlink call with
# `try/except OSError: self.skipTest(...)`.
SKIP_CALLS = ("pytest.skip", "pytest.importorskip", "self.skipTest", "self.skip_test",
              "skipTest", "skip_test")
SKIP_DECORATOR_ATTRS = ("skipif", "skip")
MODULE_SKIP_NAMES = ("pytestmark",)

RULE_PATHS = "host-absolute-path"
RULE_CAPABILITY = "host-capability-without-skip"
RULE_FROZEN_HASH = "unregistered-frozen-hash"
RULE_SYNTAX = "syntax-error"
RULE_UNREADABLE = "unreadable-file"
BASELINEABLE = (RULE_PATHS, RULE_CAPABILITY)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Line numbers of docstrings (they may discuss such paths)."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                value = body[0].value
                if isinstance(value.value, str):
                    for lineno in range(value.lineno, (value.end_lineno or value.lineno) + 1):
                        lines.add(lineno)
    return lines


def _string_literals(tree: ast.AST, doc_lines: set[int]) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.lineno in doc_lines:
                continue
            out.append((node.value, node.lineno))
        elif isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    if part.lineno in doc_lines:
                        continue
                    out.append((part.value, part.lineno))
    return out


def _receiver(node: ast.AST) -> str:
    """Human-readable receiver chain for a capability call (`path`, `Path(p)`, ...)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_receiver(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return f"{_receiver(node.func)}()"
    return "?"


def _call_sites(tree: ast.AST) -> list[tuple[str, ast.Call]]:
    """Capability call sites as (api label, call node).

    Only exact receivers count: ``os.symlink``/``os.link``/``os.mkfifo`` when the
    receiver is literally ``os``, and ``<expr>.symlink_to``/``<expr>.hardlink_to``
    (Path methods).  A bare ``link(...)`` is NOT a capability call.
    """
    sites: list[tuple[str, ast.Call]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        func = node.func
        if func.attr in CAPABILITY_METHODS:
            sites.append((f"{_receiver(func.value)}.{func.attr}", node))
        elif isinstance(func.value, ast.Name) and f"{func.value.id}.{func.attr}" in CAPABILITY_FUNCTIONS:
            sites.append((f"{func.value.id}.{func.attr}", node))
    return sites


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _enclosing_function(parents: dict[int, ast.AST], node: ast.AST) -> ast.AST | None:
    current: ast.AST | None = node
    while current is not None:
        current = parents.get(id(current))
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
    return None


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _has_skip_call(node: ast.AST) -> bool:
    """AST-level guard detection: a real ``pytest.skip``/``pytest.importorskip``
    CALL, not the word appearing in a comment, a docstring or a variable name
    (B.VR1307-02: a raw-text search exempted the whole file for any of those)."""
    return any(
        isinstance(child, ast.Call) and _dotted_name(child.func) in SKIP_CALLS
        for child in ast.walk(node)
    )


def _has_skipif_decorator(node: ast.AST) -> bool:
    """``@pytest.mark.skipif(...)`` (an Attribute named ``skipif`` in the decorator)."""
    return any(
        isinstance(child, ast.Attribute) and child.attr in SKIP_DECORATOR_ATTRS
        for child in ast.walk(node)
    )


def _function_is_guarded(function: ast.AST) -> bool:
    """A function guards itself either by a skip decorator or by a skip call in its
    own body (a ``try/except OSError: pytest.skip(...)`` handler counts)."""
    decorators = getattr(function, "decorator_list", [])
    if any(_has_skipif_decorator(decorator) for decorator in decorators):
        return True
    return _has_skip_call(function)


def _module_level_skip(tree: ast.AST) -> bool:
    """A file-wide guard really is file-wide: ``pytestmark = pytest.mark.skipif(...)``
    or a module-level ``pytest.importorskip(...)``.  Anything else is judged per
    function (B.VR1307-02: an unrelated ``pytest.skip`` in a sibling test used to
    exempt every capability call in the file)."""
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in MODULE_SKIP_NAMES
            for target in node.targets
        ):
            if _has_skipif_decorator(node.value):
                return True
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            if _dotted_name(node.value.func) in SKIP_CALLS:
                return True
    return False


def _capability_violations(tree: ast.AST) -> list[dict[str, Any]]:
    if _module_level_skip(tree):
        return []
    parents = _parents(tree)
    violations: list[dict[str, Any]] = []
    for api, node in _call_sites(tree):
        function = _enclosing_function(parents, node)
        if function is not None and _function_is_guarded(function):
            continue
        owner = getattr(function, "name", None) or "<module>"
        violations.append({"rule": RULE_CAPABILITY, "line": node.lineno,
                           "value": f"{api} in {owner}"})
    return violations


def scan_file(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # Fail closed, but say what happened instead of raising a traceback
        # (B.VR1307-07): an unreadable file has not been checked.
        return [{"rule": RULE_UNREADABLE, "file": str(path), "line": 0,
                 "value": f"{type(exc).__name__}: {exc}"}]
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        # Deliberately fail-closed (the first version's inline comment claimed the
        # opposite - B.VR1307-06): a file we cannot parse has not been checked.
        return [{"rule": RULE_SYNTAX, "file": str(path), "line": exc.lineno or 0,
                 "value": f"does not parse: {exc.msg} - fix it or keep unparseable "
                          f"fixtures out of the scanned .py set"}]
    doc_lines = _docstring_nodes(tree)
    violations: list[dict[str, Any]] = []
    in_tests = "tests" in path.parts
    for value, lineno in _string_literals(tree, doc_lines):
        stripped = value.strip()
        if not stripped or URL.match(stripped):
            continue
        # Rule 1 is scoped to TESTS on purpose: product code legitimately detects
        # the host (lock.py reads /proc/stat, startup.py probes C:/Windows), and a
        # path literal there is a deliberate platform branch.  In a test it is
        # almost always a portability bug - the class that failed CI.
        if in_tests and (WIN_ABS.match(stripped) or POSIX_ABS.match(stripped)):
            violations.append({"rule": RULE_PATHS, "file": str(path), "line": lineno,
                               "value": stripped})
        if HEX64.match(stripped):
            violations.append({"rule": RULE_FROZEN_HASH, "file": str(path), "line": lineno,
                               "value": stripped})
    if in_tests:
        for item in _capability_violations(tree):
            item["file"] = str(path)
            violations.append(item)
    return violations


def load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{path} is not readable JSON ({type(exc).__name__}: {exc}); "
                         f"the gate cannot run - fix the file")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roots", nargs="*", default=list(DEFAULT_ROOTS))
    parser.add_argument("--report", action="store_true", help="report only, never fail")
    parser.add_argument("--emit-baseline", action="store_true",
                        help="PRINT the current violations as a baseline JSON for a human to "
                             "paste (this script never writes into the tree)")
    args = parser.parse_args(argv)

    registry = load_json(REGISTRY, {"registered_hashes": {}})
    registered = {digest.lower() for digest in registry.get("registered_hashes", {})}
    baseline = set(load_json(BASELINE, {"baseline": []}).get("baseline", []))

    def key(item: dict[str, Any]) -> str:
        rel = Path(item["file"]).resolve().relative_to(REPO).as_posix()
        # The FULL value is the identity (B.VR1307-03): truncating it to a prefix
        # let a brand-new literal that shared 40 characters with a baselined one
        # pass as "already known".
        return f"{item['rule']}|{rel}|{item['value']}"

    violations: list[dict[str, Any]] = []
    for root in args.roots:
        base = (REPO / root).resolve()
        if not base.is_dir():
            continue
        if REPO.resolve() not in base.parents:
            raise SystemExit(f"--roots {root!r} resolves outside the repository "
                             f"({base}); the gate only judges this tree")
        # `.endswith('.py')` after the glob: `rglob('*.py')` is case-insensitive on
        # Windows and case-sensitive on Linux, so the same tree would be scanned
        # differently on the two platforms.
        for path in sorted(p for p in base.rglob("*.py") if p.name.endswith(".py")):
            violations.extend(scan_file(path))

    if args.emit_baseline:
        recorded = sorted(
            {key(item) for item in violations if item["rule"] in BASELINEABLE}
            | baseline
        )
        print(json.dumps(
            {
                "note": ("Ratchet baseline for the host-assumption guard.  These entries are "
                         "PRE-EXISTING: absolute-path literals in tests that are deliberate "
                         "inputs (a path that must be rejected) and capability uses that already "
                         "skip.  The gate fails on anything NEW, so a new absolute path or an "
                         "un-skipped capability use must be fixed rather than silently added.  "
                         "The identity is rule|relative_path|FULL_VALUE, so entries are exact."),
                "baseline": recorded,
            },
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    new: list[dict[str, Any]] = []
    for item in violations:
        if item["rule"] in BASELINEABLE and key(item) in baseline:
            continue  # recorded pre-existing offender (ratchet: only NEW ones fail)
        if item["rule"] == RULE_FROZEN_HASH:
            if item["value"].lower() in registered:
                continue
            if key(item) in baseline:
                continue
        new.append(item)

    for item in new:
        rel = Path(item["file"]).resolve().relative_to(REPO).as_posix()
        print(f"VIOLATION {item['rule']}: {rel}:{item['line']}  {item['value'][:200]}")
    print(f"scanned roots={args.roots}; violations={len(violations)}; "
          f"new(not baselined/registered)={len(new)}; "
          f"baseline={len(baseline)}; registered_hashes={len(registered)}")
    if new:
        print("\nFix the assertion to be host-neutral (tmp_path.anchor, pytest.skip in the "
              "same test, or a platform-independent property).  A frozen digest that is "
              "genuinely host-independent (content hashing, not a host-derived payload) can be "
              f"registered with a rationale in {REGISTRY.relative_to(REPO).as_posix()}.  A "
              "CONCATENATED or COMPUTED host path/digest is outside this gate's reach - review "
              "it by hand.")
    if args.report:
        return 0
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
