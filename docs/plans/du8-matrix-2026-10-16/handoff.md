# DU8-FF-MATRIX-COMPLETION �?交接（v2，独立审查后更正�?
状态：**A/B 完成；C 未达 41PASS（具名外部根因）。作�?STOP，待 ROOT 独立验收�?*
**�?v2 更正�?v1 的过度声�?*——见 §0�?
工作目录：`C:/Users/郑曾�?Projects/filing-fetch-du8-matrix`
分支：`codex/du8-ff-matrix-20261016`
源码基线：`e8a85585b4c64a9596e576ff3b73e5c2ee29c334`（PWF 种子 `7a682bc`�?只读依赖（未改源�?Git）：
- CWP `company-wiki-du6-ff-readonly` @ `f08aa101ab49ca983d3a40356abfb05347f586b3`
- ET `earnings-transcripts-du6-ff-readonly` @ `d0ac42c60dcca992db78860b8469cfed3dd527e5`

## 0. v1 的错误与更正（独立审查发现，已复现）

独立审查 agent 与作者复算都确认 v1 有两�?*实质性过度声�?*�?
| # | v1 声称 | 实际 | 处理 |
|---|---|---|---|
| 1 | 调度改善关键路径 16.10s�?.107×�? 21.16s�?.132×�?| 那些数字是在**只覆�?24/41 �?29/41 �?case 的成本表**上算的；缺失的正�?NOT_RUN 饥饿尾部，被按常�?`2.0` 计价。证据：组负载之和比 `measured_case_seconds` 恰好�?34.0�?17×2.0）与 24.0�?12×2.0）。在**唯一全覆盖（41/41�?*的表上，真实改善只有 **1.52s / 2.02%**，且 79.8% 的随机分区也超过旧轮转�?| **撤回该声�?*；删除两份部分覆盖收据；对照脚本改为**拒绝**部分表；README/handoff 改写为真实规�?|
| 2 | A 节点首份 RED�? failed」证明位置轮转缺�?| 8 个失败中 **7 个是 `ModuleNotFoundError`/`FileNotFoundError`**（证明新模块还不存在），**只有 1 个是真实行为断言**（`stop_reason`）。位置轮转缺陷本�?*没有行为 RED**；其“负对照”测试在基线上也通过�?| **新增 3 个真实行�?RED**：驱动真�?`cli_main.main`，证�?runner 是否真的委派调度；分类收据见 `receipts/A-red-baseline-classified.txt` |

其余 v1 内容经独立复�?*成立**（白名单、限额、既有失败、stop_reason 修复、无 41PASS 声称、清理）�?
## 1. 根因

### 根因 1：调度按位置轮转，不含成本信�?
`cli_main.main` 原用 `groups = [entries[index::workers] for index in range(workers)]`�?在保留的 W07 **41/41 全覆�?*实测表上：g1 = **75.5306s**、g2 = **59.8019s**�?不平�?**15.7287s�?6.3%，相对下�?67.6663s�?*。g1 成为唯一关键路径�?
**真实改善规模**（勿夸大）：

| 分区 | 关键路径 | 相对下界 |
|---|---|---|
| 旧位置轮�?| 75.5306s | 1.1162 |
| �?shipped 静态模�?| **74.0080s** | 1.0937 |
| 完美均衡下界 | 67.6663s | 1.0000 |

改善 **1.5226s / 2.02%**�?9.8% 的随�?20/21 分区也能超过旧轮�?�?这是**可复现的小幅改善**�?**不是**接近最优的调度�?
### 根因 2：批次绝对截止触发的截断不留具名原因

`run_case_group` �?`time.monotonic() >= deadline.end` �?`break`，`stop_reason` 保持 `None`�?保留证据佐证：W07 �?`final-41-report.json` �?41 PASS �?`stop_reason` 也是 `None`—�?该字段此前从不因绝对截止而具名�?
## 2. 成本模型选择（v3 更正：v2 的“过拟合”论�?*已被独立审查推翻**�?
- **shipped**：`CaseSpec.runs` 链数（`2.0 + 2.0×(runs-1)`）。真�?ratio 1.0937�?- **layer 模型**：在 W07 表上 ratio **1.0008**（更好），仅 4 个取值、最优权重区间窄�?- **v2 曾声�?*「layer 过拟合（bootstrap 1.0598 / 64.2%）故 run-count 泛化更好�?.0498 / 70.2%）」�?  **该论断不成立**：它只反�?*分层重采�?*一种方案。四种方案并列（`receipts/cost-model-bootstrap*.json`）：

