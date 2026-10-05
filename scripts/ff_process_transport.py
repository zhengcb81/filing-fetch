"""Bounded subprocess transport for filing-fetch JSON helpers.

One shared layer for every JSON-speaking child this repo spawns (the
company-wiki catalog CLI and the ET tool). It bounds stdout and stderr in
actual UTF-8 bytes *while reading*, shares one deadline per request, decodes
strictly, and reaps only the process tree it created. It knows nothing about
filings, sources or transcripts — bytes/time/exit/cleanup only.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Any, cast

# One ceiling for every JSON subprocess this repo spawns; the filing runner
# imports it and the ET/transcript transport shares the same module so all
# transports fail closed at the same number.
MAX_JSON_OUTPUT_BYTES = 32 * 1024 * 1024

_DEFAULT_STDOUT_CAP = MAX_JSON_OUTPUT_BYTES
_DEFAULT_STDERR_CAP = 64 * 1024

# Cleanup grace used to reap the child tree after a deadline/cap failure.
# Bounded; it is never counted as new download budget.
_TREE_KILL_GRACE_SECONDS = 10.0


class TransportError(Exception):
    """Base class for named bounded-transport failures."""


class OutputLimitExceeded(TransportError):
    """The child wrote past a read-time byte cap (stdout or stderr)."""


class ChildTimeout(TransportError):
    """The child outlived the bounded deadline."""


class ChildFailed(TransportError):
    """The child exited nonzero without hitting any cap."""

    def __init__(
        self,
        message: str,
        *,
        returncode: int,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _job_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import win32api  # type: ignore[import-untyped]  # noqa: F401
        import win32job  # type: ignore[import-untyped]  # noqa: F401
    except ImportError:
        return False
    return True


def _assign_windows_job(proc: subprocess.Popen) -> Any | None:
    """Windows: assign the child (before grandchildren exist) to a job with
    KILL_ON_JOB_CLOSE, so reaping the tree is deterministic and never
    dependent on taskkill's snapshot walk. Returns the job handle or None."""
    try:
        import win32api  # type: ignore[import-untyped]
        import win32job  # type: ignore[import-untyped]

        job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
        # PROCESS_ALL_ACCESS: assignment with narrower rights is refused
        # with EPERM on standard processes.
        handle = win32api.OpenProcess(0x1F0FFF, False, proc.pid)
        win32job.AssignProcessToJobObject(job, handle)
        return job
    except Exception:
        return None


def _creationflags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _preexec() -> None:
    # POSIX only: own process group so the reaper can signal the whole tree.
    os.setsid()  # type: ignore[attr-defined]  # pragma: no cover - POSIX only


def _windows_tree_kill(job: Any | None, proc: subprocess.Popen) -> None:
    if job is not None:
        try:
            import win32job  # type: ignore[import-untyped]

            win32job.TerminateJobObject(job, 1)
        except Exception:
            pass
        return
    try:
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _posix_group_kill(pid: int) -> None:
    import errno
    import signal

    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)  # type: ignore[attr-defined]
    except OSError as exc:
        if exc.errno != errno.ESRCH:
            try:
                os.kill(pid, signal.SIGKILL)  # type: ignore[attr-defined]
            except OSError:
                pass


def _kill_tree(job: Any | None, proc: subprocess.Popen) -> None:
    """Kill exactly the tree this call created (never scan other processes)."""
    try:
        if os.name == "nt":
            _windows_tree_kill(job, proc)
        else:
            _posix_group_kill(proc.pid)
    finally:
        try:
            proc.kill()
        except OSError:
            pass


def _drain_tree(job: Any | None, proc: subprocess.Popen) -> None:
    _kill_tree(job, proc)
    try:
        proc.wait(timeout=_TREE_KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass  # reaped on job close; never hang on it


def pid_is_alive(pid: int) -> bool:
    """Best-effort pid liveness for tests/diagnostics; unknown states count
    as alive (conservative)."""
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _close_job(job) -> None:
    if job is None:
        return
    try:
        import win32api  # type: ignore[import-untyped]

        win32api.CloseHandle(job)
    except Exception:
        pass


def _spawn(command, input_bytes, cwd, env):
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
        shell=False,
        creationflags=_creationflags(),
        preexec_fn=None if os.name == "nt" else _preexec,
    )
    job = _assign_windows_job(proc) if _job_available() else None
    return proc, job


def _reader_loop(stream, counter, cap, kind):
    # Count bytes AS THEY ARE READ: an exceeded cap stops the read close to
    # the cap, never waiting on a fully-buffered child first. Bytes are the
    # raw read size, so non-ASCII is counted as UTF-8 bytes.
    chunks: list[bytes] = []
    error: BaseException | None = None
    try:
        while True:
            remaining = cap - counter[0]
            if remaining <= 0:
                raise OutputLimitExceeded(f"{kind} exceeded its byte cap")
            piece = stream.read(min(65536, remaining + 1))
            if not piece:
                return chunks, error
            chunks.append(piece)
            counter[0] += len(piece)
            if counter[0] > cap:
                raise OutputLimitExceeded(f"{kind} exceeded its byte cap")
    except OutputLimitExceeded as exc:
        return chunks, exc
    except OSError as exc:
        return chunks, exc


