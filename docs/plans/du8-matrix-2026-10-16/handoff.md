# DU8-FF-MATRIX-COMPLETION — 交接

状态：**A/B 完成并冻结；C 完成但未达 41PASS，如实记录具名根因，不冒称全系统通过。作者 STOP，由 ROOT 独立验收与合流。**

工作目录：`C:/Users/郑曾波/Projects/filing-fetch-du8-matrix`
分支：`codex/du8-ff-matrix-20261016`
源码基线：`e8a85585b4c64a9596e576ff3b73e5c2ee29c334`（本卡起点 HEAD `7a682bc`，仅 PWF 种子）
只读依赖（未改源码/Git）：
- CWP `C:/Users/郑曾波/Projects/company-wiki-du6-ff-readonly` @ `f08aa101ab49ca983d3a40356abfb05347f586b3`
- ET `C:/Users/郑曾波/Projects/earnings-transcripts-du6-ff-readonly` @ `d0ac42c60dcca992db78860b8469cfed3dd527e5`

## 1. 已查明的根因

### 根因 1（主）：调度按位置轮转，不含任何成本信息

`cli_main.main` 原用 `groups = [entries[index::workers] for index in range(workers)]`——按 registry
序号奇偶切片。`CaseSpec` 的成本差异极大（1-run 本地命中 ~1.5–2.3s vs 真三层 `chainA_download_reuse`
~10.6s vs 2-run `request_after_failure_retry` ~8.3s），位置与该成本无关。

从保留的 W07 完整批报告实测（`docs/handoffs/w07-ff-matrix-efficiency/evidence/final-41-report.json`，
逐 case `actual.elapsed_seconds`）：

- 逐 case 之和 = **135.333s**；两 worker 理想 makespan ≈ 67.67s；实测墙钟 **90.294s**
- 旧分区 g1 = **75.53s** / g2 = **59.80s** → 不平衡 **15.73s（26%）**
- g1 成为唯一关键路径：75.53 + seed ≈ 85.2 + binding 3.0 + proof 1.5 + cleanup 0.3 ≈ **90.0s**（与实测吻合）

后果：轻组提前 ~15s 空闲，重组在自己尾部追赶。这正是施工卡记录的“任务尾部饿死”。

### 根因 2：批次绝对截止触发的截断**不留具名原因**

`run_case_group` 在 `time.monotonic() >= deadline.end` 时 `break`，但 `stop_reason` 保持 `None`。
于是报告 `scope.stop_reason = null` 而批次已被静默截断——尾部饿死没有可诊断的原因记录。
（reserve 分支的 `break` 是留原因的；只有绝对截止分支漏了。）

## 2. 职责/接口变化

| 层 | 变化 |
|---|---|
| 新 `tools/offline_contract_matrix/case_scheduling.py` | 纯调度 owner。LPT 贪心 + 全序 (cost desc, id asc)。**无**时钟/子进程/环境/IO/随机。 |
| `cli_main.py` | `groups` 改由 `case_scheduling.assign_groups` 产出；新增 `_measured_case_costs()`；报告新增 `scope.case_scheduling`；绝对截止截断写入具名 `stop_reason`。 |
| `run.py` | **未改**（Context/预算/限额原样）。 |
| `runtime.py` | **未改**（deadline/transport 原样）。 |
| `measurement.py` | **未改**。 |
| `README.md` | 新增「调度」小节，记录成本均衡依据与约束不变。 |

**未改（只读）**：`oracle.py`、`case_specs.py`、`matrix_outcome.py`、`report.py`、`source_proofs.py`、
`matrix_cases.py`、`extended_cases.py`、`fixture_builder.py`、生产 `scripts/`、ET/CWP、旧 tests/gold/CI/config。

### 成本模型（关键设计）

`case_scheduling.static_cost` 只用**运行前可得**的固定信息：`CaseSpec.runs` 的链数
（`DEFAULT_COST_SECONDS=2.0` + `RUN_WEIGHT_SECONDS=2.0 × (runs-1)`）。

**不读历史计时文件**——矩阵必须能从固定输入复现；机器相关的陈旧计时表是隐藏输入，会让
“同一固定输入”在不同机器上产生不同分区。静态模型在 41 case 上即得 **52.0/52.0 完美均衡**。

## 3. 现行为兼容矩阵

