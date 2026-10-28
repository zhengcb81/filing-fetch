# W20-FF-REPLAY 交接报告（handoff）

- 卡：`docs/plans/w20-ff-replay-2026-10-28/construction_card.md`（W20-FF-REPLAY：下载、入库与回执中断的离线恢复反证）
- 工区：`C:\Users\郑曾波\Projects\filing-fetch-w20-replay`，分支 `codex/w20-ff-replay-20261028`
- 基线：`5396bd688e5b775e746fe3290852f0532d4548f8`（与卡一致；实现自该基线推进，见实现提交清单）
- 状态：READY_FOR_ROOT_REVIEW
- 日期：2026-10-28

## 1. 交付了什么

在**不改动 41 例必需 case 权威与无参数完整命令语义**的前提下，为 FF↔ET↔CWP 离线联调矩阵加入六类中断/恢复行为反证：

1. **通用显式 case 选择（`--cases`）**：`case_selection.py`（纯解析/校验/汇总）+ `case_registry.py`（41 必需 + 补充套件的并集解析）。选择运行自标 supplemental：报告带 `scope.selection`（selected/completed/skipped/selected_not_executed/certifies），未选 case 全部具名 `NOT_RUN`（"not selected" 诊断），`required_cases` 恒为完整 41（缩小被 oracle 以 `required_cases_shrunk` 拒绝），退出码 0 只对所选 case 负责。oracle 新增 selection 一致性审计（行缺失/重复/标签错置），并对 harness 真正杀掉的 run 豁免"当时不存在的 ET 回执"（GET 计数与请求/响应字节绑定照常审计）。无 `--cases` 路径语义/兼容不变（既有 232 项矩阵套件全绿验证）；全量报告现无条件新增顶层附加键 `supplemental_cases`（恒为 9 个补充 id，只增不改既有键），字节因此非严格不变。
2. **W20 补充故障套件（9 case，schema `w20-supplemental/1`）**：`w20_case_specs.py`（冻结定义+断言权威）+ `w20_fault_cases.py`（handler）。覆盖：
   - `w20_call_kill_before_durable`：GET 在途时杀 FF 进程树（复用 FF 自有 `ff_process_tree` 语义）→ 无假成功、无持久残留、恢复恰好 1 次下载、最终复用 0 请求；
   - `w20_call_kill_after_import`：规范原件落盘瞬间杀树 → durable-at-kill 分支由恢复运行事后判定（reused=已持久 / downloaded=未持久），最终复用 0 请求；
   - `w20_call_et_truncated` / `w20_call_et_exit_nonzero`：ET 结果流截断 / 完整结果后非零退出 → 具名 `provider_result_invalid` / `provider_result_oversized`（真实子进程路径；seam 路径为 `provider_tool_failed`），无持久、无盲重放、恢复 1 次下载；
   - `w20_call_hash_lie`：ET 谎报 payload sha → CWP 导入端拒绝，FF 具名 `transcript_import_failed`，无假成功；
   - `w20_call_receipt_binding`：旧回执（他人 request_id）/截断回执 → 用量保持 unknown（null 非 0）、调用不吞，回放复用 0 请求；
   - `w20_call_concurrent_same`：两 FF 并发同公司期次 → 无假成功、单一持久版本（并发窗口不承诺 exactly-once 下载）、回放 0 请求；该 case 在单组内有意同时运行 2 个 FF 子进程——这正是被注入的故障本体，不属于调度并发增额（`--workers` 仍 ≤2，两个组各自的组内并发不变）；
   - `w20_filing_kill_recovery`：财报供应商已返回、CWP 导入窗口杀树 → 无持久残留、恢复 1 次 fetch、复用 0 fetch；
   - `w20_filing_concurrent_cross_company`：CN/HK 同年并发年报 → 各自公司/期间绑定互不复用，回放各 0 fetch。
3. **ET test-proxy 边界故障场景**：`truncated_json`、`crash_after_result`、`hash_lie`、`stale_usage`、`truncated_usage`——全部是对真实 ET 结果/回执流的边界后处理（worker HTTP 之下的真实 supervisor/worker 链照跑），产品无 failpoint、无环境变量后门。
4. **harness 清理加固**：`runtime.py` 清理对 Windows 共享锁加有界耐心（20×1s），超限如实失败（不假报 restored）。

**产品 FF 代码零改动**（no-code 结论）：既有行为在全部反证下已正确（具名拒绝、不误复用、不重复下载、用量不吞不造假），交付为回归+矩阵级证据。唯一产品侧记录：真实子进程非零退出落在共享传输失败 reason `provider_result_oversized` 上（seam 路径为 `provider_tool_failed`）——行为诚实但 reason 语义宽泛，列 root_followup 由 ROOT 决定是否单列。

## 2. 冻结代码依赖（R7）

