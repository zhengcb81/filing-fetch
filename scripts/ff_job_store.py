"""Durable on-disk job store for the ff-job/1 façade.

Layout under ``--jobs-dir`` (default ``<skill_root>/.ff_jobs``):

    jobs/<owner_job_id>.json        full durable record (atomic replace + fsync)
    index/idem/<sha256(key)>.json   idempotency pointer {"owner_job_id", "request_hash"}
    index/idem/.submit.lock         OS lock for submission publication
    locks/<owner_job_id>.lock       O_EXCL mutation lock with dead-pid takeover
    logs/<owner_job_id>.log         append-only runner audit trail (JSON lines)

Cross-process discipline:

- Reads never block: every read is a single atomic file read.
- Mutations hold the per-job lock. The lock records the holder's pid; a lock
  whose pid is provably dead (or older than LOCK_STALE_SECONDS) is stolen, so
  a crashed runner cannot wedge its job forever.
- Cancel is a queued-only state transition under the same lock (the engine is
  one bounded subprocess call with no interruption point); no separate flag
  protocol exists.
- ``status=running`` is written atomically together with ``owner_pid`` and
  ``run_deadline_at``; any reader that finds a running job whose pid is dead
  or whose deadline plus a grace has passed flips it to ``unknown`` /
  ``status_known=false`` (G-m8-FF-04). No terminal state is ever invented.

PID liveness reuses the engine's own diagnostic (``ff_process_tree.pid_is_alive``);
pid reuse on Windows can keep a dead runner's lock looking alive — in that
case the lock age bound still forces a takeover, and this heuristic is
declared in the module rather than hidden.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from ff_job_contracts import (
    FFJobError,
    FF_JOB_SCHEMA_VERSION,
    RECOVERY_CAPABILITY,
    RUN_STALENESS_GRACE_SECONDS,
    job_intent,
    validate_owner_job_id,
)
from ff_process_tree import pid_is_alive

LOCK_STALE_SECONDS = 24 * 3600.0
_LOCK_POLL_SECONDS = 0.05
_MAX_EVENTS = 50
# Bound contention for the short owner-local submission transaction.
_IDEM_BUSY_TIMEOUT_SECONDS = 5.0


@contextmanager
def _submission_lock(path: Path) -> Iterator[None]:
    """Serialize pointer and job publication with a crash-released OS lock."""
    deadline = time.monotonic() + _IDEM_BUSY_TIMEOUT_SECONDS
    # Leave the file in place so every process always locks the same inode.
    with path.open("a+b") as stream:
        while True:
            try:
                if os.name == "nt":
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
                    raise FFJobError(
                        "job submission is busy; retry the submission", code="request_error",
                    ) from exc
                time.sleep(_LOCK_POLL_SECONDS)
            else:
                break
        yield


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, payload: dict) -> None:
    """One durable record write: temp file in the same directory + fsync + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=1)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _read_json(path: Path) -> dict | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


class _JobLock:
    """O_EXCL lock with pid-stamped content and takeover semantics."""

    def __init__(self, path: Path, token: str, pid: int) -> None:
        self.path = path
        self.token = token
        self.pid = pid

    def release(self) -> None:
        content = _read_json(self.path)
        if content is not None and content.get("token") == self.token:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


