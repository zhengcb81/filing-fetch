---
name: filing-fetch
description: Fetch a company financial filing into company-wiki on demand. Reuses an existing filing if one is already indexed; otherwise, only when explicitly authorized, downloads via the correct market tool — A-shares (CN) via StockInfoDLSimple/cninfo, HK and US via dayu-agent — and stores the new file under company-wiki's companies/{entity}/raw/ with immutable provenance. Use when any skill (revenue-forecast, invest-*, industry-research) needs an annual/quarterly/semi-annual report or regulatory filing and must not blindly re-download.
---
# Filing Fetch

v1.1.0 — on-demand, market-routed fetch of a company financial filing into the
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
4. **Ensure (download) — only with `--allow-download`** — if missing and
   authorized, company-wiki routes by market. New bytes are written into
   `companies/{entity}/raw/{kind}/` with a `.source.json` provenance sidecar.
5. **Validate handle** — before returning, the handle is deeply validated:
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
| `market` | no | Hint only — does not override verified identity |
| `exchange` | no | Hint only |
| `form_type` | no | |
| `fiscal_period` | no | |
| `language` | no | |
| `provider` | no | |
| `provider_document_id` | no | |

### Response (schema 1.1)

Success: `{schema_version:"1.1", status:"capture_ready", handle:{…}}`

Error: `{schema_version:"1.1", status:"<code>", error:"…", error_code:"<code>", retryable:bool}`

| Status code | Meaning | Retryable |
|---|---|---|
| `capture_ready` | Filing found / reused | — |
| `request_error` | Invalid request | no |
| `config_error` | Config missing / invalid | no |
| `identity_error` | Ambiguous / inactive identity | no |
| `not_found` | No matching filing | no |
| `upstream_error` | company-wiki subprocess failure | yes |
| `catalog_locked` | company-wiki catalog locked by another operation; auto-retried with backoff | yes |
| `fatal` | Unexpected error | no |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | capture-ready |
| 2 | request / identity / not-found / config error |
| 1 | fatal |

## Owner / trust boundary

- **Identity, catalog lookup, market routing, download, dedup, and canonical
  write** are owned by `company-wiki`'s source catalog.
- **Cross-skill request, authorization, upstream schema compatibility, and
  handle validation** are owned by `filing-fetch`.
- **Consumer-specific source/capture records** (e.g. revenue-forecast) are
  owned by the consuming skill — they call `filing-fetch` and convert the
  returned handle.

## Notes

- Downloads are blocked while the company-wiki worker is **paused** — resume it first.
- An ambiguous request (multiple filings match) never auto-picks; refine
  `fiscal_year` / `form_type`.
- Consuming skills convert the returned handle into their own capture schema
  (e.g., revenue-forecast builds its revenue source record from it).
- Language: Python; request: JSON stdin or `--request-file`; response: JSON stdout.
