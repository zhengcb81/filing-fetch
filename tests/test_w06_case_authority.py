"""Case-authority TDD. Pure tool proofs, never product execution or supplier claims."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools/offline_contract_matrix"
sys.path.insert(0, str(TOOLS))
import oracle  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures/w06_contract_matrix/authority"


def frozen_report():
    report = json.loads((FIXTURE / "original-41-report.json").read_text(encoding="utf-8"))
    report["evidence_root"] = str(FIXTURE / "artifacts")
    return report


def case(report, cid):
    return next(c for c in report["cases"] if c["id"] == cid)


def test_authority_omitted_required_cases_cannot_be_declared_away():
    report = frozen_report()
    report["cases"] = [c for c in report["cases"] if c["result"] == "PASS"]
    report["required_cases"] = [c["id"] for c in report["cases"]]
    assert any(f.vector == "coverage_gap" for f in oracle.audit(report))


def test_authority_removed_cutoff_expectation_cannot_remove_check():
    report = frozen_report()
    case(report, "call_past_cutoff")["expected"] = {}
    findings = oracle.audit(report)
    assert any(f.vector == "wrong_cutoff" and f.case_id == "call_past_cutoff" for f in findings)


def test_authority_hashed_wrong_market_request_is_still_wrong(tmp_path):
    report = frozen_report()
    shutil.copytree(FIXTURE / "artifacts", tmp_path / "artifacts")
    report["evidence_root"] = str(tmp_path / "artifacts")
    run = case(report, "fin_cn_annual_hit")["actual"]["runs"][0]
    path = tmp_path / "artifacts" / run["request_ref"]
    request = json.loads(path.read_text(encoding="utf-8"))
    request.update(company_query="Tencent Holdings Limited", market="HK")
    raw = json.dumps(request, ensure_ascii=False).encode("utf-8")
    path.write_bytes(raw)
    run["request_sha256"] = hashlib.sha256(raw).hexdigest()
    assert any(
        f.vector == "case_request_mismatch" and f.case_id == "fin_cn_annual_hit"
        for f in oracle.audit(report)
    )


@pytest.mark.parametrize("index", range(41))
def test_authority_every_required_case_is_mandatory_even_if_list_changes(index):
    from case_specs import audit_coverage

    report = frozen_report()
    removed = report["cases"].pop(index)
    report["required_cases"] = [c["id"] for c in report["cases"]]
    issues = audit_coverage(report["cases"])
    assert issues and any(removed["id"] in detail for detail in issues)


@pytest.mark.parametrize("index", range(41))
def test_authority_duplicate_or_extra_cannot_replace_required_case(index):
    from case_specs import audit_coverage

    rows = frozen_report()["cases"]
    removed = rows.pop(index)
    rows.append(deepcopy(rows[0]))
    assert audit_coverage(rows)
    rows[-1]["id"] = "extra-case-" + removed["id"]
    assert audit_coverage(rows)


def test_authority_valid_full_registry_and_single_case_contract_positive():
    from case_specs import audit_coverage, get_spec

    report = frozen_report()
    assert audit_coverage(report["cases"]) == []
    c = case(report, "fin_cn_annual_hit")
    assert get_spec(c["id"]).metadata_errors(c) == []
    assert oracle.audit_case(get_spec(c["id"]), c) == []
    run = c["actual"]["runs"][0]
    request = json.loads((FIXTURE / "artifacts" / run["request_ref"]).read_text(encoding="utf-8"))
    assert get_spec(c["id"]).request_errors(0, request) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("company_query", "wrong"),
        ("market", "HK"),
        ("document_kind", "quarterly_report"),
        ("fiscal_year", 2025),
        ("fiscal_period", "Q1"),
        ("as_of_date", "2025-01-01"),
        ("filing_intent", "fetch_if_missing"),
        ("mode", "latest_as_of"),
    ],
)
def test_authority_request_contract_covers_all_source_dimensions(field, value):
    from case_specs import get_spec

    spec = get_spec("fin_cn_annual_hit")
    request = spec.runs[0].request()
    request[field] = value
    assert spec.request_errors(0, request)


def test_authority_companion_limits_and_execution_scope_are_fixed():
    from case_specs import get_spec

    spec = get_spec("call_max_bytes")
    request = spec.runs[0].request()
    request["companion_transcript"]["fiscal_quarter"] = 2
    assert spec.request_errors(0, request)
    request = spec.runs[0].request()
    request["companion_transcript"]["acquisition_limits"]["max_bytes"] = 1000000
    assert spec.request_errors(0, request)
    c = case(frozen_report(), spec.id)
    c["declared_layer"] = "ff-only"
    assert spec.metadata_errors(c)
    # Registry is immutable even if callers mutate a returned projection.
    request = spec.runs[0].request()
    request["market"] = "HK"
    assert spec.runs[0].request()["market"] == "US"


@pytest.mark.parametrize(
    "cid", [c["id"] for c in frozen_report()["cases"] if c["result"] == "FAIL"]
)
def test_authority_failed_response_cannot_be_laundered_as_pass(cid):
    report = frozen_report()
    c = case(report, cid)
    c["result"] = "PASS"
    assert any(
        f.vector == "case_assertion_failed" and f.case_id == cid for f in oracle.audit(report)
    )


def test_authority_fixed_fixture_scenario_cannot_be_self_declared():
    from case_specs import get_spec

    spec = get_spec("call_past_cutoff")
    state = spec.runs[0].fixture()
    state["call_date"] = "2025-06-01"
    assert spec.fixture_errors(0, state, True)
    state = spec.runs[0].fixture()
    state["scenario"] = "wrong_quarter"
    assert spec.fixture_errors(0, state, True)
    assert spec.fixture_errors(0, spec.runs[0].fixture(), False)
    missing = get_spec("err_missing_creds")
    assert missing.fixture_errors(0, {}, True)


@pytest.mark.parametrize("cid", [c["id"] for c in frozen_report()["cases"]])
def test_authority_original_all_case_contracts_and_request_vectors_match(cid):
    from case_specs import get_spec

    c = case(frozen_report(), cid)
    spec = get_spec(cid)
    assert spec.metadata_errors(c) == []
    for index, run in enumerate(c["actual"]["runs"]):
        request = json.loads(
            (FIXTURE / "artifacts" / run["request_ref"]).read_text(encoding="utf-8")
        )
        assert spec.request_errors(index, request) == []


def test_authority_runner_registry_consumes_same_fixed_objects():
    from cli_main import _case_registry
    from case_specs import case_specs

    rows = _case_registry()
    assert tuple(cid for cid, _ in rows) == tuple(spec.id for spec in case_specs())
    assert all(runner.__self__ is spec for (_, runner), spec in zip(rows, case_specs()))


def test_authority_runner_rejects_drift_before_process_and_binds_valid_input(tmp_path):
    from case_specs import get_spec
    from run import Context
    from subprocess import CompletedProcess
    from unittest.mock import patch

    ctx = Context(
        ff_root=tmp_path / "ff",
        cwp_root=tmp_path / "cwp",
        et_root=tmp_path / "et",
        scratch=tmp_path / "scratch",
        out_root=tmp_path / "output",
    )
    spec = get_spec("fin_cn_annual_hit")
    bad = spec.runs[0].request()
    bad["market"] = "HK"
    with patch("run.run_process") as launch:
        with pytest.raises(ValueError, match="contract drift"):
            ctx.run_ff(bad, case_id=spec.id)
        launch.assert_not_called()
        launch.return_value = CompletedProcess([], 0, b'{"status":"synthetic-control-only"}', b"")
        trace = ctx.run_ff(spec.runs[0].request(), case_id=spec.id)
        assert json.loads(launch.call_args.kwargs["input"]) == spec.runs[0].request()
        path = ctx.artifacts / trace["fixture_ref"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == trace["fixture_sha256"]
    ctx.active_case_spec = get_spec("call_past_cutoff")
    with patch("run.run_process") as launch:
        with pytest.raises(ValueError, match="active case"):
            ctx.run_ff(spec.runs[0].request(), case_id=spec.id)
        launch.assert_not_called()


def test_authority_runner_rejects_wrong_fixture_before_launch(tmp_path):
    from case_specs import get_spec
    from run import Context
    from unittest.mock import patch

    ctx = Context(
        ff_root=tmp_path / "ff",
        cwp_root=tmp_path / "cwp",
        et_root=tmp_path / "et",
        scratch=tmp_path / "scratch",
        out_root=tmp_path / "output",
    )
    spec = get_spec("call_past_cutoff")
    ctx.write_state(
        scenario="success",
        calls_file=ctx.env.calls_file(spec.id),
        call_date="2025-06-01",
        receipt_tag=spec.id,
    )
    with patch("run.run_process") as launch:
        with pytest.raises(ValueError, match="fixture"):
            ctx.run_ff(spec.runs[0].request(), case_id=spec.id)
        launch.assert_not_called()
