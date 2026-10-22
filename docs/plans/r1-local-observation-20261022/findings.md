# Findings

- Real H1 exact2026/H1 reuse_only failed local_prepare budget_exceeded, provider_started=false, usage_complete=true, retry_scope=none, calls3/downloads0. Existing RF stderr preserved only the six-field cause and producer exit0.
- FF `_validated` accepts operations/diagnostics but throws only reason/cause. FilingFetchError and v2 envelope have no local observation sibling. This silently drops producer details even for a complete successful transport.
- CWP LocalReadBudget owns candidate/byte/discovery counters; prepare_local_source catches a budget SourceReadError and returns an empty operations/diagnostics result. The public8-field receipt currently carries no actual counters/triggered-bound. ROOT owns that producer fix; FF must not infer actual local I/O zero from provider activity false.
- FF local read request is64 candidates/128MiB/min(remaining,600)s. This limits local verification/discovery, distinct from any remote50MiB acquisition limit. Neither ceiling is changed.
- RF `filing_upstream_cause.validated_filing_fetch_failure` accepts only the seven base keys plus acquisition_observation, so a new optional local_preparation_observation requires ROOT additive consumer support; otherwise the whole sidecar disappears.
- FF AGENTS.md is absent; CWP/parent constraints and current W02 handoff were read. Mother FF main has untracked .planning/du11-empty-placeholder-original.py and config/FMP_API_KEY.txt; neither was modified/read. CodeGraph indexes returned no focal local_prepare symbol; exact known files were read as fallback.


## Independent-review address leak repair (2026-10-22)

W02 found two genuine nested schema_version address leaks (old source 6dbb9e84: independent15P/2RED). Product a30024e57fd22b68662fbdfb1c344b8709391556 rejects only explicit drive:/ and scheme:// address prefixes. The original machine/schema namespace grammar remains: urn:owner:budget/2, owner/schema/1 and reason=file:missing are positive controls. No owner business map, permission, identity or accounting rule was added.

Final same-group139P/24.29s (no skip), Ruff and existing two-entrypoint mypy pass. Final12-case test against the old Git helper loaded in memory is5F/7P (0.78s), retaining safe cause when the optional observation is rejected. evidence/schema-hygiene-fix/final-source.json binds actual and Git LF bytes. Earlier red.xml contains one overly narrow slash test later converted to a positive; use old-source-red.xml and final-green.xml as the final RED/GREEN pair. Initial green.xml137P was intermediate and is not final acceptance. Normal commit hook originally flagged two malicious test inputs as absolute host assumptions; exact original baseline entries now document that the strings never reach filesystem/Path operations and rejection must hold on every OS. No skip, computed-path concealment, gate removal or blanket exemption was used.

W02 re-review on the new frozen source is pending; this repair does not claim cross-layer acceptance. All prior runtime installation requirements and ROOT responsibilities remain.
