# R6-FF-CAUSE findings — CWP public interface observations

Survey date: 2026-10-08. Method: read-only `rg`/read of canonical
`C:/Users/郑曾波/Projects/company-wiki` at the lane baseline era (no writes,
canonical owner WIP untouched). FF side read at worktree baseline
`697af966475a4aa7bb0687c78bfb81a7edb54f21`.

## Observation table — what CWP actually publishes on failure

| # | Public surface (file) | Shape | Machine fields | provider_started? | usage? | Notes |
|---|---|---|---|---|---|---|
| 1 | `src/company_wiki/source_catalog/cli.py` main() catch-all (line ~1358) | stderr JSON `{status:"failed", error_type, error, retryable}` via `error_taxonomy.structured_error`, exit 1 | `error_type` ∈ {catalog_busy, catalog_locked, db_timeout, worker_paused, legacy_evidence_archived, fatal}; `retryable` bool | NO | NO | error-taxonomy-1.1 / version 1.1. `error` is raw `str(exc)` — unsafe to propagate (may carry paths/keys). |
| 2 | Retired maintenance commands (cli.py ~803) | stderr JSON `{status:"failed", error_type:"maintenance_operation_retired", error_code, operation, error, retryable:false}` | `error_type` + short `error_code`/`operation` | NO | NO | Only reachable via those command names; FF never issues them today. |
| 3 | N-1 pre-taxonomy emission | `error_type` = exception class name (e.g. `CatalogOperationLockedError`, `RuntimeError`) | class-name family only | NO | NO | FF `_classify_wiki_error` already maps these; cause layer keeps the same limited mapping. |
| 4 | `error_taxonomy.classify_exception` | internal | text-marker fallback: "timeout"/"timed out" → db_timeout, "paused" → worker_paused, else fatal | — | — | Provider HTTP text containing "timeout" lands in db_timeout today (existing behavior, unchanged by this lane). |
| 5 | Adapter process bridge `adapter_process.py` (`AdapterProcessError`) | in-process only | `error_code`, `retryable`, `acquisition_usage`, `acquisition_usage_complete` parsed from the adapter's structured 1.0 stderr | YES (adapter level) | YES (usage dict + completeness) | **Does NOT cross the CLI boundary**: `SourceAcquisitionService._ensure` re-raises; cli.py catch-all re-serializes through the 6-code taxonomy, so adapter machine codes/usage are lost. Journal keeps `error_type=type(exc).__name__` internally only. |
| 6 | Success/gap path stdout (`_plain(result)` + `project_operation_result`) | `{operation_schema_version, operation, status, request_id, outcome, download_events, policy_hash, source_ref, candidate, gap_plan}` | — | — | `download_events` (0/1) | Not a failure surface; FF validates this contract already. |

## Conclusions driving the design

1. The only machine cause CWP publishes on the failing boundary is the
   error-taxonomy `error_type` (6 codes). FF's `upstream_cause.code`
   vocabulary is therefore: those verified codes (catalog_locked,
   catalog_busy, db_timeout, worker_paused, legacy_evidence_archived,
   maintenance_operation_retired, fatal) + FF-observed producer conditions
   (producer_start_failed / producer_deadline_exceeded /
   producer_output_exceeded / producer_transport_failure) + `unknown`.
2. Account/HTTP rejection, entitlement denial, budget exhaustion and
   post-download verification failure are NOT distinguishable machine-side
   today (they arrive as `fatal` + raw text). They must surface as
   code=fatal/unknown with provider_started=null, usage_complete=null —
   honest unknown, no guessing from message text (card rule: 禁止直接复制
   未验证message字符串).
3. provider_started / usage_complete never appear in public failure
   emissions → null whenever a producer subprocess ran. FF-provable
   no-start (spawn OSError; deadline gone before first attempt) is the only
   evidence-backed False/True pair (provider_started=False,
   usage_complete=True — usage is final at zero because nothing ran).

## Interface gaps for MAIN (this lane does NOT cross-write CWP)

- G1: error-taxonomy stderr carries no `provider_started` / `usage_complete`.
  A future error-taxonomy-1.2 adding both (bool, fail-closed unknown on
  malformed) would let FF fill them honestly; FF's parser/mapping table is
  the single place to extend.
