## ROOT 接收更新 — 2026-10-17

最终实现/复审已通过，详情 [ROOT_RECEPTION](ROOT_RECEPTION.md)。正常主线发布后以母 PWF 的远端 SHA 为准；下方旧状态是作者历史。

# Task Plan — DU10-FF41-CLOSE

- 卡：完成 filing-fetch 固定 41 例端到端矩阵（关闭 DU8 遗留 C）
- 仓库：`C:/Users/郑曾波/Projects/filing-fetch-du10-41-matrix`（worktree）
- 分支：`codex/du10-ff41-close`；起点 main `c7c8867da35cd19d4f419fa70947332615e8e9c0`
- 母卡：`company-wiki/docs/plans/document-understanding-2026-10-13/parallel/du10-2026-10-17/du10_ff41_close.md`
- Python：3.13.9（`C:\Miniconda\python.exe`，`python` 即此）

## 确切 OPEN（不可改述）

1. 既有记录 `20 PASS / 0 FAIL / 4 PARTIAL / 17 NOT_RUN`（173.27s，DU8 ROOT 实跑）→ 需要一次按固定
   case 定义/oracle/预算（case≤30s、batch≤180s、workers≤2、proof reserve 10s）的完整实跑。
2. 完整矩阵中断后重启恢复为 NOT_RUN → 需要受控中断、重启、继续/停止、清理 E2E。

## 固定不可变

- 41 CaseSpec + oracle（`case_specs.py`、`oracle.py`、`matrix_outcome.py`、report schema 只读）。
- CASE_TIMEOUT=30 / BATCH_DEADLINE=180 / WORKERS=2 / PROOF_RESERVE_SECONDS=10 不上调。
- 只读依赖（固定提交，测试前后记录）：
  - CWP `900dbf6489f3b995a0bfb7fcbb8a001a68df241d` → 快照 `C:/Users/郑曾波/Projects/.du10-deps/cwp`
  - ET `7d06777e250ee3f7ae58f0be2cee62944bd2c104` → 快照 `C:/Users/郑曾波/Projects/.du10-deps/et`
  - 由 `git archive <commit>` 提取，无 .git，不写不更新；ET tests seam（`tests/__init__.py`、
    `test_retrieval_runtime.py`、`test_transcript_api.py`）已确认在快照内。
- 不碰 `config/FMP_API_KEY.txt`（只 stat）；不改 CWP/ET/Dayu/provider 生产脚本；
  0 真实网络 / 0 LLM / 0 翻译；原主树未跟踪文件字节不变。

## 写范围

`tools/offline_contract_matrix/` 内最小根因代码；新 `tests/test_du10_ff41_*.py`；专属 fixtures；本 PWF 与 receipts。

## 节点

### A — 固定基线与失败复现
- [x] 盘点当前 main 实现（cli_main/run/runtime/matrix_cases/case_scheduling/measurement/oracle/extended_cases/seed_batch/source_proofs/report/fixture_builder/case_specs）
- [x] 历史状态记录：DU8 ROOT `ff-root-full41.json`（173.27s；binding 15.54、seed 61.66 累计、ff_cli 241.93 累计、197 boots）
- [x] 基线实跑一次（今日机器，当前 main 代码，固定 argv）→ 真实 41 分母 + 阶段计时
- [x] RED：fake clock 行为级复现确证的重复准备（两组各自全量 seed；两组各自 fresh-proof boot）

### B — 根因修复
- [x] 每组 seed 只覆盖本组 case 固定消费的 warm 项（各组仍走真实 ensure writer；union=全量，覆盖不缩水）
- [x] fresh source proof 合并为单 helper 进程（逐组 part 保留、merge 语义不变）
- [x] 窄回归 `tests/test_du10_ff41_*.py`；既有 DU8/W07 测试保持全绿

### C — 完整端到端与恢复
- [x] 新独立测试根串行实跑完整 41 例一次（workers=2 固定默认），保存每 case 真实结果/总耗时/分阶段
- [x] 受控中断（0→新增 GET 观察）→ 树回收 → 重启新 attempt → 完整完成 → 清理 E2E
- [x] 只有 41/41 PASS 且恢复行为通过、sentinel/原目录准确恢复才标记完成；否则保留真实结果

### 独立审查与交接
- [x] 冻结 HEAD 后另派独立审查 agent（复核 diff/边界/分母/预算/恢复/日志真实性）
- [x] handoff.md/json + 紧凑 receipts

## 完成标记（2026-10-17）

全部节点关闭：A（基线+RED）→ B（seed 子集化）→ C（41/41 PASS 97.68s + 恢复 E2E v3 12/12）
→ 独立审查两轮（REQUEST_CHANGES→修复→APPROVE 零 findings）→ handoff.md/json + 清理收据。
详见 handoff.md；状态 COMPLETE。
