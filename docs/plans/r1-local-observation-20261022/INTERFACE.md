# Local preparation observation: additive FF public sibling

FF v2 error envelope retains schema_version2.0 and all existing filing/cause/exit/retry/calls/downloads meanings. An optional **top-level** `local_preparation_observation` carries this9-key closed outer object:

| Key | Type / meaning |
|---|---|
| schema_version | filing-local-preparation-observation/1 |
| usage_scope | local_original_verification |
| status | ready/not_found/blocked/unavailable/ambiguous, original CWP status |
| reason | original bounded machine code, not a new FF business enum |
| blocks_download | original strict bool; observation does not change FF routing |
| local_read_limits | actual request's max_candidates int, max_bytes int, timeout_seconds finite number; these are local verification/discovery limits, not acquisition/download quotas |
| operations | original bounded list of machine JSON objects, including owner-versioned local-read-budget/1 unchanged |
| diagnostics | original bounded list of machine JSON objects, unchanged |
| local_io_usage | null; FF does not extract/recompute/infer an aggregate from owner operations |

FF permits up to128KiB compact UTF-8 JSON, depth8, lists1024, dicts32 keys, finite numbers/null/bools. Strings are bounded ASCII machine tokens (256 characters); schema_version allows slash, other token values allow letters/digits/underscore/dot/colon/plus/minus. Dictionary keys are ASCII identifiers up to64 characters. Existing shared physical-location keys and raw body/content/text/stdout/stderr/header/credential/free-detail fields are rejected. This is wire hygiene, not source identity/hash/period/business/budget revalidation. Unknown owner machine fields/reasons remain unchanged within these bounds. CWP owns their semantics.

Bad optional observation is omitted while the original safe failure cause survives; never convert it to source_candidate or usage0. Above-cap diagnostics are not silently truncated or claimed complete. The cause's provider_started=false/usage_complete=true describe provider work only. They do not mean local read0. Actual local counters/trigger are exactly the CWP owner operation, including observed_charge_bytes greater than charged_read_bytes for rejected tail reads and triggered_bound=null when producer cannot prove which bound fired.

RF consumers must not import FF code. Accept the additive optional sibling by outer schema/type/bounded/pathless JSON validation and copy it unchanged; do not interpret owner counters or duplicate every owner diagnostic enum. Existing RF16KiB complete-sidecar and64KiB stderr decode windows need coordinated bounds, or larger valid observations disappear despite the new key allowance. ROOT owns RF compatibility and installed skill synchronization.

Fixtures: evidence/wire-valid.json is a full actual FF envelope from production serializer with a native-format budget operation. evidence/wire-rejections.json contains wrong outer type/schema, physical location, raw header, wrong reason type, and invalid local_io_usage examples. tests/test_local_preparation_observation.py executes real bounded children/FF CLI, native budget operation equality, deep-copy isolation and refusal cases. No network/provider/source scan is involved.

Installation: sync all five changed FF runtime files together, including NEW scripts/ff_local_preparation_observation.py. No installed copy is changed by this lane. Native CWP wire stays local-source-prepare/1 with its original8 top keys. This FF sibling is optional and separate from acquisition_observation, never stuffed into provider usage.