- G2: adapter-level machine codes (`AdapterProcessError.error_code`, e.g.
  `upstream_unavailable`), `acquisition_usage` and `acquisition_usage_complete`
  are dropped at the CLI boundary (finding #5). Surfacing a bounded, safe
  subset (or the journal's `error_type` class name mapped to a named safe
  code) is CWP-side work; FF will map only codes CWP actually publishes.
- G3: no named public code separates account/entitlement rejection vs budget
  ceiling vs post-download verification failure; the card's category
  distinction is therefore implemented as unknown + no auto-retry, with the
  category list handed to MAIN for the taxonomy extension.

## FF-side facts (baseline)

- `scripts/fetch_filing.py::_run_company_wiki_json` / `_classify_wiki_error`
  / `_run_company_wiki_json_retry` / `_run_source_query` are the four
  attachment points; `FilingFetchError` (filing_contracts.py) already carries
  stage/attempts/resolution_trace — upstream_cause follows the same pattern.
- v2 error serialization: `ff_v2_envelope.error_envelope` (filing dict is the
  documented place for the optional field per card).
- Auto-retry set `_CATALOG_RETRY_CODES` = {catalog_locked, catalog_busy,
  db_timeout} with jittered backoff sharing the remaining deadline — must
  stay byte-identical in behavior.
- Complexity ratchet: fetch_filing.py frozen 34 (now 32), filing_contracts.py
  39 (now 39 — headroom only in small functions), ff_v2_envelope.py under
  NEW_FILE rule? No — ratchet's FROZEN_MAX covers the two; other files in
  scripts/ must stay <= 10 per function (NEW_FILE_MAX applies to all
  non-frozen files), so the new module is written to that budget.
- Canonical FF `config/FMP_API_KEY.txt` is owner WIP: absent in this worktree
  (verified `git status` clean; `ls config/` → company_wiki.json only);
  never read, never committed.

## RED/GREEN log

### RED (baseline `697af96`, before implementation)

- `python -m pytest tests/test_provider_cause_contract.py -q` → **24 failed, 2 passed**.
  Mechanisms: named machine causes (`legacy_evidence_archived`,
  `maintenance_operation_retired`, catalog codes, `worker_paused`,
  `CatalogOperationLockedError`, `RuntimeError+paused`) raised
  `AttributeError: 'FilingFetchError' object has no attribute
  'upstream_cause'` — the machine cause CWP published on stderr was dropped
  after classification; malformed/mixed/oversized stderr and secret-laden
  payloads had no pinned fail-closed/no-leak contract;
  `import ff_provider_cause` → ModuleNotFoundError (parser absent).
- `python -m pytest tests/test_provider_diagnostics_cli.py -q` → **5 failed, 5 passed**.
  Mechanisms: v1/v2 failure envelopes lacked `upstream_cause` (KeyError);
  `FilingFetchError(..., upstream_cause=...)` → TypeError (no kwarg);
  the real-subprocess CLI tests showed no diagnostic on a named structured
  failure or an unstructured traceback. The 5 passing cases document the
  compat side: success/gap envelopes, no-cause failures and config errors
  already behave and must stay unchanged.

### GREEN (after implementation, worktree branch)

- `python -m pytest tests/test_provider_cause_contract.py tests/test_provider_diagnostics_cli.py -q`
  → **36 passed** (~2.5 s).
- Full offline suite
  `python -m pytest tests/ --ignore=tests/test_e2e_download.py --ignore=tests/test_e2e_isolated_wiki.py --ignore=tests/test_fc805_real_download_t3.py --ignore=tests/test_real_tool_conformance.py -q`
  → **552 passed, 6 skipped, 78 subtests passed** (~91 s).
- Offline gated suites that DO run locally:
  `python -m pytest tests/test_e2e_isolated_wiki.py tests/test_real_tool_conformance.py -q`
  → **21 passed, 1 skipped** (~56 s; the skip is the production-catalog
  availability gate, pre-existing).
- Static gates: `ruff check scripts tests` → clean;
  `python -m mypy scripts/filing_contracts.py scripts/fetch_filing.py` → clean;
  `python -m pytest tests/test_complexity_ratchet.py -q` → 2 passed
  (ff_provider_cause.py initially measured 12 on `validated_cause`; split a
  header validator helper to stay ≤ 10 — fixed by refactor, not by moving
  the ratchet).
- Network/real-download gates (`FILING_FETCH_E2E_DOWNLOAD=1` suites) NOT run:
  out of scope for an offline lane node (recorded as NOT_RUN in handoff).

### E2E evidence (concentrated node, offline)

`python docs/implementation/cmrf-provider-diagnostics-20261008/run_isolated_cause_e2e.py`
→ **PASS**, 25/25 checks (A 6/6, B 7/7, C1 5/5, C2 7/7); temp root removed
on exit (`--keep` available). Key honest-null cross-check (scenario B): the
fake provider logged `provider_started` + an HTTP 503 attempt, while the FF
envelope correctly kept `provider_started: null, usage_complete: null`
because CWP's public stderr taxonomy publishes no such fields (gaps G1/G2) —
production output never guesses what only the test report can prove.

### Documented behavior decisions

- Deadline exhausted during catalog-contention retry keeps the LAST catalog
  cause code with `retry_scope=catalog_contention` (the class the bounded
  auto-retry covers); top-level code stays `upstream_error`, attempts carries
  the real attempt count, and no re-request happens after the hard cutoff
  (verified: exactly one producer call in the exhaustion test).
- One pre-existing divergence kept as-is: `_run_source_query`'s OSError keeps
  historical `upstream_error` (retryable=true) while its diagnostic honestly
  records `producer_start_failed` with `provider_started=false,
  usage_complete=true` and `retry_scope=none` — the only retryable start
  failure; changing its code was out of scope (semantic freeze).
- The stderr size guard applies AFTER the callers' existing `.strip()`
  (leading whitespace is meaningless); a trim-insensitive >64 KiB valid-JSON
  payload stays unknown (tested with a 70 KB `error` string).
