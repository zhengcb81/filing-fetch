# 调查 (DU8-FF-MATRIX-COMPLETION)

## A.1 环境与基线（已核实）

- 工作目录 `C:/Users/郑曾波/Projects/filing-fetch-du8-matrix`，分支 `codex/du8-ff-matrix-20261016`，HEAD 起点 `7a682bc`（PWF 种子），源码基线 `e8a85585b4c64a9596e576ff3b73e5c2ee29c334`。
- 只读依赖实测存在：CWP `C:/Users/郑曾波/Projects/company-wiki-du6-ff-readonly`、ET `C:/Users/郑曾波/Projects/earnings-transcripts-du6-ff-readonly`。本卡不改其源码/Git。
- Python 3.13.9（`C:\Miniconda\python.exe`）。
- 既有矩阵快测 8 个文件**当前全绿：272 passed in 45.74s**
  （`test_w07_matrix_efficiency` + `test_w06_contract_matrix` + `test_w06_matrix_runtime` + `test_w06_case_authority` + `test_du6_portable_matrix_evidence` + `test_du67_matrix_process_owner` + `test_du67_replay_output_ownership` + `test_root_w07_matrix_boundaries`）。
- 历史保留证据：W07 `evidence/final-41-report.json` 为 **41 PASS / 90.294s / 2 workers / oracle 0 findings**。

## A.2 当前 41 链的真实成本分解（从 W07 保留报告实测，非估算）

`evidence/final-41-report.json` 的 `scope.phase_timing` 与逐 case `actual.elapsed_seconds`：

| 阶段 | 秒 | 说明 |
|---|---|---|
| binding | 2.9965 | 一次 child import 预热全部热模块 + SHA 绑定 |
| seed | 19.4385 | 含 `seed_helper` 17.6973（1 个 helper 进程内 10 个 ensure） |
| ff_cli（累计，2 组相加） | 132.6748 | 52 次 FF CLI 子进程工作总和（并行累计，非墙钟） |
| et_supervisor_worker | 10.6909 | |
| fixture | 3.1491 | |
| fresh_source_proof | 1.4717 | 2 个 proof 子进程 |
| cleanup | 0.337 | |
| **total 墙钟** | **90.294** | |

逐 case `elapsed_seconds` 之和 = **135.333s**；两 worker 理想 makespan ≈ 67.7s；实测 90.294s。

**分组实测（现行 `entries[index::workers]` 轮转）**：
- g1：n=21，sum = **75.53s**（含 chainA 10.61、request_after_failure_retry 8.27、incomplete_sidecar 4.79、fin_cn_annual_fetch 4.67）
- g2：n=20，sum = **59.80s**

→ g1 比 g2 重 **15.7s**（26%），g1 是唯一关键路径：75.53 + seed(~9.7/组) ≈ 85.2s，+ binding 3.0 + proof 1.5 + cleanup 0.3 ≈ 90.0s，与实测 90.294 吻合。

## A.3 根因（责任缺口）

1. **调度按“位置轮转”而非“成本均衡”**：`cli_main.main` 用 `groups = [entries[index::workers] for index in range(workers)]`
   把固定 registry 按序号奇偶切片。分类信息（`CaseSpec.runs` 数量、`case_fin_fetch` 是 2-run 链、
   `chainA` 是 real-3layer）完全没有参与分配。实测把最重的 3 个 case 中的 2 个放进同一组。
2. **无成本模型/无测量反馈**：`measurement.py` 已产出逐 case `elapsed_seconds`，但没有任何路径把它回送给调度。
3. **尾部饿死是“组内尾部”而非“全批尾部”**：g2 提前 ~15s 空闲，g1 仍在自己尾部跑；共享 180s 绝对值不变，
   但在 174.565/180s 观测到的 `request_after_failure_retry` PARTIAL + `original_wrong_mime`/`incomplete_sidecar_metadata_gap`
   NOT_RUN，与“重 case 全部堆在 g1 尾部”一致。
