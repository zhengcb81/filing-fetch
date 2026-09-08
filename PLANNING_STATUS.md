# filing-fetch 当前规划状态

> **CI 推送协议（2026-09-08）**：本仓任何推送都必须走 revenue-forecast 的
> [CI 反复失败根因与根治协议](../revenue-forecast/assurance/runs/2026-09-02_remaining-gap-closure/ci_root_fix.md)：
> 先跑本仓 `python tools/pre_push_gate.py`（CI 等价面 + 安装一致性，绿才推），推送后立即自盯
> GitHub Actions 至绿；若失败面是本门漏掉的，必须同时扩展本页矩阵与该 gate，再推。

> **2026-09-08 当前规划覆盖：R4**。按用户要求，整改的唯一活动编排现为[虚拟数据湖收敛计划](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/simplified-execution-plan.md)，配套[真实测试/审计矩阵](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/simplified-test-matrix.md)与[旧WP迁移表](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/r4-transition.md)。四个增量A/B/C/D及独立收入M取代旧15包/95门执行顺序；原117项、GP和原始负例保留。下方较早“15包/旧总计划为准”仅指当时交付，不再驱动执行。v5继续独占worker正式合同，仅约束对应后台能力，不阻普通本地读取。本次仅文档，没有复验源码/运行状态或授权实施；下方HEAD和daily均为历史观测，未来实施重新锁定输入。

> **2026-09-07最新覆盖**：其他任务继续推进，wiki HEAD=d92f8bf、revenue=6682ecf、filing=89c8bdb。最新daily为20260906T210001Z、ok=false/空triplet；默认观察账本已改到wiki路径，revenue旧ledger的green不可替代。revenue旧closure工具/测试及CI step已实际删除，wiki批3延后，不能再按下方旧快照重复删除或称“只等时间”。详见[并发状态差异与未验证边界](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/current-delta-2026-09-07.md)；下方9/6事实保留为当时观测，相关原反证在新HEAD须独立重验。本轮仅同步文档，没有执行这些代码/删除/运行。

核对日期：2026-09-06。当前效果判定及未实施整改以[三仓原痛点审计与计划](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/README.md)为准。本次用户只批准文档同步/计划细化，未重新运行真实E2E、下载或CI。
代码基线：`89c8bdb2cfba4d88720d005d0558f422957e8ade`；审计前工作区干净。

> **2026-09-08 最新观测修正（本地只读核对）**：调度已连续触发成功（09-06、09-07 22:00），最新 daily=`20260907T210001Z`、period=7；`--run-daily` 参数错误与 manifest `cat-file` 的 `safe.directory` 缺失均已修复（revenue `2ff20d9` / `56ba0eb`）。**FC-705 门仍 close_allowed=false**（权威账本在 wiki `.source_catalog/legacy_periods.json`，待 09-08 22:00 P7 完成）。本仓相关缺口（policy 传递、eligible 副本选择、期间修订、补缺授权/deadline/失败计数、完整 E2E、FC-903 收据不匹配）仍归 WP02/03/04/06/13，未实施。

## 活动计划全量索引（2026-09-08，防遗漏路由）

> 本表是**全部活动计划与审计入口的唯一路由**：任何新计划必须先登记在此，再进入执行讨论。当前**全部整改均为 NOT_IMPLEMENTATION_AUTHORIZED**。

| # | 计划/文档 | 入口 | 状态 | 边界 |
|---|---|---|---|---|
| 1 | **R4 虚拟数据湖收敛计划**（唯一活动编排，44 步：A8/B10/C10/D10/M6+） | [simplified-execution-plan.md](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/simplified-execution-plan.md) | PLAN_ONLY / NOT_IMPLEMENTATION_AUTHORIZED | 每步需精确授权；DR/VR/AR 独立审查 |
| 2 | R4 真实测试矩阵（36 组：L/P/O/M） | [simplified-test-matrix.md](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/simplified-test-matrix.md) | 全 pending | 真实 CN/HK/US 与真实修订需 C 授权 |
| 3 | R4 旧 WP 迁移表（WP00-14） | [r4-transition.md](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/r4-transition.md) | PLANNING_ONLY | 只调归属 |
| 4 | **架构减法诊断**（R4 依据） | [data-lake-simplification/README.md](../company-wiki/docs/plans/data-lake-simplification-2026-09-07/README.md) | 只读诊断已交付 | 未运行真实业务/性能 |
| 5 | R4 接班手册 | [execution-handbook.md](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/execution-handbook.md) | 待授权 | 15 包/逐步检查点 |
| 6-8 | 分面手册（控制面、数据面、模型面） | [control](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/execution-control-plane.md) / [data](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/execution-data-plane.md) / [model](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/execution-model-plane.md) | 待授权 | G0–G5 独立审查；真实动作各自批准 |
| 9 | R2/R3 总计划（15 包，被 R4 取代） | [remediation-plan.md](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/remediation-plan.md) | 历史领域细节 | 不作执行编排 |
| 10 | R4 计划独立审查 | [r4-independent-review.md](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/r4-independent-review.md) | accepted_for_planning_delta | 不授实施 |
| 11 | R4 文档验证 | [r4-document-validation.json](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/r4-document-validation.json) | 文档核验通过 | 非产品测试 |
| 12 | 原目标索引 117 项 | [unit-ledger.md](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/unit-ledger.md) | 53 CONTRADICTED + 58 PARTIAL + 6 HISTORICAL_ONLY | 非生产重跑 |
| 13 | 机器门展开 95 门 | [gate-dag.json](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/gate-dag.json) | 全 pending | 只验计划结构 |
| 14 | 审计报告群 | [filing-audit](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/filing-audit.md) / [assurance-audit](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/assurance-audit.md) / [upstream-asset-audit](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/upstream-asset-audit.md) / [legacy-inheritance](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/legacy-inheritance.md) | 只读审计已交付 | 需独立复核 |
| 15 | 独立审查群 | [assurance](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/assurance-independent-review.md) / [retention](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/retention-independent-review.md) / [plan](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/remediation-plan-independent-review.md) / [consistency](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/document-consistency-review.md) | 历史/计划级 | 不绑定 R4 当前版本 |
| 16 | 并发差异覆盖（9/7） | [current-delta-2026-09-07.md](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/current-delta-2026-09-07.md) | 覆盖 9/6 观测 | 旧反证须新 HEAD 复验 |
| 17 | **Worker v5 独立计划**（V5-1/2/3 pending） | [v5 README](../company-wiki/docs/plans/source-catalog-worker-recovery-v5-2026-09-03/README.md) / [task_plan](../company-wiki/docs/plans/source-catalog-worker-recovery-v5-2026-09-03/task_plan.md) | V5_BASELINE_READY / VERSION_CONTRACT_PENDING / NOT_IMPLEMENTATION_AUTHORIZED | 与主线不合并；H01 为恢复前置 |
| 18 | GP 组（历史执行/批准 + 部署尾项） | [remaining-gap-closure](../revenue-forecast/assurance/runs/2026-09-02_remaining-gap-closure/task_plan.md) | 历史 + 部署尾项 | 不并行领取；旧批准不扩为新许可 |
| 19 | 文档同步（9/4，历史） | [planning-sync-2026-09-04](../company-wiki/docs/plans/planning-sync-2026-09-04/task_plan.md) | 历史交付 | 历史 hash 库存非当前合同 |

