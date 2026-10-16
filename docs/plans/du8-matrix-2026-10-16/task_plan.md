# DU8-FF-MATRIX-COMPLETION

状态：A/B 完成；C 完成但**未达 41PASS**（具名外部根因，未编造）。**独立审查发现的 2 处 HIGH 过度声称已复现并更正（v2）**。作者 STOP，待 ROOT 独立验收与合流。
工作目录`C:/Users/郑曾波/Projects/filing-fetch-du8-matrix`；分支`codex/du8-ff-matrix-20261016`；源码基线`e8a85585b4c64a9596e576ff3b73e5c2ee29c334`。

PLAN_ID：`du8-matrix-2026-10-16`；计划目录为本目录，先读施工卡/INTERFACES/findings/progress，不恢复其他根计划。

> **v2 更正摘要**：v1 声称调度改善关键路径 16.10–21.16s，实为在**部分覆盖（24/41、29/41）**成本表上评分、
> 把 NOT_RUN 尾部按常数计价所致；**全覆盖真实改善仅 1.5226s / 2.02%**。v1 的 RED 8 个失败中 7 个是同义反复，
> 已补 3 个驱动真实 `cli_main` 的行为 RED。详见 handoff.md §0、findings.md。

## A：调查与真实行为RED

Status: complete

读实际源码和历史PWF，明确根因/原正确行为，独立期望先冻结。见 findings.md A.1–A.5。
分类后的 RED（基线 `e8a8558`）：`receipts/A-red-baseline-classified.txt` →
**3 个真实行为失败 + 8 个模块缺失失败**。

## B：所属层实施与集中回归

Status: complete

不跨白名单，不改旧gold/预算/门禁；集中相关快套件一次。
新增纯调度 owner `case_scheduling.py`（含 `cost_of` 实测钩子）；`cli_main.py` 接入成本均衡分组 +
具名 stop_reason + `scope.case_scheduling`；README 更新（含真实收益规模与过拟合弃用记录）。
新套件 **32 passed**（`receipts/B-du8-suite.txt`）；12 文件集中回归 **339 passed**（`receipts/B-regression.txt`）；Ruff clean。
全仓 15 个失败经纯净基线复现证明**全部既有**，本卡零新增失败。

## C：公开入口E2E、恢复与交接

Status: complete（未达 41PASS，如实记录）

- 真实 41 链**三次**（公开入口，未改 argv/限额）：21 PASS@{174.31s}、26 PASS@{174.56s}、
  14 PASS@{182.49s}（恢复脚本 clean attempt，最弱，如实列出）。调度层完全均衡，`stop_reason` 具名。
- 受控中断/恢复端到端：**14/14 检查通过**；注意该 `exit 0` 是**恢复脚本自身**的退出码，
  没有任何真实批次 exit 0（v1 表述已更正）。
- 对照（全覆盖 41/41 唯一合法口径）：旧 75.5306s → 新 **74.0080s**（改善 1.5226s / 2.02%）。

## Next Step

ROOT 独立验收：核对白名单 → 读 handoff.md §0（勿恢复 v1 的 16–21s 数字）→ 空载重跑 C 的 41 链 →
决定 OPEN-2（`case_specs.py:490` 的 1s deadline）。作者 STOP，不并主线、不安装技能、不推远端。

## 固定只读依赖（仅FF）

- `C:/Users/郑曾波/Projects/company-wiki-du6-ff-readonly` @ `f08aa101ab49ca983d3a40356abfb05347f586b3`，只读，不改源码/Git。
- `C:/Users/郑曾波/Projects/earnings-transcripts-du6-ff-readonly` @ `d0ac42c60dcca992db78860b8469cfed3dd527e5`，只读，不改源码/Git。

## Decisions Made

| 决定 | 理由 |
|---|---|
| 成本模型用静态 run 计数，不读历史计时文件 | 矩阵必须能从固定输入复现；机器相关陈旧计时表是隐藏输入 |
| **ship** run-count 成本模型（而非 layer 模型） | 理由**不是**“更稳健”（v2 曾如此声称，已被独立审查推翻——结论随重采样方案翻转）；真实理由是**更简单、provenance 透明、完全可由冻结输入推导**，且在真实全覆盖数据上有已验证的小幅改善 |
| 两处 bootstrap 脚本作为可复现收据提交 | v2 曾把决定性的 bootstrap 数字写成散文式断言而脚本已删——与本卡批评的"隐藏证据"同类错误 |
| 新增 `cost_of` 钩子供调用方传入实测成本 | 这是本层唯一合法且有效的调度优化；runner 不隐式使用以免依赖上次计时 |
| 对照脚本**拒绝**任何 <41/41 覆盖的表 | 部分覆盖会把 NOT_RUN 饥饿尾部按常数计价，正是 v1 过度声称的成因 |
| 不提高限额、不裁分母、不重跑到偶然绿 | 施工卡明令禁止 |
| 具名记录 OPEN-1/OPEN-2 而非隐瞒 | `case_specs.py`/`extended_cases.py` 本卡只读 |
| 受控中断脚本只判定恢复语义，不判定是否 41PASS | 把“机器忙”和“恢复坏了”混为一谈就是卡里禁止的伪装门禁 |
| 审查指出后**撤回并改写**而非辩解 | 独立审查复现了作者的过度声称，作者二次复现确认后更正 |

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| PowerShell 不支持 `python - <<'PY'` heredoc | 1 | 改为写临时 `.py` 文件再 `python file` |
| 新 fixture 脚本 `parents[2]` 解析到 `docs/plans` 而非仓库根 | 1 | 改为 `parents[4]`，并加显式路径存在性核验 |
| 测试断言“持重 case 的组必须更轻”过严 | 1 | 近完美均衡下无意义；改为“不得实质性更重”（≤1%） |
| Ruff F401/F841/E731 4 项 | 1 | `ruff --fix` + 手工改写 lambda 为 def |
| **v1 调度收益被部分覆盖成本表放大**（独立审查发现） | 1 | 撤回头条数字；改用唯一全覆盖 41/41 表；对照脚本改为拒绝部分表 |
| **v1 RED 中 7/8 是同义反复**（独立审查发现） | 1 | 新增 3 个驱动真实 `cli_main.main` 的行为 RED |
| layer 成本模型的“过拟合”论断（v2） | 2 | 独立审查指出该 bootstrap 数字不可复现且结论随方案翻转；作者提交四种方案的可复现收据后确认**审查正确**，改为“ship 理由是简单/透明/可推导” |
| **v2 把决算性 bootstrap 数字写成散文断言而脚本已删**（独立审查再指出） | 1 | 提交 `fixtures/cost_model_bootstrap.py` 与 `..._sensitivity.py` + 两份 JSON 收据 |
| **提交的 `scheduling-comparison.json` 是拒绝产物而非全表对照**（独立审查再指出） | 1 | 重新用全覆盖 W07 生成并提交；拒绝样本另存独立文件名 |
| `_assign` 测试辅助默认注入了实测成本，掩盖 shipped 路径 | 1 | 改为 `cost=None` 默认走 shipped 静态模型 |