4. **取消/超时后不停止开新 case**：`run_case_group` 只在每轮开头检查 `deadline.end - PROOF_RESERVE_SECONDS`；
   一旦某 case 因 `DeadlineExceeded` 结束，循环会继续进入**下一个** case（只由顶部检查兜住，若 case 刚好跨过边界，
   下一个 case 的 `ctx.begin_case()` 已经会抛 DeadlineExceeded，但依然算一次“启动尝试”，无 0 新增启动的强保证）。
5. **共享只读准备重复执行**：每个 group 各自 `seed_all(ctx)`（各自 10 次 ensure、各自 scan）；
   wiki 必须独立（可变），但 `materials`/fixture 准备的**只读**部分（adapter/proxy/guard/sitecustomize、
   短路径与 pycache 根创建）每组重复。已在 W07 由 `_env_cache` 部分覆盖。

## A.4 期望行为（独立冻结，用于 RED）

- 调度必须在**不放大并发、不提高任何限额**的前提下，把固定 41 case 分配到 ≤2 组，使两组的预测成本尽量均衡；
  输入顺序不影响结果（反序调度等价）；同一 case 的 download→reuse 链绝不跨组。
- 关键路径必须显著低于现 90.294s 的分组不平衡，且仍受同一 `BATCH_DEADLINE=180`、`CASE_TIMEOUT=30`、
  `PROOF_RESERVE_SECONDS=10` 约束（值不变、起点不变、不重置 remaining）。
- 达到 deadline 后**新增启动数必须为 0**（已退出管道完整回收、非协作子进程被终止）。
- 取消后不得再把失败目录重用为成功；分组之间 wiki/config/counter/cache 互不污染。

## A.5 C 节点实测（两次真实 41 链，公开入口，未改 argv/限额）

| 运行 | 结果 | 秒 | binding | seed | 调度 |
|---|---|---|---|---|---|
| run1 `.tmp/du8-c` | 21 PASS/1 FAIL/2 PARTIAL/17 NOT_RUN | 174.31 | 14.07 | 49.16 | 52/52，imbalance 0.0 |
| run2 `.tmp/du8-c2` | 26 PASS/1 FAIL/2 PARTIAL/12 NOT_RUN | 174.56 | 7.63 | 37.16 | 52/52，imbalance 0.0 |

调度层**已完全均衡**（两组预测负载 52.0/52.0，imbalance 0.0），两次 `stop_reason` 都具名。
未达 41PASS 的原因**不在调度层**，是工作站被其他 lane 打满：

- 实测 CPU load **82% → 63%**（12 逻辑核），25 个非本卡 `python` 进程属 `invest-quick-scan`、
  `revenue-forecast-du8-comparison` 等并行 lane；**本卡自身泄漏进程 0**。
- 与 W07 保留报告同机同输入对比：binding 2.997→7.63~14.07s、seed 19.44→37.16~49.16s、
  chainA 10.61→23.63~29.20s、`request_after_failure_retry` 8.27→26.78~28.22s、
  `fin_cn_annual_hit` 1.94→4.62~7.50s。即整体 ~2–4× 变慢。
- 后果：固定准备（binding+seed）即吃掉 25–35% 的 180s；2 worker 下 case 工作量 ~160s，
  数学上无法在 180s 内跑完 41 case。这不是分层可修的调度问题。

### 负载归一化的对照 —— v1 版本已被独立审查推翻并更正

**v1 的错误（已复现、已撤回）**：v1 报告「关键路径 167.33→151.22s / 181.14→159.98s」。
那些数字是在**只覆盖 24/41（run1）与 29/41（run2）个 case 的成本表**上算出的；
缺失的正是 NOT_RUN 饥饿尾部，被按常数 `DEFAULT_COST_SECONDS=2.0` 计价。
算术铁证：组负载之和比 `measured_case_seconds` **恰好多 34.0（=17×2.0）与 24.0（=12×2.0）**，
缺失集合 = 恰好是 NOT_RUN 集合。11.6%/7.8% 的评分负载是猜的，且猜在**最重的那端**。

