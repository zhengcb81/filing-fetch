"""Bounded, data-minimal native diagnostics for filing-fetch."""

from __future__ import annotations

import builtins
from datetime import UTC, datetime
from io import BytesIO
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import sys

from ff_persistence import acquire_file_lock, owner_io_path, separate_partial_line


RUNTIME_LOG_NAME = "runtime-errors.jsonl"
_MAX_LOG_BYTES = 2 * 1024 * 1024
_LABEL = re.compile(r"[A-Za-z0-9_.:/-]+")
_AUTHORIZATION = re.compile(
    r"(?im)\bauthorization[\"']?[ \t]*[:=](?:[ \t]|\r?\n[ \t]+)*[\"']?(?:bearer|basic)\b[^\r\n,;]*"
    r"(?:\r?\n[ \t]+[^\r\n]*)*"
)
_CREDENTIAL_URL = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s@]+@")
_CREDENTIAL_PREFIX = re.compile(r"(?i)(?:sk-|tvly-|gh[pousr]_|AIza)[a-z0-9_-]{8,}")
_API_CREDENTIAL = re.compile(
    r"(?i)(\b(?:access[_-]?token|api[_-]?key|client[_-]?secret|password)"
    r"[\"']?\s*[:=]\s*[\"']?)[^\s,\"';&]+"
)


def redact_text(value: str) -> str:
    """Remove credential shapes from human-facing text before writing any stream."""
    value = _AUTHORIZATION.sub("Authorization: <redacted>", value)
    value = _CREDENTIAL_URL.sub(r"\1<redacted>@", value)
    value = _CREDENTIAL_PREFIX.sub("<redacted>", value)
    return _API_CREDENTIAL.sub(r"\1<redacted>", value)


