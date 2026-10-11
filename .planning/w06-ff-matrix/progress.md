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
