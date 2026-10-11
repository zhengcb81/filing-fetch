"""Unit tests for the offline FF↔ET↔CWP contract matrix.

Fast, offline, no cross-repo subprocess. The full real three-layer chain is a
manual runner entry point (``tools/offline_contract_matrix/run.py``) exercised at
the engineering node, not here.

Node A proves the runner ORACLE detects each pre-declared failure vector (RED):
a whole layer faked while claiming real, a second run that re-downloads, a
missing ET receipt, a wrong cutoff, a fake zero-cost, and an unrestored scratch.
A clean report must pass. Fixture builders must emit *valid* synthetic originals,
and the report schema must round-trip.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


TOOLS = Path(__file__).resolve().parents[1] / "tools" / "offline_contract_matrix"
sys.path.insert(0, str(TOOLS))

import oracle as oracle_mod  # noqa: E402
from fixture_builder import (  # noqa: E402
    make_valid_html, make_valid_pdf, make_valid_txt, sha256_hex, SYNTHETIC_MARKER,
)
from report import CaseResult, Dependency, build_report, emit, SCHEMA  # noqa: E402


# ── oracle RED: each failure vector is detected ────────────────────────────


def _case(case_id, *, declared="ff+cwp", expected=None, actual=None, counters=None):
    return {
        "id": case_id, "declared_layer": declared,
        "expected": expected or {}, "actual": actual or {},
        "provider_counters": counters or {},
    }


def _report(cases, restore=None):
    return {"schema_version": SCHEMA, "cases": cases,
            "restore": restore if restore is not None else {"restored": True}}


def test_oracle_flags_faked_layer_claiming_real():
    case = _case("c1", declared="real-3layer",
                 actual={"real_layer_evidence": {"ff_public_cli": True,
                                                 "et_supervisor_worker": False,
                                                 "cwp_import": True}})
    findings = oracle_mod.audit(_report([case]))
    assert any(f.vector == "fake_layer_claimed_real" for f in findings)


def test_oracle_flags_missing_et_receipt():
    case = _case("c1", declared="real-3layer",
                 actual={"real_layer_evidence": {"ff_public_cli": True,
                                                 "et_supervisor_worker": True,
                                                 "cwp_import": True},
                         "et_usage_receipt": False},
                 counters={"fixture_requests": 1})
    findings = oracle_mod.audit(_report([case]))
    assert any(f.vector == "missing_et_receipt" for f in findings)


def test_oracle_flags_second_run_still_downloads():
    case = _case("c1", expected={"run_twice": True},
                 counters={"fixture_requests": 1, "run2_fixture_requests": 2})
    findings = oracle_mod.audit(_report([case]))
    assert any(f.vector == "second_run_still_downloads" for f in findings)


def test_oracle_flags_wrong_cutoff():
    case = _case("c1", expected={"past_cutoff": True},
                 actual={"cutoff_diagnostic": False})
    findings = oracle_mod.audit(_report([case]))
    assert any(f.vector == "wrong_cutoff" for f in findings)


def test_oracle_flags_fake_zero_cost():
    case = _case("c1", expected={"unknown_usage": True},
                 actual={"unknown_usage_reported_as_zero": True, "calls_swallowed": False})
    findings = oracle_mod.audit(_report([case]))
    assert any(f.vector == "fake_zero_cost" for f in findings)


def test_oracle_flags_swallowed_call():
    case = _case("c1", expected={"unknown_usage": True},
                 actual={"unknown_usage_reported_as_zero": False, "calls_swallowed": True})
    findings = oracle_mod.audit(_report([case]))
    assert any(f.vector == "fake_zero_cost" for f in findings)


def test_oracle_flags_unrestored_scratch():
    findings = oracle_mod.audit(_report([], restore={"restored": False}))
    assert any(f.vector == "unrestored_scratch" for f in findings)


def test_oracle_clean_report_passes():
    case = _case("c1", declared="real-3layer",
                 expected={"run_twice": True, "past_cutoff": False, "unknown_usage": True},
                 actual={"real_layer_evidence": {"ff_public_cli": True,
                                                 "et_supervisor_worker": True,
                                                 "cwp_import": True},
                         "et_usage_receipt": True, "cutoff_diagnostic": False,
                         "unknown_usage_reported_as_zero": False, "calls_swallowed": False},
                 counters={"fixture_requests": 1, "run2_fixture_requests": 0})
    findings = oracle_mod.audit(_report([case]))
    assert findings == []
    assert oracle_mod.passes(findings) is True


# ── valid synthetic originals (not %PDF placeholders) ──────────────────────


def test_valid_pdf_is_structurally_complete():
    data = make_valid_pdf("Synthetic annual report")
    assert data.startswith(b"%PDF-1.4")
    assert data.rstrip().endswith(b"%%EOF")
    text = data.decode("latin-1")
    assert "xref" in text and "trailer" in text and "startxref" in text
    # cross-reference table present with real object offsets
    assert "/Root 1 0 R" in text


def test_valid_html_and_txt_are_real_documents():
    html = make_valid_html("T", "body")
    assert html.lstrip().startswith(b"<!DOCTYPE html>")
    assert b"</html>" in html
    txt = make_valid_txt("T", "body")
    assert SYNTHETIC_MARKER.encode("utf-8") in txt


def test_originals_have_stable_digests():
    assert sha256_hex(make_valid_pdf("x")) == sha256_hex(make_valid_pdf("x"))


# ── report schema round-trip ───────────────────────────────────────────────


def test_report_schema_and_emit(tmp_path):
    case = CaseResult(id="c1", title="t", declared_layer="ff+cwp",
                      observed_layer="ff-cli", result="PASS",
                      provider_counters={"fixture_requests": 1, "translations": 0})
    dep = Dependency(repository="ff", root="/r", head="abc123",
                     modules=[{"path": "scripts/fetch_filing.py", "sha256": "0" * 64}])
    report = build_report(
        dependencies=[dep], cases=[case],
        cost={"real_provider_calls": 0, "paid_usd": 0, "unknown_charge": None,
              "fixture_requests": 1},
        scope={"translation": "0"}, restore={"restored": True},
    )
    assert report["schema_version"] == SCHEMA
    assert report["cost"]["unknown_charge"] is None  # unknown stays null, never 0
    out = tmp_path / "report.json"
    emit(report, out)
    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert loaded["cases"][0]["result"] == "PASS"
    assert loaded["dependencies"][0]["head"] == "abc123"
