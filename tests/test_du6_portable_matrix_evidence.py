"""DU6-FF-PORTABLE-EVIDENCE: portable retained-evidence replay contracts.

Frozen before implementation (node A):

* ``interface RED`` — the missing public API itself (``audit(..., evidence_root=)``
  and the ``replay`` CLI branch). A missing interface is not a production defect;
  it is listed separately from behaviour RED.
* ``behaviour`` — relocated retained evidence must stay byte-identical, the old
  default findings must stay exactly as they are, and nothing may silently fall
  back to the report's recorded absolute ``evidence_root``.

The controlled corpus below is a synthetic, fully bound 41-case matrix: every
request/response/fixture/ET receipt is written to disk and SHA-bound exactly the
way ``run.py`` writes them. It proves tool behaviour only — it is never evidence
of a real three-layer run, a re-download or any supplier/company figure.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools" / "offline_contract_matrix"
sys.path.insert(0, str(TOOLS))

import cli_main  # noqa: E402
import oracle as oracle_mod  # noqa: E402
from case_specs import case_specs, get_spec  # noqa: E402
from report import SCHEMA  # noqa: E402

AUTHORITY = Path(__file__).parent / "fixtures" / "w06_contract_matrix" / "authority"
REPLAY_SCHEMA = "ff-matrix-evidence-replay/1"
# Canonical sha256 of [f.to_dict() for f in audit(frozen 41 report)] captured on
# base commit e2efa81 BEFORE any DU6 change (sort_keys, ensure_ascii=False).
# Freezes "no override => findings exactly preserved".
FROZEN_DEFAULT_FINDINGS_SHA256 = "417a7891420e02e1bb9fb1641cb95ab5037c5fd754581488cf6dd4f919a64e30"
FROZEN_DEFAULT_FINDING_COUNT = 65


# ── helpers ────────────────────────────────────────────────────────────────


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(value) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _tree_digest(root: Path) -> dict:
    return {
        str(p.relative_to(root)).replace("\\", "/"): _sha256_file(p)
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _doc_ref(doc_id: str, *, mime: str = "text/plain") -> dict:
    return {
        "document_id": doc_id,
        "source_id": "src-" + doc_id,
        "content_sha256": hashlib.sha256(("content:" + doc_id).encode("utf-8")).hexdigest(),
        "byte_size": 512,
        "mime_type": mime,
    }


_NO_OVERRIDE = object()


def _findings(report: dict, evidence_root=_NO_OVERRIDE):
    if evidence_root is _NO_OVERRIDE:
        return oracle_mod.audit(report)
    return oracle_mod.audit(report, evidence_root=evidence_root)


def _finding_keys(report: dict, evidence_root=_NO_OVERRIDE) -> list[tuple]:
    return [(f.vector, f.case_id) for f in _findings(report, evidence_root)]


def _relocate(source: Path, target: Path) -> Path:
    """Full byte copy of a retained artifacts tree (a test copy, not a pack)."""
    shutil.copytree(source, target)
    return target


# ── controlled 41-case corpus ──────────────────────────────────────────────


def _synthetic_runs(spec) -> tuple[list[dict], dict, dict]:
    """Per-run responses/counters plus case-level actual extras and counters."""
    handler = spec.handler.split(":")[1]
    rows = []
    extra: dict = {}
    for index, run_spec in enumerate(spec.runs):
        request = run_spec.request()
        rows.append(
            {
                "response": {},
                "fixture_requests": 0,
                "et_fixture_requests": 0,
                "adapter_fixture_requests": 0,
                "exit_code": 0,
            }
        )
        row = rows[-1]
        filing = {}
        transcript = {}
        if handler == "case_chain_a":
            ref = _doc_ref(f"{spec.id}.transcript")
            transcript = {
                "status": "downloaded" if index == 0 else "reused",
                "fiscal_year": 2025,
                "fiscal_quarter": 1,
                "source_ref": dict(ref),
            }
            row["fixture_requests"] = 1 if index == 0 else 0
            row["et_fixture_requests"] = 1 if index == 0 else 0
            extra = {
                "real_layer_evidence": {
                    "ff_public_cli": True,
                    "et_supervisor_worker": True,
                    "cwp_import": True,
                },
                "et_usage_receipt": True,
            }
        elif handler == "case_fin_local_hit":
            kind, year, period = request["document_kind"], request["fiscal_year"], request["fiscal_period"]
            ref = _doc_ref(f"{spec.id}.filing", mime="application/pdf")
            filing = {
                "status": "source_candidate",
                "document_kind": kind,
                "resolution_outcome": "reused_existing",
                "download_events": 0,
                "fiscal_year": year,
                "fiscal_period": period,
                "source_ref": dict(ref),
            }
            row["response"]["status"] = "source_candidate"
        elif handler == "case_fin_fetch":
            kind, year, period = request["document_kind"], request["fiscal_year"], request["fiscal_period"]
            ref = _doc_ref(f"{spec.id}.filing", mime="application/pdf")
            filing = {
                "status": "source_candidate",
                "document_kind": kind,
                "resolution_outcome": "downloaded_new" if index == 0 else "reused_existing",
                "download_events": 1 if index == 0 else 0,
                "fiscal_year": year,
                "fiscal_period": period,
                "source_ref": dict(ref),
            }
            row["response"]["status"] = "source_candidate"
            row["fixture_requests"] = 1 if index == 0 else 0
            row["adapter_fixture_requests"] = 1 if index == 0 else 0
        elif handler == "case_nonperiod":
            stored = spec.expected()["stored_kind"]
            ref = _doc_ref(f"{spec.id}.filing", mime="application/pdf")
            filing = {
                "status": "source_candidate",
                "document_kind": stored,
                "resolution_outcome": "downloaded_new",
                "download_events": 1,
                "fiscal_year": request["fiscal_year"],
                "source_ref": dict(ref),
            }
            row["response"]["status"] = "source_candidate"
            row["fixture_requests"] = 1
            row["adapter_fixture_requests"] = 1
        elif handler == "case_call_fy_only":
            transcript = {
                "status": "period_unresolved",
                "reason": "exact_fy_q_required",
                "fiscal_year": 2025,
                "fiscal_quarter": None,
            }
            row["response"]["status"] = "period_unresolved"
        elif handler == "case_call_past_cutoff":
            transcript = {
                "status": "provider_unavailable",
                "reason": "past_cutoff",
                "fiscal_year": 2025,
                "fiscal_quarter": 2,
            }
            row["response"]["status"] = "provider_unavailable"
            row["et_fixture_requests"] = 1
            extra["cutoff_diagnostic"] = True
        elif handler == "case_call_wrong_quarter":
            transcript = {
                "status": "provider_unavailable",
                "reason": "quarter_mismatch",
                "fiscal_year": 2025,
                "fiscal_quarter": 3,
            }
            row["response"]["status"] = "provider_unavailable"
            row["et_fixture_requests"] = 1
        elif handler == "case_err_request":
            filing = {"status": "request_error", "reason": "synthetic request validation failure"}
            row["response"]["status"] = "request_error"
            row["exit_code"] = 2
        elif handler == "case_err_402":
            transcript = {
                "status": "provider_unavailable",
                "reason": "provider_entitlement_required",
                "fiscal_year": 2025,
                "fiscal_quarter": 4,
            }
            row["response"]["status"] = "provider_unavailable"
            row["et_fixture_requests"] = 1
        elif handler == "case_err_missing_creds":
            transcript = {
                "status": "provider_unavailable",
                "reason": "credentials_missing",
                "fiscal_year": 2026,
                "fiscal_quarter": 1,
            }
            row["response"]["status"] = "provider_unavailable"
        elif handler == "case_err_unknown_usage":
            transcript = {
                "status": "upstream_error",
                "reason": "provider_loss",
                "provider_requests": None,
                "provider_usage_complete": False,
                "fiscal_year": 2026,
                "fiscal_quarter": 2,
            }
            row["response"]["status"] = "upstream_error"
            row["et_fixture_requests"] = 1
        elif handler == "case_local_txt":
            ref = _doc_ref(f"{spec.id}.transcript", mime="text/plain")
            transcript = {
                "status": "reused",
                "fiscal_year": 2024,
                "fiscal_quarter": 2,
                "source_ref": dict(ref),
            }
            row["response"]["status"] = "reused"
        elif handler == "case_reuse_only_gap":
            filing = {"status": "not_found"}
            row["response"]["status"] = "not_found"
        elif handler in {"_negative_transcript", "case_failure_then_retry"}:
            reasons = spec.expected()["reasons"]
            if handler == "case_failure_then_retry" and index == 1:
                ref = _doc_ref(f"{spec.id}.transcript")
                transcript = {
                    "status": "downloaded",
                    "fiscal_year": 2029,
                    "fiscal_quarter": 1,
                    "source_ref": dict(ref),
                }
                row["response"]["status"] = "downloaded"
            else:
                transcript = {
                    "status": "failed",
                    "reason": reasons[0],
                    "fiscal_year": 2028 if handler == "_negative_transcript" else 2029,
                    "fiscal_quarter": request["companion_transcript"]["fiscal_quarter"],
                }
                row["response"]["status"] = "failed"
            row["et_fixture_requests"] = 1
            extra["worker_cleanup"] = True
        elif handler == "filing_negative":
            filing = {
                "status": "upstream_error",
                "upstream_cause": {"code": "acquisition_validation_failed"},
            }
            row["response"]["status"] = "upstream_error"
            row["adapter_fixture_requests"] = 2
        elif handler == "case_unverified_sidecar":
            filing = {
                "status": "local_metadata_gap",
                "upstream_cause": {"code": "local_metadata_gap"},
            }
            row["response"]["status"] = "local_metadata_gap"
        else:  # pragma: no cover - registry drift guard
            raise AssertionError(f"no controlled response for handler {spec.handler}")
        row["response"].setdefault("schema_version", "2.0")
        if filing:
            row["response"]["filing"] = filing
        if transcript:
            row["response"]["transcript"] = transcript
        row["fixture_requests"] += row["et_fixture_requests"]
    counters = {
        "fixture_requests": sum(r["fixture_requests"] for r in rows),
        "run2_fixture_requests": rows[1]["fixture_requests"] if len(rows) > 1 else 0,
        "downloads": 0,
        "translations": 0,
    }
    return rows, extra, counters


def build_controlled_matrix(target: Path) -> tuple[dict, Path]:
    """Write a complete synthetic 41-case matrix plus fully bound evidence."""
    artifacts = target / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    proofs: dict[str, dict] = {}
    cases = []
    for spec in case_specs():
        rows, extra, counters = _synthetic_runs(spec)
        runs = []
        for index, (run_spec, row) in enumerate(zip(spec.runs, rows)):
            label = f"run{index + 1}"
            base = f"{spec.id}.{label}"
            request = run_spec.request()
            request_path = artifacts / f"{base}.request.json"
            _write_json(request_path, request)
            response_path = artifacts / f"{base}.response.json"
            _write_json(response_path, row["response"])
            fixture_state = run_spec.fixture() or {}
            fixture_path = artifacts / f"{base}.fixture.json"
            _write_json(
                fixture_path,
                {"state": fixture_state, "with_fmp_key": run_spec.with_fmp_key},
            )
            stderr_path = artifacts / f"{base}.stderr.txt"
            stderr_path.write_text("", encoding="utf-8")
            content = run_spec.fixture() or {}
            trace = {
                "exit_code": row["exit_code"],
                "response": row["response"],
                "stderr": "",
                "request_ref": request_path.name,
                "response_ref": response_path.name,
                "stderr_ref": stderr_path.name,
                "et_fixture_requests": row["et_fixture_requests"],
                "adapter_fixture_requests": row["adapter_fixture_requests"],
                "fixture_requests": row["fixture_requests"],
                "receipt_tag": spec.id,
                "fixture_scenario": content.get("scenario"),
                "fixture_ref": fixture_path.name,
                "fixture_sha256": _sha256_file(fixture_path),
                "expected_original_content_sha256": (
                    hashlib.sha256(content.get("content_utf8", "").encode("utf-8")).hexdigest()
                    if content.get("content_utf8")
                    else None
                ),
                "request_sha256": _sha256_file(request_path),
                "response_sha256": _sha256_file(response_path),
            }
            if row["et_fixture_requests"] > 0:
                for kind in ("result", "usage"):
                    receipt = artifacts / f"{spec.id}.{kind}.json"
                    _write_json(receipt, {"receipt_tag": spec.id, "kind": kind})
                    trace[f"et_{kind}_receipt"] = {
                        "file": receipt.name,
                        "sha256": _sha256_file(receipt),
                    }
            runs.append(trace)
            for kind in ("filing", "transcript"):
                ref = (row["response"].get(kind) or {}).get("source_ref")
                if not ref:
                    continue
                document_kind = (
                    request.get("document_kind")
                    if kind == "filing"
                    else "investor_call_transcript"
                )
                proof = {
                    "verified": True,
                    "reference": dict(ref),
                    "content_sha256": ref["content_sha256"],
                    "byte_size": ref["byte_size"],
                    "source_versions": 1,
                    "physical_originals": 1,
                    "document_kind": document_kind,
                    "original_language_content_sha256": trace["expected_original_content_sha256"],
                }
                proofs.setdefault(ref["document_id"], proof)
        case = {
            "id": spec.id,
            "title": spec.id,
            "declared_layer": spec.declared_layer,
            "observed_layer": spec.declared_layer,
            "result": "PASS",
            "scope": spec.scope,
            "expected": spec.expected(),
            "actual": {"elapsed_seconds": 0.1, "runs": runs, **extra},
            "provider_counters": counters,
            "request_ref": runs[0]["request_ref"],
            "response_ref": runs[0]["response_ref"],
            "receipt_refs": [],
            "diagnostics": [],
        }
        cases.append(case)
    report = {
        "schema_version": SCHEMA,
        "runner": {"tool": "tools/offline_contract_matrix", "version": "2.1.0"},
        "dependencies": [],
        "code_binding": {"verified": True},
        "required_cases": [spec.id for spec in case_specs()],
        "evidence_root": str(artifacts),
        "source_proofs": {"proofs": proofs},
        "scope": {
            "batch_elapsed_seconds": 5.0,
            "case_limit_seconds": 30,
            "batch_deadline_seconds": 180,
            "network_guard_boots": 1,
            "network_attempts_denied": 0,
            "translation_attempts": 0,
        },
        "cost": {
            "real_provider_calls": 0,
            "paid_usd": 0,
            "unknown_charge": None,
            "fixture_requests": sum(c["provider_counters"]["fixture_requests"] for c in cases),
        },
        "cases": cases,
        "restore": {"restored": True},
        "oracle": {"pass": True, "findings": []},
    }
    return report, artifacts


@pytest.fixture()
def controlled(tmp_path):
    report, artifacts = build_controlled_matrix(tmp_path / "controlled")
    report_path = tmp_path / "controlled" / "report.json"
    _write_json(report_path, report)
    return report, artifacts, report_path


# ── interface RED (missing API; not a production defect) ────────────────────


def test_interface_red_audit_exposes_evidence_root_override(controlled):
    report, artifacts, _ = controlled
    import inspect

    parameters = inspect.signature(oracle_mod.audit).parameters
    assert parameters["evidence_root"].default is None
    assert parameters["evidence_root"].kind is inspect.Parameter.KEYWORD_ONLY
    relocated = _relocate(artifacts, artifacts.parent / "relocated artifacts 搬迁")
    assert oracle_mod.audit(report, evidence_root=relocated) == []


def test_interface_red_cli_exposes_replay_branch(controlled, tmp_path):
    report, artifacts, report_path = controlled
    out = tmp_path / "replay.json"
    code = cli_main.main(
        ["replay", "--report", str(report_path), "--evidence-root", str(artifacts), "--output", str(out)]
    )
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["schema_version"] == REPLAY_SCHEMA


# ── frozen old default behaviour ───────────────────────────────────────────


def _frozen_report() -> dict:
    report = json.loads((AUTHORITY / "original-41-report.json").read_text(encoding="utf-8"))
    report["evidence_root"] = str(AUTHORITY / "artifacts")
    return report


def test_default_audit_findings_are_exactly_preserved():
    report = _frozen_report()
    findings = oracle_mod.audit(report)
    assert len(findings) == FROZEN_DEFAULT_FINDING_COUNT
    assert _sha256_json([f.to_dict() for f in findings]) == FROZEN_DEFAULT_FINDINGS_SHA256
    assert Counter(f.vector for f in findings) == {
        "missing_case_fixture_evidence": 40,
        "case_not_passed": 22,
        "fake_layer_claimed_real": 1,
        "wrong_cutoff": 1,
        "fake_zero_cost": 1,
    }
    assert _finding_keys(report) == [
        (f.vector, f.case_id) for f in oracle_mod.audit(_frozen_report())
    ]


def test_default_audit_does_not_mutate_report_or_inputs():
    report = _frozen_report()
    before = copy.deepcopy(report)
    artifacts_before = _tree_digest(AUTHORITY / "artifacts")
    oracle_mod.audit(report)
    assert report == before
    assert _tree_digest(AUTHORITY / "artifacts") == artifacts_before


def test_explicit_none_and_same_root_do_not_change_findings_or_inputs():
    report = _frozen_report()
    before = copy.deepcopy(report)
    artifacts_before = _tree_digest(AUTHORITY / "artifacts")
    default_keys = _finding_keys(report)
    assert _finding_keys(report, evidence_root=None) == default_keys
    assert _finding_keys(report, evidence_root=AUTHORITY / "artifacts") == default_keys
    assert report == before
    assert _tree_digest(AUTHORITY / "artifacts") == artifacts_before


# ── relocation behaviour ───────────────────────────────────────────────────


def test_override_relocates_reads_and_keeps_original_bytes(controlled, tmp_path):
    report, artifacts, report_path = controlled
    report_sha = _sha256_file(report_path)
    artifacts_before = _tree_digest(artifacts)
    relocated = _relocate(artifacts, tmp_path / "搬迁 copy with spaces" / "artifacts")
    findings = oracle_mod.audit(report, evidence_root=relocated)
    assert findings == []
    assert _finding_keys(report, evidence_root=relocated) == _finding_keys(report, evidence_root=artifacts)
    assert _sha256_file(report_path) == report_sha
    assert _tree_digest(artifacts) == artifacts_before
    assert report["evidence_root"] == str(artifacts)


def test_override_reads_only_the_override_never_the_report_root(controlled, tmp_path):
    report, artifacts, _ = controlled
    relocated = _relocate(artifacts, tmp_path / "relocated" / "artifacts")
    # the report's recorded root becomes wrong on purpose; the override stays clean
    tampered = artifacts / report["cases"][-1]["actual"]["runs"][0]["response_ref"]
    tampered.write_bytes(tampered.read_bytes() + b" ")
    assert _finding_keys(report, evidence_root=relocated) == []
    assert any(v == "invalid_bound_evidence" for v, _ in _finding_keys(report))


def test_missing_override_root_never_falls_back_to_report_root(controlled, tmp_path):
    report, artifacts, _ = controlled
    gone = tmp_path / "gone" / "artifacts"
    shutil.copytree(artifacts, gone)
    shutil.rmtree(gone)
    keys = _finding_keys(report, evidence_root=gone)
    assert keys and all(v != "coverage_gap" for v, _ in keys)
    assert any(v in {"invalid_bound_evidence", "missing_bound_evidence", "missing_case_fixture_evidence"} for v, _ in keys)
    assert keys != _finding_keys(report)


# ── byte/contract negative controls (native oracle, explicit root) ─────────


def _case_run(report: dict, case_id: str, index: int = 0) -> dict:
    return next(c for c in report["cases"] if c["id"] == case_id)["actual"]["runs"][index]


def _tamper(root: Path, ref: str) -> None:
    path = root / ref
    path.write_bytes(path.read_bytes() + b" ")


def test_single_byte_response_tamper_is_detected(controlled):
    report, artifacts, _ = controlled
    _tamper(artifacts, _case_run(report, "err_request_error")["response_ref"])
    findings = oracle_mod.audit(report, evidence_root=artifacts)
    assert [(f.vector, f.case_id, f.detail) for f in findings] == [
        ("invalid_bound_evidence", "err_request_error", "ValueError: receipt bytes changed")
    ]


def test_single_byte_request_tamper_is_detected(controlled):
    report, artifacts, _ = controlled
    _tamper(artifacts, _case_run(report, "err_request_error")["request_ref"])
    findings = oracle_mod.audit(report, evidence_root=artifacts)
    assert [(f.vector, f.case_id) for f in findings] == [("invalid_bound_evidence", "err_request_error")]


def test_single_byte_fixture_tamper_is_detected(controlled):
    report, artifacts, _ = controlled
    _tamper(artifacts, _case_run(report, "err_unknown_usage")["fixture_ref"])
    findings = oracle_mod.audit(report, evidence_root=artifacts)
    assert [(f.vector, f.case_id) for f in findings] == [
        ("missing_case_fixture_evidence", "err_unknown_usage")
    ]
    assert "fixture receipt bytes changed" in findings[0].detail


def test_et_usage_and_result_receipt_tamper_is_detected(controlled):
    report, artifacts, _ = controlled
    run = _case_run(report, "call_past_cutoff")
    _tamper(artifacts, run["et_usage_receipt"]["file"])
    _tamper(artifacts, run["et_result_receipt"]["file"])
    details = [f.detail for f in oracle_mod.audit(report, evidence_root=artifacts)]
    assert sorted(d.split(":")[0] for d in details) == ["ET result", "ET usage"]
    assert all(f.case_id == "call_past_cutoff" for f in oracle_mod.audit(report, evidence_root=artifacts))


def test_inline_response_self_claim_mismatch_is_detected(controlled):
    report, artifacts, _ = controlled
    report["cases"][-1]["actual"]["runs"][0]["response"]["status"] = "downloaded"
    findings = oracle_mod.audit(report, evidence_root=artifacts)
    assert [(f.vector, f.case_id) for f in findings] == [
        ("invalid_bound_evidence", "incomplete_sidecar_metadata_gap")
    ]
    assert "self-claim" in findings[0].detail


def test_missing_artifact_file_is_detected(controlled):
    report, artifacts, _ = controlled
    (artifacts / _case_run(report, "err_request_error")["response_ref"]).unlink()
    findings = oracle_mod.audit(report, evidence_root=artifacts)
    assert [(f.vector, f.case_id) for f in findings] == [("invalid_bound_evidence", "err_request_error")]
    assert "FileNotFoundError" in findings[0].detail


def test_ref_pointing_at_directory_is_detected(controlled):
    report, artifacts, _ = controlled
    path = artifacts / _case_run(report, "err_request_error")["response_ref"]
    path.unlink()
    path.mkdir()
    findings = oracle_mod.audit(report, evidence_root=artifacts)
    assert [(f.vector, f.case_id) for f in findings] == [("invalid_bound_evidence", "err_request_error")]
    # a directory ref must surface as a named bound-evidence fault on any OS
    assert ("IsADirectoryError" in findings[0].detail) or ("PermissionError" in findings[0].detail)


def test_illegal_json_in_bound_evidence_is_detected(controlled):
    report, artifacts, _ = controlled
    run = _case_run(report, "err_request_error")
    path = artifacts / run["response_ref"]
    path.write_bytes(b"{not json")
    run["response_sha256"] = _sha256_file(path)  # claim matches bytes; content is not JSON
    findings = oracle_mod.audit(report, evidence_root=artifacts)
    assert [(f.vector, f.case_id) for f in findings] == [("invalid_bound_evidence", "err_request_error")]
    assert "JSONDecodeError" in findings[0].detail


def test_path_escaping_evidence_root_is_detected(controlled, tmp_path):
    report, artifacts, _ = controlled
    run = _case_run(report, "err_request_error")
    outside = artifacts.parent / "escaped.request.json"
    outside.write_bytes((artifacts / run["request_ref"]).read_bytes())
    run["request_ref"] = "../escaped.request.json"
    run["request_sha256"] = _sha256_file(outside)
    findings = oracle_mod.audit(report, evidence_root=artifacts)
    assert [(f.vector, f.case_id) for f in findings] == [("invalid_bound_evidence", "err_request_error")]
    assert "escapes attempt" in findings[0].detail


# ── no silent upgrade of historical/unknown results ────────────────────────


def test_historical_failures_and_recorded_findings_cannot_be_upgraded(tmp_path):
    report = _frozen_report()
    report_path = tmp_path / "original-41-report.json"
    _write_json(report_path, report)
    before = _sha256_file(report_path)
    out = tmp_path / "replay.json"
    code = cli_main.main(
        [
            "replay",
            "--report",
            str(report_path),
            "--evidence-root",
            str(report["evidence_root"]),
            "--output",
            str(out),
        ]
    )
    assert code == 1
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["certified"] is False
    assert record["exit_status"] == 1
    assert record["original_case_results"] == {"total": 41, "PASS": 19, "FAIL": 21, "PARTIAL": 1, "NOT_RUN": 0}
    assert record["original_recorded_oracle"] == report["oracle"]
    assert record["original_recorded_oracle"]["pass"] is False
    assert record["original_case_rows"] == {c["id"]: c["result"] for c in report["cases"]}
    assert record["native_replay"]["pass"] is False
    assert record["native_replay"]["findings"]
    assert _sha256_file(report_path) == before


def test_unknown_usage_and_null_cost_never_upgrade(controlled, tmp_path):
    report, artifacts, report_path = controlled
    case = next(c for c in report["cases"] if c["id"] == "err_unknown_usage")
    case["actual"]["unknown_usage_reported_as_zero"] = True
    case["actual"]["provider_requests"] = 0
    _write_json(report_path, report)
    out = tmp_path / "replay.json"
    code = cli_main.main(
        ["replay", "--report", str(report_path), "--evidence-root", str(artifacts), "--output", str(out)]
    )
    assert code == 1
    record = json.loads(out.read_text(encoding="utf-8"))
    assert any(f["vector"] == "fake_zero_cost" for f in record["native_replay"]["findings"])
    assert record["certified"] is False
    assert report["cost"]["unknown_charge"] is None


def test_missing_fresh_proof_cannot_upgrade(controlled, tmp_path):
    report, artifacts, report_path = controlled
    report["source_proofs"]["proofs"].pop("chainA_download_reuse.transcript")
    _write_json(report_path, report)
    out = tmp_path / "replay.json"
    code = cli_main.main(
        ["replay", "--report", str(report_path), "--evidence-root", str(artifacts), "--output", str(out)]
    )
    assert code == 1
    record = json.loads(out.read_text(encoding="utf-8"))
    vectors = {f["vector"] for f in record["native_replay"]["findings"]}
    # a dropped fresh proof leaves the source bytes unverified AND breaks the
    # original-language binding; neither may be read as a pass
    assert vectors == {"source_bytes_not_verified", "translated_or_changed_text"}
    assert record["certified"] is False


def test_component_positive_control_cannot_certify_full_matrix(controlled, tmp_path):
    report, artifacts, report_path = controlled
    single = copy.deepcopy(report)
    single["cases"] = [single["cases"][0]]
    assert oracle_mod.audit_case(get_spec(single["cases"][0]["id"]), single["cases"][0]) == []
    findings = oracle_mod.audit(single, evidence_root=artifacts)
    assert any(f.vector == "coverage_gap" for f in findings)
    assert oracle_mod.passes(findings) is False
    _write_json(report_path, single)
    out = tmp_path / "replay.json"
    assert (
        cli_main.main(
            ["replay", "--report", str(report_path), "--evidence-root", str(artifacts), "--output", str(out)]
        )
        == 1
    )
    assert json.loads(out.read_text(encoding="utf-8"))["certified"] is False


# ── replay CLI contract ────────────────────────────────────────────────────


def test_full_controlled_matrix_passes_and_replay_certifies(controlled, tmp_path):
    report, artifacts, report_path = controlled
    assert oracle_mod.audit(report) == []
    out = tmp_path / "replay.json"
    code = cli_main.main(
        ["replay", "--report", str(report_path), "--evidence-root", str(artifacts), "--output", str(out)]
    )
    assert code == 0
    record = json.loads(out.read_text(encoding="utf-8"))
    assert record["schema_version"] == REPLAY_SCHEMA
    assert record["report"]["sha256"] == _sha256_file(report_path)
    assert record["report"]["sha256_after_replay"] == record["report"]["sha256"]
    assert record["report"]["schema_version"] == SCHEMA
    assert record["evidence_root"]["requested"] == str(artifacts)
    assert record["evidence_root"]["source"] == "explicit_override"
    assert record["original_case_results"] == {"total": 41, "PASS": 41, "FAIL": 0, "PARTIAL": 0, "NOT_RUN": 0}
    assert record["original_recorded_oracle"] == {"pass": True, "findings": []}
    assert record["native_replay"] == {"pass": True, "findings": []}
    assert record["certified"] is True
    assert record["exit_status"] == 0
    assert not (out.parent / (out.name + ".partial")).exists()  # staged write left no partial record
    scope = record["scope"]
    assert scope["kind"] == "retained-evidence replay"
    assert "RETAINED-EVIDENCE REPLAY" in scope["statement"]
    assert "NOT a fresh real 41-case" in scope["statement"]
    assert "fresh real chain" in scope["fresh_41_chain_scope"] or "separate fresh run" in scope["fresh_41_chain_scope"]
    assert any("download" in item for item in scope["does_not_prove"])
    assert any("41" in item or "chain" in item for item in scope["does_not_prove"])
    assert any("SourceVersionReader" in item or "fresh" in item for item in scope["does_not_prove"])


def test_replay_refuses_same_path_and_existing_output(controlled, tmp_path, capsys):
    report, artifacts, report_path = controlled
    report_before = _sha256_file(report_path)
    assert (
        cli_main.main(
            [
                "replay",
                "--report",
                str(report_path),
                "--evidence-root",
                str(artifacts),
                "--output",
                str(report_path),
            ]
        )
        == 2
    )
    assert _sha256_file(report_path) == report_before
    existing = tmp_path / "existing.json"
    existing.write_text("OLD", encoding="utf-8")
    assert (
        cli_main.main(
            [
                "replay",
                "--report",
                str(report_path),
                "--evidence-root",
                str(artifacts),
                "--output",
                str(existing),
            ]
        )
        == 2
    )
    assert existing.read_text(encoding="utf-8") == "OLD"
    inside = artifacts / "replay.json"
    assert (
        cli_main.main(
            [
                "replay",
                "--report",
                str(report_path),
                "--evidence-root",
                str(artifacts),
                "--output",
                str(inside),
            ]
        )
        == 2
    )
    assert not inside.exists()
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "mutation",
    ["missing_report", "bad_json", "unknown_schema", "missing_root", "missing_args"],
)
def test_replay_input_errors_are_explicit_not_tracebacks(controlled, tmp_path, capsys, mutation):
    report, artifacts, report_path = controlled
    out = tmp_path / "replay.json"
    argv = ["replay", "--report", str(report_path), "--evidence-root", str(artifacts), "--output", str(out)]
    if mutation == "missing_report":
        argv[2] = str(tmp_path / "absent.json")
    elif mutation == "bad_json":
        report_path.write_text("{not json", encoding="utf-8")
    elif mutation == "unknown_schema":
        report["schema_version"] = "ff-et-cwp-offline-matrix/999"
        _write_json(report_path, report)
    elif mutation == "missing_root":
        argv[4] = str(tmp_path / "absent-artifacts")
    elif mutation == "missing_args":
        argv = ["replay", "--report", str(report_path)]
    code = cli_main.main(argv)
    assert code == 2
    assert not out.exists()
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err and "Traceback" not in captured.out


@pytest.mark.parametrize("mutation", ["duplicate", "unknown", "removed"])
def test_replay_gate_refuses_duplicate_unknown_or_removed_case_rows(controlled, tmp_path, mutation):
    report, artifacts, report_path = controlled
    tampered = copy.deepcopy(report)
    if mutation == "duplicate":
        tampered["cases"].append(copy.deepcopy(tampered["cases"][0]))
    elif mutation == "unknown":
        tampered["cases"][-1]["id"] = "extra-case-never-defined"
    elif mutation == "removed":
        tampered["cases"] = tampered["cases"][1:]
    _write_json(report_path, tampered)
    out = tmp_path / f"replay-{mutation}.json"
    code = cli_main.main(
        ["replay", "--report", str(report_path), "--evidence-root", str(artifacts), "--output", str(out)]
    )
    record = json.loads(out.read_text(encoding="utf-8"))
    assert code == 1
    assert record["certified"] is False
    assert record["exit_status"] == 1
    assert any(f["vector"] == "coverage_gap" for f in record["native_replay"]["findings"])


def test_replay_never_starts_context_seed_provider_or_network(controlled, tmp_path):
    report, artifacts, report_path = controlled
    out = tmp_path / "replay.json"

    def banned(*args, **kwargs):
        raise AssertionError("replay must not start producer/runtime/network work")

    with ExitStack() as stack:
        for target in (
            "cli_main.Context",
            "cli_main.ProductionGuard",
            "cli_main.OwnedAttempt",
            "cli_main.seed_all",
            "cli_main._verify_binding",
            "cli_main._fresh_proofs",
            "cli_main.run_case_group",
            "cli_main.run_process",
            "run.run_process",
            "runtime.run_process",
            "subprocess.Popen",
            "subprocess.run",
            "socket.socket",
            "socket.create_connection",
            "socket.getaddrinfo",
        ):
            stack.enter_context(mock.patch(target, banned))
        code = cli_main.main(
            [
                "replay",
                "--report",
                str(report_path),
                "--evidence-root",
                str(artifacts),
                "--output",
                str(out),
            ]
        )
    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["certified"] is True


def test_replay_requires_no_production_code_roots(controlled, tmp_path):
    report, artifacts, report_path = controlled
    out = tmp_path / "replay.json"
    argv = ["replay", "--report", str(report_path), "--evidence-root", str(artifacts), "--output", str(out)]
    assert all(not any(flag in word for word in argv) for flag in ("--cwp-project", "--et-project"))
    assert cli_main.main(argv) == 0
    # the old matrix dispatch still demands its original arguments
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main(["--owned-root", str(tmp_path / "scratch")])
    assert excinfo.value.code == 2


def test_old_matrix_argv_dispatch_is_unchanged(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main([])
    assert excinfo.value.code == 2
    with pytest.raises(SystemExit) as excinfo:
        cli_main.main(
            [
                "--cwp-project",
                str(tmp_path / "cwp"),
                "--et-project",
                str(tmp_path / "et"),
                "--owned-root",
                str(tmp_path / "scratch"),
            ]
        )
    assert excinfo.value.code == 2


def test_public_entrypoint_run_py_replays_without_code_roots(controlled, tmp_path):
    report, artifacts, report_path = controlled
    out = tmp_path / "replay.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            str(TOOLS / "run.py"),
            "replay",
            "--report",
            str(report_path),
            "--evidence-root",
            str(artifacts),
            "--output",
            str(out),
        ],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    assert json.loads(out.read_text(encoding="utf-8"))["schema_version"] == REPLAY_SCHEMA
