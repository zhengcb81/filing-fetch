# DU10-FF41-CLOSE 独立最终审查报告 — 第一轮（原样存档）

审查 SHA：`af3f7a14486d83ac6c3a3f63cbfad427e200ccd9`（实现 `bb60678`，文档 `cb7e2fb`/`af3f7a1`），基线 `c7c8867da35cd19d4f419fa70947332615e8e9c0`。审查全程只读，未修改 worktree 任何 tracked 文件、未提交、未读 `config/FMP_API_KEY.txt` 内容、未发网络/供应商/LLM 请求、未重跑 41 例矩阵。

## 1. VERDICT: REQUEST_CHANGES

代码与全部实跑证据均核验为真（1–5 项 PASS），但母卡"交接"节明确要求的 receipts 内容有实质缺口（sentinel 前后 SHA 实值缺失），且 C-2 脚本的 pass 门槛不校验重启腿结果完整性——正是任务点名要排查的"可被降级通过"路径。两项均只需改 docs 下 fixture/receipt（不触碰保护代码），修复后按最终 SHA 轻量复核即可转 APPROVE。

## 2. 逐项结论表

| # | 项目 | 结论 | 证据 |
|------|------|------|------|
| 1 | 完整 diff 与保护边界 | **PASS** | `git diff c7c8867..af3f7a1 --stat`：tools/ 下仅 `matrix_cases.py`(+96/-12)、`cli_main.py`(+7) 改动，14 个保护文件全部零改动；`CASE_TIMEOUT=30`(run.py:43)、`BATCH_DEADLINE=180`(:44)、`PROOF_RESERVE_SECONDS=10.0`(:49)、`WORKERS=2`(cli_main.py:32)、`--workers choices=range(1, WORKERS+1)`(=range(1,3)) 均未变；case_specs.py/oracle.py/matrix_outcome.py 零改动且 `case_specs()` 恰 41 个唯一 id（ids-sha256 `2e774563…bcbdd`，与 report 一致）；`config/FMP_API_KEY.txt` 不在 diff、main 树 stat mtime=2026-09-27（早于本卡）；CWP/ET/Dayu 生产脚本不在写范围（diff 仅本仓 16 个文件） |
| 2 | 根因修复正当性 | **PASS** | `warm_consumption` 仅从冻结 CaseSpec 的 reuse_only filing/companion 行推导键；独立脚本验证 41 case 全量 union=恰好 10 个 warm ensure+TXT（`union==full: True`），消费缺口键 `(CN,annual,2030,FY)`/`(CN,annual,2032,FY)`/畸形请求 `(US,annual,None,None)` 均不在固定清单、永不 seed；按静态成本模型复算分组=实跑一致（g1=5 ensure 无 TXT、g2=6 ensure+TXT，`us_annual_2025` 两组重叠 1 项故 union=10），与 `g1/g2.seed-batch.stdout.json`（5/6 行，tags 逐一吻合）一致；每个被消费 seed 仍经 `ctx.warm_seed_batch(seeds)` 走真实 ensure writer（receipts 显示 `in_process_cli_service_single_helper`、真实 ensure argv、exit 0）；`getattr(ctx,"seed_cases",None) is not None` 否则回退历史全量，W07/DU8 钉死的 `seed_all(ctx)` 单参调用兼容（W07 全量断言测试通过） |
| 3 | RED 真实性 | **PASS** | 我自建 `git worktree add --detach .du10-review-tmp/baseline-wt c7c8867` + 植入 HEAD 测试文件复跑：**3 failed / 2 passed**，与 `A-red-baseline.txt` 逐名吻合——行为级 `test_each_group_warm_seed_batch_covers_only_its_consumed_keys`（两组全量 seed 断言失败）、行为级 `test_txt_transcript_seed_lands_only_in_the_group_that_consumes_it`（`g1.: local TXT seed present=True, expected False`）、API 级 `test_seed_plan_for_rejects_unknown_case_ids`（`AttributeError: no attribute 'seed_plan_for'`）；同一文件在 HEAD worktree 5/5 通过（含于第 5 项套件）。临时 worktree 已删除 |
| 4 | 节点 C 证据真实性 | **PASS**（附 2 条 P2 见 findings） | C-1：`report.json` SHA256=`a0dd3c1a…d83da` 与 `final-run.json` 一致；41 case 全 PASS 且 id 集合 hash 与 `case_specs()` 相同；batch 97.6772s≤180、逐 case max 10.4227s≤30、workers=2、proof reserve=10.0、`oracle={pass:true,findings:[]}`、`restore.restored=true`、`network_guard_boots=260>0 / denied=0 / translation_attempts=0`；seed 子集 g1=5/g2=6 行与我的独立推导逐 tag 吻合；抽 3 case（chainA 双 run、fin_cn_annual_hit、local_txt_exact_reuse）request/response 文件 SHA 与 report 内 `request_sha256/response_sha256` 全部一致。C-2：脚本逐行审查无"恒真/吞异常成 pass"——中断标记要求 0→新增 GET 递进+fixture 状态一致+无 response，异常一律 fail-closed；receipt 证实 chainA run1 在途(0→1 GET)被杀、树回收、39 文件残留无 report 伪装、重启 126.767s exit 0（cli_main.py:562 exit 0 ⟺ 全 PASS 且 oracle 干净）、新唯一 attempt、残留指纹未改写、sentinel/既有条目不变、临时树移除。依赖：我自算 `git cat-file blob 900dbf64/7d06777e` 与 `.du10-deps` 快照 5+3 个文件逐字节 **8/8 MATCH**；report 内 code_binding 的两个 SHA 经我验算恰等于 blob 纯 LF→CRLF smudge 后的哈希（`dependency-eol-equivalence.json` 的 60 样本 rule/mismatch=[] 吻合） |
| 5 | 测试全绿 | **PASS**（数字声明失实，P3） | 本人在 worktree 根实跑指定 11 文件：**329 passed in 54.85s**，0 failed/0 skipped，一次通过（无负载波动）。但作者声明 185 passed 数字不实：11 文件实收 5+18+20+14+25+12+35+6+14+**161**+**19**=329（progress.md 将 case_authority+root_du8_acceptance 记为 36，实为 180）。全绿结论成立，计数声明需更正 |
| 6 | 卡片余留义务 | **FAIL**（2 条 P2 缺口） | 已具备：完整 commit、PWF 三件套、精确 41 case 结果+命令/exit/耗时（final-run.json）、固定 CWP/ET HEAD（dependency-record.json）、恢复结果（interruption-restart.json）、基线与负载失败证据保留。缺：① 母卡点名的"sentinel 前后 SHA"实值未落盘（脚本算了 `sentinel_before` 但 receipt 只存布尔）；② C-2 pass 门槛不含重启腿结果完整性。另"最终 HEAD、独审所审 SHA/报告、finding 修复映射、测试目录清理 receipt、handoff.md/json"按 NEXT_HANDOFF 属审查后待办，不计 finding。全文无"真实 provider/财报质量通过"类越权声明（scope_note 明确免责） |