| 面 | 旧行为 | 现行为 | 兼容 |
|---|---|---|---|
| CLI argv | `--cwp-project --et-project --owned-root --out-root [--workers]` | 同 | 不变 |
| `--workers` 取值 | `range(1,3)` | 同 | 不变 |
| report schema | `ff-et-cwp-offline-matrix/1` | 同 | 不变 |
| `replay` 子命令 | 读保留证据 + 原生 audit | 同 | 不变（`tests/test_du6_portable_matrix_evidence.py` 全过） |
| `WORKERS` | 2 | 2 | 不变 |
| `CASE_TIMEOUT` | 30 | 30 | 不变 |
| `BATCH_DEADLINE` | 180 | 180 | 不变 |
| `PROOF_RESERVE_SECONDS` | 10.0 | 10.0 | 不变 |
| 组数 | ≤2 | ≤2 | 不放大并发 |
| 同一 case 的 download→reuse 链 | 同组 | 同组 | 不变 |
| 每组 wiki/config/counter/cache | 独立 | 独立 | 不变 |
| `scope.stop_reason` | 绝对截止时可为 `null` | **必具名** | 仅补原因，不改判定 |
| report 新增字段 | — | `scope.case_scheduling` | 纯新增，旧消费者不受影响 |

## 4. 实际运行命令

快速回归（离线、不跑跨仓）：
```
python -B -m pytest -q tests/test_du8_matrix_scheduling.py tests/test_du8_matrix_deadline_recovery.py
python -B -m pytest -q tests/test_w06_contract_matrix.py tests/test_w06_matrix_runtime.py \
  tests/test_w06_case_authority.py tests/test_w07_matrix_efficiency.py \
  tests/test_du6_portable_matrix_evidence.py tests/test_du67_matrix_process_owner.py \
  tests/test_du67_replay_output_ownership.py tests/test_root_w07_matrix_boundaries.py
```

真实 41 链（公开入口，手动，不进每 commit CI）：
```
python -B tools/offline_contract_matrix/run.py \
  --cwp-project <company-wiki-du6-ff-readonly> \
  --et-project  <earnings-transcripts-du6-ff-readonly> \
  --owned-root  <new-owned-root> --out-root <new-out-root>
```

负载归一化的调度对照（不改源码，只读一份实测 report）：
```
python docs/plans/du8-matrix-2026-10-16/fixtures/scheduling_comparison.py <report.json>
```

受控中断/恢复端到端（公开入口被硬中断后核验恢复不变量）：
```
python -B docs/plans/du8-matrix-2026-10-16/fixtures/interruption_recovery_e2e.py
```

## 5. 数字/单位手工锚点

| 量 | 值 | 来源（可手算复核） |
|---|---|---|
| 逐 case 之和（W07 保留批） | 135.333s | `final-41-report.json` 各 case `actual.elapsed_seconds` 求和 |
| 旧分区 g1 / g2 | 75.5306 / 59.8019 | 上式按 `i%2` 分桶求和 |
| 旧分区不平衡 | 15.7287s = 26.3% | 75.5306 − 67.6662（=135.333/2） |
| 新分区预测负载 | 67.669 / 67.664 | `case_scheduling.group_loads`（实测成本表输入） |
| 新分区不平衡 | 0.0028s | 67.669 − 67.6662 |
| 静态模型负载 | 52.0 / 52.0 | run 计数权重，20/21 case |
| 41 case 判定分母 | 41 | `case_specs.case_specs()` 长度 |
| 2-run case 数 | 11 | `chainA` + 9× `fin_*_fetch` + `request_after_failure_retry` |

## 6. 测试结果与 NOT_RUN

| 命令 | 结果 | 收据 |
|---|---|---|
| 新 RED 首份（改源码前） | **8 failed / 18 passed in 3.17s** | `receipts/A-red-baseline.txt` |
| 新 B 集中回归 12 文件 | **333 passed in 52.43s** | `receipts/B-regression.txt` |
| 全仓 `pytest tests`（本卡树） | 15 failed / 1164 passed / 22 skipped | 见 §7 |
| 全仓 同批失败文件（纯净基线 `e8a8558`） | **同样 15 failed** / 265 passed | 证明 15 个失败全部既有 |
| C run1 真实 41 链 | 21 PASS / 1 FAIL / 2 PARTIAL / 17 NOT_RUN，174.31s，exit 1 | `.tmp/du8-c/out/attempt-*/report.json` |
| C run2 真实 41 链 | 26 PASS / 1 FAIL / 2 PARTIAL / 12 NOT_RUN，174.56s，exit 1 | `.tmp/du8-c2/out/attempt-*/report.json` |
| 调度对照 run1/run2 | 关键路径 167.33→151.22s / 181.14→159.98s | `receipts/scheduling-comparison-run{1,2}.json` |
| 受控中断/恢复 | 见 `handoff.md` §8 | `fixtures/interruption-recovery.json` |

**NOT_RUN 与未达标原样保留，不升级**：C 两次都未达 41PASS。**不写 41PASS**。

