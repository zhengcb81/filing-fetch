"""User settings and local-calendar slots for scheduled source refresh."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


CONFIG_SCHEMA = "ff-scheduled-refresh-config/1"
STATUS_SCHEMA = "ff-scheduled-refresh-status/1"
RUNS_SCHEMA = "ff-scheduled-refresh-runs/1"
_KINDS = ("annual_report", "semi_annual_report", "quarterly_report")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,256}")
_KIND = re.compile(r"[a-z][a-z0-9_]{0,63}")
_TIME = re.compile(r"\d{2}:\d{2}")


def default_settings() -> dict[str, Any]:
    return {
        "enabled": False,
        "cadence": {
            "frequency": "weekly", "weekday": 1, "local_time": "07:30",
            "time_zone": "Europe/London",
        },
        "roster": None,
        "document_kinds": list(_KINDS),
        "transcripts_enabled": True,
        "reading_level": "local",
        "backlog_enabled": True,
    }


def _roster_scope(value: object) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        mode = value.get("mode")
        field = {"universe": "universe_id", "pinned": "roster_ref"}.get(mode) if isinstance(mode, str) else None
        if field and isinstance(value.get(field), str) and _ID.fullmatch(value[field]):
            return {"mode": mode, field: value[field]}
    raise ValueError("roster must identify a universe or pinned roster")


def _cadence(value: object) -> dict:
    if not isinstance(value, dict) or value.get("frequency") not in ("daily", "weekly"):
        raise ValueError("cadence.frequency must be daily or weekly")
    local_time, zone = value.get("local_time"), value.get("time_zone")
    if not isinstance(local_time, str) or not _TIME.fullmatch(local_time):
        raise ValueError("cadence.local_time must be HH:MM")
    try:
        time.fromisoformat(local_time)
        if not isinstance(zone, str):
            raise ValueError("zone is missing")
        ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("cadence needs a valid local time and installed IANA time zone") from exc
    cadence = {"frequency": value["frequency"], "local_time": local_time, "time_zone": zone}
    if value["frequency"] == "weekly":
        weekday = value.get("weekday")
        if type(weekday) is not int or not 1 <= weekday <= 7:
            raise ValueError("weekly cadence.weekday must be an ISO weekday from 1 to 7")
        cadence["weekday"] = weekday
    return cadence


def validate_settings(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("settings must be an object")
    settings = default_settings()
    for key in ("enabled", "transcripts_enabled", "backlog_enabled"):
        settings[key] = value.get(key, settings[key])
        if type(settings[key]) is not bool:
            raise ValueError(f"{key} must be a boolean")
    settings["cadence"] = _cadence(value.get("cadence", settings["cadence"]))
    settings["roster"] = _roster_scope(value.get("roster"))
    if settings["enabled"] and settings["roster"] is None:
        raise ValueError("an enabled schedule requires an explicit roster")
    kinds = value.get("document_kinds", settings["document_kinds"])
    if not isinstance(kinds, list) or any(
        not isinstance(kind, str) or not _KIND.fullmatch(kind) for kind in kinds
    ):
        raise ValueError("document_kinds must contain source document kinds")
    settings["document_kinds"] = list(dict.fromkeys(kinds))
    reading = value.get("reading_level", settings["reading_level"])
    if reading not in ("off", "local", "summary"):
        raise ValueError("reading_level must be off, local or summary")
    settings["reading_level"] = reading
    return settings


def parse_config_request(payload: object) -> tuple[dict, int | None]:
    if not isinstance(payload, dict) or payload.get("schema_version") != CONFIG_SCHEMA:
        raise ValueError(f"request must use {CONFIG_SCHEMA}")
    revision = payload.get("expected_revision")
    if revision is not None and (type(revision) is not int or revision < 0):
        raise ValueError("expected_revision must be a non-negative integer")
    return validate_settings(payload.get("settings")), revision


@dataclass(frozen=True)
class Slot:
    slot_id: str
    local_date: date
    due_at: datetime
    next_at: datetime


def due_slot(cadence: dict, now: datetime) -> Slot:
    if now.tzinfo is None:
        raise ValueError("schedule clock must have a time zone")
    zone = ZoneInfo(cadence["time_zone"])
    clock_time = time.fromisoformat(cadence["local_time"])
    current = now.astimezone(timezone.utc)
    local_date = now.astimezone(zone).date()
    weekly = cadence["frequency"] == "weekly"
    step = timedelta(days=7 if weekly else 1)
    if weekly:
        local_date -= timedelta(days=(local_date.isoweekday() - cadence["weekday"]) % 7)

    def at(day: date) -> datetime:
        # The first occurrence of an ambiguous wall time wins. A forward
        # jump moves a skipped time forward by the transition's duration.
        return datetime.combine(day, clock_time, zone).astimezone(timezone.utc)

    if current < at(local_date):
        local_date -= step
    return Slot(
        f"{cadence['frequency']}:{local_date.isoformat()}", local_date, at(local_date),
        at(local_date + step),
    )


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def work_scope(settings: dict) -> dict:
    """Settings that change which external work a tick may start."""
    return {
        **{key: settings[key] for key in ("roster", "transcripts_enabled", "reading_level", "backlog_enabled")},
        "document_kinds": sorted(settings["document_kinds"]),
    }


def slot_consumed(last: dict | None, slot: Slot, settings: dict) -> bool:
    return (last is not None and last.get("scope") == work_scope(settings)
            and (last["slot_id"] == slot.slot_id or last["due_at"] >= utc_text(slot.due_at)))
