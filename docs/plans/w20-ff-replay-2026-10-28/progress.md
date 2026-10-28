# 实施进度

2026-10-28 ROOT只完成工区与施工文档准备，尚未实施本卡或运行测试。三个大节点均未开始；作者接手后按实际记录，交接前必须真实独立agent审查、修复和复审。

## B阶段（作者，2026-10-28）
- 新增 tools/offline_contract_matrix/{case_selection,case_registry,w20_case_specs,w20_fault_cases}.py；et_transcript_proxy加truncated_json/crash_after_result/hash_lie/stale_usage/truncated_usage场景（纯边界后处理）；cli_main加--cases通用显式过滤+supplemental标注+选择运行exit语义（全量路径行为不变）；oracle加selection一致性分支+被杀run回执豁免（GET计数仍审计）；matrix_cases.seed_plan_for与case_scheduling.static_cost改经union解析。41例权威与case_specs.py零改动。
- tests/test_w20_replay_selection.py（12测：解析/校验/汇总/registry健全性/跨公司向量拒绝/oracle选择一致性RED向量/全量路径回归/被杀run回执豁免）+tests/test_w20_replay_faults.py（9测：截断结果/非零退出/旧回执/截断回执/hash谎报的FF侧单元反证+proxy成形函数）全绿；既有w06/du8矩阵套件253测全绿；ruff clean。
- 产品FF零改动（既有行为已正确，单元反证全为GREEN回归，无RED缺陷）。