- CWP 视图：`618df929ffa889424b3346d5299d67b9b1c72709`（src+pyproject，403 文件）；
- ET 视图：`2584b7eed062a9a30254bc06b4f19ab5471b414e`（12 文件 AST 传递闭包；该 commit 为 A 阶段只读解析的已提交 main HEAD，= DU11 冻结 ET commit）；
- 构建：DU10 配方 `git -c core.autocrlf=false archive <commit> | tar -x` 到 FF 工区自有 `.w20-deps/`；`git cat-file blob` 全量字节核验 0 不匹配；manifest=`docs/plans/w20-ff-replay-2026-10-28/receipts/dependency-record.json`；
- **拒绝复用 `.du10-deps`**（其 CWP 绑定旧 `900dbf6489`，与本卡冻结 commit 不符）；
- **测试后已删除视图**（cleanup-receipt.json：6,265,876 字节，deleted=true）。CWP/ET 源码全程只读，未动其 git 索引/工作区。

## 3. 测试与证据

单元/契约（全部真实命令，宿主 Python；fast 离线）：
- 新增 `tests/test_w20_replay_selection.py`（12 测）+ `tests/test_w20_replay_faults.py`（10 测）：选择语义 RED 向量（缩 required_cases、重标签、缺行）、双路径 ET 退出分类、hash 谎报、旧/截断回执、proxy 成形函数。
- 既有矩阵套件回归：`test_w06_contract_matrix + test_w06_matrix_runtime + test_w06_case_authority + test_du8_matrix_scheduling + test_du8_matrix_deadline_recovery` = 232 passed（提交 3dd6eb1 后）。
- ruff 全绿（tools/offline_contract_matrix/ 与新测试文件）。

真实链集成（`run.py --cases ...`，真实 FF CLI→真实 ET supervisor/worker（HTTP 边界 fixture）→真实 CWP ensure/import→SourceVersionReader 实读→新进程复用）：
- 17 个 attempt 全录 `receipts/run-receipts.json`。要点：
  - `w20_call_et_truncated`+`w20_call_et_exit_nonzero`：attempt-17a4c68 2/2 PASS、oracle 0 findings；
  - kill_after_import、hash_lie、receipt_binding、concurrent_same、filing_kill_recovery、filing_concurrent_cross_company：attempt-b9d326 5 PASS + 2 FAIL（当次断言缺陷，2ad2677 修复）；
  - 全 9 选择批：attempt-465ac1a/d163ba8 各 7 PASS（其余为当时未修断言/负载）；最终批 attempt-3bb0a6bc 5 PASS + 4 PARTIAL（全部"absolute case deadline exceeded"具名）；
  - base 兼容批（chainA_download_reuse,fin_cn_annual_hit,call_wrong_quarter）：attempt-81af81 选择机制验证，2 PASS + chainA 负载 PARTIAL（其 41/41 PASS 有 DU10 保留证据）。

**宿主负载诚实声明（R6/R8）**：本机全天 2–4× 负载波动（W07 已知共因）。3-run 补充 case 与 base chainA 在**后期**整批窗口间歇撞固定 30s/case 界 → 按设计诚实 PARTIAL（具名原因，绝不假 PASS）。9 个补充 case 每个都有至少一次真实链整链 PASS（单例绿地图见 `receipts/run-receipts.json` single_case_green_map）。按卡 R8 未为追绿重跑超时整批。**部分运行从未冒充 41 例完整通过**。

## 4. 清理

`receipts/cleanup-receipt.json`：代码视图 6.27MB 已删；owned scratch 根 19.5MB 已整体移除（卡前不存在）；保留 17 attempt 证据 4.69MB（小 JSON 工件/报告，位于仓外 `C:\Users\郑曾波\Projects\_w20-runs\out`）。无真实下载/密钥读取/生产写入。

## 5. 已知局限与 ROOT 跟进

- `limitations`：3-run case 在高负载宿主上 30s 界紧张——后期整批窗口出现负载 PARTIAL（矩阵既有诚实语义；每个 case 的整链 PASS 证据见单例绿地图）；W19 结构化三表为独立 CWP 数据服务、无 FF 侧下载/导入状态，与本机制无关（按卡 R4 说明而不强加 case）。
- `root_followups`：(1) ET 非零退出 reason 语义（真实子进程路径归类到共享传输失败 reason `provider_result_oversized`；可考虑单列）；(2) 全量 41 的当日复跑受负载影响，沿用 DU10 安静窗口惯例。

## 6. 兼容性

- 无 `--cases` 的完整命令、报告 schema、oracle 全量路径、DU6 replay 语义全部不变（`required_cases` 恒 41；含 NOT_RUN 的报告仍不可被 replay 认证）。
- `matrix_cases.seed_plan_for` 与 `case_scheduling.static_cost` 改经 union 解析 spec，行为对 41 例不变（套件回归验证）。

## 7. 独立审查

见 `review/initial.md|json`（初审）与 `review/final.md|json`（修复后复审）。初审发现的本范围问题已全部修复；复审最终 OPEN 必须为空。跨仓事项（见 root_followups）如实单列，不计入本范围完成度。
