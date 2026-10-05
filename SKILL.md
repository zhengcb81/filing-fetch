---
name: filing-fetch
description: Fetch a company financial filing into company-wiki on demand. Reuses an existing filing if one is already indexed; otherwise, only when explicitly authorized, downloads via the correct market tool — A-shares (CN) via StockInfoDLSimple/cninfo, HK and US via dayu-agent — and stores the new file under company-wiki's companies/{entity}/raw/financial_reports/{kind}/ with immutable provenance. Use when any skill (revenue-forecast, invest-*, industry-research) needs an annual/quarterly/semi-annual report or regulatory filing and must not blindly re-download.
---
# Filing Fetch

On-demand, market-routed fetch of a company financial filing into the shared
`company-wiki` catalog, with **reuse-first** semantics so the same filing is
never downloaded twice.

Two request schemas are accepted:

| Schema | Status | Download intent | Result |
|---|---|---|---|
| `2.0` | **recommended** | one `filing_intent`, bounded by `acquisition_limits` | pathless `source_ref` candidate |
| `1.2` / `1.1` | legacy, thin compatibility | the `--allow-download` flag plus explicit resource limits when acquiring | path-bearing handle |

New callers use `2.0`. The older schemas keep working for existing callers and
retain their result shapes. Legacy acquisition requests may provide the same
validated `acquisition_limits` object; existing read-only reuse does not need it.

## Required workflow (schema 2.0)

1. **Validate request** — unknown fields are rejected, `company_query` is
   required (`entity` + `security_id` are forbidden), dates are `YYYY-MM-DD`,
   and `filing_intent` must be `reuse_only` or `fetch_if_missing`.
2. **Identify** the company (fuzzy name / brand / ticker) to **one verified,
   active security** with a canonical `market` + `security_id`.
3. **Derive one download intent** — `filing_intent` is the only authority.
   The CLI and the library both derive from it, so the same request behaves
   identically whichever entry point is used; an `allow_download` argument
   that contradicts it is a `request_error`, never a second, silently
   different decision.
4. **Resolve (reuse)** — query company-wiki for an already-indexed,
   capture-ready filing. If found, return the pathless candidate — no
   download.
 5. **Pause around downloads (retired)** — filing-fetch no longer probes
    worker-status or writes pause files: the old pause-around orchestration
    was removed in this lane. company-wiki retired the worker routes
    (`73de6be refactor: retire legacy source catalog worker routes`):
    `ensure --allow-download` never consults worker state. `--no-pause-worker`
    and the `--worker-*` timing flags still parse for existing callers and are
    accepted as inert no-ops.
6. **Ensure (download)** — only for `fetch_if_missing`. company-wiki routes by
   market and writes new bytes under
   `companies/{entity}/raw/financial_reports/{annual|semi_annual|quarterly}/`
   with a `<file>.source.json` provenance sidecar. The request's byte, time
   and fee ceilings travel on this call (see *Acquisition limits*).
7. **Return the result** — either a capture-ready `source_candidate` or an
   honest `gap`. A gap the producer still reports is never rewritten into a
   capture that did not happen.

## Acquisition limits

`filing_intent: "fetch_if_missing"` **requires** `acquisition_limits`, and
`reuse_only` **forbids** it (except bounded metadata discovery for
`latest_as_of`). Legacy 1.1/1.2 can also supply this object when explicitly
acquiring; FF never invents byte, time or fee ceilings:

| Field | Rule |
|---|---|
| `max_bytes` | positive integer (not a bool) |
| `timeout_seconds` | positive finite number (int or float, not a bool) |
| `max_cost_usd` | non-negative decimal string, at most two decimals, passed through unchanged |

The three ceilings are forwarded to company-wiki's `ensure` / `close-gap` as
`--max-download-bytes`, `--max-download-seconds` and
`--max-download-cost-usd`. They are not decorative: filing-fetch's own
subprocesses share one deadline, computed as the **smallest** of

- what remains of the global deadline (`--timeout-seconds`, default 900),
- the configured `timeout_seconds` budget,
- the request's own `acquisition_limits.timeout_seconds`.

Every company-wiki subprocess of that request inherits the same deadline, and
its stdout is capped at a fixed byte ceiling. On timeout filing-fetch
terminates the process it started and touches nothing else; a child that
exits non-zero or returns an oversized body fails by name.

The identity of a request (`Request ID`) never carries resource ceilings, and
a ceiling is never silently widened, reformatted or dropped.

> **Producer note.** company-wiki must accept the three `--max-download-*`
> flags. While it does not, a `fetch_if_missing` request fails with a named
> error rather than being re-sent without its ceilings, downgraded to `1.x`,
> or reported as a completed capture.

## Command

Read the request from stdin (or `--request-file`). Default is **read-only
reuse**. For schema `1.2`/`1.1` add `--allow-download` only when a missing
filing should actually be fetched; for schema `2.0` the flag is ignored — the
request's `filing_intent` is the intent.

- `--timeout-seconds` — overall deadline for the request (default 900).
- `--source-ref-v2` — return a pathless source reference for a later
  company-wiki read (implied by schema `2.0`).