**更正后的真实规模**（唯一合法的全覆盖 41/41 表）：
`receipts/scheduling-comparison.json`

| 分区 | 关键路径 | 相对下界 |
|---|---|---|
| 旧 `entries[index::workers]` | 75.5306s | 1.1162 |
| 新 `case_scheduling`（shipped run-count 静态模型） | **74.0080s** | 1.0937 |
| 完美均衡下界（135.3325/2） | 67.6663s | 1.0000 |

→ 真实改善 **1.5226s / 2.02%**；**79.8% 的随机 20/21 分区也超过旧轮转**；
经 `cost_of` 传入实测成本才达到 67.6690s（ratio 1.0000）。
对照脚本已改为**拒绝任何不足 41/41 的表**并在部分表上明确 `comparison_refused: true`。

### 成本模型选择：一次被判定为过拟合并弃用的尝试

按 `declared_layer` 加权的模型在 W07 表上 ratio **1.0008**（看似近乎最优），但：
- 41 个 case 只有 **4 个不同取值**（排名粒度极粗）；
- 最优权重区间窄（`real-3layer` 权重 ±1 即劣化到 70.06s）；
- **Spearman(model, real) = 0.7855**，反而**低于**纯 run-count 的 0.8247；
- **bootstrap 5000 次重采样**：mean ratio 退化 **1.0598**，胜过旧轮转仅 **64.2%**，
  且 **35.8% 的重采样中不如旧轮转**。

对比 shipped run-count 模型：bootstrap mean **1.0498**，胜过旧轮转 **70.2%**。
→ **弃用 layer 模型，ship run-count**。理由与数字写入 `case_scheduling.py` 注释，
并由 `test_static_model_is_honestly_labelled_and_not_near_optimal` 钉住（断言真实 makespan > 下界+5s）。

### 具名 OPEN（白名单外，需 ROOT 决定）

`call_hard_timeout` 两次都 FAIL，但**业务判定本身完全正确**：
`transcript.status=provider_unavailable`、`reason=provider_deadline`、`worker_cleanup=true`、
`et_result.status=deadline_exceeded`。失败来自 handler 的附加断言
`ctx.fixture_requests(calls) == 1`（`extended_cases.py:33`）：该 case 的 ET 供应商 deadline 只有
**1 秒**（`case_specs.py:490`，`stall` 场景），在 2–4× 慢机上 ET 在 fixture adapter 记录 GET
**之前**就已超时 → `fixture_requests=0`、`provider_requests=null`。

**v1 的原因表述有误并已更正**：v1 说 `ctx.fixture_requests`/`run_ff` 不在白名单——不准确，
它们在 `run.py`（属白名单）。真正的阻塞点是上述两处**只读**文件
（冻结的 `seconds=1` 请求向量 + 只读断言）。结论不变。

### RED 质量：v1 的 8 个 RED 中 7 个是同义反复

在纯净基线 `e8a8558` 上按失败原因分类（`receipts/A-red-baseline-classified.txt`）：
**6× `ModuleNotFoundError: case_scheduling` + 1× `FileNotFoundError` + 仅 1× 真实行为断言**
（`stop_reason`）。即 v1 的 RED 主要证明「新模块还不存在」，**没有为位置轮转缺陷提供行为 RED**；
其“负对照”测试只重实现了一遍轮转，在基线上也通过。

**已修复**：新增 3 个驱动**真实 `cli_main.main`** 的行为 RED——
`test_runner_delegates_grouping_to_the_cost_balanced_scheduler`（基线上失败于
「cli_main 从未咨询调度 owner」）、`test_runner_reports_the_scheduling_decision_it_made`、
`test_group_stops_launching_cases_the_moment_the_batch_expires`。
现在基线 RED = **3 个真实行为失败 + 8 个模块缺失失败**。

