"""FC-1204-b gate: per-file max-cyclomatic-complexity ratchet (filing).

Frozen from the measured 2026-08-12 baseline (findings 60):
fetch_filing.py 33 / filing_contracts.py 39.  Ratchet moves DOWN only;
new files must stay <= 10.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "scripts"

FROZEN_MAX = {
    "fetch_filing.py": 33,
    "filing_contracts.py": 39,
}

NEW_FILE_MAX = 10


def _mccabe(node: ast.AST) -> int:
    if not isinstance(node, ast.AST):
        return 0
    total = 0
    for child in ast.iter_child_nodes(node):
        total += _mccabe(child)
    if isinstance(node, (ast.If, ast.For, ast.While, ast.And, ast.Or,
                         ast.ExceptHandler, ast.comprehension, ast.Assert,
                         ast.With)):
        total += 1
    if isinstance(node, ast.BoolOp):
        total += len(node.values) - 1
    return total


def _max_complexity(text: str) -> int:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return 0
    top = 0
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("test_"):
            seg = ast.get_source_segment(text, node) or ""
            top = max(top, 1 + _mccabe(ast.parse(seg)))
    return top


def test_frozen_files_do_not_worsen():
    for rel, frozen in sorted(FROZEN_MAX.items()):
        path = SRC / rel
        assert path.is_file(), f"ratchet file missing: {rel}"
        actual = _max_complexity(path.read_text(encoding="utf-8"))
        assert actual <= frozen, f"{rel} max {actual} > frozen {frozen}"


def test_new_files_stay_simple():
    for path in sorted(SRC.rglob("*.py")):
        rel = str(path.relative_to(SRC)).replace("\\", "/")
        if rel in FROZEN_MAX:
            continue
        actual = _max_complexity(path.read_text(encoding="utf-8"))
        assert actual <= NEW_FILE_MAX, f"{rel} max {actual} > {NEW_FILE_MAX}"
