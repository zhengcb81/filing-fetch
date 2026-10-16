"""DU8-FF-MATRIX-COMPLETION — controlled interruption / recovery end-to-end.

Public-entry only: this script launches the *real* ``run.py`` matrix as a child
process over the fixed read-only CWP/ET inputs, in a fresh owned root, and then
interrupts it hard once case work has demonstrably started. It then inspects the
on-disk state to prove the recovery invariants the card requires:

  1. a killed attempt leaves *no* success report behind — the failure is never
     reused as a success and never upgraded to PASS;
  2. no non-replayable side effect is claimed: the interrupted attempt produced
     no complete ``report.json``, so nothing downstream can treat it as a chain;
  3. exit cleanup is complete — no owned child python process survives, and the
     owned root's pre-existing content is untouched;
  4. a *second*, uninterrupted attempt in a new owned root is an independent
     run: fresh UUID children, its own artifacts, and its own report.

It is deliberately NOT part of any per-commit CI: it starts real three-layer
chains and takes tens of seconds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
RUNNER = ROOT / "tools" / "offline_contract_matrix" / "run.py"

CWP = Path(r"C:\Users\郑曾波\Projects\company-wiki-du6-ff-readonly")
ET = Path(r"C:\Users\郑曾波\Projects\earnings-transcripts-du6-ff-readonly")

SENTINEL_NAME = ".w06_matrix_sentinel"
SENTINEL_CONTENT = b"w06-matrix-sentinel-do-not-modify\n"


def _children(root: Path) -> set[str]:
    return {p.name for p in root.iterdir()} if root.exists() else set()


def _attempt_dirs(out_root: Path) -> list[Path]:
    return sorted(p for p in out_root.glob("attempt-*") if p.is_dir())


def _python_children_of(root: Path) -> list[int]:
    """Best-effort: no owned python child should reference this owned root."""
    if os.name != "nt":
        return []
    try:
        import subprocess as sp
        out = sp.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine"],
            capture_output=True, text=True, timeout=30,
        ).stdout
    except Exception:
        return []
    own = str(root).lower()
    hits = []
    for line in out.splitlines():
        low = line.lower()
        if own in low or "offline_contract_matrix" in low:
            parts = line.split()
            for token in reversed(parts):
                if token.isdigit():
                    hits.append(int(token))
                    break
    return hits


def main() -> int:
    owned = ROOT / ".tmp" / "du8-c-recovery" / "owned"
    out = ROOT / ".tmp" / "du8-c-recovery" / "out"
    for path in (owned, out):
        path.mkdir(parents=True, exist_ok=True)
    # Pre-place a sentinel that must survive both attempts byte-for-byte.
    sentinel = owned / SENTINEL_NAME
    sentinel.write_bytes(SENTINEL_CONTENT)
    out_sentinel = out / SENTINEL_NAME
    out_sentinel.write_bytes(SENTINEL_CONTENT)

    before_owned, before_out = _children(owned), _children(out)

    report: dict = {
        "schema": "du8-interruption-recovery/1",
        "inputs": {
            "cwp": {"path": str(CWP), "exists": CWP.is_dir()},
            "et": {"path": str(ET), "exists": ET.is_dir()},
        },
        "attempts": [],
    }

    # ── attempt 1: interrupt hard once case work starts ────────────────────
    cmd = [
        sys.executable, "-B", str(RUNNER),
        "--cwp-project", str(CWP),
        "--et-project", str(ET),
        "--owned-root", str(owned),
        "--out-root", str(out),
    ]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    started = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    interrupted_after = None
    try:
        # Wait until a case artifact appears (real chain work is underway).
        deadline = time.monotonic() + 240
        saw_work = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            live = _attempt_dirs(out)
            if live and any((d / "artifacts").is_dir() and any((d / "artifacts").iterdir())
                            for d in live):
                saw_work = True
                break
            time.sleep(0.25)
        if saw_work and proc.poll() is None:
            time.sleep(2.0)
            proc.kill()
            interrupted_after = round(time.monotonic() - started, 3)
        proc.communicate(timeout=60)   # drain and reap the interrupted attempt
    except Exception:  # pragma: no cover - diagnostic path
        if proc.poll() is None:
            proc.kill()

    time.sleep(1.0)
    dirty = _attempt_dirs(out)
    interrupted = {
        "interrupted_after_seconds": interrupted_after,
        "owned_seen": bool(dirty),
        "reports_present": sorted(str(p.relative_to(out)) for d in dirty
                                  for p in d.glob("report.json")),
        "artifacts_present": sorted({d.name for d in dirty if (d / "artifacts").is_dir()}),
        "live_owned_python": _python_children_of(owned),
        "owned_children_after": sorted(_children(owned)),
        "out_children_after": sorted(_children(out)),
        "sentinel_owned_intact": sentinel.read_bytes() == SENTINEL_CONTENT,
        "sentinel_out_intact": out_sentinel.read_bytes() == SENTINEL_CONTENT,
        "preexisting_owned_preserved": before_owned <= _children(owned),
        "preexisting_out_preserved": before_out <= _children(out),
        "exit_code": proc.returncode,
    }
    report["attempts"].append({"kind": "interrupted", **interrupted})

    # ── attempt 2: independent, uninterrupted, in a NEW owned root ─────────
    owned2 = ROOT / ".tmp" / "du8-c-recovery" / f"owned2-{uuid.uuid4().hex[:8]}"
    out2 = ROOT / ".tmp" / "du8-c-recovery" / f"out2-{uuid.uuid4().hex[:8]}"
    owned2.mkdir(parents=True)
    out2.mkdir(parents=True)
    cmd2 = [
        sys.executable, "-B", str(RUNNER),
        "--cwp-project", str(CWP),
        "--et-project", str(ET),
        "--owned-root", str(owned2),
        "--out-root", str(out2),
    ]
    rc2 = subprocess.call(cmd2, env=env)
    dirs2 = _attempt_dirs(out2)
    reports2 = [p for d in dirs2 for p in d.glob("report.json")]
    data2 = json.loads(reports2[-1].read_text(encoding="utf-8")) if reports2 else {}
    cases2 = data2.get("cases") or []
    counts = {k: sum(1 for c in cases2 if c.get("result") == k)
              for k in ("PASS", "FAIL", "PARTIAL", "NOT_RUN")}
    counts["total"] = len(cases2)
    report["attempts"].append({
        "kind": "clean",
        "exit_code": rc2,
        "owned_root": str(owned2),
        "out_root": str(out2),
        "attempt_dirs": [d.name for d in dirs2],
        "reports": [str(p.relative_to(out2)) for p in reports2],
        "case_counts": counts,
        "oracle": (data2.get("oracle") or {}).get("pass"),
        "batch_elapsed_seconds": (data2.get("scope") or {}).get("batch_elapsed_seconds"),
        "case_scheduling": (data2.get("scope") or {}).get("case_scheduling"),
        "stop_reason": (data2.get("scope") or {}).get("stop_reason"),
        "worker_isolation": (data2.get("scope") or {}).get("worker_isolation"),
        "distinct_from_interrupted": not (set(d.name for d in dirs2) & {d.name for d in dirty}),
        "restore": data2.get("restore"),
    })

    # ── independent verdicts (no self-certification) ───────────────────────
    # These check the RECOVERY invariants only. Whether the clean attempt
    # reached 41 PASS is machine-load dependent and is reported as data, never
    # asserted here: conflating "the box was busy" with "recovery is broken"
    # would be exactly the kind of disguised gate the card forbids.
    a1, a2 = report["attempts"][0], report["attempts"][1]
    checks = [
        ("interruption produced real chain work", a1["owned_seen"] and bool(a1["artifacts_present"])),
        ("no success report from the interrupted attempt", a1["reports_present"] == []),
        ("no owned python child survived the kill", a1["live_owned_python"] == []),
        ("owned sentinel intact", a1["sentinel_owned_intact"]),
        ("output sentinel intact", a1["sentinel_out_intact"]),
        ("pre-existing owned entries preserved", a1["preexisting_owned_preserved"]),
        ("pre-existing output entries preserved", a1["preexisting_out_preserved"]),
        ("second attempt used fresh owned directories", a2["distinct_from_interrupted"]),
        ("second attempt completed and wrote a report", bool(a2["reports"])),
        ("second attempt ran the full fixed denominator", a2["case_counts"]["total"] == 41),
        ("second attempt recorded a real outcome for every case",
         a2["case_counts"]["total"] == a2["case_counts"]["PASS"] + a2["case_counts"]["FAIL"]
         + a2["case_counts"]["PARTIAL"] + a2["case_counts"]["NOT_RUN"]),
        ("recovery restored owned scratch", bool((a2["restore"] or {}).get("restored"))),
        ("recovery left no production metadata change",
         bool((a2["restore"] or {}).get("production_metadata_unchanged"))),
        ("a truncated batch names its stop reason or completed fully",
         a2["case_counts"]["total"] == a2["case_counts"]["PASS"] or bool(a2["stop_reason"])),
    ]
    report["checks"] = [{"name": n, "ok": bool(ok)} for n, ok in checks]
    report["passed"] = all(ok for _, ok in checks)
    # Machine-load-dependent facts, reported but never gated here.
    report["batch_outcome_is_data_not_a_gate"] = {
        "exit_code": a2["exit_code"],
        "case_counts": a2["case_counts"],
        "oracle_clean": a2["oracle"],
        "batch_elapsed_seconds": a2["batch_elapsed_seconds"],
        "note": ("A non-zero exit with PARTIAL/NOT_RUN cases means the fixed 180s batch "
                 "could not fit on this loaded machine; it is reported here and judged "
                 "by the C-node evidence, not by recovery correctness."),
    }


    dest = HERE / "interruption-recovery.json"
    dest.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, ok in checks:
        print(f"[{'ok' if ok else 'FAIL'}] {name}")
    print(f"recovery record: {dest}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
