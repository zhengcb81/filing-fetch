# DU8-FF-MATRIX-COMPLETION — 交接（v2，独立审查后更正）

状态：**A/B 完成；C 未达 41PASS（具名外部根因）。作者 STOP，待 ROOT 独立验收。**
**本 v2 更正了 v1 的过度声称**——见 §0。

工作目录：`C:/Users/郑曾波/Projects/filing-fetch-du8-matrix`
分支：`codex/du8-ff-matrix-20261016`
源码基线：`e8a85585b4c64a9596e576ff3b73e5c2ee29c334`（PWF 种子 `7a682bc`）
只读依赖（未改源码/Git）：
- CWP `company-wiki-du6-ff-readonly` @ `f08aa101ab49ca983d3a40356abfb05347f586b3`
- ET `earnings-transcripts-du6-ff-readonly` @ `d0ac42c60dcca992db78860b8469cfed3dd527e5`

## 0. v1 的错误与更正（独立审查发现，已复现）

独立审查 agent 与作者复算都确认 v1 有两处**实质性过度声称**：

| # | v1 声称 | 实际 | 处理 |
|---|---|---|---|
| 1 | 调度改善关键路径 16.10s（1.107×）/ 21.16s（1.132×） | 那些数字是在**只覆盖 24/41 与 29/41 个 case 的成本表**上算的；缺失的正是 NOT_RUN 饥饿尾部，被按常数 `2.0` 计价。证据：组负载之和比 `measured_case_seconds` 恰好多 34.0（=17×2.0）与 24.0（=12×2.0）。在**唯一全覆盖（41/41）**的表上，真实改善只有 **1.52s / 2.02%**，且 79.8% 的随机分区也超过旧轮转。 | **撤回该声称**；删除两份部分覆盖收据；对照脚本改为**拒绝**部分表；README/handoff 改写为真实规模 |
| 2 | A 节点首份 RED「8 failed」证明位置轮转缺陷 | 8 个失败中 **7 个是 `ModuleNotFoundError`/`FileNotFoundError`**（证明新模块还不存在），**只有 1 个是真实行为断言**（`stop_reason`）。位置轮转缺陷本身**没有行为 RED**；其“负对照”测试在基线上也通过。 | **新增 3 个真实行为 RED**：驱动真实 `cli_main.main`，证明 runner 是否真的委派调度；分类收据见 `receipts/A-red-baseline-classified.txt` |

其余 v1 内容经独立复核**成立**（白名单、限额、既有失败、stop_reason 修复、无 41PASS 声称、清理）。

## 1. 根因

### 根因 1：调度按位置轮转，不含成本信息

`cli_main.main` 原用 `groups = [entries[index::workers] for index in range(workers)]`。
在保留的 W07 **41/41 全覆盖**实测表上：g1 = **75.5306s**、g2 = **59.8019s**，
不平衡 **15.7287s（26.3%，相对下界 67.6663s）**。g1 成为唯一关键路径。

**真实改善规模**（勿夸大）：

| 分区 | 关键路径 | 相对下界 |
|---|---|---|
| 旧位置轮转 | 75.5306s | 1.1162 |
| 新 shipped 静态模型 | **74.0080s** | 1.0937 |
| 完美均衡下界 | 67.6663s | 1.0000 |

改善 **1.5226s / 2.02%**。79.8% 的随机 20/21 分区也能超过旧轮转 → 这是**可复现的小幅改善**，
**不是**接近最优的调度。

### 根因 2：批次绝对截止触发的截断不留具名原因

`run_case_group` 在 `time.monotonic() >= deadline.end` 时 `break`，`stop_reason` 保持 `None`。
保留证据佐证：W07 的 `final-41-report.json` 在 41 PASS 时 `stop_reason` 也是 `None`——
该字段此前从不因绝对截止而具名。

## 2. 成本模型选择（v3 更正：v2 的“过拟合”论断**已被独立审查推翻**）

