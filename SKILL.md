---
name: filing-fetch
description: Fetch a company financial filing into company-wiki on demand. Reuses an existing filing if one is already indexed; otherwise, only when explicitly authorized, downloads via the correct market tool — A-shares (CN) via StockInfoDLSimple/cninfo, HK and US via dayu-agent — and stores the new file under company-wiki's companies/{entity}/raw/financial_reports/{kind}/ with immutable provenance. Use when any skill (revenue-forecast, invest-*, industry-research) needs an annual/quarterly/semi-annual report or regulatory filing and must not blindly re-download.
---
# Filing Fetch

v1.4.0 — on-demand, market-routed fetch of a company financial filing into the
shared `company-wiki` catalog, with **reuse-first** semantics so the same
filing is never downloaded twice.

## Required workflow

1. **Validate request** — schema 1.1 rejects unknown fields, requires
   `company_query` (legacy explicit-entity requests are forbidden), and
   validates dates as `YYYY-MM-DD`.
2. **Identify** the company (fuzzy name / brand / ticker) to **one verified,
   active security** with a canonical `market` + `security_id`.
3. **Resolve (reuse)** — query company-wiki for an already-indexed, capture-ready
   filing. If found, validate the handle and return it — no download.
4. **Pause around downloads (worker)** — before an authorized download, the
   company-wiki background worker is paused if it is running and enabled. The
   worker's long batches (e.g. `backfill_text_fingerprints` over 20k+ documents)
   hold the global catalog `operation.lock`, which would otherwise block the
   download until a 900-second retry deadline; pausing releases the lock and the
   stale lock is auto-reclaimed. After the download the worker is resumed so its
   pending batch continues (batches are pending-driven and idempotent). A worker
   that is already stopped, or paused by the user, is left untouched — a
   user-initiated pause is **never** resumed. Pass `--no-pause-worker` for the
   legacy behavior.
5. **Ensure (download) — only with `--allow-download`** — if missing and
   authorized, company-wiki routes by market. New bytes are written into
   `companies/{entity}/raw/financial_reports/{annual|semi_annual|quarterly}/`
   (kind-to-subdirectory mapping; other kinds use their own subdirectory) with
   a `<file>.source.json` provenance sidecar. The download runs with the
   company-wiki `--allow-acquisition-while-paused` opt-in so the deliberate
   pause-around does not trip the paused-acquisition guard.
6. **Validate handle** — before returning, the handle is deeply validated:
   required fields, path containment inside `companies/`, lowercase SHA-256,
   HTTPS URL, byte-size consistency, file content hash, published-date ≤
   as-of-date.

## Hard failure gates

- Unknown request fields are rejected (callers cannot silently depend on
  ineffective modifiers).
- An explicit `entity`/`security_id` without `company_query` is rejected —
  every request must go through verified-active identity.
- `capture_ready` without every required field (canonical_path, snapshot_sha256,
  https_url, published_date, provider, …) is rejected.
- A handle whose `canonical_path` escapes the `companies/` subtree, whose
  SHA-256 does not match the canonical file, whose URL is not HTTPS, or whose
  `published_date` is after the request `as_of_date` is rejected.
- The overall deadline is enforced with `--timeout-seconds`; each subprocess
  only receives the remaining time.
- Unknown upstream response schemas, non-JSON stdout, or non-object responses
  fail closed.

## Command

