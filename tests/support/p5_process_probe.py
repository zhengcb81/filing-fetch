"""Controlled child scenarios for MAIN acceptance; no network or source files."""

from __future__ import annotations
import ctypes
import json
import os
from pathlib import Path
import sys
import threading
import time

sys.stdin.buffer.read(1)  # Outer watchdog assigns its job before allowing children.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import ff_process_transport as fpt  # noqa: E402

case, root_text = sys.argv[1:3]
root = Path(root_text)
pid_path = root / "child.pid"
grand_path = root / "grand.pid"
signal_path = root / "assign.signal"
common = "import os,sys,threading;from pathlib import Path;Path(sys.argv[1]).write_text(str(os.getpid()));"
programs = {
    "closed_pipes": common + "os.close(1);os.close(2);threading.Event().wait(30)",
    "stdin_blocked": common + "threading.Event().wait(30)",
    "one_stream_overflow": common + "os.write(1,b'x'*65);threading.Event().wait(30)",
    "still_running": common + "os.write(1,b'ok');threading.Event().wait(30)",
}
early = []
if case == "grandchild":
    grand_code = "import os,sys,threading;from pathlib import Path;Path(sys.argv[1]).write_text(str(os.getpid()));threading.Event().wait(30)"
    programs[case] = common + (
        "import subprocess;"
        f"subprocess.Popen([sys.executable,'-S','-c',{grand_code!r},sys.argv[2]]);"
        "\nwhile not Path(sys.argv[2]).exists(): threading.Event().wait(0.005)\n"
        "os.write(1,b'parent-exit')"
    )
    if os.name == "nt":
        original_assign = fpt._assign_windows_job

        def delayed_assign(proc):
            signal_path.write_text("assignment entered")
            end = time.monotonic() + 0.7
            while not grand_path.exists() and time.monotonic() < end:
                threading.Event().wait(0.005)
            early.append(grand_path.exists())
            return original_assign(proc)

        fpt._assign_windows_job = delayed_assign


def alive(pid):
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_uint32()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # Linux zombies are already terminated; only a living process is a leak.
    stat = Path(f"/proc/{pid}/stat")
    return not stat.exists() or stat.read_text().split(") ", 1)[1][0] != "Z"


original_spawn = fpt._spawn


def tracked_spawn(*args, **kwargs):
    proc, job = original_spawn(*args, **kwargs)
    (root / "owned.pid").write_text(str(proc.pid))
    return proc, job


fpt._spawn = tracked_spawn

started = time.monotonic()
try:
    kwargs = {"timeout_seconds": 3.0 if case == "grandchild" else 1.0, "stdout_cap_bytes": 64}
    if case == "stdin_blocked":
        kwargs["input_bytes"] = b"x" * (2 * 1024 * 1024)
    result = fpt.run_bounded(
        [sys.executable, "-S", "-c", programs[case], str(pid_path), str(grand_path)],
        **kwargs,
    )
    outcome = "ok"
    stdout = result["stdout"].decode("utf-8")
except BaseException as error:
    outcome, stdout = type(error).__name__, ""
pids = {p.name: int(p.read_text()) for p in (pid_path, grand_path) if p.exists()}
print(
    json.dumps(
        {
            "outcome": outcome,
            "stdout": stdout,
            "elapsed": time.monotonic() - started,
            "alive_before_watchdog_cleanup": {name: alive(pid) for name, pid in pids.items()},
            "reader_threads": [
                t.name for t in threading.enumerate() if t.name.startswith("ff-process")
            ],
            "early_descendant_before_job": any(early),
        }
    )
)
