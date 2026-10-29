# W20-FF-REPLAY 交接报告（handoff）

- 卡：`docs/plans/w20-ff-replay-2026-10-28/construction_card.md`（W20-FF-REPLAY：下载、入库与回执中断的离线恢复反证）
- 工区：`C:\Users\郑曾波\Projects\filing-fetch-w20-replay`，分支 `codex/w20-ff-replay-20261028`
- 基线：`5396bd688e5b775e746fe3290852f0532d4548f8`（与卡一致；实现自该基线推进，见实现提交清单）
- 状态：READY_FOR_ROOT_REVIEW
- 日期：2026-10-28

## 1. 交付了什么

在**不改动 41 例必需 case 权威与无参数完整命令语义**的前提下，为 FF↔ET↔CWP 离线联调矩阵加入六类中断/恢复行为反证：

1. **通用显式 case 选择（`--cases`）**：`case_selection.py`（纯解析/校验/汇总）+ `case_registry.py`（41 必需 + 补充套件的并集解析）。选择运行自标 supplemental：报告带 `scope.selection`（selected/completed/skipped/selected_not_executed/certifies），未选 case 全部具名 `NOT_RUN`（"not selected" 诊断），`required_cases` 恒为完整 41；补充套件现为 11 个（R1/R2 各增 1）；（缩小被 oracle 以 `required_cases_shrunk` 拒绝），退出码 0 只对所选 case 负责。oracle 新增 selection 一致性审计（行缺失/重复/标签错置），并对 harness 真正杀掉的 run 豁免"当时不存在的 ET 回执"（GET 计数与请求/响应字节绑定照常审计）。无 `--cases` 路径语义/兼容不变（既有 232 项矩阵套件全绿验证）；全量报告现无条件新增顶层附加键 `supplemental_cases`（恒为全部注册的补充 id，现 11 个，只增不改既有键），字节因此非严格不变。
2. **W20 补充故障套件（现 11 case，schema `w20-supplemental/1`；R1/R2 各增 1）**：`w20_case_specs.py`（冻结定义+断言权威）+ `w20_fault_cases.py`（handler）。覆盖：
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

**宿主负载诚实声明（R6/R8）**：本机全天 2–4× 负载波动（W07 已知共因）。3-run 补充 case 与 base chainA 在**后期**整批窗口间歇撞固定 30s/case 界 → 按设计诚实 PARTIAL（具名原因，绝不假 PASS）。补充套件每个 case 都有至少一次真实链整链 PASS（绿地图见 run-receipts.json；R1/R2 新增两例各以其自身 attempt 为证）（单例绿地图见 `receipts/run-receipts.json` single_case_green_map）。按卡 R8 未为追绿重跑超时整批。**部分运行从未冒充 41 例完整通过**。

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

---

## 返工轮 R1（2026-10-29，ROOT RETURN_FF 三项全部处理）

ROOT 验收结论 CHANGES_REQUESTED（ff-review.md：FF-R1/P2 durable 后分支未证、FF-R2/P2 触发器被旧 sidecar 误触发、FF-R3/P3 两处机器字段失真）。本轮在原分支续改（RED→修复→真链复验→独立复审）：

**FF-R1（durable 后中断独立确定性证明）**：新增 `w20_call_kill_after_durable`（schema `w20-supplemental/1`，补充套件 9→10）。确定性设计（CWP 写入经异步 worker，"sidecar 出现"≠durable，故不再猜杀点）：
1. run0 正常完整采集（1 GET）建立 durable；
2. **公开接口实读确认**：`cwp_public_readback` 经与 FF 复用链相同的 provider-scoped transcript-lookup envelope（`source_query_cli` in-process）+ `SourceVersionReader.open_version` 实读，逐字节 SHA 比对 **run0 响应中的本请求 Ref**（f1778c54…），有界重试窗口确认后才继续；
3. run1 发起同请求、在其返回送达前杀树（0 GET、无 envelope——durable 后回执/返回中断）；
4. run2 恢复复用：**0 额外 GET**、Ref/SHA 与实读证明相同；再次复用 0 GET。
断言拒绝 not_durable 代签（恢复若再下载/1 GET 即 FAIL；RED 测试 `test_durable_assertions_reject_a_not_durable_recovery_proxy` 固化 ROOT 反例）。真链：单跑 attempt-2ebbf3d7 **PASS/oracle 0 findings**；前序窗口 attempt-2a273f32 **PASS**。未 durable 路径单列：原 `w20_call_kill_after_import` 保留 id，scope/expected 改为 `interruption_phase: "mid_import_observed"`，触发器改为本请求 ET receipt 文件（ET 完成、导入未始的确定窗口），并加 `durable_at_kill_public_readback` 公开实读观察（必须 False）；单跑 attempt-8a972aa6 **PASS**。三 kill case 相位谱：pre-GET（before_durable）/ post-ET-pre-import（mid_import）/ post-durable（after_durable）。

