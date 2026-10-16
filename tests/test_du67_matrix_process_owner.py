"""ROOT: matrix subprocess lifetime belongs to the public FF transport."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools/offline_contract_matrix"), str(ROOT / "scripts")]
import runtime  # noqa: E402
import ff_process_transport as transport  # noqa: E402


def test_matrix_delegates_exact_bytes_and_remaining_absolute_deadline(tmp_path, monkeypatch):
    assert runtime.process_transport is transport
    deadline = runtime.Deadline(30)
    command = ["example-child"]
    payload = b"\x00\xff\xe5\xad\x97"
    env = {"ROOT_TEST": "only"}
    captured = {}

    def bounded(argv, **kwargs):
        captured.update(argv=argv, **kwargs)
        return {"stdout": b"\xff", "stderr": b"\x00", "returncode": 0}

    monkeypatch.setattr(transport, "run_bounded", bounded)
    monkeypatch.setattr(deadline, "remaining", lambda: 0.125)
    result = runtime.run_process(command, env=env, cwd=tmp_path, deadline=deadline, input=payload)
    assert captured == {
        "argv": command,
        "timeout_seconds": 0.125,
        "input_bytes": payload,
        "cwd": str(tmp_path),
        "env": env,
    }
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.args == command
    assert (result.returncode, result.stdout, result.stderr) == (0, b"\xff", b"\x00")


def test_expired_matrix_deadline_never_enters_transport(tmp_path, monkeypatch):
    monkeypatch.setattr(
        transport, "run_bounded", lambda *a, **kw: pytest.fail("expired request entered transport")
    )
    with pytest.raises(runtime.DeadlineExceeded):
        runtime.run_process(
            [sys.executable], env={}, cwd=tmp_path, deadline=runtime.Deadline(end=-1)
        )


def test_child_timeout_maps_to_matrix_timeout_with_original_cause(tmp_path, monkeypatch):
    def expired(*args, **kwargs):
        raise transport.ChildTimeout("original transport deadline")

    monkeypatch.setattr(transport, "run_bounded", expired)
    with pytest.raises(runtime.DeadlineExceeded) as caught:
        runtime.run_process(["example-child"], env={}, cwd=tmp_path, deadline=runtime.Deadline(5))
    assert isinstance(caught.value.__cause__, transport.ChildTimeout)


@pytest.mark.parametrize("code", [0, 7])
def test_actual_success_and_nonzero_process_preserve_raw_pipe_bytes(tmp_path, code):
    payload = b"\x00\xff original-language bytes\n"
    command = [
        sys.executable,
        "-B",
        "-S",
        "-c",
        'import sys;sys.stdout.buffer.write(sys.stdin.buffer.read());sys.stderr.buffer.write(b"error\\xff");sys.exit(int(sys.argv[1]))',
        str(code),
    ]
    result = runtime.run_process(
        command,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        cwd=tmp_path,
        deadline=runtime.Deadline(5),
        input=payload,
    )
    assert (result.returncode, result.stdout, result.stderr) == (code, payload, b"error\xff")


def test_actual_timeout_reaps_child_and_descendant_without_taskkill(tmp_path, monkeypatch):
    marker = tmp_path / "pids.json"
    command = [
        sys.executable,
        "-B",
        "-S",
        "-c",
        "import os,subprocess,sys,time,json;from pathlib import Path;"
        'p=subprocess.Popen([sys.executable,"-B","-S","-c","import time;time.sleep(60)"]);'
        "Path(sys.argv[1]).write_text(json.dumps([os.getpid(),p.pid]));time.sleep(60)",
        str(marker),
    ]
    taskkill_calls = []

    def no_taskkill(*a, **kw):
        taskkill_calls.append(a)
        raise AssertionError("external taskkill must not run")

    monkeypatch.setattr(subprocess, "run", no_taskkill)
    began = time.monotonic()
    pids = []
    try:
        with pytest.raises(runtime.DeadlineExceeded):
            runtime.run_process(
                command,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                cwd=tmp_path,
                deadline=runtime.Deadline(1.5),
            )
        assert time.monotonic() - began < 5
        assert marker.is_file(), "descendant did not start; cannot claim tree coverage"
        pids = json.loads(marker.read_text())
        assert len(pids) == 2
        assert not any(transport.pid_is_alive(pid) for pid in pids)
        assert taskkill_calls == []
    finally:
        if marker.exists():
            pids = json.loads(marker.read_text())
        for pid in reversed(pids):
            if transport.pid_is_alive(pid):
                os.kill(pid, signal.SIGTERM)
