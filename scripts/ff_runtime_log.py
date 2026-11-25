"""Bounded, data-minimal native diagnostics for filing-fetch."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re

from ff_persistence import acquire_file_lock, owner_io_path, separate_partial_line


RUNTIME_LOG_NAME = "runtime-errors.jsonl"
_MAX_LOG_BYTES = 2 * 1024 * 1024
_LABEL = re.compile(r"[A-Za-z0-9_.:/-]+")


def diagnostic_fields(
    value: object, *, labels: tuple[str, ...], numbers: tuple[str, ...] = (),
) -> dict:
    if not isinstance(value, dict):
        return {}
    projected: dict[str, str | int] = {}
    for key in labels:
        field = value.get(key)
        if isinstance(field, str) and re.fullmatch(r"[\w.<>-]+", field):
            projected[key] = field
    for key in numbers:
        field = value.get(key)
        if type(field) is int:
            projected[key] = field
    return projected


def diagnostic_view(value: object) -> dict | None:
    # Keep the existing cause vocabulary. Older free-form diagnostics must
    # not introduce messages or physical paths into this public receipt.
    if not isinstance(value, dict) or value.get("schema_version") != "ff-failure-detail/1":
        return None
    public = diagnostic_fields(value, labels=("reason", "owner_reason", "diagnostic"))
    public["schema_version"] = "ff-failure-detail/1"
    causes = value.get("causes")
    if isinstance(causes, list):
        public["causes"] = []
        for cause in causes:
            row = diagnostic_fields(
                cause, labels=("relation", "type"),
                numbers=("errno", "winerror", "lineno", "colno", "pos"),
            )
            if not isinstance(cause, dict) or not {"relation", "type"} <= row.keys():
                continue
            for field, labels, numbers in (
                ("frames", ("file", "function", "source_sha256"), ("line",)),
                ("process_cleanup", ("stage", "type"), ()),
            ):
                entries = cause.get(field)
                if isinstance(entries, list):
                    row[field] = [
                        item for entry in entries
                        if (item := diagnostic_fields(entry, labels=labels, numbers=numbers))
                    ]
            public["causes"].append(row)
    child = value.get("child_process")
    if isinstance(child, dict):
        fields = diagnostic_fields(
            child, labels=("stderr_form", "builtin_exception", "exception_type"), numbers=("exit_code",),
        )
        frame = diagnostic_fields(child.get("last_frame"), labels=("file",), numbers=("line",))
        if frame:
            fields["last_frame"] = frame
        if fields:
            public["child_process"] = fields
    return public


def _label(value: str) -> str:
    if (_LABEL.fullmatch(value) and not value.startswith("/")
            and all(part not in value for part in ("..", "://", ":/"))):
        return value
    return "ref-" + hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()


def _fields(item: dict, keys: tuple[str, ...]) -> dict[str, str]:
    return {key: _label(value) for key in keys if isinstance(value := item.get(key), str)}


class _OwnerLogHandler(RotatingFileHandler):
    failed = False

    def handleError(self, record: logging.LogRecord) -> None:
        # Python's default handler writes tracebacks and record text to stderr.
        self.failed = True


def _write(path: Path, text: str) -> bool:
    path = owner_io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Rotation and append use the same owner lock across processes.
    with acquire_file_lock(path.with_suffix(".lock"), timeout_seconds=0.7):
        with path.open("ab+") as existing:
            separate_partial_line(existing)
        handler = _OwnerLogHandler(path, maxBytes=_MAX_LOG_BYTES, backupCount=1, encoding="utf-8", delay=True)
        try:
            handler.handle(logging.makeLogRecord({"msg": text, "levelno": logging.WARNING}))
        finally:
            handler.close()
        return not handler.failed


def append_runtime_issue(roots: list[Path], rows: list[dict], detail: dict | None = None) -> None:
    """Keep one native warning per observed stage without depending on outbox availability."""
    try:
        if not any(row.get("disposition") in {"deviation", "unknown"} or row.get("refusal_code") for row in rows):
            return
        scope = _fields(rows[0], ("owner", "run_id", "attempt_id", "step_id", "evidence_ref", "version"))
        record: dict[str, object] = {
            "schema_version": "ff-runtime-log/1",
            "level": "warning",
            "observed_at": datetime.now(UTC).isoformat(),
            "event": scope["step_id"].partition("/")[0],
            **scope,
            "checks": [
                _fields(row, ("check_id", "expected", "actual", "disposition", "issue_key", "refusal_code"))
                for row in rows
            ],
        }
        projected = diagnostic_view(detail)
        if projected is not None:
            record["diagnostic"] = projected
        payload = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
        for root in roots:
            try:
                if _write(root / "logs" / RUNTIME_LOG_NAME, payload):
                    return
            except (OSError, ValueError):
                continue
    except Exception:
        # Diagnostics are operational evidence. They cannot change a business result.
        return