**登记纪律**：新增计划/审计目录必须先在上表登记入口与边界，再进入任何执行讨论；未登记的计划视为未授权。

## 状态入口与全部规划文件处置

- 根 `task_plan.md`、`findings.md`、`progress.md` 由 [TERMINAL_NOTICE](TERMINAL_NOTICE.json) 标为 `closed_superseded_incomplete`，原文保留，不是活动队列。旧8/9 FCAP是中间接管入口。
- [统一机器账本](../revenue-forecast/assurance/unified_completion/state.json) 当前记录 `plan_status=completed`、`implementation_status=completed`、117/117 units accepted；只是账本读取，不是本次复跑117项及全部依赖收据验收。
- [GP计划](../revenue-forecast/assurance/runs/2026-09-02_remaining-gap-closure/task_plan.md)保留历史执行和批准记录；新的效果缺口统一路由到[15包修复计划](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/remediation-plan.md)，不重复领取。GP-008参数已在2ff20d9修复，但实际部署证据/真实roots CI/生产语义尚未全面关闭。
- [E2E设计](e2e/E2E_DESIGN.md) 已按当前 companies-root reuse-only 实现收窄；它不是完整三仓全链路保证。
- `assurance/fc/FC-903/03_change_contract.md`、`REVIEWER_REPORT.md`及两个receipt为历史审查证据，保持原字节；其范围不覆盖当前HEAD所有后续变更。
- 递归源码目录与Git清单仅发现一组三件套；缓存/运行生成物不是活动规划。完整9份732行阅读覆盖和支持代码证据见 [独立审计](../company-wiki/docs/plans/planning-sync-2026-09-04/filing-fetch-audit.md)。

## 历史矛盾的当前解释

9/6[逐项filing审计](../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/filing-audit.md)确认policy传递、eligible副本选择、期间修订、补缺授权/deadline/失败计数及完整E2E仍有缺口，对应WP02/03/04/06/13。117 accepted只作历史登记，不能再解释为原完整目标全部解决。现有synthetic harness保留为T1，真实文件、真实生产入口和真实provider的E2E另列，不以改golden或合成fallback关闭。

根文档的66/113 tests、96% coverage、未提交、无pyproject、当前基线及D1–D15缺陷清单均属历史。HK早期阻断已在后文追记FY2025修正后跑通；不重复记为当前阻断，也不把旧成功当今天已通过。

FC-903存在 `receipt_binding_mismatch`：reviewer所指implementer SHA256为 `010d0b9e9f4547ef2a71d9e7b47a90eb768744c8dca4825fe6b32ea157bdb3df`，当前文件为 `010699cab407eb20aafd7f985ed494e262d84f2fd0c3c479e83c2c1ed96f089d`。CRLF转LF后仍不匹配；原因与原始签署字节需后续独立核对。本次不改收据、重签或撤销旧verdict，不能声称当前两文件形成完整互证链。

## 校验与限制

- 只读 `python -B tools/verify_plan_claims.py --plan task_plan.md --progress progress.md --json` 返回exit 0、ok=true，但只识别Phase 1/2/3/5/6，漏掉带HK环境阻断后缀的Phase 4；不是全面闭环证明。
- 本地pre-commit现用ruff/mypy轻量检查，旧`.githooks`全量脚本未被core.hooksPath选用；完整测试另行执行。
- 本次不修改代码、安装镜像、生产配置或机器任务，不启动worker，不更改Git全局设置。源项目下一步修复需另外授权；本页不是重开旧计划的指令。
