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


def audit(report: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    cases = report.get("cases") or []

    for case in cases:
        case_id = case.get("id")
        declared = case.get("declared_layer")
        expected = case.get("expected") or {}
        actual = case.get("actual") or {}
        counters = case.get("provider_counters") or {}
        evidence = actual.get("real_layer_evidence") or {}

        # 1. whole layer faked but claims real three-layer.
        if declared == "real-3layer" and not _real_layer_ok(case):
            findings.append(Finding(
                "fake_layer_claimed_real", case_id,
                "declared real-3layer but ff_public_cli/et_supervisor_worker/cwp_import "
                f"evidence is not all present (got {evidence})",
            ))

        # 3. real three-layer started a provider call but has no ET receipt.
        if (
            declared == "real-3layer"
            and (counters.get("fixture_requests") or 0) > 0
            and not actual.get("et_usage_receipt")
        ):
            findings.append(Finding(
                "missing_et_receipt", case_id,
                "provider call was made but no ET usage receipt was recorded",
            ))

        # 2. a reuse case that still downloads on the second run.
        if expected.get("run_twice") and (counters.get("run2_fixture_requests") or 0) != 0:
            findings.append(Finding(
                "second_run_still_downloads", case_id,
                f"second run performed {counters.get('run2_fixture_requests')} provider "
                "requests; a reuse hit must be 0",
            ))

        # 4. a past-cutoff case that did not surface the cutoff diagnostic.
        if expected.get("past_cutoff") and not actual.get("cutoff_diagnostic"):
            findings.append(Finding(
                "wrong_cutoff", case_id,
                "past-cutoff case did not report the actual cutoff diagnostic",
            ))

        # 5. unknown usage/cost rendered as zero, or a call swallowed.
        if expected.get("unknown_usage"):
            if actual.get("unknown_usage_reported_as_zero") or actual.get("calls_swallowed"):
                findings.append(Finding(
                    "fake_zero_cost", case_id,
                    "unknown usage/cost was reported as 0 or the provider call was swallowed",
                ))

    # 6. production bytes changed or sentinel not restored.
    restore = report.get("restore") or {}
    if restore.get("restored") is not True:
        findings.append(Finding(
            "unrestored_scratch", None,
            f"restore receipt does not confirm restoration (got {restore})",
        ))

    return findings


def passes(findings: list[Finding]) -> bool:
    return not findings
