复核完成，worktree 干净。出具最终复核报告。

# DU10-FF41-CLOSE 独立最终审查报告 — 第二轮（轻量复核）

审查 SHA：`22ef5a14e8b72d840608282e3ed413322cbaa6b2`（相对第一轮 `af3f7a1` 仅一个修复 commit `22ef5a1`），分支 `codex/du10-ff41-close`。复核全程只读：未修改任何 tracked 文件、未提交、未读 `config/FMP_API_KEY.txt` 内容、未发网络/供应商/LLM 请求、未重跑 41 例矩阵。

## 1. VERDICT: APPROVE

四项 findings 全部真实修复且有正向+反向双向证据（v2 fail-closed 拦截与 v3 全绿共同证明门槛非恒真）；保护边界无破坏（tools/ 仅 `matrix_cases.py` 6 行命名改动），受影响测试 42/42 绿、工作树干净。可以进入 handoff.md/json + 清理阶段。

## 2. 逐项修复映射核验

| # | Finding → 修复 | 结论 | 证据 |
|---|------|------|------|
| 1 | [P2] sentinel SHA 实值 → fixture `sha_pairs` + v2/v3 重跑 | **PASS** | fixture 新增 `sha_pairs`（sentinel 与 preexisting_output_entry 的 before/after 实值）写入收据；v2/v3 两收据均含实值且 before==after（sentinel `fc0c0cbe…`、entry `1dbea917…`）；母卡"sentinel 前后 SHA"义务已由 v3 收据满足 |
| 2 | [P2] 门槛可被降级重启通过 → 硬门槛 + fail-closed | **PASS** | 脚本现含 `leg2_completed_clean`（status==completed 且 exit_code==0）与 `restart_all_41_pass`（PASS==41 且 total==41 且 FAIL/PARTIAL/NOT_RUN 全 0），`passed=all(checks.values())` 经逐行核对**无任何排除项**，`restart_case_counts`/`restart_non_pass_cases` 已移出 checks 纯作数据；`transport.ChildFailed` 类真实存在（`scripts/ff_process_transport.py:53`，run_bounded 非零退出即抛）并被显式捕获记录 exit_code/stdout/stderr 尾部。**v2 证实门槛非恒真**：40 PASS/1 PARTIAL、exit 1 的负载退化重启被 `leg2_completed_clean=False` + `restart_all_41_pass=False` 拦下，其余 10 项恢复语义全 True → passed=False 原样保留 |
| 3 | [P3] 测试计数 185/329 → findings A.9 + progress/NEXT_HANDOFF 更正 | **PASS** | A.9 给出分文件明细（5+18+20+14+25+12+35+6+14+161+19=329）并溯源旧 185=「三文件批次 161+19+5」的混淆、progress 旧句 36 为笔误；NEXT_HANDOFF 同步改为"329 passed（独审实测）" |
| 4a | [P3] warm-seed-receipts 互覆 → 按 `artifact_prefix` 命名 | **PASS** | `matrix_cases.py` 唯一改动（+6/-1）：`getattr(ctx,"artifact_prefix","")` 前缀命名；W07 `_SeedProbe` 无该属性 → 默认 `''` → 仍写 `warm-seed-receipts.json`（测试 163 行读该名，通过）；`test_root_du8_matrix_acceptance` 的同名文件是诱饵 fixture 写入，与命名无关，通过。副作用佐证：v1 残留 39 文件 → v2/v3 残留 40 文件（两组收据不再互覆） |
| 4b | [P3] 残留抽样 → 全量 per-file SHA map | **PASS** | `_attempt_residue` 改为 `file_shas` 全量映射；v2/v3 收据 `file_count=40 == len(file_shas)=40`，`residue_not_rewritten` 比较全目录字节哈希（前 12 位可比对一致），"残留未改写"升级为全量证明 |

补充核验：
- **保护边界**：`git diff af3f7a1..22ef5a1 --name-only -- tools/ config/` 仅 `matrix_cases.py`；14 个保护文件、`cli_main.py`、`case_specs.py`、`oracle.py` 零改动；`CASE_TIMEOUT=30 / BATCH_DEADLINE=180 / WORKERS=2 / PROOF_RESERVE_SECONDS=10.0` 逐一 grep 复确认未变；分母（41 CaseSpec）不受影响。
- **v3 全绿主张逐字段核实**：`passed=True`、12/12 checks 全 True、leg2 `144.542s exit 0`、counts `{PASS:41,total:41}`、`restart_non_pass_cases=[]`、`restart_oracle_findings=0`、sha_pairs 相等、残留 40 文件全量一致、临时树移除——与主张完全一致。
- **v2 主张核实**：171.23s 来自 stdout tail（矩阵自报秒数，leg2 壁钟 171.945s，一致）、exit 1、oracle findings=2，恢复语义 10 项全过、仅两硬门槛 false——"fail-closed 实证"成立。
- **测试**：`python -B -m pytest tests/test_du10_ff41_rootcause.py tests/test_w07_matrix_efficiency.py tests/test_root_du8_matrix_acceptance.py -q` → **42 passed in 7.07s**（含 4a 涉及的两个 warm-seed-receipts 消费测试），一次通过。
- **诚实性**：v1 收据保留未删改；A.10 修复映射表与实际 diff 一一对应；`independent-review-round1.md` 为我第一轮报告原样存档；无"真实 provider/财报质量通过"类越权声明。

## 3. Findings

**无。**（两条非阻塞备注，不需修复：a) `interruption-restart-v2.json` 由中间版脚本生成，缺 `restart_non_pass_cases`/`restart_oracle_findings` 两个数据字段——A.11 已如实记录该字段系 v2 之后新增，门槛字段完整，不影响证据成立；b) v2 的 `stderr_tail` 为空串、v3 为 null，系两条返回分支的既有差异，无实质影响。）

## 4. 本轮执行命令摘要

- `git log/status` → HEAD=`22ef5a1`，工作树干净，仅 1 个修复 commit。
- `git diff af3f7a1..22ef5a1 --stat / --name-only / 全文` → 8 文件 +419/-40；tools/ 仅 `matrix_cases.py`(+6/-1)；config/ 无改动。
- 逐行审 `interruption_restart_e2e.py` diff → `all(checks.values())` 无排除、两硬门槛入 checks、ChildFailed 显式捕获、全量 file_shas、sha_pairs 落盘。
- `python -c` 解析 `interruption-restart-v2/v3.json` 的 checks/sha_pairs/counts/leg2 字段 → v2 恰在两硬门槛 false（fail-closed）、v3 12/12 全真。
- `grep` 复核预算常量 4 项未变；`grep warm-seed-receipts tests/` + 读 W07 `_SeedProbe` → 前缀默认 `''` 兼容成立。
- `python -B -m pytest <3 文件> -q` → **42 passed in 7.07s**。
- 收尾 `git status --short` → 干净。

**结论**：4 项 findings 修复映射逐一核实成立，门槛经 v2/v3 双向证据证明真实（既拦得住降级、也过得全绿），保护边界与预算零破坏。VERDICT: APPROVE —— 作者可按母卡流程写 COMPLETE 与 `handoff.md/json`（含独审 SHA `22ef5a1`/本报告、finding 修复映射 A.10、最终 HEAD）并执行临时目录清理（含 FMP key stat 前后对照收据）。