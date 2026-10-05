# P5-FF MAIN acceptance (2026-10-05)

State: local responsibility tests and offline E2E GREEN; normal commit/push and exact Ubuntu CI pending.
Producer CWP: 1b0feb44ff1695a8bae761eac538ce68236c04d6 (PWF head 3fe77ae).
ET: 63c4090. Original delivery: ab9ce33 / code 7c6cf48. MAIN worktree:
C:/Users/郑曾波/Projects/cwp-lanes-20261005/ff-main-integration.

## Actual corrections

- Native standard-library Windows Job, waiting bootstrap assigned before releasing user command.
  Explicit stdin/stdout/stderr handles are passed to the child; inherited defaults lost output
  in the initial experiment. No pywin32 production dependency or taskkill snapshot fallback.
- POSIX starts one session and retains its PGID even after the leader exits.
- One deadline starts before spawn and covers stdin writing, both pipe reads, and process exit.
  Equal cap permits EOF; cap+1 raises immediately. Failures stop the owned tree before joining
  threads. Cleanup has one 2.5s total grace. 32MiB/64KiB and ET's outer 3s stay unchanged.
- Nonzero exit retains actual output for caller error classification. Messages never echo payloads.
- 1.1/1.2 requests now accept the EXISTING optional acquisition_limits object, validated by
  the same code as 2.0. This additive input compatibility fixes the inability to supply
  mandatory upstream resource limits; no default ceilings are guessed. Existing response,
  handle, wire versions and v2 reuse-only rules remain unchanged.
- Offline spy/noop adapters now declare bounded support and return usage matching simulated
  bytes; spy rejects oversize before staging. The production CWP enforcement was not weakened.
- Two stale identity assertions referred to a nonexistent _run_bounded alias; they now prove
  both actual _run_bounded_json entries are the shared implementation.

## Test evidence (not one whole-suite claim)

- New lifecycle TDD: 14 RED / 5 pass, 33.81s.
- First combined implementation: 18 failed / 19 passed, 77.56s; then 37 passed, 11.08s.
- Baseline download failures reproduced: 10 failed, 43.50s.
- Fixture-only limits first attempt: 10 failed, 19.92s (legacy validator rejected the field).
- Legacy validator TDD: 8 RED, 0.12s.
- Node: 45 passed / 8 failed, 84.83s; remaining scope 10 passed / 35 deselected, 57.17s.
  Together all 53 distinct node cases GREEN, including 23 lifecycle / 8 legacy budget cases.
  This is NOT a single 53-case all-green run. The earlier 37-case process/Worker package
  is separate; tests overlap and should not be summed as unique.
- Ruff and public-contract mypy GREEN.
- Formal FF -> ET -> CWP offline acceptance GREEN (real production code, fake provider HTTP):
  exact FY/Q, unchanged golden, raw JSON and untranslated text SHA/size, one initial provider
  call, duplicate zero provider, deadline result and ET worker scratch cleanup.
- Fixed actual AMEC FY2025 PDF: 9,165,875B,
  d64c410832f22f5127277bad6dc357c664aede523561af99150c494857fd3aa5.
  Real FF 2.0 reuse twice returns source_candidate/pending_verified_open. CWP public
  source_reader_cli returns EXACT original bytes and matching SHA/size receipt.
  Identity/period/publication sidecar is a labelled fixture, not verified live metadata.

## Reproduce concentrated checks

    python -m pytest tests/test_p5_process_lifecycle.py tests/test_p5_process_transport.py tests/test_p5_worker_scope_retirement.py tests/test_p5_legacy_request_limits.py -q

With PYTHONPATH pointing to current company-wiki/src and TEMP/TMP inside an independent root:

    python -m pytest tests/test_fc803_minimal_download.py tests/test_e2e_isolated_wiki.py -q
    python -B e2e/run_p5_ff_real_source_acceptance.py --raw-file <original-pdf> --scratch-root <existing-empty-independent-root>

From company-wiki (manual, not added to daily CI):

    python -B tests/e2e/run_ff_et_cwp_offline_acceptance.py --ff-root <this-worktree> --et-root <ET-owner-root>

Normal CI remains one Ubuntu job and one focused suite. Only the short lifecycle and legacy
budget tests are added there to verify the actual POSIX process-group branch. No Windows
matrix, full historical download suite, daily real-PDF copying, model or provider network.

## Protection and remaining publication

All ffmred/green/green2/base/basegreen/final/fix/e2e/real scratch roots restored absent.
No production raw/config/catalog changes, no external provider, translation or LLM call.
Original owner dirty test is identical to the committed delivery; FMP_API_KEY.txt unread.
Dayu/RF/ET/StockWiki owner files and delivery-tree history untouched.
Exact CI status/SHA and published main belong in CWP MAIN receipt after normal publication.

