# W08 findings

- Loss at stderr parse: six-field cause projection retains started/completeness but drops validated operation byte/cost values. Returned GAP has the same loss. Existing CWP accounting is correct.
- Local_prepare/source query reason is converted to a human string; subtype disappears in RF. New cause vocabulary belongs to local/query boundary, not provider acquisition.
- v2 error_envelope does not receive stage/attempts, whereas v1 already emits them. Keep same status/retry rules.
- Normal no-candidate producer result currently supplies no operation usage; consumer must report unknown, not use a configured $0 limit or downloads=0 as a receipt.
- Parent confirmed six-field compatibility and additive optional CWP observation. No permissions/gates added.

## Root correction and limits

The root RED identifies repeated consumer projection loss. Existing CWP accounting remains correct. The single copier accepts only an already emitted exact seven-field operation DTO with finite code/type/decimal/count validation. It preserves incomplete lower bounds, null flags and absent receipts; it neither settles nor calculates a fee ledger. Malformed DTO/extras do not enter new public observation fields.

Local_prepare/query contracts do not issue provider HTTP, so finite local-condition flags are known false/true; no numeric zero receipt is inferred. Invalid schema/transport does not prove zero usage. Calls/downloads are CWP subprocess/canonical download facts, not provider HTTP counts.

Historical unknown US failed-call costs cannot be inferred from later checks or configured ceilings. MAIN W11 owns recording. Legacy resolution_trace/free-text capture and identity diagnostic fields are not comprehensively migrated by this narrow card; no blanket safety claim is made for them. Optional environment skips are separate from passes; no W08 new case skipped.
