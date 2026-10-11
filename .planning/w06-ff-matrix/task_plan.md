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
Phase A — 记录旧覆盖矩阵/固定入口，先写 runner oracle 失败向量（RED）

## Next Step
勘察 FF SKILL.md/真实 argv、isolated_wiki、ET private retrieval launcher、CWP open_version/config/load_company_wiki_root，然后写 oracle 失败向量 stub（RED）。

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
