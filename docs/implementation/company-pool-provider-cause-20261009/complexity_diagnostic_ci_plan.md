# Complexity diagnostic and focused CI correction

Status: implementation/verification complete; owner audit_campaign_design_review in this isolated branch.

## Scope and evidence

Candidate afbef65 business consumer implementation stays unchanged. Root reproduced quality run37861936346: curated suite 419 passed / 4 skipped / 78 subtests with one numeric-only failure, ff_provider_cause.py legacy score14 > new-file reference10. No FF root AGENTS.md exists. pre-commit uses Ruff, public-contract mypy and host-assumption checks; pre-push fast checks are preserved.

## Plan

1. RED: add explicit tests for a runnable read-only complexity diagnostic, legal low/high scores both exit0, invalid syntax and missing input exit1, score changes independent of exit status. Preserve old numeric failure evidence.
2. Implement a small tools diagnostic using the existing legacy AST score, clearly label it as an estimate with historical references. Remove both frozen-file and new-file score blockers; do not increase10, split business functions or hide syntax failures.
3. Replace the old score gate in quality curated tests with diagnostic contract tests and add existing provider-cause/operation-consumer responsibility suites. Add one read-only diagnostic command; do not expand to the slow full suite.
4. GREEN: run the exact YAML curated suite, Ruff over its CI scope and pinned mypy public contracts; record actual counts, skips, runtimes and owned TEMP restoration. Keep compile/import/behavior checks intact.
5. Append handoff/proof, commit only this card after normal hooks; no push, merge, installation or production writes.

## Acceptance

Score14 remains visible and no longer blocks. Illegal Python cannot be silently scored0. Real source/provider start, unknown usage, retry and safe-cause behavior remain covered by tests. No provider/model calls or fees. Owned short TEMP restored in finally; no raw/config/other-owner writes. Large-node verification only.

## Next Step

Write diagnostic contract tests and capture RED before implementation.

## RED and implementation record

2026-10-09: old gate reproduced1 FAIL/1 PASS, exact ff_provider_cause14>10. New diagnostic contracts7 FAIL/0 errors before tool creation; owned TEMP restored. Evidence complexity_red.json. Both old score blockers removed as policy change; historical references10/34/39 unchanged and visible. Existing estimator moved to a read-only tool and syntax errors no longer return0. No business runtime file changed.

Next Step: concentrated diagnostic GREEN, then the exact modified curated suite and CI static scope.

## GREEN and handoff

See complexity_ci_proof.json: diagnostic7 PASS, curated527 PASS/5 SKIP/78subtests, explicit CWP2 PASS, syntax/import/Ruff/mypy/unique symbols PASS, TEMP restored. Remaining3 original production/capability skips retained. Business implementation unchanged. Next Step: normal-hook local commit then root-controlled publication.
