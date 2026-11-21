"""Filing-fetch schedule metadata. Native document jobs stay in JobStore."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from ff_persistence import acquire_file_lock, atomic_write_json, owner_io_path
from ff_refresh_policy import Slot, default_settings, slot_consumed, utc_text, work_scope


class ConfigConflict(ValueError):
    """A newer settings change would be overwritten."""


class RefreshStateError(RuntimeError):
    """The owner cannot safely read or update the original refresh state."""


COUNTS = ("candidates", "reused", "downloaded", "read", "summarized", "skipped", "pending", "failed")


def summarize_run(run: dict) -> dict:
    summary = {field: run[field] for field in (
        "run_id", "slot_id", "roster_snapshot_id", "started_at", "updated_at", "state",
        "counts", "usage", "reason_codes",
    )}
    if run.get("failures"):
        summary["failures"] = run["failures"]
    if run.get("active_action") is not None:
        summary["active_action"] = run["active_action"]
    return summary


class RefreshStore:
    def __init__(self, jobs_dir: Path) -> None:
        self.root = owner_io_path(jobs_dir) / "scheduled"
        self._state_file = self.root / "state.json"
        self._history = self.root / "runs"

    def host_receipt(self) -> dict | None:
        try:
            receipt = json.loads((self.root / "windows-task.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            # Diagnostic data does not decide whether a manual tick may run.
            return None
        return receipt if isinstance(receipt, dict) else None

    def record_host(self, receipt: dict) -> None:
        atomic_write_json(self.root / "windows-task.json", receipt)

    def load(self) -> dict:
        try:
            state = json.loads(self._state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {
                "revision": 0, "settings": default_settings(), "current": None, "last_run": None,
                "last_slot": None, "watermarks": {}, "pending": {},
            }
        except (OSError, UnicodeError, ValueError) as exc:
            raise RefreshStateError("scheduled refresh state is unreadable") from exc
        if not isinstance(state, dict) or not {
            "revision", "settings", "current", "last_run", "last_slot", "watermarks", "pending",
        } <= state.keys():
            raise RefreshStateError("scheduled refresh state is unreadable")
        return state

    @contextmanager
    def execution(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with acquire_file_lock(self.root / "tick.lock", 0):
            yield

    def _update(self, change: Callable[[dict], bool]) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        with acquire_file_lock(self.root / "state.lock", 5):
            state = self.load()
            if change(state):
                atomic_write_json(self._state_file, state)
        return state

    def configure(self, settings: dict, expected_revision: int | None) -> dict:
        def set_settings(state: dict) -> bool:
            if state["settings"] == settings:
                return False
            if expected_revision is not None and expected_revision != state["revision"]:
                raise ConfigConflict("scheduled refresh settings changed")
            state["settings"] = settings
            state["revision"] += 1
            return True

        return self._update(set_settings)

    def begin(self, slot: Slot, revision: int, now: datetime) -> dict | None:
        def start(state: dict) -> bool:
            if state["current"] is not None or not state["settings"]["enabled"]:
                return False
            if state["revision"] != revision:
                return False
            if slot_consumed(state["last_slot"], slot, state["settings"]):
                return False
            stamp = slot.due_at.strftime("%Y%m%dT%H%M%SZ")
            digest = hashlib.sha256(f"{slot.slot_id}:{revision}".encode()).hexdigest()[:10]
            state["current"] = {
                "run_id": f"sr-{stamp}-{digest}", "slot_id": slot.slot_id,
                "due_at": utc_text(slot.due_at),
                "as_of_date": now.astimezone(ZoneInfo(state["settings"]["cadence"]["time_zone"])).date().isoformat(),
                "started_at": utc_text(now), "updated_at": utc_text(now),
                "settings": state["settings"].copy(), "state": "discovering",
                "roster_snapshot_id": None, "roster_cursor": None, "members": [],
                "work": state["pending"].copy(), "suspended": {},
                "discovery_index": 0, "discovery_cursor": None,
                "discovery_complete": True, "discovery_cursors": [],
                "backlog_index": 0, "backlog_cursor": None, "backlog_cursors": [],
                "reading_batch": None, "partial": False, "counts": dict.fromkeys(COUNTS, 0),
                "usage": {"metadata_requests": 0, "metadata_bytes": 0, "owner_cost_unknown": 0},
                "reason_codes": [],
            }
            return True

        return self._update(start)["current"]

    def admit(self, run: dict, stage: str, reference: str, when: str) -> bool:
        """Order new external work against config writes without holding I/O locks."""
        accepted = False

        def reserve(state: dict) -> bool:
            nonlocal accepted
            self._require_active(state, run)
            configured = state["settings"]
            if not configured["enabled"] or work_scope(configured) != work_scope(run["settings"]):
                return False
            run["active_action"] = {"stage": stage, "reference": reference, "admitted_at": when}
            state["current"] = run
            accepted = True
            return True

        self._update(reserve)
        return accepted

    def checkpoint(self, run: dict, *, watermarks: dict[str, str] | None = None) -> None:
        def save(state: dict) -> bool:
            self._require_active(state, run)
            state["current"] = run
            for key, date in (watermarks or {}).items():
                state["watermarks"][key] = max(date, state["watermarks"].get(key, date))
            return True

        self._update(save)

    def finish(self, run: dict, pending: dict) -> None:
        def close(state: dict) -> bool:
            self._require_active(state, run)
            receipt = summarize_run(run)
            atomic_write_json(self._history / f"{run['run_id']}.json", receipt)
            state.update(
                current=None, last_run=receipt, pending=pending,
                last_slot={"slot_id": run["slot_id"], "due_at": run["due_at"],
                           "scope": work_scope(run["settings"])},
            )
            return True

        self._update(close)

    @staticmethod
    def _require_active(state: dict, run: dict) -> None:
        if state["current"] is None or state["current"]["run_id"] != run["run_id"]:
            raise RefreshStateError("scheduled refresh run changed during execution")

    def history(self, cursor: str | None, limit: int) -> tuple[list[dict], str | None]:
        paths = sorted(self._history.glob("sr-*.json"), reverse=True)
        if cursor is not None:
            paths = [path for path in paths if path.stem < cursor]
        rows = []
        for path in paths[:limit]:
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, UnicodeError, ValueError) as exc:
                raise RefreshStateError("scheduled refresh history is unreadable") from exc
        next_cursor = paths[limit - 1].stem if len(paths) > limit else None
        return rows, next_cursor
