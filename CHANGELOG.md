# Changelog

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
