"""Measured phase timing and launch accounting for the offline contract matrix.

Contract (W07-FF-PERF):

* every named phase is reported with measured seconds or an explicit
  ``unknown`` status carrying a reason — an unobserved phase is NEVER
  estimated;
* timing never changes a deadline's start, budget or remaining time;
* launch accounting separates parent-observed tool launches from every
  synthetic-env child process boot recorded by the startup guard.

Child wall spans for nested layers (ET supervisor/worker, fixture adapter)
come from ``launches.jsonl`` wall-clock rows written by the startup guard;
a killed child leaves no exit row and its span stays unknown.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
import time

REQUIRED_PHASES = (
    "binding",
    "seed",
    "ff_cli",
    "et_supervisor_worker",
    "fixture",
    "fresh_source_proof",
    "cleanup",
    "total",
)

MEASURED = "measured"
UNKNOWN = "unknown"


class PhaseTimer:
    """Collects measured phase spans; never fabricates an unobserved phase."""

    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._spans: dict[str, dict] = {}
        self._unknown: dict[str, str] = {}
        self._launches: dict[str, int] = {}

    @contextmanager
    def span(self, name: str):
        start = self._clock()
        try:
            yield
        finally:
            self.record(name, self._clock() - start)

    def record(self, name: str, seconds: float) -> None:
        entry = self._spans.setdefault(name, {"seconds": 0.0, "spans": 0})
        entry["seconds"] += float(seconds)
        entry["spans"] += 1

    def mark_unknown(self, name: str, reason: str) -> None:
        self._unknown[name] = reason

    def count_launch(self, kind: str, count: int = 1) -> None:
        self._launches[kind] = self._launches.get(kind, 0) + int(count)

    def launch_counts(self) -> dict[str, int]:
        return dict(self._launches)

    def snapshot(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for name in REQUIRED_PHASES:
            out[name] = self._entry(name)
        for name in self._spans:
            if name not in out:
                out[name] = self._entry(name)
        return out

    def merge(self, other: "PhaseTimer") -> "PhaseTimer":
        """Sum measured spans/launches of a concurrent worker group."""
        for name, entry in other._spans.items():
            target = self._spans.setdefault(name, {"seconds": 0.0, "spans": 0})
            target["seconds"] += entry["seconds"]
            target["spans"] += entry["spans"]
        for name, reason in other._unknown.items():
            self._unknown.setdefault(name, reason)
        for kind, count in other._launches.items():
            self._launches[kind] = self._launches.get(kind, 0) + count
        return self

    def _entry(self, name: str) -> dict:
        if name in self._spans:
            entry = self._spans[name]
            return {
                "status": MEASURED,
                "seconds": round(entry["seconds"], 4),
                "spans": entry["spans"],
            }
        reason = self._unknown.get(name, "phase produced no measured span")
        return {"status": UNKNOWN, "seconds": None, "reason": reason}


# ── child launch accounting (startup-guard launch log) ─────────────────────


def classify_argv(argv) -> str:
    joined = " ".join(str(part) for part in (argv or []))
    if "seed_batch.py" in joined:
        return "seed_batch"
    if "et_transcript_proxy" in joined:
        return "et_proxy"
    if "fixture_provider_adapter" in joined:
        return "fixture_adapter"
    if "fetch_filing.py" in joined:
        return "ff_cli"
    if "source_proofs.py" in joined:
        return "source_proofs"
    if "company_wiki.source_catalog" in joined:
        return "cwp_cli"
    return "other_python"


_PHASE_BY_KIND = {"et_proxy": "et_supervisor_worker", "fixture_adapter": "fixture"}


def _span_entry(kind: str, spans: list[float], unmatched: int, boots: int) -> dict:
    if not spans:
        reason = (
            "no child exit row observed (killed child or not executed)"
            if boots
            else "no child process observed for this phase"
        )
        return {"status": UNKNOWN, "seconds": None, "unknown_spans": unmatched, "count": boots,
                "reason": reason}
    return {
        "status": MEASURED,
        "seconds": round(sum(spans), 4),
        "spans": len(spans),
        "unknown_spans": unmatched,
        "count": boots,
    }


def launch_report(path: Path) -> dict:
    """Aggregate ``launches.jsonl`` into counts and nested child wall spans."""
    rows: list[dict] = []
    if Path(path).is_file():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    by_kind: dict[str, int] = {}
    matched: dict[str, list[float]] = {}
    unmatched: dict[str, int] = {}
    pending: dict[int, list[dict]] = {}
    for row in rows:
        kind = classify_argv(row.get("argv"))
        if row.get("event") == "boot":
            by_kind[kind] = by_kind.get(kind, 0) + 1
            unmatched[kind] = unmatched.get(kind, 0) + 1
            pending.setdefault(row.get("pid"), []).append(row)
        elif row.get("event") == "exit":
            queue = pending.get(row.get("pid"))
            boot = queue.pop(0) if queue else None
            if boot is not None:
                unmatched[kind] = max(0, unmatched.get(kind, 0) - 1)
                try:
                    matched.setdefault(kind, []).append(float(row["at"]) - float(boot["at"]))
                except (KeyError, TypeError, ValueError):
                    unmatched[kind] = unmatched.get(kind, 0) + 1
    child_spans = {
        phase: _span_entry(kind, matched.get(kind, []), unmatched.get(kind, 0), by_kind.get(kind, 0))
        for kind, phase in _PHASE_BY_KIND.items()
    }
    return {
        "launches": {
            "total_boot": sum(by_kind.values()),
            "total_exit": sum(len(v) for v in matched.values()),
            "by_kind": by_kind,
        },
        "child_spans": child_spans,
    }


def cache_stats(root: Path) -> dict:
    """Measured bytecode-cache outcome (the multi-layer recompile common cause)."""
    root = Path(root)
    if not root.is_dir():
        return {"pyc_files": 0, "company_wiki_pyc": 0, "max_pyc_path_len": None,
                "note": "bytecode cache root absent"}
    files = list(root.rglob("*.pyc"))
    lengths = [len(str(p)) for p in files] or [0]
    return {
        "pyc_files": len(files),
        "company_wiki_pyc": sum(1 for p in files if "company_wiki" in str(p)),
        "et_pyc": sum(1 for p in files if "transcript_tool" in p.name or "retrieval" in p.name),
        "max_pyc_path_len": max(lengths) if files else None,
        "note": "mirrored cache paths over Windows MAX_PATH (260) are silently not cached",
    }


def merge_launch_accounting(timer: PhaseTimer, path: Path) -> dict:
    report = launch_report(path)
    parent_calls = timer.launch_counts()
    report["launches"]["parent_calls"] = parent_calls
    report["launches"]["parent_launch_total"] = sum(parent_calls.values())
    report["note"] = (
        "parent_calls are tool-side launches; total_boot counts every "
        "synthetic-env python child incl. nested FF->CWP/ET/adapter processes; "
        "child wall spans nest inside ff_cli/seed parent spans"
    )
    return report


def merge_launch_reports(parts: list[dict]) -> dict:
    """Combine per-worker-group launch reports into one accounting record."""
    by_kind: dict[str, int] = {}
    totals = {"total_boot": 0, "total_exit": 0}
    child: dict[str, dict] = {}
    for part in parts:
        launches = part.get("launches") or {}
        totals["total_boot"] += launches.get("total_boot", 0)
        totals["total_exit"] += launches.get("total_exit", 0)
        for kind, count in (launches.get("by_kind") or {}).items():
            by_kind[kind] = by_kind.get(kind, 0) + count
        for phase, entry in (part.get("child_spans") or {}).items():
            target = child.setdefault(phase, {
                "status": UNKNOWN, "seconds": None, "spans": 0,
                "unknown_spans": 0, "count": 0, "reasons": [],
            })
            target["count"] += entry.get("count", 0)
            target["unknown_spans"] += entry.get("unknown_spans", 0)
            if entry.get("status") == MEASURED:
                target["status"] = MEASURED
                target["seconds"] = round((target["seconds"] or 0.0) + entry.get("seconds", 0.0), 4)
                target["spans"] += entry.get("spans", 0)
            elif entry.get("reason"):
                target["reasons"].append(entry["reason"])
    for entry in child.values():
        if entry["status"] == UNKNOWN:
            entry["reason"] = "; ".join(entry.pop("reasons")) or "no child span observed"
        else:
            entry.pop("reasons", None)
    merged = {"launches": {"total_boot": totals["total_boot"], "total_exit": totals["total_exit"],
                           "by_kind": by_kind},
              "child_spans": child}
    if parts:
        merged["note"] = parts[0].get("note")
    return merged