| 方案 | run-count mean | layer mean | run-count 胜旧轮转 | layer 胜旧轮转 | run-count �?layer |
|---|---|---|---|---|---|
| 分层重采�?| 1.0498 | 1.0598 | 70.2% | 64.2% | 57.0% |
| 比例噪声 ±10% | 1.0937 | **1.0082** | 98.5% | **100%** | 0.0% |
| 比例噪声 ±20% | 1.0936 | **1.0164** | 86.0% | **100%** | 0.04% |
| 比例噪声 ±40% | 1.0937 | **1.0328** | 70.5% | **95.5%** | 10.8% |

  �?结论**随方案翻�?*�?*ship run-count 的真实理由是简单、provenance 透明�?  完全可由冻结输入推导，且在真实全覆盖数据上有已验证的小幅改善**�?*不是**“更稳健”�?  两处 bootstrap 脚本已作为可复现收据提交，不再是散文式断言�?- **`cost_of` 钩子**：持有实测秒数的调用方可传入并达到下界（ratio 1.0000）；
  runner **不隐�?*使用，否则批次会依赖上一次运行的计时�?
## 3. 职责/接口变化

| �?| 变化 |
|---|---|
| �?`tools/offline_contract_matrix/case_scheduling.py` | 纯调�?owner。LPT + 全序 (cost desc, id asc)。无时钟/子进�?环境/IO/随机。`cost_of` 钩子�?|
| `cli_main.py` | `groups` 改由 `assign_groups` 产出；`_measured_case_costs()`；报告新�?`scope.case_scheduling`（含 `cost_source`）；绝对截止截断写具�?`stop_reason`�?|
| `run.py` / `runtime.py` / `measurement.py` | **未改**（白名单允许改，但无需改动 �?最小改动）�?|
| `README.md` | 新增「调度」小节，含真实收益规模与弃用理由�?|

**未改（只读，逐字节核验）**：`oracle.py`、`case_specs.py`、`matrix_outcome.py`、`report.py`�?`matrix_cases.py`、`extended_cases.py`、`fixture_builder.py`、`source_proofs.py`�?`fixture_provider_adapter.py`、`et_transcript_proxy.py`、`seed_batch.py`、`scripts/**`�?既有 `tests/**`、`.github/**`、`.githooks/**`、`.pre-commit-config.yaml`�?
## 4. 现行为兼容矩�?
| �?| �?| �?| 兼容 |
|---|---|---|---|
| CLI argv | `--cwp-project --et-project --owned-root --out-root [--workers]` | �?| 不变 |
| `--workers` | `range(1,3)` | �?| 不变 |
| report schema | `ff-et-cwp-offline-matrix/1` | �?| 不变 |
| `replay` 子命�?| 读保留证�?+ 原生 audit | �?| 不变 |
| `WORKERS`/`CASE_TIMEOUT`/`BATCH_DEADLINE`/`PROOF_RESERVE_SECONDS` | 2 / 30 / 180 / 10.0 | �?| 不变 |
| 组数 | �? | �? | 不放大并�?|
| 同一 case �?download→reuse �?| 同组 | 同组 | 不变 |
| `scope.stop_reason` | 绝对截止时可�?`null` | **必具�?* | 仅补原因，不改判�?|
| 新增字段 | �?| `scope.case_scheduling{...,cost_source}` | 纯新�?|

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

| �?| �?| 手算来源 |
|---|---|---|
| �?case 之和（W07�?1/41�?| 135.3325s | `final-41-report.json` �?case `actual.elapsed_seconds` 求和 |
| 旧分�?g1 / g2 | 75.5306 / 59.8019 | 同表�?`i%2` 分桶 |
| 不平�?| 15.7287s = 26.3% | 75.5306 �?67.6663 |
| 完美均衡下界 | 67.6663s | 135.3325 / 2 |
| 新分区（真实成本�?| **74.0080s** | `static_cost` 分区在实测表上评�?|
| 真实改善 | **1.5226s = 2.02%** | 75.5306 �?74.0080 |
| 随机分区超过旧轮转的比例 | 79.8% | 20000 次随�?20/21 分区 |
| �?`cost_of` 传入实测成本 | 67.6690s（ratio 1.0000�?| LPT-on-real |
| 41 case 分母 | 41 | `len(case_specs())` |

## 7. 测试结果�?NOT_RUN

| 命令 | 结果 | 收据 |
|---|---|---|
| A RED（基�?`e8a8558`，按失败原因分类�?| **3 个真实行为失�?+ 8 个模块缺失失�?* | `receipts/A-red-baseline-classified.txt` |
| A RED（本卡新套件，改前） | 8 failed / 18 passed | `receipts/A-red-baseline.txt` |
| B 新套件（改后�?| **37 passed** | `receipts/B-du8-suite.txt` |
| B 集中回归 12 文件（改后） | **344 passed** | `receipts/B-regression.txt` |
| 全仓（本卡树�?| 15 failed / 1164 passed（全仓口径见 v1；已�?15 个全部既有） | �?§8 |
| 全仓同批失败文件（纯净基线 `e8a8558`�?| 同样 15 failed | 证明既有 |
| C run1 / run2 真实 41 �?| 21 PASS@{174.31s,−} / 26 PASS@{174.56s,−}，均 exit 1 | `.tmp/du8-c*`（交付前已清理，报告内数字已抄录于下�?|
| 受控中断/恢复 | **14/14 检查通过** | `fixtures/interruption-recovery.json` |

