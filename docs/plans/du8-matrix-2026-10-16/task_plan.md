# DU8-FF-MATRIX-COMPLETION

状态：A/B 完成；C 完成�?*未达 41PASS**（具名外部根因，未编造）�?*独立审查发现�?2 �?HIGH 过度声称已复现并更正（v2�?*。作�?STOP，待 ROOT 独立验收与合流�?工作目录`C:/Users/郑曾�?Projects/filing-fetch-du8-matrix`；分支`codex/du8-ff-matrix-20261016`；源码基线`e8a85585b4c64a9596e576ff3b73e5c2ee29c334`�?
PLAN_ID：`du8-matrix-2026-10-16`；计划目录为本目录，先读施工�?INTERFACES/findings/progress，不恢复其他根计划�?
> **v2 更正摘要**：v1 声称调度改善关键路径 16.10�?1.16s，实为在**部分覆盖�?4/41�?9/41�?*成本表上评分�?> �?NOT_RUN 尾部按常数计价所致；**全覆盖真实改善仅 1.5226s / 2.02%**。v1 �?RED 8 个失败中 7 个是同义反复�?> 已补 3 个驱动真�?`cli_main` 的行�?RED。详�?handoff.md §0、findings.md�?
## A：调查与真实行为RED

Status: complete

读实际源码和历史PWF，明确根�?原正确行为，独立期望先冻结。见 findings.md A.1–A.5�?分类后的 RED（基�?`e8a8558`）：`receipts/A-red-baseline-classified.txt` �?**3 个真实行为失�?+ 8 个模块缺失失�?*�?
## B：所属层实施与集中回�?
Status: complete

不跨白名单，不改旧gold/预算/门禁；集中相关快套件一次�?新增纯调�?owner `case_scheduling.py`（含 `cost_of` 实测钩子）；`cli_main.py` 接入成本均衡分组 +
具名 stop_reason + `scope.case_scheduling`；README 更新（含真实收益规模与过拟合弃用记录）�?新套�?**37 passed**（`receipts/B-du8-suite.txt`）；12 文件集中回归 **344 passed**（`receipts/B-regression.txt`）；Ruff clean�?全仓 15 个失败经纯净基线复现证明**全部既有**，本卡零新增失败�?
## C：公开入口E2E、恢复与交接

Status: complete（未�?41PASS，如实记录）

- 真实 41 �?*三次**（公开入口，未�?argv/限额）：21 PASS@{174.31s}�?6 PASS@{174.56s}�?  14 PASS@{182.49s}（恢复脚�?clean attempt，最弱，如实列出）。调度层完全均衡，`stop_reason` 具名�?- 受控中断/恢复端到端：**14/14 检查通过**；注意该 `exit 0` �?*恢复脚本自身**的退出码�?  没有任何真实批次 exit 0（v1 表述已更正）�?- 对照（全覆盖 41/41 唯一合法口径）：�?75.5306s �?�?**74.0080s**（改�?1.5226s / 2.02%）�?
## Next Step

ROOT 独立验收：核对白名单 �?�?handoff.md §0（勿恢复 v1 �?16�?1s 数字）→ 空载重跑 C �?41 �?�?决定 OPEN-2（`case_specs.py:490` �?1s deadline）。作�?STOP，不并主线、不安装技能、不推远端�?
## 固定只读依赖（仅FF�?
- `C:/Users/郑曾�?Projects/company-wiki-du6-ff-readonly` @ `f08aa101ab49ca983d3a40356abfb05347f586b3`，只读，不改源码/Git�?- `C:/Users/郑曾�?Projects/earnings-transcripts-du6-ff-readonly` @ `d0ac42c60dcca992db78860b8469cfed3dd527e5`，只读，不改源码/Git�?
## Decisions Made

| 决定 | 理由 |
|---|---|
| 成本模型用静�?run 计数，不读历史计时文�?| 矩阵必须能从固定输入复现；机器相关陈旧计时表是隐藏输�?|
| **ship** run-count 成本模型（而非 layer 模型�?| 理由**不是**“更稳健”（v2 曾如此声称，已被独立审查推翻——结论随重采样方案翻转）；真实理由是**更简单、provenance 透明、完全可由冻结输入推�?*，且在真实全覆盖数据上有已验证的小幅改善 |
| 两处 bootstrap 脚本作为可复现收据提�?| v2 曾把决定性的 bootstrap 数字写成散文式断言而脚本已删——与本卡批评�?隐藏证据"同类错误 |
| 新增 `cost_of` 钩子供调用方传入实测成本 | 这是本层唯一合法且有效的调度优化；runner 不隐式使用以免依赖上次计�?|
| 对照脚本**拒绝**任何 <41/41 覆盖的表 | 部分覆盖会把 NOT_RUN 饥饿尾部按常数计价，正是 v1 过度声称的成�?|
| 不提高限额、不裁分母、不重跑到偶然绿 | 施工卡明令禁�?|
| 具名记录 OPEN-1/OPEN-2 而非隐瞒 | `case_specs.py`/`extended_cases.py` 本卡只读 |
| 受控中断脚本只判定恢复语义，不判定是�?41PASS | 把“机器忙”和“恢复坏了”混为一谈就是卡里禁止的伪装门禁 |
| 审查指出�?*撤回并改�?*而非辩解 | 独立审查复现了作者的过度声称，作者二次复现确认后更正 |

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| PowerShell 不支�?`python - <<'PY'` heredoc | 1 | 改为写临�?`.py` 文件�?`python file` |
| �?fixture 脚本 `parents[2]` 解析�?`docs/plans` 而非仓库�?| 1 | 改为 `parents[4]`，并加显式路径存在性核�?|
| 测试断言“持�?case 的组必须更轻”过�?| 1 | 近完美均衡下无意义；改为“不得实质性更重”（�?%�?|
| Ruff F401/F841/E731 4 �?| 1 | `ruff --fix` + 手工改写 lambda �?def |
| **v1 调度收益被部分覆盖成本表放大**（独立审查发现） | 1 | 撤回头条数字；改用唯一全覆�?41/41 表；对照脚本改为拒绝部分�?|
| **v1 RED �?7/8 是同义反�?*（独立审查发现） | 1 | 新增 3 个驱动真�?`cli_main.main` 的行�?RED |
| layer 成本模型的“过拟合”论断（v2�?| 2 | 独立审查指出�?bootstrap 数字不可复现且结论随方案翻转；作者提交四种方案的可复现收据后确认**审查正确**，改为“ship 理由是简�?透明/可推导�?|
| **v2 把决算�?bootstrap 数字写成散文断言而脚本已�?*（独立审查再指出�?| 1 | 提交 `fixtures/cost_model_bootstrap.py` �?`..._sensitivity.py` + 两份 JSON 收据 |
| **提交�?`scheduling-comparison.json` 是拒绝产物而非全表对照**（独立审查再指出�?| 1 | 重新用全覆盖 W07 生成并提交；拒绝样本另存独立文件�?|
| `_assign` 测试辅助默认注入了实测成本，掩盖 shipped 路径 | 1 | 改为 `cost=None` 默认�?shipped 静态模�?|
