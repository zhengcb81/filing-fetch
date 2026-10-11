# ROOT tool acceptance — 2026-10-11

The manual offline-contract tool is accepted: 195 focused tests and 28 independent
fixed-input probes pass. CaseSpec/RunSpec drive coverage, complete requests,
fixtures, expectations and response validation. Old failures and SHA bindings
remain. This tooling is not installed as a user skill or run on every commit.

The actual unchanged 41-case product replay is **40 PASS / 1 FAIL**, 164.62 seconds.
The remaining case is `call_past_cutoff`: ET safely excludes the future call but
collapses its reason into `not_found`, then FF maps it to provider unavailability.
ROOT owns a separate common result-boundary repair. This commit does not certify
all 41 cases, real supplier reachability, fees, or the full mother PWF.

Full evidence: company-wiki/docs/plans/cross-market-rf-e2e-2026-10-08/phase6/
w06_parallel_verification_2026-10-11/evidence/root-ff-matrix-acceptance/
independent-case-authority-final and root-matrix-replay.
