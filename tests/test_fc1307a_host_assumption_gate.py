"""Protect against host-dependent test assumptions in the real owner tree.

The shared scanner is compared with its copy at FF's explicit CWP release pin.
The check never looks for live sibling checkouts.
"""

from __future__ import annotations

import json
from pathlib import Path

from e2e_support.cwp_runtime import cwp_checkout, run_quiet

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "tools" / "host_assumption_guard.py"
BASELINE = ROOT / "tests" / "contract" / "host_assumption_baseline.json"
ROOTS = ("tests", "tools", "scripts", "e2e")


def test_fc1307a_the_repository_has_no_new_host_assumptions():
    """Any NEW violation fails here (and in the pre-commit hook and the pre-push
    gate, which run the same script)."""
    import sys

    proc = run_quiet([sys.executable, "-B", str(GUARD), "--roots", *ROOTS], cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_fc1307a_the_ratchet_baseline_is_well_formed():
    entries = json.loads(BASELINE.read_text(encoding="utf-8"))["baseline"]
    assert entries, "an empty baseline would mean the ratchet protects nothing"
    for entry in entries:
        parts = entry.split("|", 2)
        assert len(parts) == 3, entry
        rule, rel, value = parts
        assert rule in ("host-absolute-path", "host-capability-without-skip"), entry
        assert value, entry
        assert (ROOT / rel).is_file(), f"{rel} is gone (stale baseline entry)"


def test_fc1307a_fixed_hashes_need_no_manual_registry(tmp_path):
    from tools.host_assumption_guard import scan_file

    example = tmp_path / "tests" / "test_fixture.py"
    example.parent.mkdir()
    fixture_digest = "a" * 64
    path_literal = "/" + "/".join(("home", "fixture-user", "frozen-document.pdf"))
    example.write_text(
        f'digest = {fixture_digest!r}\nsource_path = {path_literal!r}\n',
        encoding="utf-8",
    )
    warnings = scan_file(example)
    assert [(entry["rule"], entry["value"]) for entry in warnings] == [
        ("host-absolute-path", path_literal),
    ]


def test_fc1307a_vendored_scanner_matches_the_pinned_cwp_release():
    upstream = cwp_checkout() / "scripts" / "host_assumption_guard.py"
    assert upstream.is_file()
    assert GUARD.read_bytes().replace(b"\r\n", b"\n") == upstream.read_bytes().replace(b"\r\n", b"\n")