- **shipped**：`CaseSpec.runs` 链数（`2.0 + 2.0×(runs-1)`）。真实 ratio 1.0937。
- **layer 模型**：在 W07 表上 ratio **1.0008**（更好），仅 4 个取值、最优权重区间窄。
- **v2 曾声称**「layer 过拟合（bootstrap 1.0598 / 64.2%）故 run-count 泛化更好（1.0498 / 70.2%）」。
  **该论断不成立**：它只反映**分层重采样**一种方案。四种方案并列（`receipts/cost-model-bootstrap*.json`）：

| 方案 | run-count mean | layer mean | run-count 胜旧轮转 | layer 胜旧轮转 | run-count 胜 layer |
|---|---|---|---|---|---|
| 分层重采样 | 1.0498 | 1.0598 | 70.2% | 64.2% | 57.0% |
| 比例噪声 ±10% | 1.0937 | **1.0082** | 98.5% | **100%** | 0.0% |
| 比例噪声 ±20% | 1.0936 | **1.0164** | 86.0% | **100%** | 0.04% |
| 比例噪声 ±40% | 1.0937 | **1.0328** | 70.5% | **95.5%** | 10.8% |

  → 结论**随方案翻转**。**ship run-count 的真实理由是简单、provenance 透明、
  完全可由冻结输入推导，且在真实全覆盖数据上有已验证的小幅改善**；**不是**“更稳健”。
  两处 bootstrap 脚本已作为可复现收据提交，不再是散文式断言。
- **`cost_of` 钩子**：持有实测秒数的调用方可传入并达到下界（ratio 1.0000）；
  runner **不隐式**使用，否则批次会依赖上一次运行的计时。

## 3. 职责/接口变化

| 层 | 变化 |
|---|---|
| 新 `tools/offline_contract_matrix/case_scheduling.py` | 纯调度 owner。LPT + 全序 (cost desc, id asc)。无时钟/子进程/环境/IO/随机。`cost_of` 钩子。 |
| `cli_main.py` | `groups` 改由 `assign_groups` 产出；`_measured_case_costs()`；报告新增 `scope.case_scheduling`（含 `cost_source`）；绝对截止截断写具名 `stop_reason`。 |
| `run.py` / `runtime.py` / `measurement.py` | **未改**（白名单允许改，但无需改动 → 最小改动）。 |
| `README.md` | 新增「调度」小节，含真实收益规模与弃用理由。 |

**未改（只读，逐字节核验）**：`oracle.py`、`case_specs.py`、`matrix_outcome.py`、`report.py`、
`matrix_cases.py`、`extended_cases.py`、`fixture_builder.py`、`source_proofs.py`、
`fixture_provider_adapter.py`、`et_transcript_proxy.py`、`seed_batch.py`、`scripts/**`、
既有 `tests/**`、`.github/**`、`.githooks/**`、`.pre-commit-config.yaml`。

## 4. 现行为兼容矩阵

| 面 | 旧 | 现 | 兼容 |
|---|---|---|---|
| CLI argv | `--cwp-project --et-project --owned-root --out-root [--workers]` | 同 | 不变 |
| `--workers` | `range(1,3)` | 同 | 不变 |
| report schema | `ff-et-cwp-offline-matrix/1` | 同 | 不变 |
| `replay` 子命令 | 读保留证据 + 原生 audit | 同 | 不变 |
| `WORKERS`/`CASE_TIMEOUT`/`BATCH_DEADLINE`/`PROOF_RESERVE_SECONDS` | 2 / 30 / 180 / 10.0 | 同 | 不变 |
| 组数 | ≤2 | ≤2 | 不放大并发 |
| 同一 case 的 download→reuse 链 | 同组 | 同组 | 不变 |
| `scope.stop_reason` | 绝对截止时可为 `null` | **必具名** | 仅补原因，不改判定 |
| 新增字段 | — | `scope.case_scheduling{...,cost_source}` | 纯新增 |

