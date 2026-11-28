"""The S6 baseline covers FF production scripts and the test dispatcher."""

from __future__ import annotations

import json
from pathlib import Path

from tools.anti_trick_gate_spec.evidence import baseline, changed_inventory, compare, renamed_waivers
from tools.anti_trick_gate_spec.static_scan import scan


ROOT = Path(__file__).resolve().parents[2]
SOURCES = ("scripts", "tools/ci_tests.py")
MACHINE_ENTRYPOINTS = (
    "scripts/fetch_filing.py",
    "scripts/fetch_statements.py",
    "scripts/ff_job.py",
    "scripts/ff_scheduled_refresh.py",
    "scripts/ff_t3_receipt.py",
)


def test_anti_trick_baseline_covers_real_filing_fetch_sources():
    result = scan(ROOT, SOURCES, entry=MACHINE_ENTRYPOINTS)
    expected = {path.relative_to(ROOT).as_posix() for path in (ROOT / "scripts").rglob("*.py")}
    assert expected | {"tools/ci_tests.py"} == set(result.files)
    saved = json.loads((ROOT / "tests/contract/ratchet_baseline.json").read_text(encoding="utf-8"))
    current = {**baseline(result.findings), "constant_shapes": result.constant_shapes}
    assert not changed_inventory(result, saved, ROOT)
    assert not compare(current, saved)
    assert not renamed_waivers(current, saved)
