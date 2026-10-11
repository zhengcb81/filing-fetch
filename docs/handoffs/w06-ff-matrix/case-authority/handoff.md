# W06 CaseSpec authority repair — ROOT handoff

**Author FROZEN_STOP. Engineering tests GREEN, product integration remains PARTIAL_PRODUCT_FAILURES.**

The independent blocker was common: a report could redefine omitted cases, remove a mandatory assertion, or change the intended request vector while updating its hash. Fixed immutable `CaseSpec`/`RunSpec` now owns registry, full request/fixture vector, expected assertions and execution scope; runner and oracle consume it. No extra license, identity store, manual review or signoff was added.

## TDD / concentrated verification

- Retained exact three independent authority inputs → formal 3 FAIL (red.log).
- Fixed response meaning proof: each of 21 real FAIL labels changed to PASS → 21 FAIL before implementation (assertion-red.log).
- Full package: 195 PASS / 4.42 seconds (green-final.log), Ruff clean. Includes all 41 missing-case properties, all 41 duplicate/extra replacements, complete registry and named single-case positives, all 41 original full request vectors, dimensions/companion budgets, fixture/date/credential drift, shared runner registry and rejection before process launch.
- No full 41-case CLI/provider/network/model rerun. Test component fixtures do not claim newly completed product execution.

## Original evidence and remaining work

Original 41 actual statuses remain 19 PASS / 21 FAIL / 1 PARTIAL. New read-only audit reports 22 required cases not passed, original three unmet-stage checks, and 40 missing newly-required fixture receipts. No new business assertion errors occur on original 19 PASS cases. Historical missing receipts must stay missing; no retroactive manufacture. These 40 gaps are newly required test observability only, not production authorization, provider permission or acquisition prerequisites.

Old freeze/report/ZIP hashes and original independent FAIL are preserved. Actual steady source-fact assertion absence and primary2025 missing remain ROOT diagnosis; ET not-started is not proof of an ET defect. ROOT reruns unchanged real matrix after producer prerequisites are resolved.

## Read / replay interfaces

Canonical independent evidence: C:\Users\郑曾波\Projects\company-wiki\docs\plans\cross-market-rf-e2e-2026-10-08\phase6\w06_parallel_verification_2026-10-11\evidence\root-ff-matrix-acceptance\fix\case-authority

1. Read report.json/manifest.json, exact-inputs.json and frozen-matrix-re-audit.json.
2. Run from this FF root: `python -B -m pytest -q tests/test_w06_contract_matrix.py tests/test_w06_matrix_runtime.py tests/test_w06_case_authority.py --basetemp <fresh-short-owned-path>`.
3. Run `python -B -m ruff check tools/offline_contract_matrix tests/test_w06_contract_matrix.py tests/test_w06_matrix_runtime.py tests/test_w06_case_authority.py`.
4. Independent reviewer replays original three counterexamples; use fresh owned paths for modified request bytes. Never overwrite originals or old ZIP.
5. ROOT alone commits/merges/installs/pushes. This author stops after freeze.

Construction helper scripts are archived one-shot implementation records and not re-executable acceptance commands. Scope is test tooling only; no scripts/config/CI/Dayu/IQS changes.
