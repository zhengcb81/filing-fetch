# W06-FF-MATRIX：真实三层代码的离线联调和文档矩阵

## Goal
建设显式手动运行、完全独立临时状态的跨仓离线套件 `tools/offline_contract_matrix/`，证明「FF 公开入口 → ET 真实 supervisor/worker/transcript_api → FF 真实 import → CWP 原文注册 → SourceVersionReader.open_version 实读 → 再次 FF 命中缓存」真三层链路，并加文档类型覆盖图。产品源码只读，发现共因交 ROOT。

## 固定依赖
- FF base 08ec85b27133cdf8a8d3b38fdba15255fc1ebac2（本 worktree HEAD）
- CWP 01ea86a37edb5506d6269b6e10d9cb56a1270efd
- ET c91f5f54bc2a24e7b5d6e648dba3f9d578f5fa52

## 排他写集
- tools/offline_contract_matrix/（runner、README、fixture builder、测试代理）
- tests/test_w06_contract_matrix.py、tests/fixtures/w06_contract_matrix/
- .planning/w06-ff-matrix/、docs/handoffs/w06-ff-matrix/

## Current Phase
Case authority engineering repair complete and frozen; ROOT independent reception next. Product integration remains partial.

## Next Step
ROOT reviews the independent case-authority freeze, then diagnoses producer source-fact setup before unchanged real matrix rerun.

## Phases

### Phase A — 记录旧覆盖/固定入口 + oracle RED
- [ ] 勘察 FF SKILL.md/真实 argv、scripts/fetch_filing.py 公开入口、transcript_tool_transport.EarningsTranscriptsTransport
- [ ] 勘察 tests/e2e_support/isolated_wiki.py 三市场复用/缺口能力（只读，不重写）
- [ ] 勘察 ET transcript_tool.main + tests/test_retrieval_cli_e2e.py private retrieval launcher
- [ ] 勘察 CWP source_reader.SourceVersionReader.open_version、config.load_company_wiki_root、cli help 字段
- [ ] 读已有 test_et_s0b_contract.py、test_cwp_s0b_source_ref_contract.py
- [ ] 写 runner oracle 失败向量 RED：整层fake却写real、第二次仍下载、少ET receipt、错cutoff、假0cost、未恢复scratch
- **Status:** in_progress

### Phase B — 实现 fixture/计数器 + runner
- [ ] 小 synthetic 原件 fixture builder（valid PDF/HTML/TXT，元数据 synthetic）
- [ ] provider request/下载/translation 计数器
- [ ] runner：链 A 真三层 + 矩阵 1-5 case
- [ ] 顶层 report schema ff-et-cwp-offline-matrix/1
- [ ] 单元 `python -B -m pytest -q tests/test_w06_contract_matrix.py`
- [ ] 至少一次 FF 真实公开 CLI + 一次 ET 真实 supervisor 子进程
- **Status:** pending

### Phase C — 新 scratch 手动跑 + 交接
- [ ] 新 scratch 跑手动 runner（每 case ≤30s、批次 ≤180s）
- [ ] 保存小型报告/精确日志，关闭 worker/SQLite，恢复 sentinel/baseline
- [ ] 第二次执行新 attempt 不覆第一次
- [ ] handoff.json/handoff.md/manifest.json + 正常 commit
- **Status:** pending

## Decisions Made
- (待补)

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|


## ROOT reception repair — 2026-10-11

Engineering scope is the offline test harness only. No producer scripts, production configs, CI, installed skill copies, Dayu, IQS or original company documents are modified. ROOT owns producer remediation and merge/commit.

1. Preserve independent intake probes and original worker receipts. Freeze exact helper/oracle false positives into formal RED (7 FAIL / 13 PASS). Freeze secret-byte reads, host credential inheritance and pre-existing scratch deletion into runtime RED (3 FAIL / 1 PASS).
2. Shared typed outcome, absolute Deadline, uniquely OwnedAttempt, platform environment allowlist, synthetic HOME/config/key, startup socket deny and translation-factory instrumentation. FF CLI, CWP scan/import/fresh reader and ET supervisor/worker run as actual producer code; fixture replaces only supplier HTTP/adapter response.
3. Required registry: all CN/HK/US × annual/semi/quarterly local hits and missing-period fetch; chain A JSON download/reuse; local TXT reuse; FY-only, cutoff, quarter/symbol, MIME, byte limit, hard timeout, 402, missing credentials, unknown usage, request-after-failure/retry; nonperiodic prospectus/equity/convertible/IR; bad raw SHA/MIME/size; unverified-sidecar gap. Runtime success requires all registry cases PASS and bound file/SHA/fresh byte evidence; PARTIAL/NOT_RUN never exit zero.
4. Initial fixture state must be declared. Scanned sidecar is not an importer-verified warm source. Warm controls use real CWP ensure/CanonicalSourceWriter with supplier fixtures, initial calls recorded separately. Keep original legacy/raw-seed FAIL receipts; do not relabel them as a cross-period producer defect without actual diagnostics.
5. Concentrated focused package: 33 PASS. Actual offline matrix report separately records producer failures; engineering GREEN does not mean producer flow COMPLETE. Final independent reception is ROOT's next large node.

Restore: every attempt creates unique scratch/output children. Only own scratch is removed. Existing files/sentinels/output reports and existing empty directories survive. Initially absent owned parent shape is restored. Retained output is explicitly evidence. Key/config production baseline is stat-only; never digest real key bytes. Hard caps stay 30s/case, 180s/batch and zero paid/provider/model requests.

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
