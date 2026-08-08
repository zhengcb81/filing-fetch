"""WU-6.1: cross-process append-only JSONL spy log.

Records observable expensive actions (discover/fetch/parser/LLM/scan) as
append-only JSONL so child processes can append and the test process can
count. Never rewrites earlier lines; readback is in append order.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class SpyLog:
    def __init__(self, path: Path):
        self.path = Path(path)

    def record(self, *, kind: str, detail: dict[str, Any] | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"kind": kind, "detail": detail or {}}
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


def read_events(path: Path) -> list[dict[str, Any]]:
    if not Path(path).is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events