class JobStore:
    """All durable job state access; the only module that touches job files."""

    def __init__(self, jobs_dir: Path) -> None:
        self.jobs_dir = jobs_dir
        self.jobs = jobs_dir / "jobs"
        self.idem_index = jobs_dir / "index" / "idem"
        self.locks = jobs_dir / "locks"
        self.logs_dir = jobs_dir / "logs"
        for directory in (self.jobs, self.idem_index, self.locks, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)

    # -- paths --------------------------------------------------------------

    def _job_path(self, owner_job_id: str) -> Path:
        return self.jobs / f"{validate_owner_job_id(owner_job_id)}.json"

    def _lock_path(self, owner_job_id: str) -> Path:
        return self.locks / f"{validate_owner_job_id(owner_job_id)}.lock"

    def _log_path(self, owner_job_id: str) -> Path:
        return self.logs_dir / f"{validate_owner_job_id(owner_job_id)}.log"

    def _idem_path(self, idempotency_key: str) -> Path:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self.idem_index / f"{digest}.json"

    # -- creation / reads ---------------------------------------------------

    def create_job(self, body: dict, *, command_id: str) -> tuple[dict, bool]:
        """Persist one submission. Same idempotency_key + same canonical
        request returns the existing job untouched (``replayed=True``); the
        same key with a different request is a named conflict, never a
        silent second acquisition (G-m8-FF-03).

        Hold the submission lock until the pointer and complete job are
        published. A later submit can repair a pointer left by a dead writer.
        """
        request_hash = _canonical_hash({"kind": body["kind"], "request": body["request"]})
        key = body["idempotency_key"]
        pointer_path = self._idem_path(key)
        with _submission_lock(self.idem_index / ".submit.lock"):
            existing = self._idempotency_lookup(key, request_hash)
            if existing is not None:
                return existing, True
            owner_job_id = f"ffjob-{uuid.uuid4().hex[:12]}"
            created = now_iso()
            record = {
                "schema_version": FF_JOB_SCHEMA_VERSION,
                "owner_job_id": owner_job_id,
                "command_id": command_id,
                "kind": body["kind"],
                "idempotency_key": body["idempotency_key"],
                "request_hash": request_hash,
                "request": body["request"],
                "intent": job_intent(body["kind"], body["request"]),
                "status": "queued",
                "status_known": True,
                "created_at": created,
                "updated_at": created,
                "started_at": None,
                "run_deadline_at": None,
                "owner_pid": None,
                "heartbeat_at": None,
                "attempts": 0,
                "execution_count": 0,
                "cancel_requested": False,
                "provider_phase_reached": False,
                "spend_evidence": {
                    "provider_started": None,
                    "usage_complete": None,
                    "download_events": None,
                },
                "error": None,
                "cost": None,
                "cost_state": "not_applicable",
                "result": None,
                "recovery_capability": RECOVERY_CAPABILITY,
                "actions": [],
                "events": [{"at": created, "event": "submitted"}],
            }
            _atomic_write_json(
                pointer_path, {"owner_job_id": owner_job_id, "request_hash": request_hash},
            )
            _atomic_write_json(self._job_path(owner_job_id), record)
            return record, False

    def _idempotency_lookup(self, key: str, request_hash: str) -> dict | None:
        """Read or repair a key under the submission lock."""
        pointer_path = self._idem_path(key)
        pointer = _read_json(pointer_path)
        if pointer is None and not pointer_path.exists():
            return None
        job_id = pointer.get("owner_job_id") if pointer else None
        prior = None
        if isinstance(job_id, str):
            try:
                prior = self.load(job_id)
            except FFJobError:
                pass
        if prior is None or prior.get("idempotency_key") != key:
            prior = self._recover_idempotency_pointer(key)
            if prior is not None:
                _atomic_write_json(pointer_path, {
                    "owner_job_id": prior["owner_job_id"], "request_hash": prior["request_hash"],
                })
        if prior is not None and prior.get("request_hash") != request_hash:
            raise FFJobError(
                "idempotency_key already bound to a different request", code="request_error",
            )
        return prior

    def _recover_idempotency_pointer(self, key: str) -> dict | None:
        """Look for an existing job only when its index entry is damaged."""
        match = None
        for job_id in self.iter_job_ids():
            job = self.load(job_id)
            if job is None:
                raise FFJobError("job history is unreadable", code="request_error")
            if job.get("idempotency_key") == key:
                if match is not None:
                    raise FFJobError(
                        "idempotency_key already has multiple stored jobs", code="request_error",
                    )
                match = job
        return match

    def load(self, owner_job_id: str) -> dict | None:
        return _read_json(self._job_path(owner_job_id))

    def iter_job_ids(self) -> Iterator[str]:
        for path in sorted(self.jobs.glob("ffjob-*.json")):
            yield path.stem

    # -- liveness (G-m8-FF-04) ----------------------------------------------

    def run_lost(self, record: dict, *, now: float | None = None) -> str | None:
        """Return why a running job must be reported unknown, or None.

        The rule is declared, never inferred: the owning pid is dead, or the
        runner's own declared deadline plus the grace has passed. A live,
        within-budget runner stays ``running`` — the bounded engine finishes
        or times out on its own.
        """
        if record.get("status") != "running":
            return None
        pid = record.get("owner_pid")
        now_monotonic_basis = now if now is not None else time.time()
        deadline = record.get("run_deadline_at")
        expired = isinstance(deadline, str) and self._past(deadline, now_monotonic_basis)
        if not isinstance(pid, int) or not pid_is_alive(pid):
            return "owner_pid_dead"
        if expired:
            return "run_deadline_exceeded"
        return None

    @staticmethod
    def _past(iso_deadline: str, now: float) -> bool:
        try:
            moment = datetime.fromisoformat(iso_deadline.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return True
        return now > moment + RUN_STALENESS_GRACE_SECONDS

    def _mark_unknown(self, record: dict, reason: str) -> dict:
        updated = dict(record)
        stamp = now_iso()
        updated["status"] = "unknown"
        updated["status_known"] = False
        updated["error"] = {
            "code": "run_lost",
            "message": f"the owning run process was lost ({reason}); reconcile to re-check owner state",
            "owner": "filing-fetch",
            "retryable": True,
            "next_actions": ["reconcile"],
            "correlation_id": record.get("owner_job_id", ""),
        }
        updated["cost"] = None
        updated["cost_state"] = "unknown" if updated.get("intent") != "reuse_only" else "not_applicable"
        updated["updated_at"] = stamp
        updated["events"] = [*record.get("events", []), {"at": stamp, "event": "run_lost",
                                                         "detail": {"reason": reason}}][-_MAX_EVENTS:]
        return updated

    def load_checked(self, owner_job_id: str, *, fix: bool) -> tuple[dict, bool]:
        """Load a record and evaluate run liveness. ``fix=True`` persists an
        unknown transition (best-effort under the lock); otherwise the record
        is returned as stored."""
        record = self.load(owner_job_id)
        if record is None:
            raise FFJobError(f"unknown owner_job_id: {owner_job_id}", code="request_error")
        reason = self.run_lost(record)
        if reason is None:
            return record, False
        if not fix:
            return record, False
        try:
            with self.lock(owner_job_id, timeout_seconds=2.0):
                current = self.load(owner_job_id)
                if current is None:
                    return record, False
                reason = self.run_lost(current)
                if reason is not None:
                    current = self._mark_unknown(current, reason)
                    _atomic_write_json(self._job_path(owner_job_id), current)
                    return current, True
                return current, False
        except FFJobError:
            # Lock busy (a live runner owns it): report as stored; the runner
            # is still inside its own bounded budget and will finish the state.
            return record, False

    # -- mutation -----------------------------------------------------------

    def lock(self, owner_job_id: str, *, timeout_seconds: float = 5.0) -> "_LockContext":
        return _LockContext(self, owner_job_id, timeout_seconds)

    def mutate(
        self,
        owner_job_id: str,
        mutator: Callable[[dict], dict],
        *,
        timeout_seconds: float = 5.0,
    ) -> dict:
        """One locked read-modify-write cycle. The mutator returns the new
        record; the store stamps ``updated_at`` and appends nothing else."""
        with self.lock(owner_job_id, timeout_seconds=timeout_seconds):
            record = self.load(owner_job_id)
            if record is None:
                raise FFJobError(f"unknown owner_job_id: {owner_job_id}", code="request_error")
            return self.write_locked(mutator(record))

    def write_locked(self, record: dict) -> dict:
        """Persist one record; the caller must already hold the job's lock."""
        owner_job_id = record.get("owner_job_id")
        record["updated_at"] = now_iso()
        _atomic_write_json(self._job_path(str(owner_job_id)), record)
        return record

    def acquire_lock(self, owner_job_id: str, timeout_seconds: float) -> _JobLock:
        lock_path = self._lock_path(owner_job_id)
        token = secrets.token_hex(8)
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise FFJobError(
                        f"job {owner_job_id} is busy in another process", code="request_error"
                    )
                self._maybe_steal(lock_path)
                time.sleep(_LOCK_POLL_SECONDS)
                continue
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"pid": os.getpid(), "token": token, "acquired_at": now_iso()}, stream)
            return _JobLock(lock_path, token, os.getpid())

    def _maybe_steal(self, lock_path: Path) -> None:
        content = _read_json(lock_path)
        try:
            age = time.time() - lock_path.stat().st_mtime
        except OSError:
            return
        if content is None:
            if age > 60.0:
                lock_path.unlink(missing_ok=True)
            return
        pid = content.get("pid")
        if not isinstance(pid, int) or not pid_is_alive(pid) or age > LOCK_STALE_SECONDS:
            lock_path.unlink(missing_ok=True)

    # -- audit log ----------------------------------------------------------

    def append_log(self, owner_job_id: str, entry: dict) -> None:
        line = json.dumps({"at": now_iso(), **entry}, ensure_ascii=False)
        with self._log_path(owner_job_id).open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")
            stream.flush()

    def read_log(self, owner_job_id: str) -> list[str]:
        try:
            return self._log_path(owner_job_id).read_text(encoding="utf-8").splitlines()
        except OSError:
            return []


class _LockContext:
    def __init__(self, store: JobStore, owner_job_id: str, timeout_seconds: float) -> None:
        self._store = store
        self._owner_job_id = owner_job_id
        self._timeout = timeout_seconds
        self._handle: _JobLock | None = None

    def __enter__(self) -> None:
        self._handle = self._store.acquire_lock(self._owner_job_id, self._timeout)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is not None:
            self._handle.release()
            self._handle = None


__all__ = ["JobStore", "now_iso"]
