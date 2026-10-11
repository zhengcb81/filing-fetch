# W04 WP04 — FF failure observation

## Scope
Only scripts/filing_contracts.py, fetch_filing.py, ff_provider_cause.py and tests/test_w04_failure_observation.py; no production config, secret, old run, canonical, install, commit or push writes.

## Phases
1. Baseline, actual sealed-input inventory, closed sibling interface — **Status:** complete
2. TDD RED examples against typed reasons and safe envelopes — **Status:** complete
3. Implement owner-local validation/envelope seams — **Status:** complete
4. One focused compatibility gate; RF sibling read integration — **Status:** complete
5. Exact SHA/diff/log handoff and STOP — **Status:** complete

## Next Step
STOP. ROOT performs independent acceptance, normal commit/push/exact CI and installation; this worker performs none.

## Errors Encountered
- CodeGraph not initialized in assigned isolated FF worktree. No index created; continue known-path reads per ROOT instructions.
- Initial source read emitted excessive output due repeated exception-context matches. Switch to bounded AST function source reads.

## Frozen accepted interface
Optional `request_diagnostic` exactly schema_version/reason/field_path, versions `filing-request-diagnostic/1`; named validator only, serializers verify copy. Original six-key cause and latest discovery semantics unchanged.
