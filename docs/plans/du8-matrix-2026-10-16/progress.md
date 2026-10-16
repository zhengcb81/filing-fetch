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

**负载归一化的调度对比** — ⚠️ **本小节 v1 的数字已被推翻，勿引用；见会话 2 更正。**

v1 曾在此写「旧 167.33s → 新 151.22s，改善 16.10s」等。**这些数字全部作废**：
它们是在只覆盖 24/41 与 29/41 个 case 的成本表上算出的，把 NOT_RUN 饥饿尾部按常数 `2.0` 计价，
因而把收益从真实的 **1.5226s / 2.02%** 放大到 16–21s。
合法权益口径见 `receipts/scheduling-comparison.json`（仅用全覆盖 41/41 表）。

未运行/未知：尚未在较空载下重跑 41 链；`call_hard_timeout` 的负载敏感性未单独隔离验证。
0 供应商 / 0 真实 HTTP / 0 LLM / 0 翻译 / 0 生产写入；第一次报告未覆写。

## 2026-10-16 会话 2 — 独立审查发现 2 处 HIGH 过度声称，已复现并更正

独立审查 agent（fork，全上下文）逐条核验 A–H 后指出两处实质问题。**作者独立复现，确认审查正确。**

### D1（HIGH，已更正）：调度收益的“隐藏分母”

v1 的 `receipts/scheduling-comparison-run{1,2}.json` 只在**覆盖 24/41 与 29/41 个 case**的成本表上评分，
缺失的正是 NOT_RUN 饥饿尾部，被按常数 `2.0` 计价——而**尾部正是最重的那端**。
算术铁证（作者复现）：组负载之和比 `measured_case_seconds` 恰好多 **34.0（=17×2.0）** 与 **24.0（=12×2.0）**。

在**唯一合法的全覆盖 41/41 表**上：旧轮转 75.5306s、shipped 新分区 **74.0080s**、下界 67.6663s
→ 真实改善只有 **1.5226s / 2.02%**，且 **79.8% 的随机 20/21 分区也超过旧轮转**。

**处理**：撤回 v1 的 16.10s/21.16s 声称；删除两份部分覆盖收据；对照脚本改为**拒绝任何 <41/41 的表**
（`comparison_refused: true`）；README/handoff/findings 改写为真实规模并标注「非接近最优」。

### 成本模型：一次过拟合尝试被弃用

作者进一步用 bootstrap 5000 次重采样自查，发现按 `declared_layer` 加权的模型（W07 ratio 1.0008，看似近乎最优）
**是过拟合**：仅 4 个取值、最优区间窄、Spearman 0.7855 **低于** run-count 的 0.8247、
重采样后 mean ratio 退化 1.0598 且只有 **64.2%** 胜过旧轮转（**差于** run-count 的 1.0498 / **70.2%**）。
→ **弃用 layer 模型，ship run-count**，并把理由与数字写进代码注释 + 一个钉住它的测试。

### D2（HIGH，已更正）：v1 的 RED 中 7/8 是同义反复

在纯净基线 `e8a8558` 分类（`receipts/A-red-baseline-classified.txt`）：
**6× ModuleNotFoundError + 1× FileNotFoundError + 仅 1× 真实行为断言**。
即 v1 的 RED 只证明「新模块不存在」，**位置轮转缺陷没有行为 RED**。
→ 新增 3 个驱动**真实 `cli_main.main`** 的行为 RED（委派、调度记录、stop_reason）。
现在基线 RED = **3 个真实行为失败 + 8 个模块缺失失败**。

### 其余更正（D4–D7）

- `implementation_commits` 不再为空；`changed_paths` 补齐（含 `commit-message.txt`）。
- 26-passed 与 339-passed 现在各有**独立收据**（`B-du8-suite.txt` / `B-regression.txt`），不再共用。
- 恢复脚本的 “exit 0” 表述更正：那 14/14 是**恢复脚本自身**的退出码，**没有任何一次真实批次 exit 0**。
- 三次真实批次**全部列出**（含最弱的恢复 clean attempt 14 PASS），v1 只写了两条。
- `supplier_calls=0`/`production_writes=0` 追加诚实限制：C 运行的 `restore.json`/`guard-events.json`
  随 `.tmp/` 删除，现仅能由未改动的 `ProductionGuard` 代码 + 中断 fixture 推断，**无独立产出物**。

**更正后回归**：新套件 **32 passed**；12 文件集中回归 **339 passed**；Ruff clean。



