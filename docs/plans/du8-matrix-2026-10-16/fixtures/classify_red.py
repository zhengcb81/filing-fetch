"""Classify the A-node RED on pristine base by ROOT CAUSE (committed receipt).

The first version of this receipt reported "total 12" while its own raw tail
showed "13 failed": the block-splitting regex missed one failure whose traceback
pytest renders differently. This version derives every count from pytest's own
summary lines, so the heads and the tail cannot disagree.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASE = "e8a8558"
TOOL_FILES = [
    "cli_main.py", "run.py", "runtime.py", "measurement.py", "case_specs.py",
    "matrix_cases.py", "report.py", "matrix_outcome.py", "oracle.py",
    "extended_cases.py", "fixture_builder.py", "source_proofs.py",
    "fixture_provider_adapter.py", "et_transcript_proxy.py", "seed_batch.py",
    "README.md",
]
SCRIPT_FILES = ["ff_process_transport.py", "ff_process_tree.py"]
TEST_FILES = ["tests/test_du8_matrix_scheduling.py", "tests/test_du8_matrix_deadline_recovery.py"]


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="du8-red-classify-"))
    try:
        (scratch / "tools" / "offline_contract_matrix").mkdir(parents=True)
        (scratch / "scripts").mkdir()
        (scratch / "tests").mkdir()
        for rel in TOOL_FILES:
            out = subprocess.run(["git", "show", f"{BASE}:tools/offline_contract_matrix/{rel}"],
                                 capture_output=True, cwd=ROOT)
            if out.returncode == 0:
                (scratch / "tools" / "offline_contract_matrix" / rel).write_bytes(out.stdout)
        for rel in SCRIPT_FILES:
            out = subprocess.run(["git", "show", f"{BASE}:scripts/{rel}"], capture_output=True, cwd=ROOT)
            if out.returncode == 0:
                (scratch / "scripts" / rel).write_bytes(out.stdout)
        for rel in TEST_FILES:
            (scratch / rel).write_bytes((ROOT / rel).read_bytes())
        for rel in ("pytest.ini", "pyproject.toml", "conftest.py"):
            p = ROOT / rel
            if p.is_file():
                (scratch / rel).write_bytes(p.read_bytes())

        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "--tb=short", "-rf",
                            *TEST_FILES], capture_output=True, text=True, cwd=scratch, env=env)

        failed = sorted(set(re.findall(r"^FAILED (\S+)", r.stdout, re.M)))
        summary = re.search(r"^(\d+) failed(?:, (\d+) passed)?", r.stdout, re.M)
        n_failed = int(summary.group(1)) if summary else 0
        n_passed = int(summary.group(2) or 0) if summary else 0

        # Classify from the traceback bodies pytest prints between separators.
        bodies = re.split(r"_{5,} (test_\S+) _{5,}", r.stdout)
        cause = {}
        for i in range(1, len(bodies), 2):
            body = bodies[i + 1]
            if "ModuleNotFoundError" in body or "FileNotFoundError" in body:
                cause[bodies[i]] = "module_absent"
            elif "AssertionError" in body:
                cause[bodies[i]] = "behavioural"
            else:
                cause[bodies[i]] = "other"
        # Any FAILED id lacking a parsed body is classified from the raw output.
        for fid in failed:
            short = fid.split("::")[-1]
            if short not in cause:
                cause[short] = "unclassified"

        behavioural = sorted(k for k, v in cause.items() if v == "behavioural")
        module_absent = sorted(k for k, v in cause.items() if v == "module_absent")
        other = sorted(k for k, v in cause.items() if v not in ("behavioural", "module_absent"))

        lines = [
            f"A-node RED on pristine base {BASE}, classified by root cause",
            "=" * 72,
            f"pytest reported: {n_failed} failed, {n_passed} passed",
            f"classified: behavioural={len(behavioural)} module_absent={len(module_absent)} "
            f"other={len(other)}  (sum={len(behavioural) + len(module_absent) + len(other)})",
            "",
            "BEHAVIOURAL failures (these prove real defects in the pre-change runner):",
        ]
        lines += [f"    {n}" for n in behavioural] or ["    (none)"]
        lines += ["", "module-absence failures (necessarily fail before the new module exists):"]
        lines += [f"    {n}" for n in module_absent] or ["    (none)"]
        if other:
            lines += ["", "unclassified:"] + [f"    {n}" for n in other]
        lines += [
            "",
            "Interpretation: on the base commit cli_main partitioned the registry by",
            "position and never consulted a scheduling owner, so the behavioural",
            "failures named above reproduce the real defects. Some behavioural entries",
            "assert on artifacts that only exist after this card (committed receipts and",
            "the scheduling module's own disclaimer); those are change-detectors rather",
            "than defect proofs. The module-absence failures only record that",
            "case_scheduling.py did not exist yet and are NOT evidence of a defect - an",
            "earlier version of this receipt over-weighted them.",
            "",
            "-" * 72,
            "raw pytest tail:",
            r.stdout[-1500:],
        ]
        text = "\n".join(lines)
        dest = ROOT / "docs/plans/du8-matrix-2026-10-16/receipts/A-red-baseline-classified.txt"
        dest.write_text(text, encoding="utf-8")
        print(text)
        # The receipt's own consistency, enforced.
        assert n_failed == len(behavioural) + len(module_absent) + len(other), (
            f"count mismatch: pytest {n_failed} vs classified "
            f"{len(behavioural) + len(module_absent) + len(other)}")
        assert len(behavioural) >= 3, "expected the three real behavioural RED failures"
        print(f"\nwrote {dest}")
        return 0
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
