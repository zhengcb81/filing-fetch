# 进度

## 2026-10-16 会话 1 �?A 启动

- 读施工卡/INTERFACES/findings/progress（PWF 种子）�?- 核实环境：Python 3.13.9；只读依�?CWP/ET 两仓存在；分�?基线正确�?- 跑既有矩阵快�?8 文件�?*272 passed / 45.74s**（全绿，作为回归前基线）�?- �?W07 保留证据做真实成本分解：total 90.294s、�?case 之和 135.333s�?  现行轮转分组 g1=75.53s / g2=59.80s（差 15.7s）→ 定位调度不平衡为关键路径根因�?- 结论写入 findings.md A.1–A.4（含独立冻结期望）�?
未运�?未知：尚未跑本卡的新测试；尚未跑 C 的真�?41 链�?0 供应�?/ 0 真实 HTTP / 0 LLM / 0 翻译 / 0 生产写入�?
## 2026-10-16 会话 1 �?A RED 冻结

新测试两件（施工卡白名单内的新建文件）：

- `tests/test_du8_matrix_scheduling.py` �?成本均衡、顺序无关、链完整、并发不放大、预算不变�?- `tests/test_du8_matrix_deadline_recovery.py` �?取消�?0 新增启动、非协作子进程树回收�?  已退出管道释放、kill �?span 保持 unknown、失败目录不复用为成功、并发组互不污染�?
**A RED 首份（未修改源码前）**：`python -B -m pytest -q tests/test_du8_matrix_scheduling.py tests/test_du8_matrix_deadline_recovery.py`
�?**8 failed / 18 passed in 3.17s**，存 `receipts/A-red-baseline.txt`�?
失败即真实缺陷：
1. �?`case_scheduling` 调度 owner，现�?`entries[index::workers]` 轮转不平衡（实测 75.53/59.80）�?2. `run_case_group` �?`time.monotonic() >= deadline.end` �?`break` �?**`stop_reason` 保持 None** �?   批次被静默截断且报告不记原因（尾部饿死盲区）�?
## 2026-10-16 会话 1 �?B 实施

- 新增 `tools/offline_contract_matrix/case_scheduling.py`（纯调度 owner）：LPT 贪心 + 全序
  (cost desc, id asc)，成本模�?= CaseSpec run 数静态权重（2.0/次额�?run，基�?2.0s）�?  无时�?无子进程/无环�?�?I/O/无随机�?- `cli_main.py`：`groups` 改由 `case_scheduling.assign_groups` 产出；新�?`_measured_case_costs()`�?  报告 `scope.case_scheduling` 记录 group_loads/counts/预测 makespan/完美均衡下界/不平衡量�?- `cli_main.py`：批次绝对截止触发的截断现在写入具名 `stop_reason`（不再静默）�?
**B 集中回归**�?2 个相邻测试文�?�?**333 passed in 52.43s**（含全部既有矩阵套件，旧期望未改）�?
全仓测试对比（证明无新增失败）：
- 本卡工作树：**15 failed / 1164 passed / 22 skipped in 259.11s**
- 纯净基线 `e8a8558` 独立 worktree 跑同一批失败文件：**同样�?15 failed / 265 passed**
�?15 个失败全�?*既有**（复杂度诊断/安装�?config 假设类），与本卡改动无关，源码零新增失败。基�?worktree �?`git worktree remove`�?
## 2026-10-16 会话 1 �?C 第一次真�?41 链（未达 41PASS，如实记录）

命令（公开入口，未�?argv）：
```
python -B tools/offline_contract_matrix/run.py \
  --cwp-project  .../company-wiki-du6-ff-readonly \
  --et-project   .../earnings-transcripts-du6-ff-readonly \
  --owned-root .tmp/du8-c/owned --out-root .tmp/du8-c/out
```
结果�?*21 PASS / 1 FAIL / 2 PARTIAL / 17 NOT_RUN�?74.31s，exit 1，oracle 39 findings**�?`scope.case_scheduling` = group_loads **[52.0, 52.0]**、imbalance **0.0**、counts [20, 21] �?**调度本身完全均衡**�?`scope.stop_reason` = 具名（final-proof reserve preserved）→ 新加的具名停止原因生效，未静默截断�?
**根因（具名证据，非本层可修）**：工作站被其他并�?lane 打满�?- 实测 CPU load 82%�?2 逻辑核）�?5 个非本卡 `python` 进程属于其他 lane
  （`invest-quick-scan`、`revenue-forecast-du8-comparison`、别�?pytest）；本卡自身泄漏进程 **0**�?- 同机同输入的阶段成本对比 W07 保留报告�?  binding **2.997�?4.07s�?.7×�?*、seed **19.44�?9.16s�?.5×�?*�?  chainA �?case **10.61�?3.63s�?.2×�?*、`request_after_failure_retry` **8.27�?8.22s�?.4×�?*�?  `fin_cn_annual_hit` **1.94�?.50s�?.9×�?*�?  这正�?W07 交接里已记录的“单进程成本 2�?× 波动”，此次更差�?- 后果�? �?PARTIAL �?`child absolute deadline expired`（批次已 ~170s 才轮到，窗口被压到极小）�?  `call_hard_timeout` FAIL 是该 case 自身�?`stall` 场景 + `seconds=1` 供应商超时竞态在 3.7× 慢机下移位—�?  负载敏感的既�?case 语义，非调度问题�?
