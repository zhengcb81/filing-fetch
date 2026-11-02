"""Business envelopes and transport failure have different owners.

stdout is the caller-owned payload; stderr is optional diagnostics. A bounded
diagnostic budget may truncate the retained log window, but it never rewrites a
complete stdout result into OutputLimitExceeded/upstream_error.
"""
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ff_process_transport as transport  # noqa: E402

DIAGNOSTIC_CAP = 64 * 1024
FLOOD_BYTES = DIAGNOSTIC_CAP + 1
LOG_LINE = b"log line\n"
FLOOD_LINES = FLOOD_BYTES // len(LOG_LINE) + 1
LAST_LINE = b"last-diagnostic-line\n"
PAYLOAD = b'{"status":"source_candidate","source_ref":{"document_id":"doc-1"}}'


def _command(source: str) -> list[str]:
    return [sys.executable, "-S", "-c", source]


def _flood_after_stdout(payload: bytes, *, exit_code: int = 0) -> str:
    """A real child: complete payload first, then a bounded-log overflow."""
    return (
        "import sys\n"
        f"sys.stdout.buffer.write({payload!r})\n"
        "sys.stdout.buffer.flush()\n"
        f"sys.stderr.buffer.write({LOG_LINE!r} * {FLOOD_LINES})\n"
        f"sys.stderr.buffer.write({LAST_LINE!r})\n"
        "sys.stderr.buffer.flush()\n"
        f"sys.exit({exit_code})\n"
    )


def _ff_threads() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name.startswith("ff-process")]


def test_nonzero_business_exit_is_opt_in_and_keeps_original_bytes():
    command = [sys.executable, "-c", "import json,sys; print(json.dumps(dict(status='not_found'),separators=(',',':'))); sys.exit(2)"]
    with pytest.raises(transport.ChildFailed):
        transport.run_bounded_json(command, timeout_seconds=5)
    stdout, stderr, code = transport.run_bounded_json(command, timeout_seconds=5,
        allow_nonzero_exit=True)
    assert stdout.rstrip() == b'{"status":"not_found"}'
    assert stderr == b""
    assert code == 2


def test_opt_in_never_converts_an_incomplete_request_into_a_business_result(monkeypatch):
    failure = transport.ChildFailed("child closed stdin early", returncode=2,
        stdout=b'{"status":"not_found"}')
    failure.input_incomplete = True
    def run(*args, **kwargs):
        raise failure
    monkeypatch.setattr(transport, "run_bounded", run)
    with pytest.raises(transport.ChildFailed):
        transport.run_bounded_json(["configured-tool"], timeout_seconds=5,
            allow_nonzero_exit=True)


@pytest.mark.parametrize("failure", [transport.ChildTimeout("timeout"),
    transport.OutputLimitExceeded("byte limit"), transport.TransportError("pipe failure")])
def test_protocol_option_keeps_real_transport_failures(monkeypatch, failure):
    def run(*args, **kwargs):
        raise failure
    monkeypatch.setattr(transport, "run_bounded", run)
    with pytest.raises(type(failure)):
        transport.run_bounded_json(["configured-tool"], timeout_seconds=5,
            allow_nonzero_exit=True)


# --- stderr is diagnostics: a bounded window cannot veto a delivered payload ---


def test_complete_stdout_survives_a_stderr_flood():
    """A diagnostic log beyond the 64KiB window must not become OutputLimitExceeded."""
    stdout, stderr, code = transport.run_bounded_json(
        _command(_flood_after_stdout(PAYLOAD)), timeout_seconds=30
    )
    assert stdout == PAYLOAD
    assert code == 0
    assert len(stderr) <= DIAGNOSTIC_CAP
    assert stderr.endswith(b"last-diagnostic-line\n")


def test_stderr_retention_is_bounded_but_the_byte_count_is_exact():
    total = FLOOD_LINES * len(LOG_LINE) + len(LAST_LINE)
    result = transport.run_bounded(
        _command(_flood_after_stdout(PAYLOAD)), timeout_seconds=30
    )
    assert result["returncode"] == 0
    assert result["stdout"] == PAYLOAD
    assert result["stderr_bytes_read"] == total
    assert len(result["stderr"]) <= DIAGNOSTIC_CAP
    assert result["stderr_truncated"] is True
    # Retention keeps the newest diagnostics, so the final line survives.
    assert result["stderr"].endswith(b"last-diagnostic-line\n")


