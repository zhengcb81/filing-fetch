# FC-903 Change Contract — filing-fetch N/N-1 envelope/bundle 契约

> Owner: filing-fetch · Base triplet: revenue `1c5f127` / filing `81d9cd9` / wiki `fd4f50b`
> Dependencies: FC-902 (accepted) · Scenario: bundle forwarding N/N-1, no artifact-validity re-decision

## Intended behavior delta (observable)

`validate_resolution_envelope` (filing-fetch consumer side) accepts BOTH
envelope generations and forwards the result:

- **N** (FC-902 company-wiki): envelope with `bundle_status` ∈
  {available, unavailable}; `available` requires a SHA-256 `bundle_hash` AND a
  bundle dict whose `bundle_hash` matches AND `schema_version == "1.0"` —
  fail closed on fabricated evidence.
- **N-1** (pre-FC-902 company-wiki): envelope WITHOUT `bundle_status` is
  accepted and normalized to the explicit honest `bundle_status="unavailable"`
  — never a faked empty-green `available`. The caller's dict is not mutated.

The function now RETURNS the (possibly normalized) envelope; the handle
builder forwards the returned dict verbatim.

## Explicitly NOT changed

- Artifact validity is NOT re-decided: the bundle's valid/invalid handles are
  forwarded verbatim (shape contract only).
- No envelope/outcome/download-event/policy semantics changed.
- No provider/root/identity rules.

## Allowed symbols / files

- `scripts/filing_contracts.py` — validate_resolution_envelope (N/N-1 + return).
- `scripts/fetch_filing.py` — handle builder uses the returned envelope.
- NEW `tests/test_fc903_bundle_contract.py`.
- `assurance/fc/FC-903/03_change_contract.md` (+ receipts).

## Forbidden changes

- Rejecting an N-1 envelope that merely omits bundle_status.
- Fabricating `available` from a missing/malformed bundle.
- Re-deciding artifact validity inside filing-fetch.
- Any catalog/root write.

## Expected call-edge delta

- `validate_resolution_envelope` gains a return-value contract (normalization);
  `fetch_filing.py` consumes it. No new production symbol.

## Side-effect budget

| Effect | Budget |
|---|---|
| catalog writes | 0 |
| external root writes | 0 |
| deletions | 0 |

## Rollback

Additive contract behavior; revert = revert commits.

## Diff budget

2 production files + 1 test file (≤200 lines). Exceeds → split.
