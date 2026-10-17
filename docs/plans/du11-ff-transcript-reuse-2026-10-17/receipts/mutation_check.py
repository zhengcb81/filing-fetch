"""Mutation check on an isolated copy: every core defect must fail the tests.

    python receipts/mutation_check.py --out receipts/c_mutation_check.json

The *shared* worktree is never mutated: ``scripts/``, ``tests/`` and
``pyproject.toml`` are copied into an owned temporary tree, each mutation is
applied there and reverted from the pristine copy, and the tree is removed.
The baseline must be green in the same isolated tree.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
TESTS = [
    "tests/test_du11_transcript_reuse_selection.py",
    "tests/test_du11_transcript_reuse_contract.py",
]
MUTATIONS = [
    (
        "M1 source request relabels an omitted provider as fmp",
        "scripts/transcript_tool_transport.py",
        '"provider": provider,\n            "provider_document_id": None,',
        '"provider": provider or "fmp",\n            "provider_document_id": None,',
    ),
    (
        "M2 neutral lookup goes through the provider-scoped envelope",
        "scripts/transcript_tool_transport.py",
        """        result = (
            self._query_local(source_request)
            if provider is None
            else self._query(source_request)
        )
        self._pending = {""",
        """        result = self._query(source_request)
        self._pending = {""",
    ),
    (
        "M3 reused provider falls back to fmp",
        "scripts/transcript_tool_transport.py",
        "        provider = self._manifest_provider(receipt)\n        if (",
        '        provider = self._manifest_provider(receipt) or "fmp"\n        if (',
    ),
    (
        "M4 a gap becomes a silent miss (download allowed)",
        "scripts/transcript_tool_transport.py",
        """        if selection.kind == "gap":
            return {""",
        """        if selection.kind == "gap":
            return None
            return {""",
    ),
    (
        "M5 companion maps an omitted provider back to fmp",
        "scripts/transcript_companion.py",
        '"provider": prepared.option.get("provider"),',
        '"provider": prepared.option.get("provider") or "fmp",',
    ),
    (
        "M6 the unknown observation is read again (extra GET)",
        "scripts/transcript_tool_transport.py",
        """            and selection.qualification is not None
            and selection.source_ref is not None""",
        "            and False",
    ),
    (
        "M7 a single unknown exclusion is reported as a true miss",
        "scripts/transcript_reuse_selection.py",
        """    if len(excluded) == 1 and excluded[0].publication_status == "unknown":""",
        """    if len(excluded) == 1 and excluded[0].publication_status == "unknown" and False:""",
    ),
]


def run_tests(tree: Path) -> tuple[int, str, list[str]]:
    process = subprocess.run(
        [sys.executable, "-m", "pytest", *TESTS, "-q", "--no-header"],
        cwd=tree,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = [line for line in process.stdout.splitlines() if line.strip()]
    summary = lines[-1] if lines else ""
    failed = [
        line.split(" - ")[0].strip()
        for line in lines
        if line.startswith("FAILED ")
    ]
    return process.returncode, summary, failed


def copy_tree(target: Path) -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(REPO / "scripts", target / "scripts", ignore=ignore)
    shutil.copytree(REPO / "tests", target / "tests", ignore=ignore)
    shutil.copy2(REPO / "pyproject.toml", target / "pyproject.toml")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    tree = Path(tempfile.mkdtemp(prefix="du11-mutation-"))
    receipt: dict = {"isolated_tree": True, "tests": TESTS, "mutations": []}
    try:
        copy_tree(tree)
        pristine = {
            name: (tree / name).read_text(encoding="utf-8")
            for _, name, _, _ in MUTATIONS
        }
        code, summary, failed = run_tests(tree)
        receipt["baseline"] = {"exit": code, "summary": summary, "failed": failed}
        print(f"baseline: exit={code} {summary}")
        if code != 0:
            raise SystemExit("baseline must be green in the isolated tree")
        for name, relative, old, new in MUTATIONS:
            text = pristine[relative]
            if old not in text:
                raise AssertionError(f"mutation anchor missing for {name}")
            (tree / relative).write_text(text.replace(old, new, 1), encoding="utf-8")
            code, summary, failed = run_tests(tree)
            (tree / relative).write_text(text, encoding="utf-8")
            print(f"{name}: exit={code} {summary}")
            receipt["mutations"].append(
                {
                    "mutation": name,
                    "file": relative,
                    "exit": code,
                    "summary": summary,
                    "failed_tests": failed,
                    "detected": code != 0,
                }
            )
        # The pristine copy must be byte-identical again before leaving.
        receipt["pristine_restored"] = all(
            (tree / name).read_text(encoding="utf-8") == text
            for name, text in pristine.items()
        )
        receipt["undetected"] = [
            item["mutation"] for item in receipt["mutations"] if not item["detected"]
        ]
        receipt["shared_worktree_untouched"] = True
        print("\nundetected:", receipt["undetected"])
        return 1 if receipt["undetected"] else 0
    finally:
        shutil.rmtree(tree, ignore_errors=True)
        receipt["isolated_tree_removed"] = not tree.exists()
        if args.out is not None:
            args.out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

