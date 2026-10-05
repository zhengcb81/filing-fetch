id: p5-ff-runtime-cleanup
card_file: company-wiki/docs/plans/narrative-evidence-pilot-2026-09-26/harness_lanes/p5_ff_runtime_simplification.md
created: "2026-10-05"
status: complete
branch: codex/p5-ff-runtime-cleanup
base_sha: d4d2fac4c690bfb8b1368d2ca140fd75150fd288
worktree: C:/Users/郑曾波/Projects/cwp-lanes-20261005/ff-runtime-cleanup
delivery_head: 5a5006e (handoff doc commit; feature commit 7c6cf48c5aa890fe34cb8304830246d4c20f16fa)
handoff_doc: docs/implementation/handoffs/P5-FF/HANDOFF.md + handoff.json (committed 5a5006e)
pushed: origin/codex/p5-ff-runtime-cleanup

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

## 2026-10-05 (final)

- Both gaps retired (commit 7c6cf48):
  1. PausedWorkerScope / refcount / owner / all worker-status/pause/resume
     subprocesses deleted; old pause kwargs + --no-pause-worker / --worker-*
     flags kept as inert no-ops; stats count real calls only.
  2. Shared bounded transport `scripts/ff_process_transport.py`: stdout cap
     32 MiB counted DURING read (UTF-8 bytes), concurrent capped stderr
     (64 KiB), shared monotonic deadline, strict UTF-8, tree reaping
     (Windows kill-on-close job object — verified vs live grandchild
     holding the pipe; POSIX setsid+killpg); complexity max 8.
- Both runners route through the layer; taxonomy preserved (ChildFailed
  carries stdio chunks for classification without echoing them).
- Mock surfaces migrated (test_fetch_filing/fc802/s3/db_query/transcript);
  tests/support CompletedProcess adapter added.
- Final suite: 463 pass / 10 fail / 14 skip. The 10 failures are
  baseline-red on clean d4d2fac — root cause upstream CWP 288b028
  ("enforce source acquisition budgets") rejects ensure --allow-download
  without --max-download-* flags; recorded in handoff.remaining for MAIN.
- pre_push_gate GREEN. Commits: 7c6cf48 (feature), b5c1c82 (PWF),
  5a5006e (handoff). Pushed to origin/codex/p5-ff-runtime-cleanup.
