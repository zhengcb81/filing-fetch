"""ROOT final: new probe states cannot be read as a legacy boolean."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/offline_contract_matrix"))
from w20_case_specs import get_w20_spec  # noqa: E402


@pytest.mark.parametrize("state,passes", [
    ("not_found", True), ("confirmed", False), ("probe_error", False),
    (None, False), ("unknown", False), (False, False), ("missing", False),
])
def test_mid_import_requires_explicit_not_found(state, passes):
    sha = "f" * 64
    ref = {"document_id": "urn:company-wiki:document:sha256:" + sha,
           "source_id": "urn:company-wiki:source:sha256:" + sha,
           "content_sha256": sha, "byte_size": 64, "mime_type": "text/plain"}
    def run(status, gets, killed=False):
        return {"killed": killed, "et_fixture_requests": gets,
                "response": {"transcript": {"status": status,
                    "source_ref": ref if status in ("downloaded", "reused") else None}}}
    actual = {"interruption_phase": "mid_import_observed",
              "durable_at_kill_public_readback": False,
              "runs": [run("interrupted", 1, True),
                       run("downloaded", 1), run("reused", 0)]}
    if state != "missing":
        actual["durable_state_public_readback"] = state
    errors = get_w20_spec("w20_call_kill_after_import").assertion_errors({"actual": actual})
    assert (not errors) is passes, errors
