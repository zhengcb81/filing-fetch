id: p5-ff-runtime-cleanup
card_file: company-wiki/docs/plans/narrative-evidence-pilot-2026-09-26/harness_lanes/p5_ff_runtime_simplification.md
created: "2026-10-05"
status: in_progress
branch: codex/p5-ff-runtime-cleanup
base_sha: d4d2fac4c690bfb8b1368d2ca140fd75150fd288
worktree: C:/Users/郑曾波/Projects/cwp-lanes-20261005/ff-runtime-cleanup

## 2026-10-05

- Created worktree + PWF scaffold.
- Surveyed `fetch_filing.py` (1896 lines) + `transcript_tool_transport.py` (581 lines):
  - `PausedWorkerScope` at L561; pause refcount/owner at L505-507, L538-558;
    `_pid_is_alive` L514; scope sites L1095-1103, L1152-1160, L1581-1592.
- Total-package plan read (p5_parallel_packages_2026-10-05.md): confirmed
  handoff.json schema `cwp-parallel-handoff/2`, per-lane `.planning/` only,
  no cross-repo writes, summary table uses actual counts (no placeholder 0s).
- Baseline full suite on clean base `d4d2fac`: 455 passed / 10 failed /
  14 skipped (173s). Pre-existing failures all reference pause/worker
  semantics this card retires (worker-paused + catalog-lock contention in
  `test_e2e_isolated_wiki.py`, LT-* in `test_fc803_minimal_download.py`) —
  to be reworked per card §4.3.
