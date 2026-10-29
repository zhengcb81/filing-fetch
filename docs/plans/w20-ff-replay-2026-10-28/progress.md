# 实施进度

2026-10-28 ROOT只完成工区与施工文档准备，尚未实施本卡或运行测试。三个大节点均未开始；作者接手后按实际记录，交接前必须真实独立agent审查、修复和复审。

## B阶段（作者，2026-10-28）
- 新增 tools/offline_contract_matrix/{case_selection,case_registry,w20_case_specs,w20_fault_cases}.py；et_transcript_proxy加truncated_json/crash_after_result/hash_lie/stale_usage/truncated_usage场景（纯边界后处理）；cli_main加--cases通用显式过滤+supplemental标注+选择运行exit语义（全量路径行为不变）；oracle加selection一致性分支+被杀run回执豁免（GET计数仍审计）；matrix_cases.seed_plan_for与case_scheduling.static_cost改经union解析。41例权威与case_specs.py零改动。
- tests/test_w20_replay_selection.py（12测：解析/校验/汇总/registry健全性/跨公司向量拒绝/oracle选择一致性RED向量/全量路径回归/被杀run回执豁免）+tests/test_w20_replay_faults.py（9测：截断结果/非零退出/旧回执/截断回执/hash谎报的FF侧单元反证+proxy成形函数）全绿；既有w06/du8矩阵套件253测全绿；ruff clean。
- 产品FF零改动（既有行为已正确，单元反证全为GREEN回归，无RED缺陷）。

## C阶段收尾（作者，2026-10-28）
- 全仓套件（tests/ 除 e2e）：1462 passed / 13 failed；13 项经冻结基线 5396bd6 临时 worktree 同命令复判**全部为基线既有**（du11 e2e×6、fc1307a×1、fc803×5、fc501×1），与 W20 改动零关联（receipts/baseline-preexisting-failures.txt）。
- 清理：.w20-deps 视图 6,265,876B 已删；_w20-runs/owned 19,540,614B 已移除；17 attempt 证据 4,685,224B 保留于仓外 _w20-runs/out（cleanup-receipt.json）。
- 独立初审（general-purpose agent）：APPROVE_WITH_FIXES，F1-F9（0 P1）；F1 纠正了作者对 kill_before_durable 的错误记载（attempt-465ac1a/d163ba8 实为整链 PASS）。F1-F9 已全部修复并提交（e07b424 文档修复 + run-receipts/dependency-record/README/handoff 更正）。
- 独立复审（第二个 general-purpose agent）：**APPROVE**；OPEN 3 项 P3 文书（OF1 green_map 从句、OF2 initial.json 成对、OF3 推送精确性）——OF1/OF3 已修复，OF2 由原初审 agent 本人补写 initial.json（作者不代签）。
- 分支已推送 origin/codex/w20-ff-replay-20261028。交接三路径：工区、delivery/w20-ff-replay/handoff.md、handoff.json。

## 返工轮R1收尾（作者，2026-10-29）
- ROOT RETURN_FF 三项全部处理：FF-R1 新增 w20_call_kill_after_durable（durable公开实读确认→同请求返回前杀→恢复0GET同Ref，单跑2ebbf3d7与前序2a273f32双PASS）；mid_import单列（8a972aa6 PASS，durable@kill=False公开观察）；FF-R2 触发器本请求绑定（纯函数+receipt tag+内置unrelated控制反例）；FF-R3 SHA刷新+exit_code=null+解释。
- 排障记录：probe三层修正（redirect_stdin不存在→provider=None被lookup拒→unknown_publication资格排除→绑定Ref而非文本SHA）；mid-import触发器组前缀误加。CWP写入经异步worker，"文件出现"≠durable——kill点设计据此改为durable确认后杀新请求。
- 独立复审（第三个独立agent）：APPROVE，OPEN空；6条非阻塞观察已处理（调试脚本删除等）。
- 最终HEAD f8b86f3 已推送 origin。STOP，等ROOT复验。
