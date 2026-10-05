"""OS ownership for exactly one subprocess tree; no external utilities/dependencies."""

from __future__ import annotations

import ctypes
import errno
import os
import signal
import subprocess
import sys
from ctypes import wintypes


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", wintypes.DWORD),
        ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t),
        ("active_processes", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD),
    ]


class _IOCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "read_ops",
            "write_ops",
            "other_ops",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits),
        ("io", _IOCounters),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


def _kernel():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    declarations = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": (
            [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
            wintypes.BOOL,
        ),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "GetExitCodeProcess": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
    }
    for name, (arguments, result) in declarations.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


def _win_error() -> OSError:
    # Typeshed exposes these only for Windows; this function is Windows-only at runtime.
    if sys.platform == "win32":
        return ctypes.WinError(ctypes.get_last_error())
    return OSError("Windows Job API unavailable on this platform")


class WindowsJob:
    """The waiting bootstrap is assigned before it can launch the user's command."""

    def __init__(self, process_handle: int) -> None:
        self.kernel = _kernel()
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise _win_error()
        try:
            info = _ExtendedLimits()
            info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.kernel.SetInformationJobObject(
                self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)
            ):
                raise _win_error()
            if not self.kernel.AssignProcessToJobObject(self.handle, process_handle):
                raise _win_error()
        except BaseException:
            self.close()
            raise

    def terminate(self) -> None:
        if self.handle and not self.kernel.TerminateJobObject(self.handle, 1):
            raise _win_error()

    def close(self) -> None:
        handle, self.handle = self.handle, None
        if handle and not self.kernel.CloseHandle(handle):
            raise _win_error()


def kill_owned_group(group_id: int) -> None:
    # start_new_session makes proc.pid the PGID. Save it; the leader may be gone.
    try:
        os.killpg(group_id, signal.SIGKILL)  # type: ignore[attr-defined] # POSIX only
    except OSError as error:
        if error.errno != errno.ESRCH:
            raise


def pid_is_alive(pid: int) -> bool:
    """Diagnostic only; a Windows handle can exist after the process has exited."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except OSError:
            return True
    kernel = _kernel()
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


def assign_windows_job(proc: subprocess.Popen) -> WindowsJob:
    # Popen already owns the process handle created with the required rights.
    # Do not reopen by PID or request extra PROCESS_ALL_ACCESS privileges.
    return WindowsJob(int(proc._handle))  # type: ignore[attr-defined] # Windows Popen handle