## 7. 既有失败（未隐藏）

全仓 `pytest tests` 有 **15 个失败**，与本卡改动**无关**：

`test_complexity_diagnostics`(4)、`test_dropbox_config_invariants`(1)、`test_fc1307a_host_assumption_gate`(1)、
`test_fc802_gap_orchestration`(1)、`test_fc803_minimal_download`(3)、`test_fetch_filing`(1)、
`test_policy_containment_fc501`(1)、`test_s3_install_surface`(2)、`test_selective_installation`(1)。

证据：在源码基线 `e8a85585` 的独立 detached worktree 上跑同一批文件，得到**完全相同的 15 个失败**。
性质是主机路径/config 假设类（与矩阵无关）。基线 worktree 已 `git worktree remove`，本卡未改这些文件。

## 8. 具名 OPEN（不在本卡白名单内，需 ROOT 决定）

### OPEN-1：C 无法在 180s 内完成 41 链——外部负载，非本层可修

实测 CPU load **82%–100%**（12 逻辑核）；25 个非本卡 `python` 进程属其他并行 lane
（`invest-quick-scan`、`revenue-forecast-du8-comparison`、别的 pytest）。**本卡自身泄漏进程 0**。

同机同输入对比 W07 保留报告：

| 阶段 | W07（快机） | DU8 run1 | DU8 run2 | 倍数 |
|---|---|---|---|---|
| binding | 2.997 | 14.065 | 7.629 | 2.5–4.7× |
| seed | 19.439 | 49.160 | 37.162 | 1.9–2.5× |
| chainA 逐 case | 10.606 | 23.628 | 29.195 | 2.2–2.8× |
| request_after_failure_retry | 8.270 | 28.219 | 26.782 | 3.2–3.4× |
| fin_cn_annual_hit | 1.943 | 7.495 | 4.619 | 2.4–3.9× |

固定准备（binding+seed）即吃掉 180s 的 25–35%；2 worker 下 case 工作量 ~160s。
**数学上无法在 180s 内跑完 41 case**，且 `WORKERS≤2` 是硬约束，不能靠加并发解决。
按卡要求：不提高限额、不换弱 case、不裁分母、不延后 batch clock、不重跑到偶然绿；
给具名证据，不编造 41PASS。

### OPEN-2：`call_hard_timeout` 的 1s 供应商 deadline 短于负载下的启动时间

两次 C 运行该 case 都 FAIL，但**业务判定完全正确**：
`transcript.status=provider_unavailable`、`reason=provider_deadline`、`worker_cleanup=true`、
`et_result.status=deadline_exceeded`。

失败来自 handler 的附加断言 `ctx.fixture_requests(calls) == 1`（`extended_cases.py:33`）：
该 case 的 ET 供应商 deadline 仅 **1 秒**（`case_specs.py:490`，`stall` 场景）。在 2–4× 慢机上，
ET 在 fixture adapter 记录 GET **之前**就超时 → `fixture_requests=0`、`provider_requests=null`（诚实保留为 null）。
即该 case 语义**负载敏感**，位于 `case_specs.py`/`extended_cases.py`——**本卡只读**。
建议 ROOT 评估该 case 的 1s deadline 是否应随案例固定语义调整（本卡不改）。

## 9. 清理

- 所有运行写自建 owned root；`OwnedAttempt` 只删自己创建的 UUID 子目录与新缓存，预存 sentinel
  与既有条目按 stat 元数据核验保留（`restore.restored`）。
- 本卡工作树**零泄漏进程**（两次 C 结束后核验本卡 `python` 进程数 = 0）。
- `ProductionGuard` 只读 stat：`config/company_wiki.json`、`config/FMP_API_KEY.txt`（**从不读内容**）、
  CWP/ET config、ET `transcripts/`。0 生产写入。
- 临时探针目录 `.tmp-du8/` 与运行目录 `.tmp/` 为未跟踪临时物，交付前删除（见 handoff.json `cleanup_receipt`）。

## 10. ROOT 如何接收

1. 复核本卡 commit 与 `changed_paths` 是否落在施工卡白名单内。
2. 在本机（非并行 lane 争抢时）重跑 C 的 41 链，确认 41 PASS；若仍超 180s，用
   `report.scope.phase_timing` + `scope.case_scheduling` 定位（两字段已足以分辨
   “准备变慢 / 调度不平衡 / 单 case 变慢”三种原因）。
3. 评估 OPEN-2 的 1s deadline 语义（`case_specs.py:490`），决定是否属 ROOT 生产修复范围。
4. 本卡只称**工程联调覆盖**，**不称**供应商网络/公司事实质量通过。
5. 作者不自行并主线、不安装技能、不推远端。