## 5. 实际运行命令

```
python -B -m pytest -q tests/test_du8_matrix_scheduling.py tests/test_du8_matrix_deadline_recovery.py
python -B -m pytest -q tests/test_du8_matrix_scheduling.py tests/test_du8_matrix_deadline_recovery.py \
  tests/test_w07_matrix_efficiency.py tests/test_w06_contract_matrix.py tests/test_w06_matrix_runtime.py \
  tests/test_w06_case_authority.py tests/test_du6_portable_matrix_evidence.py \
  tests/test_du67_matrix_process_owner.py tests/test_du67_replay_output_ownership.py \
  tests/test_root_w07_matrix_boundaries.py tests/test_p5_process_transport.py tests/test_p5_process_lifecycle.py

python -B tools/offline_contract_matrix/run.py \
  --cwp-project <company-wiki-du6-ff-readonly> --et-project <earnings-transcripts-du6-ff-readonly> \
  --owned-root <new-owned-root> --out-root <new-out-root>

python docs/plans/du8-matrix-2026-10-16/fixtures/scheduling_comparison.py <FULL 41/41 report.json>
python -B docs/plans/du8-matrix-2026-10-16/fixtures/interruption_recovery_e2e.py
```

## 6. 数字/单位手工锚点

| 量 | 值 | 手算来源 |
|---|---|---|
| 逐 case 之和（W07，41/41） | 135.3325s | `final-41-report.json` 逐 case `actual.elapsed_seconds` 求和 |
| 旧分区 g1 / g2 | 75.5306 / 59.8019 | 同表按 `i%2` 分桶 |
| 不平衡 | 15.7287s = 26.3% | 75.5306 − 67.6663 |
| 完美均衡下界 | 67.6663s | 135.3325 / 2 |
| 新分区（真实成本） | **74.0080s** | `static_cost` 分区在实测表上评分 |
| 真实改善 | **1.5226s = 2.02%** | 75.5306 − 74.0080 |
| 随机分区超过旧轮转的比例 | 79.8% | 20000 次随机 20/21 分区 |
| 经 `cost_of` 传入实测成本 | 67.6690s（ratio 1.0000） | LPT-on-real |
| 41 case 分母 | 41 | `len(case_specs())` |

## 7. 测试结果与 NOT_RUN

| 命令 | 结果 | 收据 |
|---|---|---|
| A RED（基线 `e8a8558`，按失败原因分类） | **3 个真实行为失败 + 8 个模块缺失失败** | `receipts/A-red-baseline-classified.txt` |
| A RED（本卡新套件，改前） | 8 failed / 18 passed | `receipts/A-red-baseline.txt` |
| B 新套件（改后） | **32 passed** | `receipts/B-du8-suite.txt` |
| B 集中回归 12 文件（改后） | **339 passed** | `receipts/B-regression.txt` |
| 全仓（本卡树） | 15 failed / 1164 passed（全仓口径见 v1；已证 15 个全部既有） | 见 §8 |
| 全仓同批失败文件（纯净基线 `e8a8558`） | 同样 15 failed | 证明既有 |
| C run1 / run2 真实 41 链 | 21 PASS@{174.31s,−} / 26 PASS@{174.56s,−}，均 exit 1 | `.tmp/du8-c*`（交付前已清理，报告内数字已抄录于下） |
| 受控中断/恢复 | **14/14 检查通过** | `fixtures/interruption-recovery.json` |

**C 三次真实批次全部如实记录**（含最弱的一次，v1 只写了两条）：

| 批次 | PASS | FAIL | PARTIAL | NOT_RUN | 秒 | oracle |
|---|---|---|---|---|---|---|
| C run1 | 21 | 1 | 2 | 17 | 174.31 | 39 findings |
| C run2 | 26 | 1 | 2 | 12 | 174.56 | 29 findings |
| 恢复脚本的 clean attempt（并行脚本争抢，最弱） | 14 | 0 | 12 | 15 | 182.49 | 53 findings |