**负载归一化的调度对比** �?⚠️ **本小�?v1 的数字已被推翻，勿引用；见会�?2 更正�?*

v1 曾在此写「旧 167.33s �?�?151.22s，改�?16.10s」等�?*这些数字全部作废**�?它们是在只覆�?24/41 �?29/41 �?case 的成本表上算出的，把 NOT_RUN 饥饿尾部按常�?`2.0` 计价�?因而把收益从真实的 **1.5226s / 2.02%** 放大�?16�?1s�?合法权益口径�?`receipts/scheduling-comparison.json`（仅用全覆盖 41/41 表）�?
未运�?未知：尚未在较空载下重跑 41 链；`call_hard_timeout` 的负载敏感性未单独隔离验证�?0 供应�?/ 0 真实 HTTP / 0 LLM / 0 翻译 / 0 生产写入；第一次报告未覆写�?
## 2026-10-16 会话 2 �?独立审查发现 2 �?HIGH 过度声称，已复现并更�?
独立审查 agent（fork，全上下文）逐条核验 A–H 后指出两处实质问题�?*作者独立复现，确认审查正确�?*

### D1（HIGH，已更正）：调度收益的“隐藏分母�?
v1 �?`receipts/scheduling-comparison-run{1,2}.json` 只在**覆盖 24/41 �?29/41 �?case**的成本表上评分，
缺失的正�?NOT_RUN 饥饿尾部，被按常�?`2.0` 计价——�?*尾部正是最重的那端**�?算术铁证（作者复现）：组负载之和�?`measured_case_seconds` 恰好�?**34.0�?17×2.0�?* �?**24.0�?12×2.0�?*�?
�?*唯一合法的全覆盖 41/41 �?*上：旧轮�?75.5306s、shipped 新分�?**74.0080s**、下�?67.6663s
�?真实改善只有 **1.5226s / 2.02%**，且 **79.8% 的随�?20/21 分区也超过旧轮转**�?
**处理**：撤�?v1 �?16.10s/21.16s 声称；删除两份部分覆盖收据；对照脚本改为**拒绝任何 <41/41 的表**
（`comparison_refused: true`）；README/handoff/findings 改写为真实规模并标注「非接近最优」�?
### 成本模型：一次过拟合尝试被弃�?
作者进一步用 bootstrap 5000 次重采样自查，发现按 `declared_layer` 加权的模型（W07 ratio 1.0008，看似近乎最优）
**是过拟合**：仅 4 个取值、最优区间窄、Spearman 0.7855 **低于** run-count �?0.8247�?重采样后 mean ratio 退�?1.0598 且只�?**64.2%** 胜过旧轮转（**差于** run-count �?1.0498 / **70.2%**）�?�?**弃用 layer 模型，ship run-count**，并把理由与数字写进代码注释 + 一个钉住它的测试�?
### D2（HIGH，已更正）：v1 �?RED �?7/8 是同义反�?
在纯净基线 `e8a8558` 分类（`receipts/A-red-baseline-classified.txt`）：
**6× ModuleNotFoundError + 1× FileNotFoundError + �?1× 真实行为断言**�?�?v1 �?RED 只证明「新模块不存在」，**位置轮转缺陷没有行为 RED**�?�?新增 3 个驱�?*真实 `cli_main.main`** 的行�?RED（委派、调度记录、stop_reason）�?现在基线 RED = **3 个真实行为失�?+ 8 个模块缺失失�?*�?
### 其余更正（D4–D7�?
- `implementation_commits` 不再为空；`changed_paths` 补齐（含 `commit-message.txt`）�?- 26-passed �?339-passed 现在各有**独立收据**（`B-du8-suite.txt` / `B-regression.txt`），不再共用�?- 恢复脚本�?“exit 0�?表述更正：那 14/14 �?*恢复脚本自身**的退出码�?*没有任何一次真实批�?exit 0**�?- 三次真实批次**全部列出**（含最弱的恢复 clean attempt 14 PASS），v1 只写了两条�?- `supplier_calls=0`/`production_writes=0` 追加诚实限制：C 运行�?`restore.json`/`guard-events.json`
  �?`.tmp/` 删除，现仅能由未改动�?`ProductionGuard` 代码 + 中断 fixture 推断�?*无独立产出物**�?
**更正后回�?*：新套件 **37 passed**�?2 文件集中回归 **344 passed**；Ruff clean�?


