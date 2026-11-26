"""Bounded OS locks and atomic writes for filing-fetch owned records."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import errno
import json
import os
from pathlib import Path
import secrets
import sys
import time
from typing import BinaryIO


class LockBusy(TimeoutError):
    """An existing writer still owns the lock."""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class FileLock:
    """The OS releases the claim even if its owner process exits abruptly."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream

    def release(self) -> None:
        self._stream.close()

    def __enter__(self) -> FileLock:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def owner_io_path(path: Path) -> Path:
    """Use Windows extended paths only for owner-controlled filesystem operations."""
    if os.name != "nt":
        return path
    value = os.path.abspath(path)
    if value.startswith("\\\\?\\"):
        return Path(value)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def acquire_file_lock(path: Path, timeout_seconds: float) -> FileLock:
    deadline = time.monotonic() + timeout_seconds
    stream = owner_io_path(path).open("a+b")
    try:
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise LockBusy("filing-fetch record is locked") from exc
                time.sleep(0.05)
            else:
                return FileLock(stream)
    except BaseException:
        stream.close()
        raise


def atomic_write_json(path: Path, payload: dict) -> None:
    with _atomic_text_stream(path) as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=1)
        stream.write("\n")


def atomic_write_text(path: Path, value: str) -> None:
    with _atomic_text_stream(path) as stream:
        stream.write(value)


def separate_partial_line(stream: BinaryIO) -> None:
    """Preserve a torn last record without joining it to the next append."""
    if stream.seek(0, os.SEEK_END):
        stream.seek(-1, os.SEEK_END)
        if stream.read(1) != b"\n":
            stream.write(b"\n")


@contextmanager
def _atomic_text_stream(path: Path):
    path = owner_io_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".write-{secrets.token_hex(12)}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        _replace_record(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _replace_record(temporary: Path, path: Path) -> None:
    # A Windows reader or scanner can briefly hold a share on the target.
    # Retry publication of the same fsynced bytes, never the owner operation.
    deadline = time.monotonic() + 0.7
    while True:
        try:
            os.replace(temporary, path)
            return
        except OSError as exc:
            remaining = deadline - time.monotonic()
            if (os.name != "nt" or getattr(exc, "winerror", None) not in (5, 32, 33)
                    or remaining <= 0):
                raise
            time.sleep(min(0.05, remaining))