Read the request from stdin (or `--request-file`). Default is **read-only
reuse**; add `--allow-download` only when a missing filing should actually be
fetched.  Use `--timeout-seconds` to set an overall deadline (default 900).
Downloads pause the company-wiki background worker around the fetch and resume
it afterwards; `--no-pause-worker` restores the legacy behavior (downloads can
then be blocked by the worker's catalog lock for up to the deadline).
`--worker-graceful-timeout-seconds` (default 5) is the graceful stop window
before `worker-pause` force-kills, and `--worker-resume-wait-seconds` (default 5)
is how long `worker-resume` waits for the worker to come back.
Add `--debug` to include the per-candidate exclusion trace in a `not_found`
error response (see Notes).

```bash
# Reuse-only: returns the handle if the filing exists, else exit 2.
echo '{"schema_version":"1.1","company_query":"AMD","document_kind":"annual_report","fiscal_year":2025,"as_of_date":"2026-07-18"}' \
  | python scripts/fetch_filing.py --timeout-seconds 300

# Authorized download:
echo '{"schema_version":"1.1","company_query":"贵州茅台","market":"CN","document_kind":"annual_report","fiscal_year":2024,"as_of_date":"2026-07-18"}' \
  | python scripts/fetch_filing.py --allow-download --timeout-seconds 600
```

### Request (schema 1.1)

Precise fields. Unknown fields are rejected.

| Field | Required | Notes |
|---|---|---|
| `schema_version` | yes | Must be `"1.1"` |
| `company_query` | yes | Fuzzy name / brand / ticker; `entity` + `security_id` are *forbidden* |
| `document_kind` | yes | `annual_report`, `semi_annual_report`, `quarterly_report`, … |
| `as_of_date` | yes | `YYYY-MM-DD` |
| `fiscal_year` | no | Integer (reject bool) |
| `market` | no | Hint only — must be `CN`/`HK`/`US` if provided; does not override verified identity |
| `exchange` | no | Hint only — used during the identity stage; silently ignored by the upstream `--entity` source commands and discarded by filing-fetch |
| `form_type` | no | |
| `fiscal_period` | no | |
| `language` | no | |
| `provider` | no | |
| `provider_document_id` | no | |

### Response (schema 1.1)

Success: `{schema_version:"1.1", status:"capture_ready", handle:{…}}`

Error: `{schema_version:"1.1", status:"<code>", error:"…", error_code:"<code>", retryable:bool}` (an `identity_error` for an ambiguous query also includes `candidates[]` and a `hint`)

| Status code | Meaning | Retryable |
|---|---|---|
| `capture_ready` | Filing found / reused | — |
| `request_error` | Invalid request | no |
| `config_error` | Config missing / invalid | no |
| `identity_error` | Ambiguous or inactive identity. When ambiguous, the response also carries `candidates[]` (`ticker` / `canonical_name` / `market` / `exchange`) and a `hint` — disambiguate by adding `market`/`exchange` or using a specific ticker in `company_query` | no |
| `not_found` | No matching filing | no |
| `upstream_error` | company-wiki subprocess failure (including deadline exhaustion) | yes |
| `catalog_locked` | company-wiki catalog locked by another operation; auto-retried with backoff until the deadline | yes |
| `worker_paused` | downloads blocked because the company-wiki worker is paused — resume the worker, then retry | yes |
| `fatal` | Unexpected error | no |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | capture-ready |
| 2 | **every** structured error — `request_error`, `config_error`, `identity_error`, `not_found`, `upstream_error`, `catalog_locked` (deadline exhausted), `worker_paused` |
| 1 | only an unexpected, non-`FilingFetchError` exception |

## Owner / trust boundary

- **Identity, catalog lookup, market routing, download, dedup, and canonical
  write** are owned by `company-wiki`'s source catalog.
- **Cross-skill request, authorization, upstream schema compatibility, and
  handle validation** are owned by `filing-fetch`.
- **Consumer-specific source/capture records** (e.g. revenue-forecast) are
  owned by the consuming skill — they call `filing-fetch` and convert the
  returned handle.

## Notes

- **Read-only reuse is config-driven (ADR-008 Strategy B)**: any root kind
  listed in company-wiki's `reusable_root_kinds` (`source_catalog.yaml`)
  serves its already-indexed documents directly — e.g. `dayu_portfolio`
  reuses filings dayu already downloaded, zero download.  Adding a root =
  one line in company-wiki's `source_catalog.yaml`, no code and no
  filing-fetch config change (FC-501/FC-1202: the RootPolicySnapshot is the
  single policy source; filing-fetch's `config/company_wiki.json` only
  locates the company-wiki root).
- By default, filing-fetch **pauses the background worker itself** around
  downloads and resumes it afterwards, so a worker mid-batch no longer blocks
  fetches. Only with `--no-pause-worker` are downloads blocked while the worker
  is paused (legacy behavior) — resume it first in that case.
- `worker_pause_failed` / `worker_resume_failed` error codes surface pause /
  resume failures; a resume failure never loses the download (the handle is
  returned) but leaves the worker paused — resume it manually.
- An ambiguous **identity** (multiple candidate securities, e.g. dual-class
  tickers GOOGL/GOOG) never auto-picks; the response lists `candidates[]` —
  refine `company_query` to a specific ticker or add `market`/`exchange`, then
  re-run. An ambiguous **filing** (one identity, several documents) is resolved
  with `fiscal_year` / `form_type`.
- `--debug` adds a `debug_trace` to a `not_found` error response: the
  per-candidate exclusion reasons (entity-gate count, identity / year / form /
  capture steps) from company-wiki's resolve step, so a miss explains itself.
- Consuming skills convert the returned handle into their own capture schema
  (e.g., revenue-forecast builds its revenue source record from it).
- Language: Python; request: JSON stdin or `--request-file`; response: JSON stdout.
- **Indexed ≠ reusable**: a catalog document being indexed (scanned,
  parsed, fingerprinted) does not make it a reuse handle.  Only active,
  capture-ready documents under a registered reusable root kind are
  reused; everything else fails closed (`not_found` with a debug trace).
- **exact vs latest**: an `exact` resolve matches identity+kind+period
  deterministically; `latest_as_of` picks the most recent published
  handle not after `as_of_date` (ties broken by provider_document_id,
  never file mtime).  These are distinct resolution modes — a latest
  match is never presented as an exact one.
- **Artifact invalidation**: derived artifacts (normalized/summary) are
  reusable only when their source hash and producer binding still match
  the original document; a changed producer or document hash invalidates
  only the dependent roles and schedules a minimal recompute — the
  original bytes are never rewritten by a reuse path.
- **Real-root canary limits**: read-only probes and canaries never write
  to real roots (Dropbox/dayu/companies).  Production reuse of
  Dropbox-only filings and binding-valid processed artifacts is NOT yet
  proven: legacy evidence lacks strong identity/period/binding (see the
  data-lake refactor audit receipts WU-1303/902/1304).  Fixture-level
  E2E stays green; production claims stay unclaimed until the
  observation period and remediation windows complete.