**C 三次真实批次全部如实记录**（含最弱的一次，v1 只写了两条）�?
| 批次 | PASS | FAIL | PARTIAL | NOT_RUN | �?| oracle |
|---|---|---|---|---|---|---|
| C run1 | 21 | 1 | 2 | 17 | 174.31 | 39 findings |
| C run2 | 26 | 1 | 2 | 12 | 174.56 | 29 findings |
| 恢复脚本�?clean attempt（并行脚本争抢，最弱） | 14 | 0 | 12 | 15 | 182.49 | 53 findings |

**未达 41PASS，原样保留，不升级�?*

## 8. 既有失败（未隐藏�?
全仓 15 个失败与本卡无关：`test_complexity_diagnostics`(4)、`test_dropbox_config_invariants`(1)�?`test_fc1307a_host_assumption_gate`(1)、`test_fc802_gap_orchestration`(1)、`test_fc803_minimal_download`(3)�?`test_fetch_filing`(1)、`test_policy_containment_fc501`(1)、`test_s3_install_surface`(2)�?`test_selective_installation`(1)�?在基�?`e8a8558` 独立 detached worktree 上跑同批文件 �?**完全相同�?15 个失�?*（逐文件计数一致）�?基线 worktree �?`git worktree remove`�?
## 9. 具名 OPEN

### OPEN-1：C 无法�?180s 内完�?41 链——外部负�?
CPU load **82%�?00%**�?2 逻辑核）�?5 个非本卡 `python` 进程属其他并�?lane�?*本卡泄漏进程 0**�?同机同输入对�?W07：binding 2.997�?.63~14.07s、seed 19.439�?7.16~49.16s�?chainA 10.606�?3.63~29.20s、`request_after_failure_retry` 8.270�?6.78~28.22s�?固定准备即吃 25�?5% 预算；`WORKERS�?` 是硬约束�?**但审查正确指�?OPEN-1 部分可归因于本层**：`cost_of` 钩子（本卡已加）现在允许用实测成本调�?把关键路径从 74.008 降到 67.669，仍不足以在 3.7× 慢机上装�?41 case，但这是**在本层已做的合法优化**�?不再算作“完全不可修”�?
### OPEN-2：`call_hard_timeout` 在负载下失败（原因表述已更正�?
真实 blocker �?*冻结的请求向�?* `case_specs.py:490`（`stall` 场景 `seconds=1`）与
**只读断言** `extended_cases.py:33`（`ctx.fixture_requests(calls)==1`）的组合�?1s 供应�?deadline 短于负载下的进程启动时间，ET �?fixture adapter 记录 GET **之前**即超�?�?`fixture_requests=0`。业务判定本�?*正确**（`provider_unavailable`/`provider_deadline`/
`worker_cleanup=true`/`deadline_exceeded`）�?v1 说“`ctx.fixture_requests`/`run_ff` 不在白名单�?*不准�?*（它们在 `run.py`，属白名单）�?真正的阻塞点是上述两处只读文件。结论不变，理由已更正�?
## 10. 清理

- 运行写自�?owned root；`OwnedAttempt` 只删自建 UUID 子目录与新缓存；预存 sentinel/条目�?stat 核验保留�?- 本卡工作�?*零泄漏进�?*；交付前删除 `.tmp/`、`.tmp-du8/`、`docs/plans/.tmp/` 与临时探针�?- `ProductionGuard` 只读 stat，`config/FMP_API_KEY.txt` **从不读内�?*�? 生产写入�?- **残留限制（审查指出，如实保留�?*：C 运行�?`restore.json`/`guard-events.json` �?`.tmp/` 被删�?  �?`supplier_calls=0`/`production_writes=0` 现仅由未改动�?`ProductionGuard` 代码 +
  中断 fixture �?`production_metadata_unchanged=true` 推断�?*无独立产出物**�?
## 11. ROOT 如何接收

1. 复核 commit �?`changed_paths` 是否在施工卡 §2 白名单内�?2. 在空载主机重�?C �?41 链，确认 41 PASS；若仍超 180s，用 `scope.phase_timing` +
   `scope.case_scheduling` 区分「准备变�?/ 调度不平�?/ �?case 变慢」�?3. 决定 OPEN-2 �?1s deadline 语义（`case_specs.py:490`），�?ROOT 范围�?4. 本卡只称**工程联调覆盖**�?*不称**供应商网络或公司事实质量通过�?5. 作者不并主线、不安装技能、不推远端�?