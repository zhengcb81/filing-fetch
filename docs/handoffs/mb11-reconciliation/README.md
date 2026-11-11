# MB11: accept the B34 logical candidate correction

2026-11-11 ROOT reconciliation. Base: f65e6ca75fbce0616e65870f0aea78b793ef883c. Source delivery: 53285c259b0f0c9ede3f74783f45b6f3a38287b9. This is a selective intake; no old branch tree replaces current main.

Explicit unknown publication dates remain `null` on logical SourceRef candidates. This does not read source bytes, manufacture availability, or replace CWP's verified-open. Missing/malformed/future dates retain their existing semantics. Current period, source market and issuer binding continue after metadata validation.

The baseline rejected the valid unknown-date candidate (`upstream_error`, YYYY-MM-DD required). The candidate passed the existing focused suite: 176 passed, 2 existing skips, 38 subtests (15.24 s). After adding four current period/market/issuer controls, the final B34 suite passed 23 tests (0.50 s). Tests use synthetic inputs, mocked transport and an isolated temporary root. No original or production config changes, provider calls or model calls.

Independent static review: PASS, no blocking findings; see ff_merge_review.md. This proves the intake scope, not the pending MB-FF installed-runtime/operation-isolation plan. The initial test attempt had an absent basetemp parent; it is an environment setup failure, fixed before the successful run.

The older ff-job prototype is already superseded by main 57351d0 and 7d8392e; do not re-merge it. Remaining MB-FF tasks stay in company-wiki/docs/plans/module-boundaries-2026-11-11/harness_lanes/MB-FF.md.

CI integration follow-up: the new B34 regression file is now included in the existing explicit CI_TESTS inventory, with the inventory contract test covering its presence. The fixed daily smoke is unchanged. CI-inventory plus B34 verification: 38 passed in 1.25 s. A first scratch run under the neighboring CWP checkout inherited that repository's pytest root and changed JUnit class prefixes; using a fresh outside-repository temporary directory corrected the harness without weakening assertions.