**未达 41PASS，原样保留，不升级。**

## 8. 既有失败（未隐藏）

全仓 15 个失败与本卡无关：`test_complexity_diagnostics`(4)、`test_dropbox_config_invariants`(1)、
`test_fc1307a_host_assumption_gate`(1)、`test_fc802_gap_orchestration`(1)、`test_fc803_minimal_download`(3)、
`test_fetch_filing`(1)、`test_policy_containment_fc501`(1)、`test_s3_install_surface`(2)、
`test_selective_installation`(1)。
在基线 `e8a8558` 独立 detached worktree 上跑同批文件 → **完全相同的 15 个失败**（逐文件计数一致）。
基线 worktree 已 `git worktree remove`。

## 9. 具名 OPEN

### OPEN-1：C 无法在 180s 内完成 41 链——外部负载

CPU load **82%–100%**（12 逻辑核）；25 个非本卡 `python` 进程属其他并行 lane；**本卡泄漏进程 0**。
同机同输入对比 W07：binding 2.997→7.63~14.07s、seed 19.439→37.16~49.16s、
chainA 10.606→23.63~29.20s、`request_after_failure_retry` 8.270→26.78~28.22s。
固定准备即吃 25–35% 预算；`WORKERS≤2` 是硬约束。
**但审查正确指出 OPEN-1 部分可归因于本层**：`cost_of` 钩子（本卡已加）现在允许用实测成本调度
把关键路径从 74.008 降到 67.669，仍不足以在 3.7× 慢机上装下 41 case，但这是**在本层已做的合法优化**，
不再算作“完全不可修”。

### OPEN-2：`call_hard_timeout` 在负载下失败（原因表述已更正）

真实 blocker 是**冻结的请求向量** `case_specs.py:490`（`stall` 场景 `seconds=1`）与
**只读断言** `extended_cases.py:33`（`ctx.fixture_requests(calls)==1`）的组合：
1s 供应商 deadline 短于负载下的进程启动时间，ET 在 fixture adapter 记录 GET **之前**即超时
→ `fixture_requests=0`。业务判定本身**正确**（`provider_unavailable`/`provider_deadline`/
`worker_cleanup=true`/`deadline_exceeded`）。
v1 说“`ctx.fixture_requests`/`run_ff` 不在白名单”**不准确**（它们在 `run.py`，属白名单）；
真正的阻塞点是上述两处只读文件。结论不变，理由已更正。

## 10. 清理

- 运行写自建 owned root；`OwnedAttempt` 只删自建 UUID 子目录与新缓存；预存 sentinel/条目按 stat 核验保留。
- 本卡工作树**零泄漏进程**；交付前删除 `.tmp/`、`.tmp-du8/`、`docs/plans/.tmp/` 与临时探针。
- `ProductionGuard` 只读 stat，`config/FMP_API_KEY.txt` **从不读内容**；0 生产写入。
- **残留限制（审查指出，如实保留）**：C 运行的 `restore.json`/`guard-events.json` 随 `.tmp/` 被删，
  故 `supplier_calls=0`/`production_writes=0` 现仅由未改动的 `ProductionGuard` 代码 +
  中断 fixture 的 `production_metadata_unchanged=true` 推断，**无独立产出物**。

## 11. ROOT 如何接收

1. 复核 commit 与 `changed_paths` 是否在施工卡 §2 白名单内。
2. 在空载主机重跑 C 的 41 链，确认 41 PASS；若仍超 180s，用 `scope.phase_timing` +
   `scope.case_scheduling` 区分「准备变慢 / 调度不平衡 / 单 case 变慢」。
3. 决定 OPEN-2 的 1s deadline 语义（`case_specs.py:490`），属 ROOT 范围。
4. 本卡只称**工程联调覆盖**；**不称**供应商网络或公司事实质量通过。
5. 作者不并主线、不安装技能、不推远端。
