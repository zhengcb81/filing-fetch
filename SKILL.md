---
name: filing-fetch
description: Fetch a company financial filing into company-wiki on demand. Reuses an existing filing if one is already indexed; otherwise, only when explicitly authorized, downloads via the correct market tool — A-shares (CN) via StockInfoDLSimple/cninfo, HK and US via dayu-agent — and stores the new file under company-wiki's companies/{entity}/raw/ with immutable provenance. Use when any skill (revenue-forecast, invest-*, industry-research) needs an annual/quarterly/semi-annual report or regulatory filing and must not blindly re-download.
---

# Filing Fetch

On-demand, market-routed fetch of a company financial filing into the shared
`company-wiki` catalog, with **reuse-first** semantics so the same filing is
never downloaded twice.

## What it does

1. **Identify** the company (fuzzy name / brand / ticker) to one verified,
   active security with a canonical `market` + `security_id`.
2. **Resolve (reuse)**: query company-wiki for an already-indexed, capture-ready
   filing. If found, return it — no download.
3. **Ensure (download) — only with `--allow-download`**: if missing and
   authorized, company-wiki routes by market and writes the new bytes into
   `companies/{entity}/raw/{kind}/` with a `.source.json` provenance sidecar.

Market routing (owned by company-wiki's acquisition config):
- **CN (A股)** → StockInfoDLSimple → cninfo (Chromium).
- **HK (港股)** → dayu-agent → HKEX.
- **US (美股)** → dayu-agent → SEC.

This skill is a thin client over company-wiki's acquisition engine; it does
**not** reimplement routing, storage, hashing, or dedup.

## Command

Read the request from stdin (or `--request-file`). Default is **read-only reuse**;
add `--allow-download` only when a missing filing should actually be fetched.

```bash
# Reuse-only (no download): returns the handle if the filing exists, else exit 2.
echo '{"company_query":"AMD","document_kind":"annual_report","fiscal_year":2025,"as_of_date":"2026-07-18"}' \
  | python scripts/fetch_filing.py

# Reuse, else download by market into company-wiki (authorized):
echo '{"company_query":"贵州茅台","market":"CN","document_kind":"annual_report","fiscal_year":2024,"as_of_date":"2026-07-18"}' \
  | python scripts/fetch_filing.py --allow-download
```

Request fields:
- `company_query` (fuzzy) **or** explicit `entity` + `market` + `security_id`.
- `document_kind`: `annual_report` | `semi_annual_report` | `quarterly_report` | ...
- `fiscal_year` (int), `as_of_date` (`YYYY-MM-DD`); optional `form_type`,
  `fiscal_period`, `language`, `provider`, `provider_document_id`.

Output (stdout JSON): `{schema_version, status:"capture_ready", handle:{...}}`
— the handle carries `canonical_path`, `snapshot_sha256`, `https_url`,
`capture_ready`, and the resolved `company_identity`.

Exit codes: `0` capture-ready; `2` not reusable / not found / config-identity
problem; `1` fatal error.

## Notes

- Downloads are blocked while the company-wiki worker is **paused** — resume it first.
- An ambiguous request (multiple filings match) never auto-picks; refine
  `fiscal_year` / `form_type`.
- Consuming skills convert the returned handle into their own capture schema
  (e.g., revenue-forecast builds its schema-3.4 source record from it).
