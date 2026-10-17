# 进度 (DU10-FF41-CLOSE)

## 已完成

1. worktree `filing-fetch-du10-41-matrix` + 分支 `codex/du10-ff41-close`（起点 main c7c8867）。
2. 只读依赖快照（`git archive`，无 .git）：
   - CWP `900dbf64` → `C:/Users/郑曾波/Projects/.du10-deps/cwp`
   - ET `7d06777e` → `C:/Users/郑曾波/Projects/.du10-deps/et`（含 tests seam 三文件）
3. PWF 建立。
4. **节点 A 基线实跑**（当前 main 代码、固定 argv、workers=2，2026-10-17）：
   **41/41 PASS，110.8451s / 180s，oracle 0 findings，restore=True**
   - binding 2.7938 / seed 26.9168（2 组并行累计）/ ff_cli 163.4358（52 spans 全部完成）/
     fresh_source_proof 1.6425 / cleanup 0.3583
   - boots 278（other_python 139=FF 的 CWP 子进程误分类、adapter 72、ff_cli 52、et_proxy 11、seed_batch 2、proofs 2）
   - 证据：`.du10-tmp/baseline-out/attempt-b0e39315…/report.json`（临时目录，receipt 提取后清理）
   - 含义：DU8 失败主因是当日机器 82% 负载（2–4× 变慢）；本日 38% 负载下 main 代码本就可行。
5. **节点 A RED**（fake/stub 驱动真实 `cli_main.main` + 真实 41 registry，`receipts/A-red-baseline.txt`）：
   - 基线（stash 修复后）：3 failed / 2 passed —— 两个行为级（两组各提交全量 10 项 seed；TXT 种两组都下）+ 1 个新 API 单元；2 个守卫（gap 永不 seed、单组全量）基线即绿。
6. **节点 B 根因修复**（最小 diff）：
   - `matrix_cases.py`：`_warm_seed_list`/`TXT_SEED_KEY`/`warm_consumption`（从冻结 CaseSpec 推导消费/引用）/`seed_plan_for`；`seed_all(ctx)` 读 `ctx.seed_cases`（无则保持历史全量，兼容只读测试钉死的单参调用）。
   - `cli_main.py`：`run_case_group` 把本组 case ids 写入 `ctx.seed_cases`（try/AttributeError 回退全量）。
   - 每个被消费 seed 仍在消费组内走真实 ensure writer；union=全量固定清单，覆盖不缩水。
   - 实测子集：g1=5 项 ensure（无 TXT）、g2=6 项 ensure+TXT（原各 10+TXT）→ 采集 20→11 次。
7. **节点 B 验证**：新测试 5/5 绿；既有 8 套件 144 绿；case_authority+root_du8_acceptance 36 绿。
8. **范围修正（证据驱动）**：
   - fresh-proof 合并（2 boots→1）被只读 W07 测试钉死（`test_w07_matrix_efficiency.py` 断言
     `len(proof_launches)==2`"one final fresh proof per owned wiki"）→ 不做，仅省 ~1 boot。
   - `other_python` 92/139 boots 是 FF 生产链真实子进程（`-m` 启动在 Windows 的 argv 为反斜杠路径，
     classify_argv 点分模式匹配不上）→ 只影响会计分类精度，不影响成本；不改（oracle 无此 vector）。

## 进行中

- 节点 C-1：修复后 HEAD 的完整 41 例独立测试根实跑。
- 节点 C-2：中断→重启→恢复→清理 E2E fixture。

## 开放

- 独立最终审查（冻结 HEAD 后另派 agent）。
- 交接 receipts 与临时目录清理（`.du10-tmp`、`.du10-deps`）。

## 节点 C 完成（2026-10-17）

- **C-1 完整实跑（修复后代码，独立测试根 `.du10-tmp/final-*`）**：
  **41/41 PASS，97.6772s / 180s**，oracle 0 findings，restore=True，stop_reason=None。
  phase：binding 3.5084 / seed 14.2489（子集化后，基线 26.9168）/ ff_cli 151.7909（52 spans）/
  fresh_source_proof 1.6241 / cleanup 0.3385。slowest case request_after_failure_retry 10.42s（<30s）。
  report SHA `a0dd3c1a…d83da`；receipt `receipts/final-run.json`。
- **C-2 中断→重启→恢复→清理 E2E**（`fixtures/interruption_restart_e2e.py`，passed=True）：
  - 中断腿：chainA run1 在途（0→1 GET 观察）→ 进程树回收（transport._cleanup）→ 无 report 伪装（39 个残留文件原样）
  - 重启腿：126.767s 完成，exit 0，**重启 attempt 41/41 PASS**，新唯一 UUID，残留未被改写
  - sentinel/既有 out 条目字节不变；临时树移除。receipt `receipts/interruption-restart.json`。
- 依赖快照与 EOL 等价性、负载实录见 findings A.6/A.7。
- 待办：提交 → 冻结 HEAD → 独立审查 agent → 修复 findings（如有）→ handoff + 清理。

## 2026-10-17 会话熔断收尾

- 节点 A/B/C 全部 commit 在 `bb60678`；本卡作者侧的工作已完成。
- 5h 用量上限在派发独立最终审查 subagent 时触发熔断，作者侧无法继续；
  剩余事项已 commit `cb7e2fb` 的 `NEXT_HANDOFF.md` 固化（独立审查 + handoff
  + 临时目录清理 + 快照重建备忘）。
- 恢复后请严格按 NEXT_HANDOFF.md 顺序执行；不要回退到 A/B/C 节点，不要重跑完整
  41 例矩阵（机器负载敏感）。最终并线需等独审 APPROVE。

## 独审与修复（2026-10-17T20:01:21+01:00）

- 独审第一轮对 af3f7a1：REQUEST_CHANGES（1–5 PASS / 6 FAIL）——2 P2 + 2 P3，映射见 findings A.10。
- 修复：fixture v2（sha_pairs 实值、leg2_completed_clean/restart_all_41_pass 硬门槛、
  残留全量哈希、ChildFailed 显式记录）；matrix_cases.py warm-seed-receipts 按组前缀。
- 受影响测试复测：11 文件 329 passed（52.24s）。fixture v2 重跑见 receipts/interruption-restart-v2.json。
- fixture v3（安静窗口）12/12 全过：重启腿 144.5s exit 0、41/41、sha_pairs 实值；v2 保留为 fail-closed 实证。
- 待：审查员按新 SHA 复核 → APPROVE 后写 handoff + 清理 .du10-tmp。
