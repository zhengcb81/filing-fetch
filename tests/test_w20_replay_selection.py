"""W20 replay: explicit supplemental case selection and its oracle semantics.

A ``--cases`` run may never masquerade as the full 41-case matrix: the
required-case authority stays complete, unselected cases stay honest NOT_RUN
rows with the named reason, selection rows are consistency-checked by the
oracle, and a killed run's ET receipts are only excused when the harness truly
interrupted the child before they existed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import pytest

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
MATRIX = ROOT / "tools" / "offline_contract_matrix"
for path in (str(MATRIX), str(TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import case_registry  # noqa: E402
import case_selection  # noqa: E402
import case_specs  # noqa: E402
import oracle  # noqa: E402
import w20_case_specs  # noqa: E402


# ── pure selection helpers ─────────────────────────────────────────────────


def test_parse_case_ids_splits_strips_and_rejects_duplicates() -> None:
    assert case_selection.parse_case_ids(["a, b", None, "c"]) == ["a", "b", "c"]
    with pytest.raises(case_selection.SelectionError):
        case_selection.parse_case_ids(["a,a"])
    with pytest.raises(case_selection.SelectionError):
        case_selection.parse_case_ids([])


def test_validate_selection_rejects_unknown_ids() -> None:
    known = [cid for cid, _ in case_registry.union_entries()]
    selection = case_selection.validate_selection(
        case_selection.parse_case_ids(["chainA_download_reuse"]), known)
    assert selection["mode"] == "selected"
    with pytest.raises(case_selection.SelectionError):
        case_selection.validate_selection(["no-such-case"], known)


def test_select_entries_preserves_selection_order_and_refuses_gaps() -> None:
    union = case_registry.union_entries()
    selection = case_selection.validate_selection(
        ["w20_call_hash_lie", "fin_cn_annual_hit"], [cid for cid, _ in union])
    entries = case_selection.select_entries(union, selection)
    assert [cid for cid, _ in entries] == ["w20_call_hash_lie", "fin_cn_annual_hit"]
    broken = {"mode": "selected", "selected": ["w20_call_hash_lie", "absent"]}
    with pytest.raises(case_selection.SelectionError):
        case_selection.select_entries(union, broken)


def test_summarize_reports_completed_skipped_and_unexecuted() -> None:
    selection = {"selected": ["a", "b"]}
    results = [
        {"id": "a", "result": "PASS"},
        {"id": "b", "result": "NOT_RUN"},
        {"id": "c", "result": "NOT_RUN"},
    ]
    summary = case_selection.summarize(selection, results=results, known_ids=["a", "b", "c"])
    assert summary["completed"] == ["a"]
    assert summary["selected_not_executed"] == ["b"]
    assert summary["skipped"] == ["c"]
    assert "never" in summary["certifies"]


# ── supplemental registry sanity ───────────────────────────────────────────


def test_base_authority_is_unchanged_and_supplemental_is_disjoint() -> None:
    base = case_specs.case_specs()
    assert len(base) == 41
    assert case_specs.AUTHORITY_VERSION == "w06-cases/1"
    supplemental = w20_case_specs.w20_case_specs()
    # Return R1 added the deterministic post-durable case (9 -> 10).
    assert len(supplemental) == 10
    assert not ({s.id for s in base} & {s.id for s in supplemental})
    assert len(case_registry.union_entries()) == 51


def test_cross_company_run_vectors_never_mix_identities() -> None:
    spec = w20_case_specs.get_w20_spec("w20_filing_concurrent_cross_company")
    cn = spec.runs[0].request()
    hk = spec.runs[1].request()
    assert cn["market"] == "CN" and hk["market"] == "HK"
    assert cn["company_query"] != hk["company_query"]
    swapped = dict(cn, market=hk["market"], company_query=hk["company_query"])
    assert spec.request_errors(0, swapped), "a swapped company vector must be rejected"
    assert spec.request_errors(0, cn) == []


# ── oracle selection semantics ─────────────────────────────────────────────


def _row(cid: str, spec, *, result: str = "FAIL", diagnostics: list[str] | None = None):
    return {
        "id": cid,
        "title": cid,
        "declared_layer": spec.declared_layer,
        "scope": spec.scope,
        "expected": spec.expected(),
        "result": result,
        "diagnostics": diagnostics or [],
        "actual": {},
        "provider_counters": {},
    }


def _selection_report(
    *,
    selected: list[str],
    rows: list[dict[str, Any]],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "ff-et-cwp-offline-matrix/1",
        "code_binding": {"verified": True},
        "restore": {"restored": True},
        "scope": {
            "network_guard_boots": 1,
            "network_attempts_denied": 0,
            "translation_attempts": 0,
            "batch_elapsed_seconds": 10.0,
            "selection": {"mode": "selected", "selected": selected},
        },
        "required_cases": [s.id for s in case_specs.case_specs()]
        if required is None else required,
        "cases": rows,
        "evidence_root": None,
    }


def _all_rows(selected: list[str], *, selected_result: str = "FAIL") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in [*case_specs.case_specs(), *w20_case_specs.w20_case_specs()]:
        if spec.id in selected:
            rows.append(_row(spec.id, spec, result=selected_result))
        else:
            rows.append(_row(spec.id, spec, result="NOT_RUN",
                             diagnostics=[case_selection.NOT_SELECTED_REASON]))
    return rows


def test_selection_report_with_consistent_rows_has_no_labelling_findings() -> None:
    selected = ["w20_call_et_truncated"]
    report = _selection_report(selected=selected, rows=_all_rows(selected))
    findings = oracle.audit(report)
    vectors = {finding.vector for finding in findings}
    # The selected case honestly FAILED (empty runs); that failure must be
    # reported — but never a coverage/labelling complaint.
    assert "case_not_passed" in vectors
    assert "selection_row_mislabelled" not in vectors
    assert "coverage_gap" not in vectors
    assert "required_cases_shrunk" not in vectors
    assert "selection_row_missing" not in vectors


def test_selection_report_may_not_shrink_required_cases() -> None:
    selected = ["w20_call_et_truncated"]
    report = _selection_report(selected=selected, rows=_all_rows(selected),
                               required=selected)
    findings = oracle.audit(report)
    assert any(finding.vector == "required_cases_shrunk" for finding in findings)


def test_selection_report_rejects_relabelled_unselected_rows() -> None:
    selected = ["w20_call_et_truncated"]
    rows = _all_rows(selected)
    for row in rows:
        if row["id"] == "chainA_download_reuse":
            row["result"] = "PASS"
            row["diagnostics"] = []
    report = _selection_report(selected=selected, rows=rows)
    findings = oracle.audit(report)
    assert any(finding.vector == "selection_row_mislabelled"
               and finding.case_id == "chainA_download_reuse" for finding in findings)


def test_selection_report_rejects_missing_rows() -> None:
    selected = ["w20_call_et_truncated"]
    rows = [row for row in _all_rows(selected) if row["id"] != "fin_hk_semi_hit"]
    report = _selection_report(selected=selected, rows=rows)
    findings = oracle.audit(report)
    assert any(finding.vector == "selection_row_missing" for finding in findings)


def test_selection_report_rejects_selected_row_wearing_not_selected_label() -> None:
    selected = ["w20_call_et_truncated"]
    rows = _all_rows(selected)
    for row in rows:
        if row["id"] == "w20_call_et_truncated":
            row["result"] = "NOT_RUN"
            row["diagnostics"] = [case_selection.NOT_SELECTED_REASON]
    report = _selection_report(selected=selected, rows=rows)
    findings = oracle.audit(report)
    assert any(finding.vector == "selection_row_mislabelled"
               and finding.case_id == "w20_call_et_truncated" for finding in findings)


def test_full_run_still_demands_complete_coverage_without_selection() -> None:
    selected: list[str] = []
    rows = _all_rows(selected)
    report = _selection_report(selected=selected, rows=rows)
    report["scope"].pop("selection")
    findings = oracle.audit(report)
    # Without a selection every NOT_RUN row keeps its historical meaning: the
    # coverage gap is reported exactly as before this suite existed.
    assert any(finding.vector == "coverage_gap" for finding in findings)
    assert any(finding.vector == "case_not_passed" for finding in findings)


# ── killed-run ET receipt binding ──────────────────────────────────────────


def _killed_receipt_report(tmp_path: Path, *, killed: bool) -> dict[str, Any]:
    request = {"selected": True}
    response = {"status": "provider_unavailable"}
    req = tmp_path / "r.json"
    resp = tmp_path / "s.json"
    req.write_text(json.dumps(request), encoding="utf-8")
    resp.write_text(json.dumps(response), encoding="utf-8")
    spec = w20_case_specs.get_w20_spec("w20_call_kill_before_durable")
    row = _row(spec.id, spec, result="FAIL")
    row["actual"] = {"runs": [{
        "exit_code": 1,
        "response": response,
        "stderr": "",
        "request_ref": req.name,
        "request_sha256": hashlib.sha256(req.read_bytes()).hexdigest(),
        "response_ref": resp.name,
        "response_sha256": hashlib.sha256(resp.read_bytes()).hexdigest(),
        "fixture_ref": "f.json",
        "fixture_sha256": "0" * 64,
        "et_fixture_requests": 1,
        "killed": killed,
        "kill_reason": "harness interruption" if killed else None,
    }]}
    (tmp_path / "f.json").write_text("{}", encoding="utf-8")
    return {
        "schema_version": "ff-et-cwp-offline-matrix/1",
        "code_binding": {"verified": True},
        "restore": {"restored": True},
        "scope": {"network_guard_boots": 1, "network_attempts_denied": 0,
                  "translation_attempts": 0, "batch_elapsed_seconds": 5.0},
        "required_cases": [s.id for s in case_specs.case_specs()],
        "cases": [row],
        "evidence_root": str(tmp_path),
    }


def test_killed_run_does_not_demand_receipts_that_never_existed(tmp_path: Path) -> None:
    findings = oracle.audit(_killed_receipt_report(tmp_path, killed=True))
    assert not any("ET result" in finding.detail or "ET usage" in finding.detail
                   for finding in findings)


def test_surviving_run_still_needs_bound_et_receipts(tmp_path: Path) -> None:
    findings = oracle.audit(_killed_receipt_report(tmp_path, killed=False))
    assert any("ET result" in finding.detail for finding in findings)
