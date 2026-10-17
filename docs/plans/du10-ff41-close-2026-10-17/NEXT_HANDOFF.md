# NEXT_HANDOFF — 恢复后必做事项

本卡 DU10-FF41-CLOSE 在节点 A/B/C 全部完成、修复已 commit 时，作者会话因 5 小时
额度熔断中止（`exec exec_…` 返回 `Usage limit reached`）。本文固化剩余事项
与精确恢复指令，**下一个会话不得跳过/改动已完成节点**，只需按下面顺序收尾。

## 当前状态（已 commit）

- 仓库 worktree：`C:/Users/郑曾波/Projects/filing-fetch-du10-41-matrix`
- 分支：`codex/du10-ff41-close`；HEAD `bb60678`；基线 `c7c8867`
- 工作树干净（`git status` 无未提交改动）
- 提交 `bb60678` 内容：
  - 工具改动：`tools/offline_contract_matrix/matrix_cases.py`、`cli_main.py`
    （最小 diff：新增 `_warm_seed_list`/`TXT_SEED_KEY`/`warm_consumption`/
    `seed_plan_for`；`seed_all` 读 `ctx.seed_cases`；`run_case_group` 写入本组
    case ids；`cli_main` 无其它变更）
  - 新测试：`tests/test_du10_ff41_rootcause.py`（5 个测试，作者声明全绿）
  - 新 PWF：本目录 + `receipts/` + `fixtures/interruption_restart_e2e.py`
- 修复后关键数据（保留证据，不是新跑）：
  - C-1 完整实跑 `41/41 PASS, 97.6772s/180s, oracle 0 findings, restore=True`
    `receipts/final-run.json`，报告 SHA `a0dd3c1a…d83da`
  - C-2 恢复 E2E `passed=True`，中断腿在 chainA run1（0→1 GET）、重启腿
    `41/41 PASS, 126.767s, exit 0`、sentinel/既有条目/临时树全过；
    `receipts/interruption-restart.json`
  - 既有 11 套件 185 passed（作者声明，未经独审独立复跑）

## 待做（按序，不可并行）

### 1. 独立最终审查（**不**由作者兼任；必须新开 `general-purpose` subagent）

参照任务原 agent 提示词（本次失败前最后发出的完整 prompt 仍在 ZCode 会话
历史中；如下不可访问则按本节细则重建）执行：

- 复核 `git diff c7c8867..bb60678 --stat` 与全文，保护边界与分母不变
- 验证 RED：在 scratch worktree 用 `c7c8867` 覆盖 `matrix_cases.py`/`cli_main.py`
  后跑 `tests/test_du10_ff41_rootcause.py`，确认 2 个行为级 + 1 个 API 失败
- 验证 C-1 证据：`C:/Users/郑曾波/Projects/.du10-tmp/final-out/attempt-1ce035cefbc2469688e684a0d64d637a/report.json`
  41 cases 全 PASS、SHAs 一致、oracle 干净、restore 干净、seed 接收数 g1=5/g2=6
- 验证 C-2 证据：脚本与 receipt 的"非伪造通过"路径
- 验证依赖快照：`C:/Users/郑曾波/Projects/.du10-deps/{cwp,et}` 字节等于
  `git cat-file blob <commit>:<rel>`（抽样 5+3 文件）
- 跑指定 11 个测试文件（**不要跑全仓**），期望 185 passed
- 输出格式：`VERDICT: APPROVE|REQUEST_CHANGES` + 逐项结论表 + findings 列表
  + 实际执行命令与关键输出摘要（按本卡母卡"独立最终审查"节要求）

不可重跑完整 41 例（机器负载波动大，DU8 已证）。审查员只用既有 receipts/脚本。
审查员不得 commit/push；不读 `config/FMP_API_KEY.txt`。

### 2. 写 handoff.md / handoff.json（独立 commit）

`docs/plans/du10-ff41-close-2026-10-17/handoff.{md,json}`，与 DU8 同 schema
（`du10-handoff/1`）。字段最小集：

- `card_id = "DU10-FF41-CLOSE"`
- `base_commit = "c7c8867da35cd19d4f419fa70947332615e8e9c0"`
- `branch = "codex/du10-ff41-close"`
- `implementation_commits = ["bb60678..."]`
- 任何审查后修复的提交
- `changed_paths` 列表（事实从 `git diff c7c8867..HEAD --name-only` 取）
- `interfaces`：入口/输入/输出/未变（与 DU8 对齐：entrypoint、41 CaseSpec 冻结、
  固定 CWP 900dbf64 + ET 7d06777e、case≤30s/batch≤180s/workers≤2/proof 10s 不变）
- `evidence_paths`：列出本目录 `receipts/*.json` + `fixtures/interruption_restart_e2e.py`
- `scope_proves` / `scope_does_not_prove`：明确不声称真实供应商/财报质量通过
- `independent_reviewer` + `verdict` + `review_commit`

### 3. 清理临时目录（独立 commit：仅 `progress.md` 一处更新 + `du10-tmp-cleanup.json` receipt）

只清本卡私有临时：
- `C:/Users/郑曾波/Projects/.du10-tmp/`（基线/最终/C-2 报告 + 尝试性 worktree）
- 恢复后产生的任何 scratch worktree（如果审查员建了 `git worktree add` 到其它路径）

**不要**删 `C:/Users/郑曾波/Projects/.du10-deps/`（依赖快照是确定的可复现输入，
如需重建见下"快照重建"）。

主仓、DU8 worktree/分支、其他 lane 目录一概不动。

### 4. 快照重建备忘（如需重新提取）

- CWP：`cd C:/Users/郑曾波/Projects/company-wiki && git -c core.autocrlf=false
  archive 900dbf6489f3b995a0bfb7fcbb8a001a68df241d | tar -x -C
  C:/Users/郑曾波/Projects/.du10-deps/cwp`
- ET：`cd C:/Users/郑曾波/Projects/earnings-transcripts/earnings-transcripts
  && git -c core.autocrlf=false archive 7d06777e250ee3f7ae58f0be2cee62944bd2c104
  | tar -x -C C:/Users/郑曾波/Projects/.du10-deps/et`
- 不要用 `git archive`（默认会因 `core.autocrlf=true` 把 LF 文件 CRLF smudge，
  与 EOL 等价证明不冲突，但全树逐字节不再匹配 blob；如需 byte-exact 见
  `dependency-eol-equivalence.json`）。

## 已知禁项（与母卡一致）

- 不提高 case/batch/workers/proof reserve 任一上限
- 不删/换 case 或 oracle
- 不读、不改 `config/FMP_API_KEY.txt`（只 stat）
- 不改 CWP/ET/Dayu/生产脚本
- 不发真实网络/供应商/LLM 请求
- 不重跑完整 41 例（机器负载敏感）
- 不把工程并线写成完整 41 PASS（无审查前不可；审查 APPROVE 后方可）
- 不在 `C:/Users/郑曾波/Projects/filing-fetch` 主仓上 push（review 完成后
  单独走正常并线流程）