## 3. Findings

1. **[P2] interruption-restart.json 缺母卡要求的 sentinel/既有条目前后 SHA 实值**。母卡交接节明确要求 receipts 含"测试目录清理与 sentinel 前后 SHA"，但 `fixtures/interruption_restart_e2e.py` 只把 `sentinel_before`/`preexisting_sha` 与事后哈希比成布尔（`sentinel_intact`/`preexisting_output_intact`），SHA 实值未写入收据，事后无法补录。建议：脚本把 before/after SHA 对写入 `checks`（或新增 `sha_pairs` 字段），重跑一次该 fixture（约 2 分钟，注意选低负载窗口）生成新收据；若不重跑，则须在 handoff 中如实注明"仅有布尔断言+冻结残留指纹，实值未保留"。
2. **[P2] C-2 pass 门槛可被"降级重启"通过**。`passed = all(bool(v) for k,v in checks.items() if k not in {"restart_case_counts"})`：`restart_case_counts` 被排除出门槛，且 `leg2.exit_code==0` 从未进入 checks——若重启腿 40/41 或 exit 1，只要 report 写出、restore=True，fixture 仍报 passed=True。本收据数据本身真实支持 41/41（exit 0 + counts PASS:41 + stdout tail），结论不受影响，但这是任务点名排查的"可伪造通过"类缺口。建议：把 `leg2.exit_code == 0` 和 `restart_case_counts == {"PASS":41,"total":41}` 纳入 `checks` 门槛（或在 all() 前显式断言），与 finding 1 一次重跑覆盖。
3. **[P3] 测试数量声明不实**。NEXT_HANDOFF/progress 声明"11 套件 185 passed"，实测 329 passed（test_w06_case_authority 161 个 + test_root_du8_matrix_acceptance 19 个被记为 36）。全绿成立、方向安全，但 handoff 中的数字须以独审实测 329 更正（NEXT_HANDOFF 已注明"作者声明未经复跑"，诚实性无问题）。
4. **[P3] 两条既有小缺陷（非本卡引入，供顺手修）**：a) `warm-seed-receipts.json` 两组同名互写、g1 的 6 行被 g2 覆盖（per-group 证据在 g1/g2.seed-batch.stdout.json 中完好，但该收据文件只存最后写者）；b) `_attempt_residue` 的"残留未改写"只抽 3 个文件 SHA+路径表哈希，39 个残留文件可全量字节哈希（成本极低），使"被杀残留字节未改写"成为全量证明。