- `--no-pause-worker` — accepted for compatibility; inert (the worker
  pause-around was retired). `--worker-graceful-timeout-seconds` and
  `--worker-resume-wait-seconds` are inert as well.
- `--debug` — include the per-candidate exclusion trace in a `not_found`.

```bash
# Recommended (schema 2.0): bounded reuse-first fetch.
echo '{
  "schema_version": "2.0",
  "company_query": "AMD",
  "market": "US",
  "document_kind": "annual_report",
  "mode": "exact",
  "fiscal_year": 2025,
  "as_of_date": "2026-09-29",
  "filing_intent": "fetch_if_missing",
  "acquisition_limits": {"max_bytes": 5000000, "timeout_seconds": 60, "max_cost_usd": "1.00"}
}' | python scripts/fetch_filing.py --timeout-seconds 300

# Recommended (schema 2.0): read-only reuse, never downloads.
echo '{"schema_version":"2.0","company_query":"AMD","market":"US","document_kind":"annual_report","mode":"exact","fiscal_year":2025,"as_of_date":"2026-09-29","filing_intent":"reuse_only"}' \
  | python scripts/fetch_filing.py --timeout-seconds 300

# Legacy (schema 1.2): explicit flag instead of a filing_intent.
echo '{"schema_version":"1.2","company_query":"贵州茅台","market":"CN","document_kind":"annual_report","mode":"exact","fiscal_year":2024,"as_of_date":"2026-07-18"}' \
  | python scripts/fetch_filing.py --allow-download --timeout-seconds 600
```

### Request (schema 2.0) — recommended

Precise fields. Unknown fields are rejected.

| Field | Required | Notes |
|---|---|---|
| `schema_version` | yes | `"2.0"` |
| `company_query` | yes | Fuzzy name / brand / ticker; `entity` + `security_id` are *forbidden* |
| `document_kind` | yes | `annual_report`, `semi_annual_report`, `quarterly_report`, … |
| `as_of_date` | yes | `YYYY-MM-DD` |
| `filing_intent` | yes | `reuse_only` (no `acquisition_limits`) or `fetch_if_missing` (requires them) |
| `mode` | no | `exact` (needs `fiscal_year`) or `latest_as_of` (forbids `fiscal_year`) |
| `fiscal_year` | no | Integer (rejects bool) |
| `market`, `exchange` | no | Hints only — identity stays verified/active |
| `form_type`, `fiscal_period`, `language`, `provider`, `provider_document_id` | no | |
| `acquisition_limits` | for `fetch_if_missing` | exactly `max_bytes` + `timeout_seconds` + `max_cost_usd` |
| `companion_transcript` | no | Independent transcript request, see below |

### Companion transcript (`companion_transcript`)

The filing and the earnings-call transcript are **independent results**: a
transcript failure never rolls back a successful filing, and a filing `gap`
marks the transcript `not_applicable`.

| Field | Required | Notes |
|---|---|---|
| `intent` | yes | `reuse_only` or `fetch_if_missing` |
| `fiscal_year`, `fiscal_quarter` | for any fetch | Both must be present and exact. A year **without** a quarter resolves to `period_unresolved` (`exact_fy_q_required`) — filing-fetch never invents Q4 from a full-year request |
| `provider` | no | only `fmp` (or absent) |
| `acquisition_limits` | for an exact-period fetch | same three ceilings as the filing, scoped to the transcript only |

- Language is taken as published — never translated.
- `max_cost_usd` of `"0.00"` means no paid acquisition: the transcript comes
  back `provider_unavailable` / `zero_cost_budget` with zero provider calls.
- Configure the provider tool with the `EARNINGS_TRANSCRIPTS_TOOL`
  environment variable (path to the earnings-transcripts entry script). It is
  invoked as `<tool> --request-stdin --include-source-payload`. If it is unset
  or missing, the transcript reports `provider_unavailable` /
  `transcript_tool_not_configured` — the filing result is unaffected.

### Response (schema 2.0)

Success is one of:

```jsonc
{ "schema_version": "2.0", "status": "source_candidate",
  "filing": {"status": "source_candidate", "source_ref": {"schema_version": "2.0", "document_id": "…", "source_id": "…", "content_sha256": "…", "byte_size": 0, "mime_type": "…"},
             "byte_verification": "pending_verified_open", "…": "…"},
  "transcript": {"status": "…", "retryable": false},
  "calls": 0, "downloads": 0 }

{ "schema_version": "2.0", "status": "gap",
  "filing": {"status": "gap", "reason": "metadata_only_gap_plan", "gap_hash": "…", "download_events": 0},
  "transcript": {"status": "not_applicable", "reason": "filing_not_capture_ready", "retryable": false} }
```

The `source_ref` is a *candidate*: physical bytes are read later by
company-wiki's verified open, so `byte_verification` stays
`pending_verified_open` at this boundary. There is no `canonical_path` in a
v2 response.

`transcript.status` values: `not_requested`, `not_applicable`,
`period_unresolved`, `reused`, `unknown_publication`, `downloaded`,
`not_found`, `provider_unavailable`, `upstream_error`, `request_error`,
`contract_pending`.

