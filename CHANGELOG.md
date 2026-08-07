# Changelog

## v1.4.0 — 2026-08-04

- **Worker pause-around for downloads.** `ensure --allow-download` no longer
  blocks behind the company-wiki background worker's long batches (e.g.
  `backfill_text_fingerprints` over 20k+ documents), which hold the global
  catalog `operation.lock` and previously turned every fetch into a 15-minute
  silent retry. `resolve_filing()` now wraps the download in a
  `PausedWorkerScope`: it pauses the worker (releasing the lock — the stale
  `operation.lock` is auto-reclaimed once the holder pid is dead), runs the
  download with the new company-wiki `--allow-acquisition-while-paused` opt-in,
  and resumes the worker afterwards so its pending batch continues
  (pending-driven, idempotent). A worker already stopped, or paused by the
  user, is left untouched — a user-initiated pause is never resumed.
- **Concurrency-safe.** A refcount file (`.source_catalog/filing_fetch_pause.refcount`,
  pruned by pid liveness) with an owner marker ensures concurrent fetches share
  one pause and only the last participant resumes; crashed fetches self-heal.
- **New CLI flags** (fetch_filing.py): `--no-pause-worker` (legacy behavior),
  `--worker-graceful-timeout-seconds` (default 5), `--worker-resume-wait-seconds`
  (default 5). New error codes `worker_pause_failed` / `worker_resume_failed`;
  a resume failure warns (the handle is still returned) and instructs a manual
  `worker-resume`.
- **filing_fetch_client.py** (revenue-forecast side) passes `--no-pause-worker`
  through when `pause_worker=False`; default behavior is unchanged.
- Requires company-wiki with the `ensure --allow-acquisition-while-paused`
  flag (company-wiki CHANGELOG, 2026-08-04).
- Tests: 4 new mock tests for the pause-around (pause+resume, user-paused
  respect, stopped-worker no-op, legacy `--no-pause-worker`); 97 mock tests +
  27 subtests pass. Live E2E verified against the production wiki: worker
  paused during the 06082.HK download, capture-ready handle returned, worker
  resumed and its batch continued from the same pending count.

## v1.3.0 — 2026-08-01

- Error classification aligned with the documented contract: config failures
  now carry `config_error`, identity failures `identity_error`, unreusable
  sources `not_found` (missing / ambiguous / identity_conflict / incomplete
  provenance), and contract violations `upstream_error`. The response
  `schema_version` of resolve/ensure/identity is now validated against
  `SUPPORTED_COMPANY_WIKI_CONTRACTS` (which is now a real table, not a
  frozenset) and mismatches fail closed as `upstream_error`.
- A paused company-wiki worker is now detected: the upstream
  `RuntimeError("source acquisition is paused; …")` envelope maps to
  `worker_paused` (retryable, exit 2) instead of `fatal`; it is never
  auto-retried (unlike `catalog_locked`).
- Subprocess timeouts (an attempt outliving the remaining deadline budget)
  classify as `upstream_error` instead of `fatal`.
- Request validation tightened: `company_query` is required non-empty trimmed
  text, the `market` hint must be `CN`/`HK`/`US` when provided, `fiscal_year`
  rejects floats, and the handle `request_id` must be non-empty trimmed text.
- `main()` now maps stdin / `--request-file` parse failures, non-object JSON,
  and unreadable files to `request_error` (exit 2) instead of a generic fatal.
- `exchange` hints are documented as identity-stage-only: the upstream
  `--entity` source commands silently ignore them and filing-fetch discards
  them after identify.
- Three-layer test matrix: mock contract tests (89), real-code isolated-wiki
  E2E (13 offline scenarios: reuse, missing, partial provenance, corruption,
  identity, catalog-lock retry/deadline, worker pause), and opt-in real
  download E2E (CN/US verified live; HK blocked by a dayu-agent RapidOCR
  native crash on this machine), plus a rewritten live conformance suite
  against the production wiki (incl. a production round-trip).

## v1.2.0 — 2026-07-31

- Catalog lock contention (`CatalogOperationLockedError`) is now classified as
  retryable (`catalog_locked` status instead of `fatal`). The CLI retries locked
  calls with exponential backoff (5 s, ×2) bounded by the overall
  `--timeout-seconds` deadline, so interactive fetches self-heal while the
  background worker holds the catalog lock.
- Non-lock upstream errors remain fail-closed (`fatal`, not retryable).

## v1.1.0 — 2026-07-28

- Hardened the request contract: schema 1.1 rejects unknown fields, requires
  `company_query` for every request, validates dates as YYYY-MM-DD, and forbids
  legacy explicit-entity requests that bypass identity verification.
- Added deep handle validation: required fields, path containment inside the
  company-wiki `companies/` subtree, lowercase SHA-256, HTTPS URLs, byte-size
  consistency, file content hashes, and published-date ≤ as-of-date.
- Added an overall monotonic deadline with `--timeout-seconds`; each subprocess
  only receives the remaining time.
- Structured error taxonomy (`FilingFetchError.code`) with `retryable` flag and
  machine-consumable error JSON (`error_code`, `retryable`).
- Extracted `filing_contracts.py` (version constants, error class, request/handle
  validation) from the CLI module.
- Increased test coverage from 76 % (13 tests) to 86 % (42 tests).

## v1.0.0 — 2026-07-22

- Extracted the on-demand, market-routed filing fetch out of `revenue-forecast` (`company_wiki_source.py`) into a standalone, reusable skill.
- Thin client over company-wiki's acquisition engine: identify → resolve (reuse) → ensure (download only with `--allow-download`); routing CN→StockInfo/cninfo, HK/US→dayu is owned by company-wiki.
- Fixed the unreachable CLI: added the `if __name__ == "__main__"` guard so `python scripts/fetch_filing.py` actually runs.
- Revenue-specific capture-record building (`build_revenue_source_record`) remains in revenue-forecast; this skill returns a generic capture-ready handle.
- Ported 12 fetch contracts from revenue-forecast's test suite.
