# DU8-FF-MATRIX-COMPLETION

状态：A/B 完成；C 完成但**未达 41PASS**（具名外部根因，未编造）。作者 STOP，待 ROOT 独立验收与合流。
工作目录`C:/Users/郑曾波/Projects/filing-fetch-du8-matrix`；分支`codex/du8-ff-matrix-20261016`；源码基线`e8a85585b4c64a9596e576ff3b73e5c2ee29c334`。

PLAN_ID：`du8-matrix-2026-10-16`；计划目录为本目录，先读施工卡/INTERFACES/findings/progress，不恢复其他根计划。

## A：调查与真实行为RED

Status: complete

读实际源码和历史PWF，明确根因/原正确行为，独立期望先冻结。见 findings.md A.1–A.5。
RED 首份：`python -B -m pytest -q tests/test_du8_matrix_scheduling.py tests/test_du8_matrix_deadline_recovery.py`
→ **8 failed / 18 passed in 3.17s**，收据 `receipts/A-red-baseline.txt`。

## B：所属层实施与集中回归

Status: complete

不跨白名单，不改旧gold/预算/门禁；集中相关快套件一次。
新增纯调度 owner `case_scheduling.py`；`cli_main.py` 接入成本均衡分组 + 具名 stop_reason；README 更新。
集中回归 12 文件 → **333 passed in 52.43s**（`receipts/B-regression.txt`）；Ruff clean。
全仓 15 个失败经纯净基线 `e8a8558` 复现证明**全部既有**，本卡零新增失败。

## C：公开入口E2E、恢复与交接

Status: complete（未达 41PASS，如实记录）

按卡隔离Temp/registry/sentinel，覆盖失败恢复，正常commit后handoff.md/json、冻结STOP，由ROOT合流。

- 真实 41 链两次（公开入口，未改 argv/限额）：21 PASS@174.31s、26 PASS@174.56s。
  调度层完全均衡（52.0/52.0，imbalance 0.0），两次 `stop_reason` 具名。
- 受控中断/恢复端到端：**14/14 检查通过，exit 0**
  （`fixtures/interruption-recovery.json`）：中断 attempt 无成功报告、零泄漏进程、
  sentinel 逐字节保持、第二次用全新目录、restore 完整。
- 负载归一化调度对照：旧 167.33→新 151.22s（run1）、旧 181.14→新 159.98s（run2）。

## Next Step

ROOT 独立验收：核对白名单 → 空载重跑 C 的 41 链 → 决定 OPEN-2（`case_specs.py:490` 的 1s deadline）。
作者 STOP，不并主线、不安装技能、不推远端。

## 固定只读依赖（仅FF）

- `C:/Users/郑曾波/Projects/company-wiki-du6-ff-readonly` @ `f08aa101ab49ca983d3a40356abfb05347f586b3`，只读，不改源码/Git。
- `C:/Users/郑曾波/Projects/earnings-transcripts-du6-ff-readonly` @ `d0ac42c60dcca992db78860b8469cfed3dd527e5`，只读，不改源码/Git。

## Decisions Made

| 决定 | 理由 |
|---|---|
| 成本模型用静态 run 计数，不读历史计时文件 | 矩阵必须能从固定输入复现；机器相关陈旧计时表是隐藏输入，会让同一输入在不同机器产生不同分区 |
| 保留旧分区超窗的 3 个 case 名作为对照证据 | 它们恰好是施工卡记录的上次真实失败集，直接证明修复正对目标 |
| 不提高限额、不裁分母、不重跑到偶然绿 | 施工卡明令禁止 |
| 具名记录 OPEN-1/OPEN-2 而非隐瞒 | `case_specs.py`/`extended_cases.py` 本卡只读；外部负载不在本层可修 |
| 受控中断脚本只判定恢复语义，不判定是否 41PASS | 把“机器忙”和“恢复坏了”混为一谈就是卡里禁止的伪装门禁 |

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| PowerShell 不支持 `python - <<'PY'` heredoc | 1 | 改为写 `.tmp-du8/probe*.py` 文件再 `python file` |
| 新 fixture 脚本 `parents[2]` 解析到 `docs/plans` 而非仓库根 | 1 | 改为 `parents[4]`，并加显式路径存在性核验 |
| 测试断言“持重 case 的组必须更轻”过严 | 1 | 该不变量在近完美均衡下无意义（67.669 vs 67.6635）；改为“不得实质性更重”（≤1%），并注明旧轮转如何失败 |
| Ruff F401/F841/E731 4 项 | 1 | `ruff --fix` + 手工改写 lambda 为 def |
