"""WU-6.1: cross-process append-only JSONL spy log (RED first).

The spy log records observable expensive actions (discover/fetch/parser/
LLM/scan) as append-only JSONL so a child process can append and the test
process can count. Assertions:

- append-only: existing lines are never rewritten (mtime/content stable);
- deterministic readback: records return in append order;
- counting: count_events(kind) matches exactly;
- cross-process: a subprocess appending is visible to the parent.

RED phase: the module does not exist (ImportError).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SUPPORT = Path(__file__).resolve().parent
sys.path.insert(0, str(SUPPORT))

from spy_log import SpyLog, read_events  # noqa: E402


def test_append_only_and_readback(tmp_path):
    log = SpyLog(tmp_path / "spy.jsonl")
    log.record(kind="discover", detail={"n": 1})
    log.record(kind="fetch", detail={"n": 2})
    events = read_events(tmp_path / "spy.jsonl")
    assert [e["kind"] for e in events] == ["discover", "fetch"]


def test_count_events(tmp_path):
    log = SpyLog(tmp_path / "spy.jsonl")
    log.record(kind="parser")
    log.record(kind="llm")
    log.record(kind="parser")
    events = read_events(tmp_path / "spy.jsonl")
    assert sum(1 for e in events if e["kind"] == "parser") == 2
    assert sum(1 for e in events if e["kind"] == "llm") == 1


def test_append_does_not_rewrite_existing(tmp_path):
    path = tmp_path / "spy.jsonl"
    log = SpyLog(path)
    log.record(kind="a")
    before = path.read_bytes()
    log.record(kind="b")
    after = path.read_bytes()
    assert after.startswith(before), "append must not rewrite earlier lines"
    lines = after.splitlines()
    assert len(lines) == 2


def test_cross_process_append_visible(tmp_path):
    path = tmp_path / "spy.jsonl"
    SpyLog(path).record(kind="parent")
    code = (
        "import sys; sys.path.insert(0, %r); "
        "from spy_log import SpyLog; "
        "SpyLog(%r).record(kind='child')"
    ) % (str(SUPPORT), str(path))
    subprocess.run([sys.executable, "-c", code], check=True)
    events = read_events(path)
    assert [e["kind"] for e in events] == ["parent", "child"]
