# W07 implementation handoff

Status: first local delivery was rejected by independent M2. Its common-boundary repair is locally GREEN, committed and pending independent re-review; MAIN integration and M3 live FMP authentication/entitlement remain pending. This is an engineering receipt, not accepted research or subscription entitlement.

## Exact owned worktrees and branches

- FF: `C:/Users/郑曾波/AppData/Local/Temp/ff-fresh-transcript-launch-20261009`; base `23d25644a78390ebd5d7fd4da20e42d6788c1240`; branch `codex/fresh-transcript-launch-20261009`; final commit is this package's containing commit, resolve with `git rev-parse HEAD`.
- ET: `C:/Users/郑曾波/AppData/Local/Temp/et-fresh-transcript-launch-20261009`; base `fa99f46861616bcebe120914fd3a030a6b8f34b5`; branch `codex/fresh-transcript-launch-20261009`; original commit `1d03de61e681c3769102d634f6dfb45498044962`, repair tip `c91f5f54bc2a24e7b5d6e648dba3f9d578f5fa52`.
- No merge, push, installation, key edit, production config edit or paid provider call performed by this lane. ET production WIP `.workbuddy-ai/`/`eval_results.json` and FF untracked `config/FMP_API_KEY.txt` remain.

## Runtime and interface delta

FF: `scripts/transcript_tool_transport.py`, `scripts/transcript_companion.py`, `scripts/ff_v2_envelope.py`, `scripts/fetch_filing.py`, `scripts/et_v2_contract.py`; engineering doctor: `tools/config_doctor.py`.
ET: `transcript_api.py`, `transcript_tool.py`.
Focused tests: FF `tests/test_transcript_launch_contract.py`; ET `tests/test_launch_capability_contract.py`.
Existing earnings request/result/usage and FF v2 schema versions stay unchanged. ET capability/1 adds `supported_markets`/`supported_exchanges`; only actual US exchanges are supported. ET normalizes exchange once and returns unsupported_market(HKEX)/unsupported_exchange(other valid unknown slug) before key loading or HTTP; uppercase NASDAQ reaches the supported operation. No provider switch or HK capability expansion.
FF companion/v2 serializer accepts optional `provider_started`: effective HTTP count 0 gives false, positive gives true, missing/invalid usage gives null. Public failed ET result validation now accepts the named capability/file/credential errors and still rejects unknown codes, extra fields, corrupt hashes and mismatched identity.

## Configured credential path (location metadata only)

1. Explicit transport `fmp_api_key_file` or `FMP_API_KEY_FILE` wins.
2. Otherwise existing `FMP_API_KEY` is used.
3. Otherwise the actual FF-selected `company_wiki.json` may contain optional `fmp_api_key_file`, an absolute path or a path relative to this selected config's parent. Runtime loader and doctor both accept and type-check that one optional field.
4. Without that field, only the selected config's existing fixed `FMP_API_KEY.txt` is reused; this was the user-specified existing source. No cwd/recursive/key-pattern scans or hidden fallback.
Explicit unavailable/empty/invalid/overlarge file never falls back. Raw key stays in memory and ET child environment, not argv, wire request, results or CWP environment. Known-key text or encoded source-payload leakage is rejected intact, not scrubbed into a new immutable original. Safe measured usage survives; contaminated receipt stays unknown.
Standalone ET CLI supports explicit FMP_API_KEY_FILE using its configured launch loader and passes the value to its existing supervisor runtime argument, not by mutating the parent environment or serializing key into its internal request file.

## MAIN integration steps

