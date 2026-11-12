# Public wire samples

Small, pathless examples for ROOT composition. They are **public wire
documents**, not a second CWP/ET implementation and not production data.

| File | Producer → consumer | Notes |
|---|---|---|
| `source_ref.json` | CWP → FF/RF | logical `SourceRef/2.0`; no physical path |
| `source_candidate.json` | CWP → FF | candidate metadata bound to the ref |
| `query_found.json` / `query_not_found.json` | CWP source query → FF | DB-only query results |
| `local_prepare_ready.json` | CWP local prepare → FF | `local-source-prepare/1` ready receipt |
| `operation_completed.json` / `operation_gap.json` | CWP ensure → FF | `source-operation/1.0` completed / gap |
| `transcript_import_response.json` | CWP → FF | `company-wiki-transcript-import-response/3` |
| `transcript_usage_known.json` / `transcript_usage_unknown.json` | ET → FF | `earnings-retrieval-usage/1`; unknown is not zero |
| `error_envelope.json` | FF → caller | v2 business failure envelope example |

These are manually aligned snapshots of the same public wires the isolation
fixture answers with. `tests/test_public_operation_isolation.py` checks their
required public fields, so missing keys fail fast. There is no generator in
the repository: if a fixture constant changes, update the affected sample in
the same commit. The field-level guard does not compare every value.
