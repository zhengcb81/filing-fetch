"""Runner oracle: detects the pre-declared failure vectors.

This is the acceptance gate for the offline contract matrix. It looks at a
``ff-et-cwp-offline-matrix/1`` report plus the restore receipt and flags six
failure vectors. Node A proves the oracle detects each vector (RED) before the
runner is trusted to produce clean (GREEN) reports.

Vectors:
  * fake_layer_claimed_real   — a case declares real three-layer but no real
                                ET supervisor/worker ran (a whole layer was
                                faked while the report claims real).
  * second_run_still_downloads — a reuse case re-downloadson the second run.
  * missing_et_receipt        — a real three-layer case that started a provider
                                call but produced no ET usage receipt.
  * wrong_cutoff              — a past-cutoff case that reports "eligible"
                                instead of the actual cutoff diagnostic.
  * fake_zero_cost            — unknown usage/cost reported as a real 0, or a
                                provider call swallowed instead of kept as null.
  * unrestored_scratch        — production config/original bytes changed or the
                                sentinel was not restored.

An initial missing tool/file in a stub is not itself a production failure; the
oracle only judges the recorded vectors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from pathlib import Path
import hashlib
import json
from matrix_outcome import count, source_ref
from case_specs import audit_coverage, get_spec
from case_specs import case_specs as _base_case_specs
from w20_case_specs import w20_case_specs as _supplemental_case_specs


@dataclass
class Finding:
    vector: str
    case_id: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"vector": self.vector, "case_id": self.case_id, "detail": self.detail}


def _real_layer_ok(case: dict[str, Any]) -> bool:
    evidence = (case.get("actual") or {}).get("real_layer_evidence") or {}
    return bool(
        evidence.get("et_supervisor_worker")
        and evidence.get("ff_public_cli")
        and evidence.get("cwp_import")
    )


def _selection_mode(report: dict[str, Any]) -> dict[str, Any] | None:
    selection = (report.get("scope") or {}).get("selection") or {}
    return selection if isinstance(selection, dict) and selection.get("mode") == "selected" else None


def _is_not_selected_row(case: dict[str, Any]) -> bool:
    """A row that claims nothing: NOT_RUN with the named not-selected reason."""
    return case.get("result") == "NOT_RUN" and any(
        isinstance(item, str) and item.startswith("not selected")
        for item in (case.get("diagnostics") or [])
    )


def _known_case_ids() -> set[str]:
    return {spec.id for spec in _base_case_specs()} | {spec.id for spec in _supplemental_case_specs()}


def _selection_findings(report: dict[str, Any]) -> list[Finding]:
    """Consistency of a supplemental selection report (never a certification).

    The fixed required-case authority may not shrink, every known case must
    appear exactly once, unselected rows must be honest NOT_RUN rows carrying
    the named reason, and selected rows must never wear the not-selected label.
    A selection report can still never certify the full matrix: that is a
    property of the runner's exit semantics and the DU6 replay path, not a
    finding to be re-derived here.
    """
    findings: list[Finding] = []
    selection = _selection_mode(report) or {}
    selected = [cid for cid in (selection.get("selected") or []) if isinstance(cid, str)]
    selected_set = set(selected)
    required = report.get("required_cases")
    if required is not None and sorted(required) != sorted(s.id for s in _base_case_specs()):
        findings.append(Finding(
            "required_cases_shrunk", None,
            "required_cases differs from the fixed authority; a selection may "
            "never shrink the required set to look complete",
        ))
    known = _known_case_ids()
    unknown = [cid for cid in selected if cid not in known]
    if unknown:
        findings.append(Finding(
            "selection_unknown_case", None,
            f"selection names unknown case ids: {sorted(unknown)}",
        ))
    observed = [case.get("id") for case in report.get("cases") or []]
    duplicate = sorted({cid for cid in observed if observed.count(cid) > 1})
    if duplicate:
        findings.append(Finding("selection_duplicate_row", None, f"duplicate rows: {duplicate}"))
    missing = sorted(known - set(observed))
    if missing:
        findings.append(Finding(
            "selection_row_missing", None,
            f"every known case needs a row (executed or honest NOT_RUN); missing: {missing}",
        ))
    extra = sorted(set(observed) - known)
    if extra:
        findings.append(Finding("unknown_case", None, f"unknown case rows: {extra}"))
    for case in report.get("cases") or []:
        cid = case.get("id")
        if cid in selected_set and _is_not_selected_row(case):
            findings.append(Finding(
                "selection_row_mislabelled", cid,
                "a selected case carries the not-selected NOT_RUN label",
            ))
        elif cid not in selected_set and not _is_not_selected_row(case):
            findings.append(Finding(
                "selection_row_mislabelled", cid,
                "an unselected case must stay NOT_RUN with the named not-selected reason",
            ))
    return findings


def audit(report: dict[str, Any], *, evidence_root: str | Path | None = None) -> list[Finding]:
    """Audit one matrix report.

    ``evidence_root`` optionally re-roots only the existing relative artifact
    refs (retained-evidence replay after a relocation). ``None`` keeps the old
    default exactly: the report's own ``evidence_root``. The override never
    rewrites CaseSpec judgements, SHA checks, the report or any input, and it
    is not a new identity/authorization state.
    """
    findings: list[Finding] = []
    cases = report.get("cases") or []
    if not cases:
        findings.append(Finding("empty_matrix", None, "no cases were executed"))
    if "code_binding" in report and (report.get("code_binding") or {}).get("verified") is not True:
        findings.append(
            Finding("unbound_code", None, "supplied producer code binding is unverified")
        )
    selection = _selection_mode(report)
    if selection is not None:
        # Supplemental selection run: the base full-coverage predicate does not
        # apply (cases are deliberately incomplete); selection consistency is
        # the coverage authority instead.
        findings.extend(_selection_findings(report))
    else:
        # Fixed code registry is authoritative even if runner/required_cases is erased.
        for detail in audit_coverage(cases):
            findings.append(Finding("coverage_gap", None, detail))
    if report.get("runner"):
        if (report.get("code_binding") or {}).get("verified") is not True:
            findings.append(Finding("unbound_code", None, "matrix lacks verified import binding"))
        if (report.get("scope") or {}).get("batch_elapsed_seconds", float("inf")) > 180:
            findings.append(Finding("deadline_exceeded", None, "absolute batch deadline exceeded"))

    for case in cases:
        case_id = case.get("id")
        spec = get_spec(case_id)
        if spec is None:
            from w20_case_specs import get_w20_spec
            spec = get_w20_spec(case_id)
        if spec is None:
            findings.append(
                Finding("unknown_case", case_id, "case has no fixed executable definition")
            )
            continue
        if selection is not None and _is_not_selected_row(case):
            # An explicitly unselected row claims nothing; auditing it as a
            # failure would demand evidence the selection never claimed.
            continue
        findings.extend(audit_case(spec, case))

    # 6. production bytes changed or sentinel not restored.
    restore = report.get("restore") or {}
    if restore.get("restored") is not True:
        findings.append(
            Finding(
                "unrestored_scratch",
                None,
                f"restore receipt does not confirm restoration (got {restore})",
            )
        )

    findings.extend(_bound_evidence(report, evidence_root))
    return findings


def audit_case(spec, case: dict[str, Any]) -> list[Finding]:
    """Audit one fixed case's declarations and mandatory assertions.

    This is a component check, not complete matrix acceptance; audit() also
    checks mandatory coverage and bound actual request/response/fixture bytes.
    """
    findings = []
    case_id = spec.id
    declared, expected = spec.declared_layer, spec.expected()
    for detail in spec.metadata_errors(case):
        findings.append(Finding("case_contract_mismatch", case_id, detail))
    if case.get("result") != "PASS":
        findings.append(
            Finding(
                "case_not_passed",
                case_id,
                f"actual result {case.get('result')} cannot certify required case",
            )
        )
    else:
        for detail in spec.assertion_errors(case):
            findings.append(Finding("case_assertion_failed", case_id, detail))
    actual = case.get("actual") or {}
    counters = case.get("provider_counters") or {}
    evidence = actual.get("real_layer_evidence") or {}

    # 1. whole layer faked but claims real three-layer.
    if declared == "real-3layer" and not _real_layer_ok(case):
        findings.append(
            Finding(
                "fake_layer_claimed_real",
                case_id,
                "declared real-3layer but ff_public_cli/et_supervisor_worker/cwp_import "
                f"evidence is not all present (got {evidence})",
            )
        )

    # 3. real three-layer started a provider call but has no ET receipt.
    if (
        declared == "real-3layer"
        and (counters.get("fixture_requests") or 0) > 0
        and not actual.get("et_usage_receipt")
    ):
        findings.append(
            Finding(
                "missing_et_receipt",
                case_id,
                "provider call was made but no ET usage receipt was recorded",
            )
        )

    # 2. a reuse case that still downloads on the second run.
    if expected.get("run_twice") and count(counters.get("run2_fixture_requests")) != 0:
        findings.append(
            Finding(
                "second_run_still_downloads",
                case_id,
                f"second run performed {counters.get('run2_fixture_requests')} provider "
                "requests; a reuse hit must be 0",
            )
        )

    # 4. a past-cutoff case that did not surface the cutoff diagnostic.
    if expected.get("past_cutoff") and not actual.get("cutoff_diagnostic"):
        findings.append(
            Finding(
                "wrong_cutoff",
                case_id,
                "past-cutoff case did not report the actual cutoff diagnostic",
            )
        )

    # 5. unknown usage/cost rendered as zero, or a call swallowed.
    if expected.get("unknown_usage"):
        if (
            actual.get("unknown_usage_reported_as_zero")
            or actual.get("calls_swallowed")
            or (
                "provider_requests" in actual
                and actual.get("provider_usage_complete") is not True
                and actual.get("provider_requests") is not None
            )
        ):
            findings.append(
                Finding(
                    "fake_zero_cost",
                    case_id,
                    "unknown usage/cost was reported as 0 or the provider call was swallowed",
                )
            )

    return findings


def passes(findings: list[Finding]) -> bool:
    return not findings


def _bound_evidence(report: dict, evidence_root: str | Path | None = None) -> list[Finding]:
    findings = []
    scope = report.get("scope") or {}
    if (
        (count(scope.get("network_guard_boots")) or 0) == 0
        or scope.get("network_attempts_denied") != 0
        or scope.get("translation_attempts") != 0
    ):
        findings.append(
            Finding(
                "unmeasured_isolation",
                None,
                "startup network/translation instrumentation missing or an attempt occurred",
            )
        )
    # An explicit override only relocates the existing relative refs; nothing
    # searches the disk and nothing falls back to the report's recorded root.
    root_value = evidence_root if evidence_root is not None else report.get("evidence_root")
    root = Path(root_value).resolve() if root_value else None
    proofs = (report.get("source_proofs") or {}).get("proofs") or {}
    for case in report.get("cases", []):
        cid = case.get("id")
        if _is_not_selected_row(case):
            # An explicitly unselected row claims no evidence and no result.
            continue
        if (case.get("actual") or {}).get("elapsed_seconds", float("inf")) > 30 and case.get(
            "result"
        ) == "PASS":
            findings.append(Finding("case_deadline_exceeded", cid, "late case cannot PASS"))
        runs = (case.get("actual") or {}).get("runs") or []
        spec = get_spec(cid)
        if spec is None:
            from w20_case_specs import get_w20_spec
            spec = get_w20_spec(cid)
        if spec and case.get("result") == "PASS" and len(runs) != len(spec.runs):
            findings.append(
                Finding("case_run_count_mismatch", cid, "required number of attempts not observed")
            )
        if not runs or root is None:
            findings.append(
                Finding("missing_bound_evidence", cid, "PASS lacks actual request/response files")
            )
            continue
        for index, run in enumerate(runs):
            request, response = {}, {}
            try:
                for kind in ("request", "response"):
                    path = (root / run[kind + "_ref"]).resolve()
                    if not path.is_relative_to(root):
                        raise ValueError("receipt path escapes attempt")
                    raw = path.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != run[kind + "_sha256"]:
                        raise ValueError("receipt bytes changed")
                    payload = json.loads(raw)
                    if kind == "request":
                        request = payload
                    else:
                        response = payload
                if response != run["response"]:
                    raise ValueError("response self-claim differs from bound bytes")
            except Exception as exc:
                findings.append(
                    Finding("invalid_bound_evidence", cid, f"{type(exc).__name__}: {exc}")
                )
                continue
            if spec:
                for detail in spec.request_errors(index, request):
                    findings.append(Finding("case_request_mismatch", cid, detail))
                if index < len(spec.runs) and (
                    spec.runs[index].fixture() is not None or not spec.runs[index].with_fmp_key
                ):
                    try:
                        fixture_path = (root / run["fixture_ref"]).resolve()
                        if not fixture_path.is_relative_to(root):
                            raise ValueError("fixture receipt escapes attempt")
                        raw = fixture_path.read_bytes()
                        if hashlib.sha256(raw).hexdigest() != run["fixture_sha256"]:
                            raise ValueError("fixture receipt bytes changed")
                        fixture = json.loads(raw)
                        for detail in spec.fixture_errors(
                            index, fixture["state"], fixture["with_fmp_key"]
                        ):
                            findings.append(Finding("case_fixture_mismatch", cid, detail))
                    except Exception as exc:
                        findings.append(
                            Finding(
                                "missing_case_fixture_evidence", cid, f"{type(exc).__name__}: {exc}"
                            )
                        )
                elif index < len(spec.runs) and "fixture_ref" in run:
                    # Key-presence vector is mandatory even without supplier fixture.
                    try:
                        fixture_path = (root / run["fixture_ref"]).resolve()
                        if not fixture_path.is_relative_to(root):
                            raise ValueError("fixture escapes attempt")
                        raw = fixture_path.read_bytes()
                        if hashlib.sha256(raw).hexdigest() != run["fixture_sha256"]:
                            raise ValueError("fixture bytes changed")
                        fixture = json.loads(raw)
                        for detail in spec.fixture_errors(
                            index, fixture["state"], fixture["with_fmp_key"]
                        ):
                            findings.append(Finding("case_fixture_mismatch", cid, detail))
                    except Exception as exc:
                        findings.append(Finding("invalid_bound_evidence", cid, f"fixture: {exc}"))
            if run.get("et_fixture_requests", 0) > 0:
                for receipt_kind in ("result", "usage"):
                    key = f"et_{receipt_kind}_receipt"
                    if key not in run and run.get("killed") is True:
                        # The harness interrupted the FF tree while the ET call
                        # was still in flight: the proxy was killed before it
                        # could persist this receipt, so no receipt bytes ever
                        # existed to bind. The in-flight GET itself is still
                        # counted and audited above; nothing is excused.
                        continue
                    try:
                        record = run[key]
                        receipt_path = (root / record["file"]).resolve()
                        if not receipt_path.is_relative_to(root):
                            raise ValueError("ET receipt escapes attempt")
                        if (
                            hashlib.sha256(receipt_path.read_bytes()).hexdigest()
                            != record["sha256"]
                        ):
                            raise ValueError("ET receipt bytes changed")
                    except Exception as exc:
                        findings.append(
                            Finding("missing_bound_evidence", cid, f"ET {receipt_kind}: {exc}")
                        )
            for kind in ("filing", "transcript"):
                row = response.get(kind) or {}
                ref = source_ref(row.get("source_ref"))
                accepted = row.get("status") in {
                    "downloaded",
                    "reused",
                    "unknown_publication",
                    "source_candidate",
                }
                if accepted and ref is None:
                    findings.append(
                        Finding(
                            "missing_source_ref", cid, f"{kind} accepted without complete SourceRef"
                        )
                    )
                if ref is None:
                    continue
                proof = proofs.get(ref["document_id"]) or {}
                expected_kind = (
                    request.get("document_kind") if kind == "filing" else "investor_call_transcript"
                )
                if (
                    proof.get("verified") is not True
                    or proof.get("reference") != ref
                    or proof.get("content_sha256") != ref["content_sha256"]
                    or proof.get("byte_size") != ref["byte_size"]
                    or proof.get("source_versions") != 1
                    or proof.get("physical_originals") != 1
                    or proof.get("document_kind") != expected_kind
                ):
                    findings.append(
                        Finding(
                            "source_bytes_not_verified",
                            cid,
                            f"fresh reader/source version/original count mismatch for {kind}",
                        )
                    )
                if (
                    kind == "transcript"
                    and run.get("expected_original_content_sha256")
                    and row.get("status") == "downloaded"
                    and proof.get("original_language_content_sha256")
                    != run["expected_original_content_sha256"]
                ):
                    findings.append(
                        Finding(
                            "translated_or_changed_text",
                            cid,
                            "stored original language content differs from supplied fixture text",
                        )
                    )
                period = request if kind == "filing" else request.get("companion_transcript", {})
                if row.get("fiscal_year") != period.get("fiscal_year"):
                    findings.append(
                        Finding("wrong_period", cid, f"{kind} fiscal year differs from request")
                    )
                if (
                    kind == "filing"
                    and period.get("fiscal_period") is not None
                    and row.get("fiscal_period") != period.get("fiscal_period")
                ):
                    findings.append(
                        Finding("wrong_period", cid, "filing fiscal period differs from request")
                    )
                if kind == "transcript" and row.get("fiscal_quarter") != period.get(
                    "fiscal_quarter"
                ):
                    findings.append(
                        Finding("wrong_period", cid, "transcript quarter differs from request")
                    )
        if spec and spec.expected().get("run_twice") and len(runs) >= 2:
            first, second = runs[0]["response"], runs[1]["response"]
            for kind in ("filing", "transcript"):
                ref1, ref2 = (
                    source_ref((first.get(kind) or {}).get("source_ref")),
                    source_ref((second.get(kind) or {}).get("source_ref")),
                )
                if ref1 and ref1 != ref2:
                    findings.append(
                        Finding(
                            "reuse_identity_changed",
                            cid,
                            f"{kind} second run changed source version",
                        )
                    )
    return findings