## 4. 实际执行命令与关键输出摘要

- `git -C filing-fetch-du10-41-matrix diff c7c8867..af3f7a1 --stat / --name-only / 全文` → 16 文件 +1729/-12；tools/ 仅 matrix_cases.py、cli_main.py；config/ 无改动。
- `grep CASE_TIMEOUT/BATCH_DEADLINE/WORKERS/PROOF_RESERVE…` → 30/180/2/10.0/choices=range(1,3) 均未变。
- `python -c`（case_specs/matrix_cases 推导脚本）→ 41 ids、union==full(10 ensure+TXT)、缺口键 3 个永不入计划、复算分组 g1=5/g2=6+TXT 与实跑 artifacts 一致。
- `sha256sum` report.json → `a0dd3c1a7af32f66000b92e074e69520f7aaa64550b98993af0552b4d18d83da` = final-run.json 记载；41 全 PASS、max case 10.4227s、oracle 0 findings、restore true、boots 260/denied 0。
- 抽 3 case request/response 文件哈希 vs report `request_sha256/response_sha256` → 6/6 MATCH。
- `git cat-file blob 900dbf64/7d06777e:<rel>` vs `.du10-deps` 快照 → CWP 5 文件 + ET 3 文件全部 MATCH；CRLF smudge 验算复现 code_binding 两个 SHA。
- `git worktree add --detach .du10-review-tmp/baseline-wt c7c8867` + `python -B -m pytest tests/test_du10_ff41_rootcause.py -q`（基线）→ **3 failed, 2 passed**（同名同因，见第 3 项）；随后 `git worktree remove --force` + 删除临时目录。
- `python -B -m pytest <11 个点名文件> -q`（HEAD）→ **329 passed in 54.85s**（首跑即全绿，无需重试）。
- 收尾 `git status --short` → 干净（仅 ignored 的 `__pycache__`）；`git worktree list` 确认我的临时 worktree 已移除（既有他人 worktree 未动）。

**结论**：代码改动（seed 按组子集化）、RED、C-1/C-2、依赖固定、测试全绿全部核验为真，根因修复正当且分母/预算/保护边界零破坏；REQUEST_CHANGES 仅因 receipts 完备性（finding 1）与 C-2 门槛加固（finding 2）两处需在 docs 侧修复后复核。