Errors use `status` = `request_error` / `config_error` / `identity_error` /
`not_found` / `upstream_error` / `catalog_locked` / `worker_paused` / `fatal`
with `filing.reason` carrying the reason.

### Request / response (schemas 1.2 and 1.1) — legacy

Unknown fields are rejected; `entity` + `security_id` are forbidden.
`1.2` adds `mode` and the optional `authorization` block (provider /
accessions / caps / expiry) used by the legacy close-gap path; `1.1` predates
both.

Success: `{schema_version:"1.1", status:"capture_ready", handle:{…}}`

Error: `{schema_version:"1.1", status:"<code>", error:"…", error_code:"<code>", retryable:bool}` (an `identity_error` for an ambiguous query also includes `candidates[]` and a `hint`)

| Status code | Meaning | Retryable |
|---|---|---|
| `capture_ready` | Filing found / reused | — |
| `request_error` | Invalid request (including an `allow_download` that contradicts `filing_intent`) | no |
| `config_error` | Config missing / invalid | no |
| `identity_error` | Ambiguous or inactive identity. When ambiguous, the response also carries `candidates[]` (`ticker` / `canonical_name` / `market` / `exchange`) and a `hint` — disambiguate by adding `market`/`exchange` or using a specific ticker in `company_query` | no |
| `not_found` | No matching filing | no |
| `upstream_error` | company-wiki subprocess failure (including deadline exhaustion or an oversized child body) | yes |
| `catalog_locked` | company-wiki catalog locked by another operation; auto-retried with backoff until the deadline | yes |
| `worker_paused` | legacy: a paused company-wiki worker blocked the download. Current company-wiki no longer emits it — the background worker routes were retired (`73de6be`) | yes |
| `fatal` | Unexpected error | no |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | capture-ready, pathless candidate, or a structured `gap` |
| 2 | **every** structured error — `request_error`, `config_error`, `identity_error`, `not_found`, `upstream_error`, `catalog_locked`, `worker_paused`, `fatal` |
| 1 | only an unexpected, non-`FilingFetchError` exception |

## Hard failure gates

- Unknown request fields are rejected (callers cannot silently depend on
  ineffective modifiers).
- An explicit `entity`/`security_id` without `company_query` is rejected —
  every request must go through verified-active identity.
- A v2 `fetch_if_missing` request without all three ceilings, or a v2
  `reuse_only` request carrying them, is rejected.
- An `allow_download` argument that contradicts a v2 `filing_intent` is
  rejected instead of silently winning.
- A handle whose `canonical_path` escapes the `companies/` subtree, whose
  SHA-256 does not match the canonical file, whose URL is not HTTPS, or whose
  `published_date` is after the request `as_of_date` is rejected.
- The shared deadline is enforced on every subprocess; a child body above the
  byte ceiling fails closed.
- Unknown upstream response schemas, non-JSON stdout, or non-object responses
  fail closed.
- A company-wiki failure is reported by exit status and classified code only:
  the raw stderr body is consumed for classification and never echoed, because
  it routinely carries absolute paths and provider credentials.

## Owner / trust boundary

- **Identity, catalog lookup, market routing, download, dedup, and canonical
  write** are owned by `company-wiki`'s source catalog.
- **Cross-skill request, acquisition limits, upstream schema compatibility,
  and handle validation** are owned by `filing-fetch`.
- **Consumer-specific source/capture records** (e.g. revenue-forecast) are
  owned by the consuming skill — they call `filing-fetch` and convert the
  returned handle.

## Installing this skill

Installing copies files into the shared `~/.agents`, `~/.claude` and
`~/.codex` skill roots, so it is an explicit action:

```bash
python tools/sync_installs_b3.py --install     # write
python tools/sync_installs_b3.py --check       # read-only drift report
```

The install surface is an allowlist — `scripts/`, `SKILL.md`, `CHANGELOG.md`,
`references/` and the one public config template. Credentials, local `.env`
files, `tests/`, caches and run logs are structurally outside it. The
pre-push gate reports drift but never performs the install.

## Notes

- **Read-only reuse is config-driven (ADR-008 Strategy B)**: any root kind
  listed in company-wiki's `reusable_root_kinds` (`source_catalog.yaml`)
  serves its already-indexed documents directly — e.g. `dayu_portfolio`
  reuses filings dayu already downloaded, zero download.  Adding a root =
  one line in company-wiki's `source_catalog.yaml`, no code and no
  filing-fetch config change (FC-501/FC-1202: the RootPolicySnapshot is the
  single policy source; filing-fetch's `config/company_wiki.json` only
  locates the company-wiki root).
- **Worker pause-around is retired.** filing-fetch keeps neither the
  `PausedWorkerScope` orchestration nor pause refcount/owner files; it makes
  zero `worker-status`/`worker-pause`/`worker-resume` calls. company-wiki
  retired those routes (`73de6be`) and its `ensure --allow-download` never
  consults worker state. A paused background worker neither blocks nor fails
  a download, with or without `--no-pause-worker`.
- `worker_paused` can still surface as an upstream-reported taxonomy code from
  an older company-wiki; it is passed through honestly (retryable) and never
  auto-retried.
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