1. Independently re-review the repaired exact branch tips. Each has the original delivery plus a follow-up repair commit; do not integrate only the rejected first commit. When accepted, integrate ET first and then FF. No whole installed directory replacement.
2. Add `tests/test_transcript_launch_contract.py` to the MAIN-owned FF `tools/ci_tests.py` shared list. This lane did not edit CI/tools ownership except the explicitly assigned doctor field support.
3. Selectively sync the runtime files above. Preserve all existing installed configurations, output, keys and unknown files.
4. If installed FF config does not have the existing fixed key file beside it, add only `fmp_api_key_file` pointing to the already-authorized `C:/Users/郑曾波/Projects/filing-fetch/config/FMP_API_KEY.txt`. Keep the key in its original file; no per-run export, credential copy or user approval JSON. No production/installed configuration was edited by this lane.
5. M2 real CLI checks: set the NONSECRET test-only `W07_ET_TOOL` to the accepted ET `transcript_tool.py`; run the new FF module. Three cross-repo CLI cases are explicit optional tests without this test-only path; do not call skipped cases PASS. The focused handoff ran them with the exact ET worktree, no skips.
6. At M3, make the bounded real supported US exact FY/Q call using existing configuration and budget, record current authentication vs entitlement and usage honestly. Old entitlement refusal/missing-credential run cannot stand in for this call. Do not purchase a subscription or substitute official HTML as proof ET worked.
7. W08 MAIN may now modify companion/v2 diagnostic propagation after this handoff. Existing broad ChildTimeout/ChildFailed classification in FF transport is W08 work, not claimed fixed by W07. No raw stderr or secret/physical paths may become its public cause DTO.
8. Remove these clean owned worktrees after acceptance; branch commits remain recoverable. Own pytest fixtures are restored absent per cleanup_inventory.json and m2_cleanup.json. Historical tool output incident cannot be retracted; diagnostic_incident.json intentionally includes no value/hash.

## Verification

Historical first-delivery evidence is in green_summary.json and red_summary.json: FF203PASS/1 existing snapshot skip, wire42PASS/0skip, ET116PASS. Those fixtures did not cover the M2 counterexamples and do not establish current acceptance. Current repair evidence is m2_repair_validation.json: FF67PASS/0skip and ET73PASS/0skip; Ruff and diff checks GREEN. No real external HTTP or paid call. The real CWP CLI fixture preserved original JSON bytes and reused them without a second provider call.

Commands use the ordinary OS, hooks and exclusive temporary fixtures. A coordinator can reproduce FF new contracts with `W07_ET_TOOL=<accepted ET checkout>/transcript_tool.py` and `python -m pytest tests/test_transcript_launch_contract.py -q -rs --basetemp <exclusive empty TEMP directory>`. ET affected suite: `python -m pytest tests/test_launch_capability_contract.py tests/test_provider_cost_capability.py tests/test_transcript_api.py tests/test_request_response_budget.py tests/test_retrieval_runtime.py tests/test_retrieval_cli_e2e.py -q --basetemp <another exclusive empty TEMP directory>`. Restore only owned new fixtures after terminal process exit. No production config copied into fixture directories.

## M2 repair interface and acceptance checkpoints

No wire schema, capability, credential source precedence or DTO field changed in the follow-up. The runtime installation delta is still the two existing files scripts/transcript_tool_transport.py and transcript_api.py, whose accepted tips must replace their original first-delivery versions. See installation_delta.md.

- Every decoded outer stdout/stderr JSON string, object key, nested array leaf, duplicate pair and base64-decoded provider JSON is checked before it can enter a DTO or immutable source.
- Leak rejection returns only the fixed provider_credentials_leaked reason, no raw/decoded credential, source text or original payload; no source byte rewrite.
- A separately clean valid usage receipt keeps measured counts and started. If the receipt itself contains the key in raw or legal Unicode JSON form, counters and started are null and completeness false, rather than fabricated zero or all-complete.
- Arbitrary alphanumeric child error text is never a public reason; only known producer error enums are projected.
- Re-review command can run FF tests/test_transcript_launch_contract.py and ET tests/test_launch_capability_contract.py with independent empty --basetemp roots. Keep W07_ET_TOOL set to the exact ET repair tip to avoid optional cross-repo skips. Independent reviewer must restore its own fixtures.
- The five implementation M2 fixture roots are absent; both branch worktrees remain for review. No M3 live FMP proof has been substituted with these offline fixture measurements.