def test_stdout_payload_budget_is_not_shared_with_the_diagnostic_budget():
    """Each stream spends its own ceiling; neither borrows from the other."""
    exact = b"p" * 1024
    result = transport.run_bounded(
        _command(_flood_after_stdout(exact)), timeout_seconds=30, stdout_cap_bytes=1024
    )
    assert result["stdout"] == exact
    assert result["stderr_truncated"] is True
    with pytest.raises(transport.OutputLimitExceeded, match="stdout"):
        transport.run_bounded(
            _command(_flood_after_stdout(b"p" * 1025)),
            timeout_seconds=30,
            stdout_cap_bytes=1024,
        )


def test_stderr_flood_keeps_a_business_not_found_answer():
    payload = b'{"status":"not_found","reason":"no_candidate"}'
    command = _command(_flood_after_stdout(payload, exit_code=2))
    stdout, stderr, code = transport.run_bounded_json(
        command, timeout_seconds=30, allow_nonzero_exit=True
    )
    assert json.loads(stdout)["status"] == "not_found"
    assert code == 2
    assert len(stderr) <= DIAGNOSTIC_CAP


def test_stderr_flood_does_not_mask_a_nonzero_child_failure():
    command = _command(_flood_after_stdout(PAYLOAD, exit_code=3))
    with pytest.raises(transport.ChildFailed) as caught:
        transport.run_bounded(command, timeout_seconds=30)
    assert caught.value.returncode == 3
    assert caught.value.stdout == PAYLOAD
    assert caught.value.stderr_truncated is True
    assert len(caught.value.stderr) <= DIAGNOSTIC_CAP


def test_incomplete_stdout_still_fails_as_invalid_json_under_a_stderr_flood():
    import fetch_filing

    command = _command(_flood_after_stdout(b'{"status":"source_candidate"'))
    with pytest.raises(fetch_filing.FilingFetchError, match="not JSON"):
        fetch_filing._run_company_wiki_json(
            command=command,
            root=Path(tempfile.gettempdir()),
            timeout_seconds=30,
            action="ensure",
        )


def test_incomplete_stdin_still_fails_under_a_stderr_flood():
    source = (
        "import sys\n"
        f"sys.stderr.buffer.write({LOG_LINE!r} * {FLOOD_LINES})\n"
        "sys.stderr.buffer.flush()\n"
        "sys.stdin.buffer.read(1)\n"
        "sys.exit(4)\n"
    )
    with pytest.raises(transport.ChildFailed) as caught:
        transport.run_bounded(
            _command(source), timeout_seconds=30, input_bytes=b"x" * (2 * 1024 * 1024)
        )
    assert caught.value.returncode == 4
    assert caught.value.input_incomplete is True


def test_stderr_flood_still_obeys_the_real_deadline(tmp_path):
    pid_file = tmp_path / "child.pid"
    source = (
        "import os,sys,time\n"
        f"open({str(pid_file)!r},'w').write(str(os.getpid()))\n"
        "while True:\n"
        "    sys.stderr.buffer.write(b'z' * 4096)\n"
        "    sys.stderr.buffer.flush()\n"
        "    time.sleep(0.01)\n"
    )
    start = time.monotonic()
    with pytest.raises(transport.ChildTimeout):
        transport.run_bounded(_command(source), timeout_seconds=1.5)
    assert time.monotonic() - start < 8.0
    assert _ff_threads() == []
    assert not transport.pid_is_alive(int(pid_file.read_text()))


def test_diagnostics_before_a_late_payload_do_not_deadlock():
    """A full stderr pipe must be drained while the child still owes stdout."""
    source = (
        "import sys\n"
        "sys.stderr.write('log line\\n' * 200000)\n"
        "sys.stderr.flush()\n"
        "sys.stdout.write('{\"status\":\"ok\"}')\n"
        "sys.stdout.flush()\n"
    )
    stdout, stderr, code = transport.run_bounded_json(_command(source), timeout_seconds=30)
    assert stdout == b'{"status":"ok"}'
    assert code == 0
    assert len(stderr) <= DIAGNOSTIC_CAP


