"""W20 return R1 (2026-10-29): durable-phase interruption and request-bound triggers.

ROOT reception FF-R1/FF-R2 regression. These tests encode the two P2 findings
as failing assertions BEFORE the fix:

* FF-R1 — a durable-then-interrupted case must exist whose assertions REJECT
  the not-durable recovery branch (recovery with 1 GET / a download is not a
  durable-pass proxy), and must demand public-interface read-back proof taken
  before the kill;
* FF-R2 — the interruption trigger must bind to THIS request's content
  (new durable original bytes hashing to this case's content), so a
  pre-existing unrelated-period sidecar can never fire it early.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
MATRIX = ROOT / "tools" / "offline_contract_matrix"
for path in (str(MATRIX), str(TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import case_specs  # noqa: E402
import w20_case_specs  # noqa: E402


CONTENT = "Synthetic W20 durable-interrupt transcript FY2036 Q1."
CONTENT_SHA = hashlib.sha256(CONTENT.encode("utf-8")).hexdigest()


def _ref(sha: str, size: int = 64) -> dict[str, Any]:
    return {
        "document_id": f"urn:company-wiki:document:sha256:{sha}",
        "source_id": f"urn:company-wiki:source:sha256:{sha}",
        "content_sha256": sha,
        "byte_size": size,
        "mime_type": "text/plain",
    }


def _run(response: dict[str, Any], *, killed: bool = False, gets: int = 0,
         content_sha: str | None = None, adapter_fetch: int = 0) -> dict[str, Any]:
    return {
        "response": response,
        "killed": killed,
        "et_fixture_requests": gets,
        "expected_original_content_sha256": content_sha,
        "adapter_fetch_requests": adapter_fetch,
    }


# ── FF-R1: durable-phase case exists and rejects the not-durable proxy ─────


def test_durable_case_is_registered_with_post_durable_phase() -> None:
    spec = w20_case_specs.get_w20_spec("w20_call_kill_after_durable")
    assert spec is not None, "the durable-then-interrupted case must exist"
    expected = spec.expected()
    assert expected.get("interruption_phase") == "post_durable"
    # The 41-case base authority is untouched.
    assert len(case_specs.case_specs()) == 41


def test_durable_assertions_reject_a_not_durable_recovery_proxy() -> None:
    """The exact ROOT finding: a run where the kill happened before durability
    (recovery downloads again, 1 GET) must NOT satisfy the durable case."""
    spec = w20_case_specs.get_w20_spec("w20_call_kill_after_durable")
    not_durable_report = {
        "id": "w20_call_kill_after_durable",
        "actual": {
            "interruption_phase": "post_durable",
            "verified_at_kill": _ref(CONTENT_SHA),
            "runs": [
                _run({"transcript": {"status": "downloaded", "source_ref": _ref(CONTENT_SHA)}},
                     killed=False, gets=1, content_sha=CONTENT_SHA),
                # The "recovery" RE-DOWNLOADS: the proxy for "not durable at
                # kill" that the original case wrongly accepted.
                _run({"transcript": {"status": "downloaded", "source_ref": _ref(CONTENT_SHA)}},
                     killed=True, gets=1, content_sha=CONTENT_SHA),
                _run({"transcript": {"status": "reused", "source_ref": _ref(CONTENT_SHA)}},
                     killed=False, gets=0, content_sha=CONTENT_SHA),
            ],
        },
    }
    errors = spec.assertion_errors(not_durable_report)
    assert errors, "a re-downloading recovery must be rejected as not-durable, not passed"


def test_durable_assertions_accept_only_zero_get_recovery_with_readback_proof() -> None:
    spec = w20_case_specs.get_w20_spec("w20_call_kill_after_durable")
    verified = _ref(CONTENT_SHA)
    good_report = {
        "id": "w20_call_kill_after_durable",
        "actual": {
            "interruption_phase": "post_durable",
            "verified_at_kill": verified,
            "runs": [
                # Run 0 completes normally and establishes the durable source.
                _run({"transcript": {"status": "downloaded", "source_ref": verified}},
                     killed=False, gets=1, content_sha=CONTENT_SHA),
                # The re-request is killed before its return: 0 GETs, no envelope.
                _run({}, killed=True, gets=0, content_sha=CONTENT_SHA),
                # Recovery reuses with zero extra GETs and the same Ref.
                _run({"transcript": {"status": "reused", "source_ref": verified}},
                     killed=False, gets=0, content_sha=CONTENT_SHA),
            ],
        },
    }
    assert spec.assertion_errors(good_report) == []
    # Read-back proof missing → rejected even with a zero-GET recovery.
    missing_proof = {
        "id": "w20_call_kill_after_durable",
        "actual": {"interruption_phase": "post_durable",
                   "runs": good_report["actual"]["runs"]},
    }
    assert spec.assertion_errors(missing_proof), (
        "zero-GET recovery without pre-kill public read-back proof is not durable evidence")


def test_mid_import_case_declares_its_observed_phase_and_stays_single() -> None:
    """The historical case keeps its real meaning: an observed mid-import
    interruption, never a durable-pass proxy."""
    spec = w20_case_specs.get_w20_spec("w20_call_kill_after_import")
    assert spec is not None
    assert spec.expected().get("interruption_phase") == "mid_import_observed"


# ── FF-R2: trigger binds to this request's content ─────────────────────────


def test_trigger_ignores_preexisting_unrelated_period_originals(tmp_path: Path) -> None:
    """A pre-existing unrelated-period original/sidecar must never fire the
    trigger; only a NEW original whose bytes hash to THIS case's content may."""
    from w20_fault_cases import new_original_matching_sha

    directory = tmp_path / "transcripts"
    directory.mkdir(parents=True)
    unrelated = directory / "unrelated_period.txt"
    unrelated.write_bytes(b"an unrelated period original bytes")
    (directory / "unrelated_period.txt.source.json").write_text("{}", encoding="utf-8")
    before = {p.name for p in directory.iterdir()}
    this_sha = hashlib.sha256(CONTENT.encode("utf-8")).hexdigest()
    # Nothing new for this request → no trigger.
    assert new_original_matching_sha(directory, before, this_sha) is None
    # This request's original lands → trigger returns it.
    this = directory / "this_period.txt"
    this.write_bytes(CONTENT.encode("utf-8"))
    matched = new_original_matching_sha(directory, before, this_sha)
    assert matched is not None and matched.name == "this_period.txt"


def test_trigger_is_not_fooled_by_a_sidecar_only_appearance(tmp_path: Path) -> None:
    """A sidecar appearing without this request's original bytes must not fire."""
    from w20_fault_cases import new_original_matching_sha

    directory = tmp_path / "transcripts"
    directory.mkdir(parents=True)
    before = {p.name for p in directory.iterdir()}
    this_sha = hashlib.sha256(CONTENT.encode("utf-8")).hexdigest()
    (directory / "only_sidecar.txt.source.json").write_text("{}", encoding="utf-8")
    assert new_original_matching_sha(directory, before, this_sha) is None
