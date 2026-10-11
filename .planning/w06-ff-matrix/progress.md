# Progress — W06-FF-MATRIX

## Session 2026-10-11
- 读取任务卡片 W06-FF-MATRIX.md、input/（inputs.json、construction_card.md、handoff_contract.md、ROOT_INTERFACE_AMENDMENT.md、manifest.json、amendment_manifest.json）。
- 确认 worktree 就绪：分支 codex/w06-ff-contract-matrix @ 08ec85b，sparse checkout 含 scripts/tests/tools。
- 建 .planning/w06-ff-matrix/ PWF 三文件。
- 下一步：勘察 FF/ET/CWP 源码接口。

## Session 2026-10-11 (cont)
- 三仓接口勘察完成（FF/ET/CWP），架构定稿写入 findings.md。
- 建 tools/offline_contract_matrix/{fixture_builder,et_transcript_proxy,fixture_provider_adapter}.py。
- 烟测验证：FF 本地命中 seeded 年报(reused_existing,downloads=0)；链A真三层贯通——FF公开CLI→ET真supervisor/worker/fakeHTTP(calls 3行)→FF真实import→CWP注册(source_ref 860d...)→open_version→run2复用(0请求,unknown_publication/publication_date_unknown=真诊断)。
- 关键发现：FMP transcript publication_date 恒 null，故复用命中显示 unknown_publication(as_of_cutoff_verified=False)，这是正确产品行为；call_date 须<=as_of_date 否则 cutoff 拒绝。
- 下一步：建正式 runner run.py + report.py + oracle.py，覆盖矩阵1-5。


## ROOT reception repair — 2026-10-11

- Preserved intake and RED logs under CWP W06 evidence/root-ff-matrix-acceptance/fix.
- Implemented typed outcomes, strict bound evidence, runtime isolation/ownership/deadlines, fresh SourceVersionReader byte/hash checks, physical original counts and full required matrix.
- Focused final package: 33 PASS / 2.58 seconds (no producer/network/paid requests).
- Historical node-1/node-2 failures remain unchanged and are not upgraded to COMPLETE. Final rerun after the SQL evidence-query correction is being collected in the unique next attempt; ROOT will read its result and decide producer work.
- No commit/install/push. ROOT owns normal merge reception and canonical PWF updates.

## ROOT final engineering freeze — 2026-10-11

**State: harness engineering GREEN; integration PARTIAL_PRODUCT_FAILURES. Author frozen.**

- Formal original business RED: oracle 7 FAIL / 13 PASS; runtime 3 FAIL / 1 PASS. Generic cross-market fixture SHA collision additionally proved RED (1 FAIL), then fixture identities and bodies made unique by market/security/kind/year/period.
- Concentrated final tests: 34 PASS / 2.95 seconds; Ruff passed. These do not claim product flow COMPLETE.
- Actual final offline node: 41 required cases, 19 PASS / 21 FAIL / 1 PARTIAL, 132.5406 seconds under absolute 180-second batch and 30-second case caps. Zero real provider/paid/model/network requests; translation attempts 0. Thirteen accepted source refs were independently opened with current SourceVersionReader and actual byte SHA, each 1 physical original. Existing parent entries and empty-dir/absent shape preserved; own scratch removed; retained output is explicit evidence.
- Nine warm2024 financial documents were created by real public CWP ensure/import. Local2024 hits all pass. New2025/2026 requests returned not_found without supplier fetch. The chain-A and most ET cases never reached ET because primary2025 filing preparation failed; they are failed/partial, not skipped or relabeled expected failures. Three oracle findings diagnose unmet intended checks, not three proved ET implementation defects.
- Important diagnostic: actual get_verified_assertion(reader='steady') for both US/CN acquired2024 sources returns null; actual source_fact_patch/evidence therefore absent. Real acquisition/import and a complete acquisition metadata record are NOT proof of a verified source-fact assertion. ROOT must decide whether test setup needs an additional real public preparation stage, or the producer has a registration/reconciliation defect. No handcrafted SQL assertions or source_fact_patch were introduced.
- Original attempt-1 HOME failure and earlier supplier same-SHA collision are retained but NOT production defect evidence. Earlier fully populated scanned-sidecar rejection expectation was mistaken; preserved receipt remains, final extra control is explicitly incomplete metadata (missing period/publication). No company-specific workaround or producer code modification.
- Canonical fix evidence: company-wiki/docs/plans/cross-market-rf-e2e-2026-10-08/phase6/w06_parallel_verification_2026-10-11/evidence/root-ff-matrix-acceptance/fix/. See root_report.md, cross-period-repro.json, offline-evidence.zip and freeze-manifest.json. Original worker handoff/intake unchanged.

### Next Step
ROOT non-author reception of frozen tool source/tests, followed by ROOT diagnosis of actual imported source assertions and new-period acquisition. Preserve all matrix vectors, use actual public setup if needed, rerun one major offline node after resolution. Only ROOT commits/merges/installs/pushes.

## Case authority repair reception — 2026-10-11

- Independent final review found TOOL_BLOCKER_CASE_CONTRACT_AUTHORITY_P1: report.required_cases / case.expected / hashed request could redefine intended work. Old engineering freeze remains historical; this repair has its own freeze under fix/case-authority/.
- Fixed executable immutable CaseSpec/RunSpec is now shared by registry/dispatch, launch input checks, report declaration and oracle. It owns every required ID, company/market/kind, exact FY/period/as-of/intent/companion/limits, fixture scenario/date/content and credential-presence vector, expected assertions and declared execution scope. Caller-modified required lists cannot remove work; unknown/duplicate/extra cases cannot replace missing cases.
- Fixed assertions re-evaluate actual response meaning rather than trusting PASS/summary booleans. Bound request/response/fixture SHA checks remain; caller changes to expected/scope no longer change which rules execute. Missing new fixture evidence is diagnosed, not filled in retrospectively.
- TDD: original three authority counterexamples 3 FAIL, then GREEN; an additional shared assertion proof flips each of 21 old real FAIL labels to PASS, all 21 RED then GREEN. Mandatory-case property tests cover every one of 41 removals and 41 duplicate/extra replacements; valid full-registry and named single-case positive controls, every original request vector, runner shared object registry and pre-launch drift checks are included. Concentrated package: 195 PASS / 4.42 seconds, Ruff clean.
- Old actual 41-case result stays 19 PASS / 21 FAIL / 1 PARTIAL. Re-audit retains all original response/status bytes and reports 22 required cases not passed + original three intended-stage diagnostics + 40 missing new fixture receipts. Original 19 PASS cases have no new business-assertion error. This repair does not resolve missing source-fact assertions or certify producer completion. No new full matrix/producer/provider/network/model run.
- Old manifest SHA e098e5bca867a33802d8fcf6945af7370bb092aec13a4397be475244c43e1246, original 41 report SHA aa2ab10add76f89e6e259fa0a05c8ad961f562f46b3fd21a1e94c1b2a3acc72f and ZIP SHA dd8fc402a337ef02b3db456a760162f59129c9e7ae5667c62d281294d903bea3 remain unchanged. No producer/scripts/config/CI writes, no commit/install/push, no permissions or manual signoffs added.

### Next Step
ROOT independently verifies the case-authority freeze and three retained counterexamples. ROOT owns producer/source-fact diagnosis and reruns the unchanged 41-case real matrix after prerequisite remediation; author is frozen STOP.
