# Findings — DU11-FF-TRANSCRIPT-REUSE

All upstream facts below were read from the **frozen** CWP commit `34a7dd71aaa49d18c13fcdd300ce79581114ca5b`
(verified byte-identical to the checkout for the files used: `git rev-parse 34a7dd71:<path>` == `git hash-object <path>`).

## F1 — Two real public source-query entries (do not merge them)

`src/company_wiki/source_catalog/source_query_cli.py` reads one JSON object from stdin:

- **Plain path**: `schema_version` is *not* the lookup envelope → `SourceRequest(**request_data)` → `reader.query_local(request)`.
- **Envelope path**: `schema_version == "company-wiki-transcript-import-lookup-request/1"` and keys exactly
  `{schema_version, source_request}` → `reader.lookup_transcript_import(request)`.
  `lookup_transcript_import` raises `ValueError` when `request.provider is None` (see F3) → CLI maps to
  `status="blocked"`, `reason="invalid_request"`, exit 2.

Output JSON (both paths) = `asdict(SourceQueryResult)` + `request_id` + `candidates` (only for `found`/`unknown_publication`)
+ `source_read_policy_sha256`; `excluded_candidates` is **popped when empty**.
`SOURCE_REF_SCHEMA_VERSION = "2.0"`.

## F2 — `query_local` never returns an unknown-publication success match

`SourceVersionReader._query_local` (source_reader.py:285-372):

- candidate pages always include unknown-publication documents (`include_unknown_publication=True`);
- provider filter: `request.provider and (provider != request.provider if include_unknown_publication else provider is not None and provider != request.provider)`
  → with `provider=None` (plain path) **no provider filter at all**; with the envelope path a `None` provider candidate is also excluded;
- qualification via `qualify_source(document["published_date"], as_of_date=request.as_of_date)`:
  `historical_date_eligible` is True only for an exact ISO `published_date <= as_of_date`;
- not eligible → appended to `excluded_candidates` as `{"source_ref": SourceRef2, "qualification": source-qualification/1}`
  (unless `include_unknown_publication` and status is exactly `unknown`);
- `found` only when exactly one eligible match; 2+ → `ambiguous`; none → `not_found`/`no_local_match`.
  Because eligible implies a non-empty published date, the plain path can never return `unknown_publication`.

## F3 — Envelope path (`lookup_transcript_import`) requires a concrete provider

source_reader.py:264-283 rejects (`ValueError`) `document_kind != investor_call_transcript`, missing
market/security_id/fiscal_year/fiscal_period, **`provider is None`**, or `mode not in {None,"exact"}`.
It queries with `include_unknown_publication=True`: an unknown-publication candidate matching the requested
provider becomes a `found`/`unknown_publication` match (dedup semantics for import).

## F4 — `source-qualification/1` real fields

`qualification.py`: `publication_status` ∈ `{unknown, invalid, known, eligible, after_as_of}`,
`as_of_date`, `local_bytes_status` ∈ `{not_checked, verified, unavailable}`,
`historical_date_eligible`, `historical_reuse_eligible`, `schema_version="source-qualification/1"`.
`local_bytes_status` defaults to `not_checked` (a query observation, not a byte proof).

## F5 — Real provider comes from the reader receipt manifest

`source_reader_cli` writes source bytes on stdout and one JSON receipt on **stderr** with
`manifest = reader.describe_version(ref)`; `_describe_version` (source_reader.py:374-444) exposes
`provider`, `provider_document_id`, `published_date`, `fiscal_year`, `fiscal_period`, `market`, `security_id`,
`canonical_entity_id`, `display_name`, `document_kind`, `title`, `source_url`, `language`, …
`describe_candidate` (used for the query `candidates` list) also carries `provider`, but the card requires the
verified reader receipt as the provider source — use `manifest.provider`.

## F6 — Provider metadata path through the scanner

For a `company_raw` root the `.source.json` sidecar dict is stored verbatim as `metadata_json["acquisition"]`
(scanner.py:1072-1081). `_source_metadata` (resolver.py:1072-1126) returns that container, and
`_provider_identity` reads `metadata["provider"] or metadata["source_provider"]`, lowercased.
So a sidecar `{"provider": "motley_fool", ...}` is a faithful synthetic registration of an existing source
whose real provider is `motley_fool`.

## F7 — Current FF defect (source level, to be proven by real RED)

