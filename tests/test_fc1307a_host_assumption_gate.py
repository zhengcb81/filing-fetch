"""FC-1307-a in this repository: the host-assumption gate, vendored.

The gate itself lives in ``tools/host_assumption_guard.py`` and is BYTE-IDENTICAL to
``company-wiki/scripts/host_assumption_guard.py`` and
``filing-fetch/tools/host_assumption_guard.py``; only the ratchet baseline and the
digest registry are per-repository.  Why a copy: each repository's CI checks out only
itself, so importing the wiki's script is not possible, and a silent divergence would
be worse than the duplication.  The drift check below therefore compares the copies
whenever the sibling checkouts are next to this one (they are on the development
machine, not in CI) and SKIPS otherwise - absence of the siblings is not a failure.

History: the class this catches broke this repository's CI on 2026-09-13
(run 34784800110) - a new test hard-coded ``C:\\Users\\someone\\...`` and took
``Path(...).name`` from it; on Linux a backslash is not a separator, so the name was
the whole string and the assertion inverted.  Local hooks and the pre-push gate were
green; only Linux CI was red.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "tools" / "host_assumption_guard.py"
BASELINE = ROOT / "tests" / "contract" / "host_assumption_baseline.json"
REGISTRY = ROOT / "tests" / "contract" / "host_assumption_allowlist.json"
ROOTS = ("tests", "tools", "scripts", "e2e")
SIBLINGS = {
    "company-wiki": ROOT.parent / "company-wiki" / "scripts" / "host_assumption_guard.py",
    "filing-fetch": ROOT.parent / "filing-fetch" / "tools" / "host_assumption_guard.py",
}


def test_fc1307a_the_repository_has_no_new_host_assumptions():
    """Any NEW violation fails here (and in the pre-commit hook and the pre-push
    gate, which run the same script)."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, str(GUARD), "--roots", *ROOTS],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=300,
    )
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


def test_fc1307a_every_registered_digest_carries_a_rationale():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for digest, entry in registry["registered_hashes"].items():
        assert len(digest) == 64 and digest == digest.lower(), digest
        assert entry.get("where"), digest
        assert len(entry.get("rationale", "")) > 40, digest


def test_fc1307a_the_three_vendored_copies_are_byte_identical():
    """Drift guard for the vendored copy: a local fix that only lands in one repo is
    how this kind of gate rots.  Skips where the siblings are not checked out."""
    mine = GUARD.read_bytes()
    present = {name: path for name, path in SIBLINGS.items() if path.is_file()}
    if not present:
        pytest.skip("sibling checkouts not present (expected in CI)")
    digests = {name: hashlib.sha256(path.read_bytes()).hexdigest()[:16]
               for name, path in present.items()}
    mine_digest = hashlib.sha256(mine).hexdigest()[:16]
    assert all(digest == mine_digest for digest in digests.values()), (
        f"vendored guard differs: this repo {mine_digest} vs {digests}"
    )
