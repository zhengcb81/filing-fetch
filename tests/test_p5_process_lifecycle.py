"""Actual process lifetime tests, isolated scratch and an independent watchdog."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

import pytest
import ff_process_transport as fpt

PROBE = Path(__file__).parent / "support/p5_process_probe.py"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("size", [9, 10, 11])
def test_exact_output_byte_cap_allows_eof_at_the_boundary(stream, size):
    descriptor = 1 if stream == "stdout" else 2
    command = [sys.executable, "-S", "-c", f"import os;os.write({descriptor},b'x'*{size})"]
    limits = {f"{stream}_cap_bytes": 10}
    if size > 10:
        with pytest.raises(fpt.OutputLimitExceeded):
            fpt.run_bounded(command, timeout_seconds=3, **limits)
    else:
        result = fpt.run_bounded(command, timeout_seconds=3, **limits)
        assert result[stream] == b"x" * size
        assert result[f"{stream}_bytes_read"] == size


@pytest.mark.parametrize(
    "invalid",
    [
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": float("inf")},
        {"timeout_seconds": True},
        {"stdout_cap_bytes": 0},
        {"stderr_cap_bytes": -1},
        {"stdout_cap_bytes": True},
        {"stderr_cap_bytes": 2.5},
    ],
)
def test_invalid_resources_are_rejected_without_spawning(monkeypatch, invalid):
    def unexpected_spawn(*_args, **_kwargs):
        pytest.fail("invalid resource arguments spawned a child")

    monkeypatch.setattr(fpt, "_spawn", unexpected_spawn)
    args = {"timeout_seconds": 1, **invalid}
    with pytest.raises(ValueError):
        fpt.run_bounded([sys.executable, "-S", "-c", "pass"], **args)


def _watchdog_job(proc):
    # Independent test watchdog. The probe is blocked on stdin until assigned.
    win32api = pytest.importorskip("win32api")
    win32job = pytest.importorskip("win32job")
    job = win32job.CreateJobObject(None, "")
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    info["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
    handle = win32api.OpenProcess(0x1F0FFF, False, proc.pid)
    try:
        win32job.AssignProcessToJobObject(job, handle)
    finally:
        win32api.CloseHandle(handle)
    return job


def _kill_watchdog_tree(proc, job, root):
    if os.name == "nt" and job is not None:
        import win32job

        win32job.TerminateJobObject(job, 1)
    elif os.name != "nt":
        # Production owns a separate session. The outer watchdog must also stop
        # that exact recorded group, rather than only its own probe session.
        owned = root / "owned.pid"
        if owned.is_file():
            try:
                os.killpg(int(owned.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if proc.poll() is None:
        proc.kill()


def _probe(tmp_path, case):
    import json

    before = tuple(sorted(tmp_path.iterdir()))
    root = tmp_path / "probe"
    root.mkdir()
    proc = None
    job = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-B", str(PROBE), case, str(root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            start_new_session=os.name != "nt",
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )
        if os.name == "nt":
            job = _watchdog_job(proc)
        try:
            stdout, stderr = proc.communicate(b"G", timeout=8 if case == "grandchild" else 6)
        except subprocess.TimeoutExpired:
            _kill_watchdog_tree(proc, job, root)
            proc.communicate(timeout=3)
            pytest.fail(f"{case}: outer watchdog had to stop the unbounded transport")
        assert proc.returncode == 0, stderr.decode("utf-8", errors="replace")
        return json.loads(stdout)
    finally:
        if proc is not None:
            _kill_watchdog_tree(proc, job, root)
            proc.wait(timeout=3)
            for pipe in (proc.stdin, proc.stdout, proc.stderr):
                if pipe is not None:
                    pipe.close()
        if job is not None:
            import win32api

            win32api.CloseHandle(job)
        assert root.resolve().parent == tmp_path.resolve()
        shutil.rmtree(root)
        assert tuple(sorted(tmp_path.iterdir())) == before


@pytest.mark.parametrize(
    "case,expected",
    [
        ("closed_pipes", "ChildTimeout"),
        ("stdin_blocked", "ChildTimeout"),
        ("one_stream_overflow", "OutputLimitExceeded"),
        ("still_running", "ChildTimeout"),
        ("grandchild", "ok"),
    ],
)
def test_deadline_caps_and_tree_cleanup_cover_the_entire_process_lifetime(tmp_path, case, expected):
    result = _probe(tmp_path, case)
    assert result["outcome"] == expected
    assert result["elapsed"] < (6.0 if case == "grandchild" else 4.5)
    assert result["alive_before_watchdog_cleanup"]
    assert not any(result["alive_before_watchdog_cleanup"].values())
    assert result["reader_threads"] == []
    assert result["early_descendant_before_job"] is False
    if case == "grandchild":
        assert "grand.pid" in result["alive_before_watchdog_cleanup"]
        assert result["stdout"] == "parent-exit"


def test_bootstrap_preserves_stdin_bytes_and_nonzero_exit_payload():
    payload = "原语言 request\n".encode()
    command = [
        sys.executable,
        "-S",
        "-c",
        "import sys;sys.stdout.buffer.write(sys.stdin.buffer.read());sys.stderr.buffer.write(b'error-code');sys.exit(7)",
    ]
    with pytest.raises(fpt.ChildFailed) as caught:
        fpt.run_bounded(command, input_bytes=payload, timeout_seconds=3)
    assert caught.value.returncode == 7
    assert caught.value.stdout == payload
    assert caught.value.stderr == b"error-code"


def test_strict_utf8_success_output_remains_a_named_transport_error():
    command = [sys.executable, "-S", "-c", "import os;os.write(1,b'\\xff')"]
    with pytest.raises(fpt.TransportError, match="valid UTF-8"):
        fpt.run_bounded_json(command, timeout_seconds=3)


@pytest.mark.skipif(os.name != "nt", reason="Windows job assignment")
def test_failed_job_assignment_reaps_bootstrap_before_user_command(monkeypatch, tmp_path):
    marker = tmp_path / "should-not-run"
    captured = []

    def fail_assignment(proc):
        captured.append(proc)
        raise OSError("controlled assignment failure")

    monkeypatch.setattr(fpt, "_assign_windows_job", fail_assignment)
    command = [
        sys.executable,
        "-S",
        "-c",
        "from pathlib import Path;import sys;Path(sys.argv[1]).write_text('ran')",
        str(marker),
    ]
    with pytest.raises(fpt.TransportError, match="owned process tree"):
        fpt.run_bounded(command, timeout_seconds=3)
    assert len(captured) == 1
    assert captured[0].poll() is not None
    assert not marker.exists()
    assert all(pipe.closed for pipe in (captured[0].stdin, captured[0].stdout, captured[0].stderr))


@pytest.mark.skipif(os.name != "nt", reason="Windows job assignment")
def test_spawn_time_uses_request_deadline_and_never_releases_expired_child(monkeypatch, tmp_path):
    import time

    marker = tmp_path / "should-not-run"
    original = fpt._assign_windows_job

    def delayed_assignment(proc):
        time.sleep(0.2)
        return original(proc)

    monkeypatch.setattr(fpt, "_assign_windows_job", delayed_assignment)
    command = [
        sys.executable,
        "-S",
        "-c",
        "from pathlib import Path;import sys;Path(sys.argv[1]).write_text('ran')",
        str(marker),
    ]
    with pytest.raises(fpt.ChildTimeout, match="during spawn"):
        fpt.run_bounded(command, timeout_seconds=0.1)
    assert not marker.exists()
    assert not [t for t in __import__("threading").enumerate() if t.name.startswith("ff-process")]


def test_bootstrap_preserves_configured_cwd_and_env(tmp_path):
    command = [
        sys.executable,
        "-S",
        "-c",
        "import os,sys;sys.stdout.buffer.write((os.getcwd()+'\\n'+os.getenv('P5_TEST_VALUE')).encode())",
    ]
    result = fpt.run_bounded(
        command,
        timeout_seconds=3,
        cwd=str(tmp_path),
        env=dict(os.environ, P5_TEST_VALUE="original-language-中文"),
    )
    assert result["stdout"].decode() == str(tmp_path) + "\noriginal-language-中文"
