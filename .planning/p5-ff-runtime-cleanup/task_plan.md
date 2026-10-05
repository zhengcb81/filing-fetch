# P5-FF Runtime Cleanup — Task Plan

Card: `company-wiki/docs/plans/narrative-evidence-pilot-2026-09-26/harness_lanes/p5_ff_runtime_simplification.md`
Base: `origin/main` @ `d4d2fac` (matches card HEAD `d4d2fac4…`)
Branch: `codex/p5-ff-runtime-cleanup`
Worktree: `C:/Users/郑曾波/Projects/cwp-lanes-20261005/ff-runtime-cleanup`

## Goal

1. Retire old worker orchestration in `scripts/fetch_filing.py`
   (`PausedWorkerScope`, pause refcount/owner files, worker-status/pause/resume
   subprocess calls). CWP old-Worker create/start is retired; downloads no
   longer depend on background state.
2. Build one truly bounded JSON process layer shared by both runner call
   surfaces (filing JSON runner + transcript JSON runner), replacing
   `subprocess.run(capture_output=True)`-then-truncate with counting
   read-time byte caps on stdout/stderr, shared deadline, and full cleanup of
   processes/pipes this call created.

## Non-goals / constraints (from card)

- Do NOT change wire schemas, goldens, provider routing, investment validators.
- Do NOT touch CWP/ET/RF/StockWiki/Dayu, real config/raw data, global installs.
- `--no-pause-worker` / worker-timeout args become compat no-ops; no new dual gate.
- Keep SourceRef 2.0 auto-selection as is; `--source-ref-v2` still accepted.
- stats count real upstream calls only; no invented calls to keep old numbers.
- stdout counted in actual bytes DURING read; stop at 32 MiB, not after.
- stderr also capped + read concurrently; no secrets echoed.
- Shared remaining deadline for requests; ET 3s outer cleanup grace stays.
- Windows: reap only self-created process tree (existing repo pattern or OS
  primitives); POSIX: separate session/group. No scanning/killing others.

## Steps

1. [x] Create worktree + branch from origin/main d4d2fac.
2. [ ] Survey: map `PausedWorkerScope` usage, pause file writes, worker
       status/pause/resume call sites, unused worker args.
3. [ ] RED tests: `test_p5_worker_scope_retirement.py` (no worker-* calls,
       no pause refcount/owner writes on resolve/reuse/download paths),
       `test_p5_process_transport.py` (byte cap during read, non-ASCII counted
       in UTF-8 bytes, capped stderr, grandchild-holding-pipe reap, deadline).
4. [ ] Delete scope/refcount/owner/PID maintenance; compat-no-op flags.
5. [ ] Implement `ff_process_transport.py` thin bounded-process module;
       both runners reuse it; preserve error taxonomy + stats.
6. [ ] Update existing tests that referenced pause scope behavior; migrate
       worker-specific tests to "no old calls/writes" assertions.
7. [ ] Isolated E2E: reuse + fake-provider download; verify 0 worker calls,
       0 pause writes, hashes/counts correct, overflow/timeout cleanup.
8. [ ] Full fast gate; commit; push codex branch.
9. [ ] Handoff `docs/implementation/handoffs/P5-FF/HANDOFF.md` + handoff.json.
