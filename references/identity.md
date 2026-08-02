# Identity resolution for dual-class and multi-listed issuers

How to write `company_query` for issuers with multiple tickers or multiple
listings, and how to read the diagnostics when resolution misses.

## Request writing

- **Dual-class tickers** (same issuer, same market — GOOGL/GOOG/GOOGM/GOOGN →
  "Alphabet Inc."): use any one ticker as `company_query`. company-wiki anchors
  the ticker to the issuer's canonical name (Phase 18.1), so a request by one
  class reuses the document filed under the issuer name or another class.
- **Multi-listed issuers** (same issuer, different markets — 601899/02899 CN/HK,
  9988/BABA HK/US): always add a `market` hint to select the primary market.
  The identity layer shares, but the document layer still filters by `market`
  strictly — a CN request only matches CN documents, never cross-shares.
- **Ambiguous identity**: when `identify` returns multiple candidates, the
  response carries `candidates[]` (ticker / canonical_name / market / exchange)
  and a `hint` (Phase 19.2). Pick the main ticker or add `market`/`exchange`,
  then re-run. A request without a `market` hint may legitimately resolve
  AMBIGUOUS across listings — disambiguate with the hint.
- Do not hand-guess identities: an unresolved query fails closed rather than
  auto-picking a candidate.

## Troubleshooting a not_found

Add `--debug` (Phase 19.6): the error response then includes `debug_trace`, the
per-candidate exclusion reasons from company-wiki's resolve step:

```
entity_gate_rejected: 12
Alphabet 2025 Annual Report: identity_conflict_market_or_security_id
```

The trace names each candidate that passed the entity gate and the step that
excluded it (`identity_conflict_market_or_security_id`, `fiscal_year_mismatch`,
`form_type_mismatch`, `published_after_as_of_date`, `capture_incomplete`, …).
Use it to decide whether the request needs a market hint, a specific ticker, a
fiscal-year filter, or whether the document genuinely is not in the catalog.
