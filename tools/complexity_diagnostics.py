"""Read-only legacy AST complexity estimates; scores never block work.

The historical estimator counts branch-like AST nodes in module-level sync
functions, including nested blocks, and omits test_ functions. It is not a
control-flow McCabe calculation or evidence of behavioral correctness. The old
frozen34/39 and new-file10 values remain comparisons, never acceptance limits.

Usage: python tools/complexity_diagnostics.py [Python files or directories]
Exit0 means every input was readable and valid Python, regardless of score.
Exit1 means a read/encoding/syntax error; argparse usage errors exit2.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
HISTORICAL_REFERENCES = {"fetch_filing.py": 34, "filing_contracts.py": 39}
HISTORICAL_NEW_FILE_REFERENCE = 10


def _branch_count(node: ast.AST) -> int:
    total = sum(_branch_count(child) for child in ast.iter_child_nodes(node))
    if isinstance(node, (ast.If, ast.For, ast.While, ast.And, ast.Or,
                         ast.ExceptHandler, ast.comprehension, ast.Assert, ast.With)):
        total += 1
    if isinstance(node, ast.BoolOp):
        total += len(node.values) - 1
    return total


def max_function_score(text: str) -> int:
    tree = ast.parse(text)  # SyntaxError must not become a successful score0.
    return max((1 + _branch_count(node) for node in tree.body
                if isinstance(node, ast.FunctionDef) and not node.name.startswith("test_")),
               default=0)


def measure(inputs: list[Path]) -> dict:
    files, errors, seen = [], [], set()
    for supplied in inputs:
        source = Path(supplied).resolve()
        paths = sorted(source.rglob("*.py")) if source.is_dir() else [source]
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            try:
                score = max_function_score(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, SyntaxError) as exc:
                error = {"path": str(path), "error": type(exc).__name__}
                if isinstance(exc, SyntaxError):
                    error.update(line=exc.lineno, offset=exc.offset)
                errors.append(error)
                continue
            reference = HISTORICAL_REFERENCES.get(path.name, HISTORICAL_NEW_FILE_REFERENCE)
            files.append({"path": str(path), "max_score": score,
                          "historical_reference": reference, "above_reference": score > reference})
    return {"diagnostic_only": True, "metric": "legacy_ast_branch_count",
            "scope": "module_level_sync_functions_except_test_prefix",
            "files": files, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=[SCRIPTS])
    report = measure(parser.parse_args(argv).paths)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