def _start_readers(proc, stdout_cap, stderr_cap):
    counters = {"stdout": [0], "stderr": [0]}
    holders: dict[str, BaseException | None] = {}
    chunks: dict[str, list[bytes]] = {}
    threads: list[threading.Thread] = []
    done = threading.Event()

    def _run(k: str, stream) -> None:
        data, error = _reader_loop(stream, counters[k], caps[k], k)
        chunks[k] = data
        holders[k] = error
        try:
            stream.close()
        except OSError:
            pass
        if len(holders) == 2:
            done.set()

    caps = {"stdout": stdout_cap, "stderr": stderr_cap}
    for kind, stream in (("stdout", proc.stdout), ("stderr", proc.stderr)):
        thread = threading.Thread(
            target=_run,
            args=(kind, stream),
            name=f"ff-process-{kind}-reader",
            daemon=False,
        )
        thread.start()
        threads.append(thread)
    return threads, chunks, counters, holders, done


def _pump_stdin(proc, input_bytes):
    if input_bytes is None or proc.stdin is None:
        return None
    try:
        proc.stdin.write(input_bytes)
        proc.stdin.close()
    except OSError as exc:
        return exc
    return None


def _await_streams(done, proc, job, timeout_seconds):
    """Wait until both readers finish, the shared deadline expires, or the
    child exits (then reap the tree so grandchild-held pipes can EOF)."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return ChildTimeout("child exceeded the shared deadline")
        if done.wait(min(0.25, remaining)):
            return None
        if proc.poll() is None:
            continue
        # Direct child is done but a descendant may still hold the pipe
        # write ends; it belongs to the tree this call created — reap it.
        _kill_tree(job, proc)
        try:
            proc.wait(timeout=_TREE_KILL_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            pass


def run_bounded(
    command: list[str],
    *,
    timeout_seconds: float,
    input_bytes: bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdout_cap_bytes: int = _DEFAULT_STDOUT_CAP,
    stderr_cap_bytes: int = _DEFAULT_STDERR_CAP,
) -> dict[str, object]:
    """Run one child with read-time byte caps on stdout and stderr.

    Returns ``{"stdout": bytes, "stderr": bytes, "stdout_bytes_read": int,
    "stderr_bytes_read": int, "returncode": int}`` on success. Raises a named
    TransportError subclass on cap overflow or deadline overrun; a nonzero
    exit is raised as :class:`ChildFailed` for the caller to classify.
    """
    if timeout_seconds <= 0:
        raise ChildTimeout("deadline expired before the child started")
    proc, job = _spawn(command, input_bytes, cwd, env)
    threads, chunks, counters, holders, done = _start_readers(
        proc, stdout_cap_bytes, stderr_cap_bytes
    )
    write_error = _pump_stdin(proc, input_bytes)
    overflow = _await_streams(done, proc, job, timeout_seconds)
    for thread in threads:
        thread.join(timeout=5)
    return _finalize(
        job,
        proc,
        overflow,
        write_error,
        holders,
        chunks,
        counters,
    )


def _final_result(chunks, counters, job):
    _close_job(job)
    return {
        "stdout": b"".join(chunks.get("stdout") or []),
        "stderr": b"".join(chunks.get("stderr") or []),
        "stdout_bytes_read": counters["stdout"][0],
        "stderr_bytes_read": counters["stderr"][0],
        "returncode": 0,
    }


def _raise_static(job, proc, returncode, chunks, write_error):
    _drain_tree(job, proc)
    if write_error is not None:
        raise ChildFailed(
            "child closed stdin before the request was fully written",
            returncode=returncode,
        )
    raise ChildFailed(
        f"child exited {returncode}",
        returncode=returncode,
        stdout=b"".join(chunks.get("stdout") or []),
        stderr=b"".join(chunks.get("stderr") or []),
    )


def _finalize(job, proc, overflow, write_error, holders, chunks, counters):
    if overflow is None:
        overflow = holders.get("stdout") or holders.get("stderr")
    if overflow is not None:
        _drain_tree(job, proc)
        raise overflow  # named: OutputLimitExceeded / ChildTimeout
    returncode = proc.wait()
    if returncode == 0 and write_error is None:
        return _final_result(chunks, counters, job)
    _raise_static(job, proc, returncode, chunks, write_error)


def run_bounded_json(
    command: list[str],
    *,
    timeout_seconds: float,
    input_bytes: bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stdout_cap_bytes: int = _DEFAULT_STDOUT_CAP,
    stderr_cap_bytes: int = _DEFAULT_STDERR_CAP,
) -> tuple[bytes, bytes, int]:
    """run_bounded for JSON children: strict UTF-8 decode of both pipes.

    Returns ``(stdout_bytes, stderr_bytes, returncode)``. A nonzero exit is
    still a *return* here — callers own the structured-stderr classification
    (the layer never inspects payloads). Only caps, timeouts and encoding
    failures are this layer's named errors.
    """
    result = run_bounded(
        command,
        timeout_seconds=timeout_seconds,
        input_bytes=input_bytes,
        cwd=cwd,
        env=env,
        stdout_cap_bytes=stdout_cap_bytes,
        stderr_cap_bytes=stderr_cap_bytes,
    )
    stdout_bytes = cast(bytes, result["stdout"])
    stderr_bytes = cast(bytes, result["stderr"])
    try:
        stdout_bytes.decode("utf-8", errors="strict")
        stderr_bytes.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise TransportError("child output was not valid UTF-8") from exc
    return stdout_bytes, stderr_bytes, cast(int, result["returncode"])
