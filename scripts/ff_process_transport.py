"""One bounded lifetime for JSON children: payload, diagnostics, deadline, exit, tree.

stdout is the caller-owned business payload and keeps a hard byte cap. stderr is
optional diagnostics: it is drained concurrently (so the child never blocks on a
full pipe), only the newest bounded window is retained (an explicit ``None`` cap
keeps the whole stream), and exceeding that diagnostic budget never rewrites a
complete stdout result into a transport failure. Each stream has its own
allowance; neither spends the other's.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import threading
import time
from typing import BinaryIO, cast

from ff_process_tree import (
    WindowsJob,
    assign_windows_job,
    kill_owned_group,
    wait_owned_group_stopped,
    pid_is_alive as pid_is_alive,
)

MAX_JSON_OUTPUT_BYTES = 32 * 1024 * 1024
_DEFAULT_STDOUT_CAP = MAX_JSON_OUTPUT_BYTES
_DEFAULT_STDERR_CAP = 64 * 1024
_CLEANUP_GRACE_SECONDS = 2.5

# Waiting bootstrap: no user code executes before job assignment succeeds.
# os.read avoids prefetching request bytes. Keep this parent alive and propagate
# the actual child's exit status; Windows os.execv would lose that guarantee.
_WINDOWS_BOOTSTRAP = (
    "import os,subprocess,sys\n"
    "if os.read(0,1)!=b'\\x00': sys.exit(125)\n"
    "p=subprocess.Popen(sys.argv[1:],stdin=sys.stdin,stdout=sys.stdout,stderr=sys.stderr,close_fds=True,"
    "creationflags=subprocess.CREATE_NO_WINDOW)\n"
    "sys.exit(p.wait())\n"
)


class TransportError(Exception):
    """A bounded transport failed; payloads are never included in its message."""


class ChildStartFailed(OSError):
    """Pre-Popen failure; refines OSError for existing callers without reclassification."""


class OutputLimitExceeded(TransportError):
    """A pipe exceeded its exact byte cap."""


class ChildTimeout(TransportError):
    """The complete child lifetime exceeded the single deadline."""


class ChildFailed(TransportError):
    """Nonzero exit / incomplete input; caller owns structured error classification."""

    def __init__(
        self, message: str, *, returncode: int, stdout: bytes = b"", stderr: bytes = b"",
        input_incomplete: bool = False, stderr_truncated: bool = False
    ) -> None:
        super().__init__(message)
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr
        self.input_incomplete = input_incomplete
        self.stderr_truncated = stderr_truncated


def _assign_windows_job(proc: subprocess.Popen) -> WindowsJob:
    return assign_windows_job(proc)


def _kill_tree(job: WindowsJob | None, proc: subprocess.Popen) -> None:
    try:
        if job is not None:
            job.terminate()
        else:
            kill_owned_group(proc.pid)
    finally:
        if proc.poll() is None:
            proc.kill()


def _close_pipes(proc: subprocess.Popen) -> None:
    for pipe in (proc.stdin, proc.stdout, proc.stderr):
        if pipe is not None:
            pipe.close()


def _spawn(command, input_bytes, cwd, env):
    windows = os.name == "nt"
    argv = [sys.executable, "-B", "-S", "-c", _WINDOWS_BOOTSTRAP, *command] if windows else command
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if windows or input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            shell=False,
            bufsize=0,
            start_new_session=not windows,
            creationflags=subprocess.CREATE_NO_WINDOW if windows else 0,
        )
    except OSError:
        # Only this pre-Popen boundary proves no target/provider could run.
        # Cleanup or pipe errors after this point must retain unknown usage.
        raise ChildStartFailed("could not start owned process") from None
    try:
        job = _assign_windows_job(proc) if windows else None
    except BaseException:
        # Bootstrap cannot create user children yet. Even assignment failures are reaped.
        proc.kill()
        proc.wait(timeout=_CLEANUP_GRACE_SECONDS)
        _close_pipes(proc)
        raise TransportError("could not establish owned process tree") from None
    return proc, job


def _trim_partial_utf8_head(data: bytes) -> bytes:
    """Start a retained window at a whole code point whenever one exists."""
    for cut in range(4):
        candidate = data[cut:]
        try:
            candidate.decode("utf-8")
        except UnicodeDecodeError:
            continue
        return candidate
    # Both ends may be cut; still drop a leading fragment of a code point.
    while data and 0x80 <= data[0] <= 0xBF:
        data = data[1:]
    return data


class _IOState:
    """Only reader threads own their streams; controller owns the lifecycle.

    ``counts`` are bytes read from the pipe. ``retained`` is what is still held:
    stdout is capped hard, stderr keeps a bounded newest-bytes window.
    """

    def __init__(self) -> None:
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.chunks: dict[str, list[bytes]] = {"stdout": [], "stderr": []}
        self.counts = {"stdout": 0, "stderr": 0}
        self.retained = {"stdout": 0, "stderr": 0}
        self.finished: set[str] = set()
        self.error: TransportError | None = None
        self.write_error = False
        self.stderr_truncated = False
        self.threads: list[threading.Thread] = []

    def finish(self, kind: str, error: TransportError | None = None) -> None:
        with self.lock:
            self.finished.add(kind)
            if self.error is None:
                self.error = error
        self.wake.set()

    def read(self, stream: BinaryIO, kind: str, cap: int | None) -> None:
        error: TransportError | None = None
        try:
            while True:
                # At the stdout cap still read ONE probe byte: EOF is valid; cap+1 is not.
                piece = stream.read(self._read_size(kind, cap))
                if not piece:
                    break
                self.counts[kind] += len(piece)
                if kind == "stdout":
                    self.chunks[kind].append(piece)
                    self.retained[kind] += len(piece)
                    if cap is not None and self.retained[kind] > cap:
                        error = OutputLimitExceeded("stdout exceeded its byte cap")
                        break
                else:
                    self._retain_diagnostic(piece, cap)
        except (OSError, ValueError):
            if kind == "stdout":
                error = TransportError("could not read child stdout")
            else:
                # Lost diagnostics are a bounded log gap, not a payload failure.
                self.stderr_truncated = True
        finally:
            stream.close()
            self.finish(kind, error)

    def _read_size(self, kind: str, cap: int | None) -> int:
        if kind == "stdout" and cap is not None:
            return min(65536, cap - self.retained["stdout"] + 1)
        return 65536

    def _retain_diagnostic(self, piece: bytes, cap: int | None) -> None:
        """Drain every diagnostic byte; retain only the newest bounded window."""
        chunks = self.chunks["stderr"]
        chunks.append(piece)
        self.retained["stderr"] += len(piece)
        if cap is None or self.retained["stderr"] <= cap:
            return
        self.stderr_truncated = True
        while self.retained["stderr"] > cap:
            head = chunks[0]
            overflow = self.retained["stderr"] - cap
            if overflow >= len(head):
                chunks.pop(0)
                self.retained["stderr"] -= len(head)
            else:
                chunks[0] = head[overflow:]
                self.retained["stderr"] -= overflow

    def stderr_window(self) -> bytes:
        """Return the newest retained diagnostics, at a whole-code-point start."""
        data = b"".join(self.chunks["stderr"])
        if not self.stderr_truncated:
            return data
        return _trim_partial_utf8_head(data)

    def write(self, stream: BinaryIO, data: bytes) -> None:
        try:
            view = memoryview(data)
            while view:
                size = stream.write(view)
                if not size:
                    raise OSError("incomplete stdin write")
                view = view[size:]
        except (OSError, ValueError):
            self.write_error = True
        finally:
            stream.close()
            self.finish("stdin")

    def start(
        self, proc: subprocess.Popen, payload: bytes | None, stdout_cap: int, stderr_cap: int | None
    ) -> None:
        for kind, stream, cap in (
            ("stdout", proc.stdout, stdout_cap),
            ("stderr", proc.stderr, stderr_cap),
        ):
            self.launch(self.read, (stream, kind, cap), f"{kind}-reader")
        if proc.stdin is None:
            self.finish("stdin")
        else:
            data = (b"\0" if os.name == "nt" else b"") + (payload or b"")
            self.launch(self.write, (proc.stdin, data), "stdin-writer")

    def launch(self, target, args, kind: str) -> None:
        thread = threading.Thread(target=target, args=args, name=f"ff-process-{kind}", daemon=False)
        self.threads.append(thread)
        thread.start()

    def snapshot(self) -> tuple[bool, TransportError | None]:
        with self.lock:
            return len(self.finished) == 3, self.error


def _validate_timeout(value) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("timeout must be a finite number")
    if not math.isfinite(value):
        raise ValueError("timeout must be finite")
    if value <= 0:
        raise ChildTimeout("deadline expired before the child started")


def _validate_caps(*caps) -> None:
    for cap in caps:
        if isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0:
            raise ValueError("output caps must be positive integer byte counts")


def _validate_input(command, input_bytes) -> None:
    if not command or not command[0] or not all(isinstance(arg, str) for arg in command):
        raise ValueError("command must contain string arguments and an executable")
    if input_bytes is not None and not isinstance(input_bytes, bytes):
        raise ValueError("stdin must be bytes")


def _validate(timeout_seconds, stdout_cap, stderr_cap, command, input_bytes) -> None:
    _validate_timeout(timeout_seconds)
    _validate_caps(stdout_cap)
    if stderr_cap is not None:
        _validate_caps(stderr_cap)
    _validate_input(command, input_bytes)


def _await_lifetime(proc, job, state: _IOState, deadline: float) -> None:
    tree_stopped = False
    while True:
        state.wake.clear()
        complete, error = state.snapshot()
        if error is not None:
            raise error
        code = proc.poll()
        if complete and code is not None:
            return
        if code is not None and not tree_stopped:
            _kill_tree(job, proc)  # Orphans may hold pipe handles even after root exit.
            tree_stopped = True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ChildTimeout("child exceeded the shared deadline")
        state.wake.wait(min(0.02, remaining))


def _cleanup(proc, job, state: _IOState) -> None:
    deadline = time.monotonic() + _CLEANUP_GRACE_SECONDS
    try:
        _kill_tree(job, proc)
    finally:
        if job is not None:
            job.close()  # Also kills descendants if explicit termination failed.
    proc.wait(timeout=max(0.001, deadline - time.monotonic()))
    group_stopped = job is not None or wait_owned_group_stopped(proc.pid, deadline)
    for thread in state.threads:
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
    if any(thread.is_alive() for thread in state.threads):
        raise TransportError("owned process cleanup exceeded its grace period")
    _close_pipes(proc)
    if not group_stopped:
        raise TransportError("owned process group did not stop within cleanup grace")


def _result(proc, state: _IOState) -> dict[str, object]:
    stdout, stderr = b"".join(state.chunks["stdout"]), state.stderr_window()
    if proc.returncode != 0 or state.write_error:
        raise ChildFailed(
            "child closed stdin early" if state.write_error else f"child exited {proc.returncode}",
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            input_incomplete=bool(state.write_error),
            stderr_truncated=state.stderr_truncated,
        )
    return dict(
        stdout=stdout,
        stderr=stderr,
        stdout_bytes_read=state.counts["stdout"],
        stderr_bytes_read=state.counts["stderr"],
        stderr_truncated=state.stderr_truncated,
        returncode=0,
    )


def run_bounded(
    command: list[str],
    *,
    timeout_seconds: float,
    input_bytes: bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdout_cap_bytes: int = _DEFAULT_STDOUT_CAP,
    stderr_cap_bytes: int | None = _DEFAULT_STDERR_CAP,
) -> dict[str, object]:
    """Bound stdin, the stdout payload, diagnostics and exit by one absolute deadline.

    stdout over ``stdout_cap_bytes`` raises ``OutputLimitExceeded``. stderr is
    optional diagnostics: only the newest ``stderr_cap_bytes`` are retained,
    ``stderr_bytes_read`` reports what the child actually wrote, and overflow,
    a lost diagnostic read or non-UTF-8 log bytes never fail a delivered
    payload. ``stderr_cap_bytes=None`` keeps the whole diagnostic stream for an
    explicit caller-owned receipt. Success returns bytes/counts/returncode;
    nonzero exit raises ChildFailed with the retained bytes. Cleanup has one
    separate 2.5s maximum, never a renewed request.
    """
    _validate(timeout_seconds, stdout_cap_bytes, stderr_cap_bytes, command, input_bytes)
    deadline = time.monotonic() + timeout_seconds
    proc, job = _spawn(command, input_bytes, cwd, env)
    state = _IOState()
    try:
        if time.monotonic() >= deadline:
            raise ChildTimeout("deadline expired during spawn")
        state.start(proc, input_bytes, stdout_cap_bytes, stderr_cap_bytes)
        _await_lifetime(proc, job, state, deadline)
    finally:
        _cleanup(proc, job, state)
    return _result(proc, state)


def run_bounded_json(
    command: list[str],
    *,
    timeout_seconds: float,
    input_bytes: bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdout_cap_bytes: int = _DEFAULT_STDOUT_CAP,
    stderr_cap_bytes: int | None = _DEFAULT_STDERR_CAP,
    allow_nonzero_exit: bool = False,
) -> tuple[bytes, bytes, int]:
    """Success stdout is strict UTF-8; stderr stays opaque bounded diagnostics.

    ChildFailed retains caller-owned error bytes. A diagnostic stream that is
    not valid UTF-8 is returned verbatim; it cannot veto a valid payload.
    """
    try:
        result = run_bounded(
            command,
            timeout_seconds=timeout_seconds,
            input_bytes=input_bytes,
            cwd=cwd,
            env=env,
            stdout_cap_bytes=stdout_cap_bytes,
            stderr_cap_bytes=stderr_cap_bytes,
        )
    except ChildFailed as exc:
        # Protocol owners classify named nonzero business envelopes; actual
        # write failures and absent exits remain transport failures.
        if not allow_nonzero_exit or exc.input_incomplete or exc.returncode in (None, 0):
            raise
        result = {"stdout": exc.stdout, "stderr": exc.stderr, "returncode": exc.returncode}
    stdout, stderr = cast(bytes, result["stdout"]), cast(bytes, result["stderr"])
    try:
        stdout.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise TransportError("child stdout was not valid UTF-8") from error
    return stdout, stderr, cast(int, result["returncode"])