- `transcript_tool_transport.py::_source_request` hardcodes `"provider": "fmp"`.
- `lookup_exact` always uses the `_LOOKUP_SCHEMA` envelope and returns `"provider": "fmp"`.
- `transcript_companion.py` maps an omitted provider to `"fmp"` (`prepared.option.get("provider") or "fmp"`).
- Consequence: a transcript registered by CWP under `motley_fool` (or any other real provider) is invisible to
  the default FF lookup, because the envelope provider filter (`provider != "fmp"`) drops it. The request then
  goes to ET/FMP acquisition or reports `not_found`, although verified local bytes exist.

## F8 — Import path already tolerates a null provider in `source_request`

`transcript_import_cli` → `import_transcript_tool_result` validates the request vs the candidate/tool result
(`transcript_tool_contract`: provider equality is checked between **tool result** and **candidate**), and
`canonical_writer` writes `provider` from `candidate.provider` (the FMP-etched candidate), not from
`source_request.provider`. So a neutral (provider=null) lookup that falls through to FMP acquisition keeps a
truthful `fmp` stored provider.

## F9 — Measured RED (not a source-string assertion)

Owned temp root + frozen CWP `src/` from `34a7dd71` (`git archive` tar sha256
`555b11a87ebd67858c08ddbc08971fc97deff3b19079444dc738b6eafa558eac`, 356 files) + one synthetic
`motley_fool` transcript registered through the real `scan` CLI, entity `Microsoft Corporation`, FY2026 Q3,
`published_date=2026-07-22`, request `as_of_date=2026-09-30`.

| observed wire | real result |
|---|---|
| plain `SourceRequest` `provider=null` | `found`, 1 candidate, candidate provider `motley_fool` |
| `lookup-request/1` envelope `provider=fmp` | `not_found` / `no_local_match` |
| `lookup-request/1` envelope `provider=null` | `blocked` / `invalid_request`, exit 2 |
| plain `SourceRequest` `provider=fmp` | `not_found` (provider filter applies for a concrete provider) |
| `source_reader_cli` stderr receipt | `manifest.provider=motley_fool`, `published_date=2026-07-22`, `fiscal_period=Q3`, `security_id=MSFT` |

Baseline FF companion (`f1a939e5` scripts, same wiki, same request, provider omitted):
`status=downloaded`, `provider=fmp`, `provider_calls=1`, **1 ET call**, 3 CWP child calls — i.e. FF
downloaded and imported a duplicate FMP original while the exact verified `motley_fool` original was already
registered. This is the documented defect, reproduced end to end rather than inferred from source text.

## F10 — The provider-scoped envelope still needs a positive case

`lookup_transcript_import` with a concrete provider returns `found` only for a candidate whose metadata
provider equals that provider. The card's A node requires that positive case to be measured too (not only the
`blocked`/`not_found` counter-cases), and the C node requires the explicit-`fmp` unknown branch and the neutral
branch to be measured separately. Both are covered by the real-CWP E2E set; the unknown branch
(`fmp_v2.fetched.json`, `publication_date=null`) and the known-publication branch
(`fmp_known_publication.fetched.json`) are separate fixtures on purpose.

Measured positive control (`test_real_cwp_explicit_fmp_lookup_finds_and_reuses_its_own_source`):
after one real CWP import of the known-publication fixture, both the plain `SourceRequest`
(`provider="fmp"`) and the `lookup-request/1` envelope return `status="found"` with
`candidate.provider="fmp"`, and the explicit-`fmp` replay is `reused` with `provider_calls=0` and one ET call
total.

## F11 — Which provenance source wins for a reused source

`describe_candidate` (the query `candidates` list) does expose `provider`, but the query is only a
selection observation; the verified `source_reader_cli` receipt `manifest` is what proves the bytes and
their capture facts. FF therefore reads `provider` from `receipt.manifest.provider` only. Consequence
(tested): a candidate that names no provider at all is still reused when the manifest names one, and a
candidate whose label disagrees with the manifest is not relabelled — the manifest wins, and an explicit
`provider=fmp` request whose manifest says otherwise is refused (`transcript_provider_mismatch`) rather
than silently reused.

For a freshly downloaded document the manifest normally names the provider too; when it does not, FF keeps
the tool result's own declaration — a CWP-validated fact (`tool_result.provider == candidate.provider`),
not a request default — and when neither exists the provider stays unknown (key omitted, tested).