def redact_diagnostic(value):
    """Project a JSON-compatible diagnostic without retaining credential headers."""
    if isinstance(value, dict):
        return {
            redact_text(key): "<redacted>" if key.lower().replace("-", "_") in {
                "authorization", "proxy_authorization", "api_key", "access_token", "password", "client_secret",
            } else redact_diagnostic(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_diagnostic(item) for item in value]
    return redact_text(value) if isinstance(value, str) else value


def safe_identity(value: str) -> str:
    """Keep caller identity when safe and use an opaque stable reference for any credential."""
    if redact_text(value) == value:
        return value
    return "ref-" + hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()


_TRACEBACK_HEADER = b"Traceback (most recent call last):"
_TRACEBACK_FRAME = re.compile(rb'^  File "([^"]+)", line ([0-9]{1,8})(?:, in .*)?$')
_EXCEPTION_LINE = re.compile(rb"^([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)(?::(?=\s|$)|$)")
_SAFE_FILENAME = re.compile(rb"[A-Za-z0-9_.-]{1,96}")
_BUILTIN_EXCEPTIONS = frozenset(
    name.encode("ascii")
    for name, value in vars(builtins).items()
    if isinstance(value, type) and value.__module__ == "builtins" and issubclass(value, BaseException)
)


def child_failure_details(returncode: int, stderr: bytes, *, truncated: bool = False) -> dict:
    """Project known diagnostic shapes without retaining any child stream text."""
    if not stderr:
        return {"exit_code": returncode, "stderr_form": "empty"}
    if _TRACEBACK_HEADER in stderr or truncated:
        facts = {"exit_code": returncode, "stderr_form": "python_traceback"}
        last_frame: dict[str, int | str] | None = None
        tracing = truncated
        for raw in BytesIO(stderr):
            line = raw.rstrip(b"\r\n")
            if line == _TRACEBACK_HEADER:
                last_frame = None
                tracing = True
                continue
            if not tracing:
                continue
            frame = _TRACEBACK_FRAME.fullmatch(line)
            if frame is not None:
                filename, number = frame.groups()
                basename = re.split(rb"[/\\]", filename)[-1]
                last_frame = {"line": int(number)}
                if _SAFE_FILENAME.fullmatch(basename):
                    filename_label = basename.decode("ascii")
                    if safe_identity(filename_label) == filename_label:
                        last_frame["file"] = filename_label
                continue
            name = _EXCEPTION_LINE.match(line)
            if last_frame is None or name is None:
                continue
            tracing = False  # Continuation lines are exception text, not types.
            if len(name[1]) > 96:
                continue
            kind = name[1].decode("ascii")
            facts["last_frame"] = last_frame
            if safe_identity(kind) == kind:
                facts["exception_type"] = kind
            else:
                facts.pop("exception_type", None)
            facts.pop("builtin_exception", None)
            if name[1] in _BUILTIN_EXCEPTIONS:
                facts["builtin_exception"] = facts["exception_type"]
        if not truncated or "exception_type" in facts:
            return facts
    if b": can't open file " in stderr or stderr.startswith(b"Fatal Python error:"):
        return {"exit_code": returncode, "stderr_form": "python_startup_error"}
    return {"exit_code": returncode, "stderr_form": "unclassified"}


def diagnostic_fields(
    value: object, *, labels: tuple[str, ...], numbers: tuple[str, ...] = (),
) -> dict:
    if not isinstance(value, dict):
        return {}
    projected: dict[str, str | int] = {}
    for key in labels:
        field = value.get(key)
        if isinstance(field, str) and redact_text(field) == field and re.fullmatch(r"[\w.<>-]+", field):
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
    if (safe_identity(value) == value and _LABEL.fullmatch(value) and not value.startswith("/")
            and all(part not in value for part in ("..", "://", ":/"))):
        return value
    return "ref-" + hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()


def _fields(item: dict, keys: tuple[str, ...]) -> dict[str, str]:
    return {key: _label(value) for key in keys if isinstance(value := item.get(key), str)}


class _OwnerLogHandler(RotatingFileHandler):
    failure: OSError | None = None

    def handleError(self, record: logging.LogRecord) -> None:
        # Never send a traceback or its record arguments to the host.
        raised = sys.exc_info()[1]
        self.failure = raised if isinstance(raised, OSError) else OSError("diagnostic write failed")

    def doRollover(self) -> None:
        if self.stream is not None:
            self.stream.close()
            self.stream = None  # type: ignore[assignment]  # FileHandler uses None to reopen lazily.
        # One replace preserves both existing files when a Windows reader
        # prevents rollover. The caller can try another journal destination.
        os.replace(self.baseFilename, self.baseFilename + ".1")


def append_locked_log(path: Path, event: dict) -> None:
    """Append a safe JSON object or report the owner-local I/O failure."""
    payload = json.dumps(redact_diagnostic(event), ensure_ascii=True, separators=(",", ":"))
    path = owner_io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with acquire_file_lock(path.with_suffix(".lock"), timeout_seconds=0.7):
        with path.open("ab+") as existing:
            separate_partial_line(existing)
        handler = _OwnerLogHandler(path, maxBytes=_MAX_LOG_BYTES, backupCount=1, encoding="utf-8", delay=True)
        try:
            handler.handle(logging.makeLogRecord({"msg": payload, "levelno": logging.WARNING}))
        finally:
            handler.close()
        if handler.failure is not None:
            raise handler.failure


def append_runtime_issue(
    roots: list[Path], rows: list[dict], detail: dict | None = None, *, execution: dict | None = None,
) -> Exception | None:
    """Write one warning per stage. Return the last sink error if both are unavailable."""
    try:
        if not any(row.get("disposition") in {"deviation", "unknown"} or row.get("refusal_code") for row in rows):
            return None
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
        if execution:
            record.update(_fields(execution, ("surface", "code_version", "input_ref")))
        projected = diagnostic_view(detail)
        if projected is not None:
            record["diagnostic"] = projected
        failure = None
        for root in roots:
            try:
                append_locked_log(root / "logs" / RUNTIME_LOG_NAME, record)
            except (OSError, ValueError) as error:
                failure = error
            else:
                return None
        return failure
    except Exception as error:
        # A projection problem cannot change the owner result.
        return error
