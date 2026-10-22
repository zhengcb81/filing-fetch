# Findings

- Real H1 exact2026/H1 reuse_only failed local_prepare budget_exceeded, provider_started=false, usage_complete=true, retry_scope=none, calls3/downloads0. Existing RF stderr preserved only the six-field cause and producer exit0.
- FF `_validated` accepts operations/diagnostics but throws only reason/cause. FilingFetchError and v2 envelope have no local observation sibling. This silently drops producer details even for a complete successful transport.
- CWP LocalReadBudget owns candidate/byte/discovery counters; prepare_local_source catches a budget SourceReadError and returns an empty operations/diagnostics result. The public8-field receipt currently carries no actual counters/triggered-bound. ROOT owns that producer fix; FF must not infer actual local I/O zero from provider activity false.
- FF local read request is64 candidates/128MiB/min(remaining,600)s. This limits local verification/discovery, distinct from any remote50MiB acquisition limit. Neither ceiling is changed.
- RF `filing_upstream_cause.validated_filing_fetch_failure` accepts only the seven base keys plus acquisition_observation, so a new optional local_preparation_observation requires ROOT additive consumer support; otherwise the whole sidecar disappears.
- FF AGENTS.md is absent; CWP/parent constraints and current W02 handoff were read. Mother FF main has untracked .planning/du11-empty-placeholder-original.py and config/FMP_API_KEY.txt; neither was modified/read. CodeGraph indexes returned no focal local_prepare symbol; exact known files were read as fallback.
