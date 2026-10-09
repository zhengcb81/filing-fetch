# FF consumer progress

2026-10-09

1. 读现有 MAIN phase6 PWF、producer/consumer boundary review 及 FF 原 runtime/tests；FF 根 AGENTS.md 不存在。隔离 worktree base main a1f3e4f，branch codex/company-pool-failure-consumer-20261009。
2. 初始新契约 RED：46 failed / 23 passed / 0 errors；首次未创建 basetemp parent 的 3 个 setup errors已纠正，未计为代码 RED。
3. producer返回型GAP补充 RED：4 failed / 3 passed（69 deselected）。
4. 第一轮相关集中包230 passed /1 failed /1 skipped /39 subtests；第二轮237 passed /1 failed /1 skipped /39 subtests。唯一FAIL是长基目录 ET真实import文件路径；无断言放宽。
5. 短自有 TEMP 根集中 GREEN：238 passed /1 skipped /39 subtests，24.98s；跳过 production security-master snapshots 实盘样本，真实 synthetic ET→CWP import/reuse已跑通。临时根恢复true。
6. typed start failure调用方兼容 RED 1 FAIL，继承OSError收敛后相关4 PASS；完整最终复跑与跨CLI联调待 producer ready 后同节点完成。
7. ruff changed files通过；mypy四runtime文件通过；git diff --check通过。未提交/并线/推送，主仓和NVDA初始执行不变。

8. FINAL集中 GREEN：239 passed /1 skipped /39 subtests，22.22s；确切skip tests/test_fetch_filing.py:1636 production security-master snapshots not present，Windows Job/ET真实import正常执行。短TEMP context恢复true。
9. 实际FF CLI→稳定CWP producer→本地bounded fake provider25/25 PASS；provider诊断、返回失败GAP、成功import、reuse无下载、原件SHA不变。第一轮23/24的FAIL为测试错误把CWP已有3fetch策略当FF重试；核对actual SourceAcquisitionService._stage_with_retry range(3)后精确断言FF calls2、provider starts4（1discovery+3计量fetch），不使用>=放宽。
10. FINAL Ruff、mypy4runtime、diff--check全绿。独立 worktree .test-tmp/.pytest_cache/__pycache__均安全清理；短TEMP端到端根已自动删除。只保留10.98KB联调proof及PWF。
11. 开发者单线工作完成；root仍须统一RF→FF→CWP联调/代码审查、commit并线、安装及CI，不把本lane的GREEN等同整体计划完成。

## Complexity diagnostic / CI follow-up (2026-10-09)

1. Audited absent root AGENTS, current PWF, .githooks, pre-commit, pre-push, quality.yml and all literal complexity-policy references; no business files modified.
2. RED: old ratchet1 FAIL/1 PASS (ff_provider_cause14>10), new diagnostic contracts7 FAIL/0 collection errors before implementation. Evidence complexity_red.json; short TEMP restored.
3. Implemented tools/complexity_diagnostics.py; deleted old65-line score gate; added7 diagnostic tests and focused CI contracts. Historical10/34/39 unchanged; score14 remains visible and exit0. Bad syntax/read error exit1.
4. GREEN: seven diagnostic tests; exact modified YAML focused selection527 PASS/5 SKIP/78 subtests in53.50s. Ruff0.15.18 all four CI roots PASS; mypy1.19.0 public two modules PASS. Current source diagnostic exit0, ff_provider_cause14 above_reference=true. Evidence complexity_green.json.
5. Supplemental exact2 formerly skipped CWP cases:2 PASS in16.65s, candidate root/src explicitly configured, all state in owned short TEMP. compileall, import smoke, zero duplicate test symbols PASS. Evidence complexity_cwp_and_syntax.json. This is not a second full suite; do not add duplicate pass totals.
6. Remaining skips: tests/test_fetch_filing.py:1636 two unavailable production security-master snapshot cases; tests/test_bundle_compat.py:156 Windows symlink unsupported. Assertions unchanged. All three temporary roots absent after finally; raw/config/installed writes0, paid calls0, external fees0.
7. Ready for normal-hook local commit; root owns push, exact-SHA CI observation, merge and installation. Canonical proof complexity_ci_proof.json; no NVDA report or other repository edits by this card.
