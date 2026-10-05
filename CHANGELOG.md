# Changelog

## Unreleased

- **Complete subprocess lifetime (MAIN P5-FF acceptance).** The deadline
  starts before spawn and covers blocked stdin, both pipes and process exit;
  equal byte limits are valid. Windows runs the actual command only after
  native job assignment; POSIX retains the session group after leader exit.
  One 2.5s cleanup grace reaps the owned tree and threads; no pywin32 runtime
  dependency, process scan or renewed per-stage deadline.
- **Legacy resource-limit compatibility.** 1.1/1.2 accept the existing optional
  `acquisition_limits`, sharing 2.0 validation and forwarding. Response and
  handle formats are unchanged; download budgets remain explicit.

- **Bounded process transport for every JSON child (P5-FF).** One shared
  module (`scripts/ff_process_transport.py`) bounds the filing runner's
  company-wiki calls and the transcript transport's ET/CWP calls: stdout and
  stderr are counted in actual read bytes DURING the read (the 32 MiB
  `MAX_JSON_OUTPUT_BYTES` cap stops the read instead of buffering an
  unbounded child first, and non-ASCII is counted as UTF-8 bytes, not Python
  chars); stderr is read concurrently with its own finite 64 KiB cap and its
  raw body is never echoed; all subprocesses share the caller's remaining
  deadline with no per-stage renewal; strict UTF-8 decode; the layer reaps
  exactly the process tree it created (Windows: a kill-on-close job object;
  POSIX: the child's own process group) so a grandchild holding the pipe
  cannot hang the caller, and no reader threads linger.
- **Worker pause-around orchestration retired (P5-FF).**
  `PausedWorkerScope`, the `filing_fetch_pause.refcount` / `.owner` files,
  the pid-liveness pruning and every `worker-status` / `worker-pause` /
  `worker-resume` subprocess are deleted; `resolve_filing()` accepts the old
  `pause_worker` / `worker_graceful_timeout_seconds` /
  `worker_resume_wait_seconds` kwargs and the CLI keeps `--no-pause-worker`
  / `--worker-*` flags as inert no-ops for existing callers (help updated;
  no new dual gate). `stats["calls"]` now counts real upstream calls only —
  the ~2 worker-status calls per download are gone, with no synthetic calls
  added to preserve the old number.
- **One download intent.** A schema `2.0` request derives its download
  decision from `filing_intent` alone; `resolve_filing()`'s `allow_download`
  becomes an optional confirmation (`None` by default), and an explicit value
  that contradicts the request raises `request_error` instead of silently
  diverging from the CLI. The CLI and the library share one derivation
  function.
- **Acquisition limits reach the producer.** `acquisition_limits` is forwarded
  on `ensure` / `close-gap` as `--max-download-bytes`, `--max-download-seconds`
  and `--max-download-cost-usd`; `max_cost_usd` is passed through unchanged.
- **Bounded execution.** The deadline shared by every company-wiki subprocess
  of a request is the smallest of the remaining global deadline, the
  configured `timeout_seconds` and the request's own `timeout_seconds`; child
  stdout is capped at one shared byte ceiling, and a non-zero exit reports its
  status and classified code only - never the stderr body (which routinely
  carries absolute paths and provider credentials).
- **Explicit, minimal install.** `tools/sync_installs_b3.py` requires
  `--install` to write and keeps `--check` read-only; the manifest is an
  allowlist (scripts, skill docs, references, the one public config template)
  that structurally excludes credentials, local `.env`, `tests/`, caches and
  run logs. The pre-push gate reports drift without touching the shared
  `.agents` / `.claude` / `.codex` skill roots.
- **SKILL.md** now documents schema `2.0` as the recommended entry point
  (bounded `fetch_if_missing`, pathless `source_ref`, companion transcript
  with exact FY/Q, `EARNINGS_TRANSCRIPTS_TOOL`), with `1.2` / `1.1` kept as
  legacy thin compatibility.
- **Worker pause-around documented as inert.** company-wiki retired its
  background worker routes (`73de6be refactor: retire legacy source catalog
  worker routes`), so `ensure --allow-download` never consults worker state
  and a paused worker can no longer produce `worker_paused`. SKILL.md and the
  isolated-wiki E2E pin that upstream contract instead of the retired
  `--no-pause-worker` escape hatch; the flag stays accepted for existing
  callers.
- **Vendored host-assumption guard compares content, not checkout bytes.**
  `.gitattributes` forces `*.py text eol=lf` on commit, but a working tree can
  still hold CRLF on disk while `git status` stays clean, so hashing raw bytes
  reported a checkout difference as a code difference. The drift check now
  folds `\r\n` to `\n` first; every real content difference still fails.

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
