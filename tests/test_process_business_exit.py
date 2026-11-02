"""Business envelopes and transport failure have different owners."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import ff_process_transport as transport  # noqa: E402


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