**FF-R2（触发器绑定本请求）**：新增纯函数 `new_original_matching_sha`（只认"新增且字节 SHA 等于本 case 内容"的 original；旧期次 sidecar/original 永不触发——RED 测试固化 ROOT 探针反例）；durable case 的触发器=公开实读确认 + handler 内预置 unrelated-period original 作内置控制反例（文件存在但 DB 无记录，永不能触发）；mid-import 触发器=本请求 receipt tag。阶段一致性：before_durable 与 mid_import 单跑 PASS（afb227f2/8a972aa6），前序窗口下 run0/run1 阶段观察一致（attempt-36e764e9：killed[0]=True 于本请求触发、恢复恰好 1 次下载；仅第三段复用被 30s 界截断，该段由单跑 PASS 证明——按 R8 不追跑）。

**FF-R3（机器字段）**：run-receipts.json SHA 刷新；全仓 pytest 行 exit_code 改 `null`+解释（真实退出码未在运行时记录，不重建；pytest 有失败必非 0，13 项基线失败归因保留，全仓并非绿）；受审 13+2 文件 SHA 全部重算匹配。

**诚实修正**：原 4 份 kill_after_import PASS 的真实含义=not_durable 分支（ROOT 判定），历史报告保留不改写；"R3 已完成"声明收缩为两阶段分别证明。probe 走的 provider-scoped envelope 与 FF 复用链相同（unknown_publication 资格 source 也在公开查询可见范围），实读=open_version 字节级校验。

本轮新增：`tests/test_w20_replay_return_r1.py`（6 测，RED 先行）；修复提交 b7a649c→3747e4a；260 项矩阵/单元套件回归全绿；清理：本轮重建的 .w20-deps 视图与 owned scratch 已再删除（cleanup-receipt.json 更新）。

---

## 返工轮 R2（2026-10-29，定点补完）

ROOT 第二轮（w20-reception-r2）：FF-R2-1/P2 关键场景须为"同一次采集的成功返回被截留"而非"已有原文后杀新重试"；FF-R2-2/P2 公开读回探针线程隔离与三态区分。

**FF-R2-1（关键场景重做）**：新增 `w20_call_lost_reply_after_durable`。**同一次真实新增采集**贯穿全程：run0 走完真实链（下载→durable→成功 envelope 产出），harness 在**自有 transport 输出边界截留该 envelope**（trace 标 `reply_intercepted=True`——作为证据消费、绝不作为成功交付客户端），其间公开 query+reader 实读确认**同一 Ref/SHA**（`verified_at_reply_loss`，provider-scoped lookup envelope + `open_version` 字节级比对）；run1 首次恢复 **0 额外 GET**、Ref/SHA 相同；run2 复用 0 GET。不变量断言拒绝 ROOT 反例代签：run0 已成功交付（无截留标记）+ 后续空杀 → FAIL（RED 测试固化）；Ref 漂移 → FAIL。服务端已处理完、响应传输层丢失的形态被明确允许；无微秒级杀点、无 CWP failpoint、不承诺 exactly-once。真链：attempt-dd7884e1 **PASS/oracle 0 findings**。旧 `w20_call_kill_after_durable` 保留为**对照**（scope 明示 CONTROL ONLY，prior-delivery + re-request-kill），probe 修复后复跑 attempt-248e9d19 **PASS**。

**FF-R2-2（探针隔离）**：`cwp_public_readback` 整体重做为 `probe_catalog`——**每次调用一个有界子进程**（`cwp_readback_probe.py`），父进程 `sys.stdin/stdout` 零触碰、无模块级 last_error、结果/错误归本调用；结果三态显式：`confirmed`（本请求 Ref 字节级实读确认）/ `not_found`（公开查询正常应答但非本 Ref）/ `probe_error`（探针自身失败——**永不可当"公开确认未 durable"的负证据**）。有限测试覆盖：两公司/两资料根并发不串（真 catalog、ThreadPoolExecutor）、catalog 不可用=probe_error（非 not_found）、父进程 stdio 不变、丢失 wiki/非0 返回=probe_error。真链代表运行全部通过。

**排障记录（诚实留痕）**：子进程版 probe 曾 `no_local_match`——根因是实现时丢失了 R1 的 envelope 包装（plain query 的 as-of 资格排除会隐藏未来期次的已存储原件）；恢复 provider-scoped lookup envelope 并让 probe 使用矩阵合成子进程环境（与其它 CWP 子进程一致）后，lost-reply 与对照 case 均 PASS。诊断用一次性 scratch 拷贝 wrapper（不入 git），已连诊断副本一并删除。

**收尾项**：handoff 计数同步（supplemental 11、union 52）；cleanup-receipt 的布尔字段歧义改为显式含义说明。本轮新增 `tests/test_w20_replay_return_r2.py`（7 测，RED 先行）；267 项套件回归全绿。
