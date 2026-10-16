# 进度

## 2026-10-16 会话 1 — A 启动

- 读施工卡/INTERFACES/findings/progress（PWF 种子）。
- 核实环境：Python 3.13.9；只读依赖 CWP/ET 两仓存在；分支/基线正确。
- 跑既有矩阵快测 8 文件：**272 passed / 45.74s**（全绿，作为回归前基线）。
- 从 W07 保留证据做真实成本分解：total 90.294s、逐 case 之和 135.333s、
  现行轮转分组 g1=75.53s / g2=59.80s（差 15.7s）→ 定位调度不平衡为关键路径根因。
- 结论写入 findings.md A.1–A.4（含独立冻结期望）。

未运行/未知：尚未跑本卡的新测试；尚未跑 C 的真实 41 链。
0 供应商 / 0 真实 HTTP / 0 LLM / 0 翻译 / 0 生产写入。

## 2026-10-16 会话 1 — A RED 冻结

新测试两件（施工卡白名单内的新建文件）：

- `tests/test_du8_matrix_scheduling.py` — 成本均衡、顺序无关、链完整、并发不放大、预算不变。
- `tests/test_du8_matrix_deadline_recovery.py` — 取消后 0 新增启动、非协作子进程树回收、
  已退出管道释放、kill 后 span 保持 unknown、失败目录不复用为成功、并发组互不污染。

**A RED 首份（未修改源码前）**：`python -B -m pytest -q tests/test_du8_matrix_scheduling.py tests/test_du8_matrix_deadline_recovery.py`
→ **8 failed / 18 passed in 3.17s**，存 `receipts/A-red-baseline.txt`。

失败即真实缺陷：
1. 无 `case_scheduling` 调度 owner，现行 `entries[index::workers]` 轮转不平衡（实测 75.53/59.80）。
2. `run_case_group` 在 `time.monotonic() >= deadline.end` 时 `break` 而 **`stop_reason` 保持 None** →
   批次被静默截断且报告不记原因（尾部饿死盲区）。

## 2026-10-16 会话 1 — B 实施

- 新增 `tools/offline_contract_matrix/case_scheduling.py`（纯调度 owner）：LPT 贪心 + 全序
  (cost desc, id asc)，成本模型 = CaseSpec run 数静态权重（2.0/次额外 run，基准 2.0s）。
  无时钟/无子进程/无环境/无 I/O/无随机。
- `cli_main.py`：`groups` 改由 `case_scheduling.assign_groups` 产出；新增 `_measured_case_costs()`；
  报告 `scope.case_scheduling` 记录 group_loads/counts/预测 makespan/完美均衡下界/不平衡量。
- `cli_main.py`：批次绝对截止触发的截断现在写入具名 `stop_reason`（不再静默）。

**B 集中回归**：12 个相邻测试文件 → **333 passed in 52.43s**（含全部既有矩阵套件，旧期望未改）。

全仓测试对比（证明无新增失败）：
- 本卡工作树：**15 failed / 1164 passed / 22 skipped in 259.11s**
- 纯净基线 `e8a8558` 独立 worktree 跑同一批失败文件：**同样的 15 failed / 265 passed**
→ 15 个失败全部**既有**（复杂度诊断/安装面/config 假设类），与本卡改动无关，源码零新增失败。基线 worktree 已 `git worktree remove`。

## 2026-10-16 会话 1 — C 第一次真实 41 链（未达 41PASS，如实记录）

命令（公开入口，未改 argv）：
```
python -B tools/offline_contract_matrix/run.py \
  --cwp-project  .../company-wiki-du6-ff-readonly \
  --et-project   .../earnings-transcripts-du6-ff-readonly \
  --owned-root .tmp/du8-c/owned --out-root .tmp/du8-c/out
```
结果：**21 PASS / 1 FAIL / 2 PARTIAL / 17 NOT_RUN，174.31s，exit 1，oracle 39 findings**。
`scope.case_scheduling` = group_loads **[52.0, 52.0]**、imbalance **0.0**、counts [20, 21] → **调度本身完全均衡**。
`scope.stop_reason` = 具名（final-proof reserve preserved）→ 新加的具名停止原因生效，未静默截断。

**根因（具名证据，非本层可修）**：工作站被其他并行 lane 打满。
- 实测 CPU load 82%（12 逻辑核），25 个非本卡 `python` 进程属于其他 lane
  （`invest-quick-scan`、`revenue-forecast-du8-comparison`、别的 pytest）；本卡自身泄漏进程 **0**。
- 同机同输入的阶段成本对比 W07 保留报告：
  binding **2.997→14.07s（4.7×）**、seed **19.44→49.16s（2.5×）**、
  chainA 逐 case **10.61→23.63s（2.2×）**、`request_after_failure_retry` **8.27→28.22s（3.4×）**、
  `fin_cn_annual_hit` **1.94→7.50s（3.9×）**。
  这正是 W07 交接里已记录的“单进程成本 2–3× 波动”，此次更差。
- 后果：2 个 PARTIAL 是 `child absolute deadline expired`（批次已 ~170s 才轮到，窗口被压到极小）；
  `call_hard_timeout` FAIL 是该 case 自身的 `stall` 场景 + `seconds=1` 供应商超时竞态在 3.7× 慢机下移位——
  负载敏感的既有 case 语义，非调度问题。

**负载归一化的调度对比（同一批实测秒数，公平对照）** `receipts/scheduling-comparison.json`：
| 分区 | 关键路径 | 组负载 | 不平衡 |
|---|---|---|---|
| 旧 `entries[index::workers]` | **167.33s** | 167.33 / 125.32 | 21.00s |
| 新 `case_scheduling` | **151.22s** | 151.22 / 141.42 | 4.90s |
→ 同等实测数据下关键路径改善 **16.10s（1.107×）**。新分区只用冻结的 run 计数成本模型产出，
未回灌实测计时，对照非自我实现。

未运行/未知：尚未在较空载下重跑 41 链；`call_hard_timeout` 的负载敏感性未单独隔离验证。
0 供应商 / 0 真实 HTTP / 0 LLM / 0 翻译 / 0 生产写入；第一次报告未覆写。


