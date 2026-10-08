# R6-FF-CAUSE task plan — upstream failure cause & real invocation status (safe propagation)

Baseline: `697af966475a4aa7bb0687c78bfb81a7edb54f21` (worktrees.json published FF main).
Branch: `codex/cmrf-provider-diagnostics-20261008` in
`C:/Users/郑曾波/Projects/_harness_worktrees/cmrf-20261008/ff-diagnostics`.
Card: `C:/Users/郑曾波/Projects/company-wiki/docs/plans/cross-market-rf-e2e-2026-10-08/harness_lanes/ff_provider_diagnostics.md`.

## Goal

A named producer failure today collapses to `company-wiki ensure exited 1` +
`fatal` in the FF envelope; the machine cause that CWP *did* publish on stderr
(error-taxonomy codes) is dropped. Add ONE optional, secret-safe
`upstream_cause` diagnostic (v1 top-level, v2 inside `filing`) without changing
existing status/error_code/retryable/calls/downloads semantics or the
auto-retry scope.

## Design (fixed before coding)

1. New module `scripts/ff_provider_cause.py` (per-function McCabe <= 10,
   NEW_FILE_MAX in tests/test_complexity_ratchet.py):
   - `UPSTREAM_CAUSE_SCHEMA_VERSION = "filing-upstream-cause/1"`.
   - `diagnose_stderr(operation, stderr_text) -> (ff_code, cause_dict)` — the
     single bounded-stderr parse shared by `_classify_wiki_error` and the
     diagnostics (no duplicated JSON/error parsing across branches).
   - `condition_cause(operation, condition, *, provider_started=None,
     usage_complete=None) -> (ff_code, cause_dict)` — FF-observed producer
     conditions (start failure / deadline / output cap / transport).
   - Emitted dict is EXACTLY six keys: schema_version/operation/code/
     provider_started/usage_complete/retry_scope. No raw stderr, no exception
     text, no commands, no paths, no keys — by construction.
2. Code vocabulary (verified CWP public machine codes + FF-observed producer
   conditions + `unknown`); retry_scope from one table keyed by cause code:
   catalog_locked/catalog_busy/db_timeout -> catalog_contention;
   worker_paused / producer_deadline_exceeded / producer_output_exceeded /
   producer_transport_failure -> caller_decision; everything else -> none.
   Consistency invariant: retry_scope != "none" iff existing
   FilingFetchError.retryable stays True.
3. Honest evidence rule: `provider_started=False` / `usage_complete=True` ONLY
   when FF itself can prove no CWP subprocess ran (spawn OSError;
   deadline expired before the first attempt). `True` is never claimed in
   production (CWP's public stderr has no such field); when a producer
   subprocess actually ran both stay `null` — recorded as an interface gap for
   MAIN, not papered over.
4. `FilingFetchError(..., upstream_cause: dict | None = None)` (validated
   shape-or-None); v1 CLI adds `upstream_cause` top-level when set; v2
   `error_envelope(..., upstream_cause=...)` puts it inside `filing`.
   Success/gap envelopes unchanged (no field).
5. Retry behavior untouched: `_CATALOG_RETRY_CODES` unchanged; catalog backoff
   still shares the remaining total deadline; hard cutoff / unknown usage /
   account rejection never auto-re-requested. The deadline-exhausted-during-
   catalog-retry raise keeps the LAST contention cause code (catalog_locked/
   busy/db_timeout) with retry_scope=catalog_contention — the class is what
   the bounded auto-retry covers; the top-level code stays `upstream_error`.

## Steps

1. [x] Read card/handoff/README/root-cause docs + FF SKILL + repo layout.
2. [x] Read-only CWP interface survey (see findings.md observation table).
3. [x] This plan; findings/progress initialized.
4. [ ] RED: `tests/test_provider_cause_contract.py` — named machine cause
   (`legacy_evidence_archived`, `maintenance_operation_retired`, catalog
   codes, worker_paused) currently lost; malformed/oversized/mixed stderr and
   secret-laden payloads fail closed to unknown with zero leakage.
5. [ ] GREEN: implement `ff_provider_cause.py`, wire into
   `_run_company_wiki_json` / `_run_company_wiki_json_retry` /
   `_run_source_query`, extend `FilingFetchError` + both envelopes.
6. [ ] CLI acceptance: `tests/test_provider_diagnostics_cli.py` — v1/v2 emit
   the optional field on failure only; success golden + zero-download reuse
   trace unchanged; stats calls/downloads untouched.
7. [ ] Re-run existing suites (fetch_filing / ff_v2 / golden / source reuse /
   catalog retry / limits entries), ruff, mypy, complexity ratchet.
8. [ ] Concentrated E2E `run_isolated_cause_e2e.py` (manual big-node): real
   CWP CLI in an isolated tmp wiki; fake CN json_command_v1 provider logs
   start/HTTP/usage; broken-acquisition-config + fake-typed-failure +
   no-budget scenarios flow through the FF public CLI; legal reuse path
   verifies SourceRef bytes; tmp restored on exit; report JSON next to it.
9. [ ] HANDOFF.md + handoff.json; commit branch.

## Non-goals (card-scoped)

- No transcript_companion/transcript_tool_transport/ff_process_transport
  changes; no SKILL/config/credential/CI changes; no CWP writes (CWP read
  interface survey only); no new top-level broad `upstream_error` upgrades;
  no auto-retry expansion; canonical FF `config/FMP_API_KEY.txt` (owner WIP)
  never read into logs or committed (it is absent from this worktree).