def test_single_line_diagnostic_flood_keeps_a_usable_tail():
    """A truncated one-line log keeps its newest bytes instead of collapsing."""
    source = "import sys;sys.stderr.buffer.write(b'q' * 100000 + b'\\n')"
    result = transport.run_bounded(_command(source), timeout_seconds=30)
    assert result["stderr_truncated"] is True
    assert len(result["stderr"]) == DIAGNOSTIC_CAP
    assert result["stderr"] == b"q" * (DIAGNOSTIC_CAP - 1) + b"\n"


def test_exactly_one_byte_over_the_diagnostic_cap_still_returns_the_payload():
    """The card's exact 65,537-byte case: cap+1 diagnostics, complete payload."""
    source = (
        "import sys\n"
        "sys.stdout.write('{\"status\":\"ok\"}')\n"
        "sys.stdout.flush()\n"
        f"sys.stderr.buffer.write(b'x' * {FLOOD_BYTES})\n"
        "sys.stderr.buffer.flush()\n"
    )
    result = transport.run_bounded(_command(source), timeout_seconds=30)
    assert result["stdout"] == b'{"status":"ok"}'
    assert result["returncode"] == 0
    assert result["stderr_truncated"] is True
    assert result["stderr_bytes_read"] == FLOOD_BYTES
    assert len(result["stderr"]) == DIAGNOSTIC_CAP
    assert result["stderr"] == b"x" * DIAGNOSTIC_CAP


def test_stderr_at_the_cap_is_not_truncated():
    source = "import sys;sys.stderr.write('e' * 65536)"
    result = transport.run_bounded(_command(source), timeout_seconds=30)
    assert result["stderr"] == b"e" * DIAGNOSTIC_CAP
    assert result["stderr_truncated"] is False
    assert result["stderr_bytes_read"] == DIAGNOSTIC_CAP


def test_invalid_utf8_diagnostics_do_not_veto_a_valid_payload():
    source = (
        "import sys\n"
        "sys.stdout.write('{\"status\":\"ok\"}')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.buffer.write(b'\\xff' * 20000)\n"
        "sys.stderr.buffer.flush()\n"
    )
    stdout, stderr, code = transport.run_bounded_json(_command(source), timeout_seconds=30)
    assert stdout == b'{"status":"ok"}'
    assert stderr == b"\xff" * 20000
    assert code == 0
    with pytest.raises(transport.TransportError, match="stdout was not valid UTF-8"):
        transport.run_bounded_json(
            _command("import os;os.write(1,b'\\xff')"), timeout_seconds=30
        )


class _BrokenStream:
    def __init__(self) -> None:
        self.closed = False

    def read(self, size: int) -> bytes:
        raise OSError("controlled diagnostic read failure")

    def close(self) -> None:
        self.closed = True


def test_lost_diagnostic_read_does_not_veto_the_payload():
    stderr_state = transport._IOState()
    stderr_state.read(_BrokenStream(), "stderr", 1024)
    assert stderr_state.error is None
    assert stderr_state.stderr_truncated is True

    stdout_state = transport._IOState()
    stdout_state.read(_BrokenStream(), "stdout", 1024)
    assert isinstance(stdout_state.error, transport.TransportError)


def test_partial_utf8_trim_handles_both_cut_ends():
    char = "字".encode()
    window = (char * 3 + char[:2])[1:]  # continuation head and partial tail
    trimmed = transport._trim_partial_utf8_head(window)
    assert trimmed.startswith(char)


def test_truncated_stderr_window_remains_strict_utf8():
    source = (
        "import sys\n"
        "sys.stdout.write('{\"status\":\"ok\"}')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.buffer.write('字'.encode('utf-8') * 30000)\n"
        "sys.stderr.buffer.flush()\n"
    )
    stdout, stderr, code = transport.run_bounded_json(_command(source), timeout_seconds=30)
    assert stdout == b'{"status":"ok"}'
    assert code == 0
    assert len(stderr) <= DIAGNOSTIC_CAP
    stderr.decode("utf-8", errors="strict")
