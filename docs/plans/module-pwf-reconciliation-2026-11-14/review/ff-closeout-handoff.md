# FF-PLAN-WORKTREE-CLOSEOUT 交接

- 卡：company-wiki `docs/plans/module-pwf-reconciliation-2026-11-14/owner_cards/ff_closeout.md`（唯一写入仓 = 本仓 filing-fetch）。
- 仓库：`C:/Users/郑曾波/Projects/filing-fetch`；canonical PWF：`PLANNING_STATUS.md`（2026-11-14 checkpoint 为唯一入口）。
- base：`main@d4f35cab5127d09c874d109080d911e6d394dec2`（= 交接时 `origin/main`，`git ls-remote` 实时核实）。
- final：`main`，内容候选提交 = 本卡全部变更（PLANNING_STATUS 刷新 + 根三件历史标注 + W20/DU10 冲突 banner），handoff 文档为紧随的 docs-only 提交；审查绑定与推送确认见 §9。
- remote：`https://github.com/zhengcb81/filing-fetch.git`（有 remote；`origin/main` 在开工时 = d4f35ca）。

## 1. 实时状态核对（开工重核，非卡片快照复述）

| 项 | 卡片快照 | 实时核对 | 结论 |
|---|---|---|---|
| 主线 | `main@d4f35ca` = `origin/main`，tracked clean | 一致（`git ls-remote` = d4f35ca；tracked 无改动） | 无漂移 |
| worktree 数 | 35 | 35（`git worktree list`） | 一致 |
| 待归因 ref | 3 个 | `codex/dashboard-ff-b34-candidate@9be5587`、`codex/ff-job-facade-01@154c22...`（154c292）、`codex/transcript-companion@29085f7` 均不在 main；其余全部 worktree HEAD 均在 main | 一致 |
| 未跟踪保留项 | 4 项 | `.ff_jobs/`、`.mimosa/`、`.workbuddy-ai/`、`config/FMP_API_KEY.txt` 原样保留，密钥未读取 | 一致 |

关键历史事实（解释 ff-job 分支不在 main 但代码已吸收）：reflog 显示 2026-11-07 本地 main 曾快进到 `154c292`（release=eaf8a5e，未推送），2026-11-10 `reset: moving to origin/main`（f65e6ca）丢弃该本地线；origin/main 上以 `57351d0`/`7d8392e` 重落等价 job facade 内容，随后 MB-FF `c870ab7` 继续演化。分支上的 lane 收据（`.planning/ff-job-facade-01/**`，含 F-08）因此只存在于分支。

## 2. PWF landing 动作（步骤 1）

1. `PLANNING_STATUS.md`：新 "Current checkpoint — 2026-11-14" —— 唯一主线 `main@d4f35ca`、owner、无未结产品 lane（本 closeout 为唯一在办）、已完成 lane 索引、FF 产品面唯一未决项 F-08、下一步、保留项。原 10-04 checkpoint 原文逐字保留在 "历史快照入口" 节内并标注取代关系；更早 9 月段落原样保留。
2. 根 `task_plan.md`/`progress.md`/`findings.md`：顶部加 2026-11-14 历史档案 banner（链接 `PLANNING_STATUS.md` 与 `TERMINAL_NOTICE.json`），原文未动。
3. `docs/plans/w20-ff-replay-2026-10-28/task_plan.md`：顶部 banner —— READY 状态被 `root_closeout.md`（2026-10-29 ROOT 收尾：mid-import 三态修复，7 参数化 RED，短包 203 passed，R3 复审由 company-wiki w20-reception-r3 记录）取代；分支 tip `2b61088` 已在 main。状态 completed（superseded）。
4. `docs/plans/du10-ff41-close-2026-10-17/NEXT_HANDOFF.md`：顶部 banner —— 待做 1–4 被 `ROOT_RECEPTION.md`（PASS / 0 未解决）与作者最终提交 `ff2ba40`（含 handoff/审查归档/临时树清理）取代；保留作熔断中断恢复的历史记录。状态 superseded（completed）。

## 3. 冲突逐条标记（步骤 2）

| 冲突 | 标记 | 依据 |
|---|---|---|
| MB-FF handoff 未记当前 d4f35ca | completed（+ 后续 docs 提交） | §9 已记 41acdc8 并线；其后 e6088f2、d4f35ca 为 docs-only 推进，主线历史含全部交付；完整 CI 收据 ci-full-r6（1012 passed / 2 skipped / 44 subtests）绑 c870ab7 |
| W20 task_plan READY vs root_closeout 完成收据 | superseded → completed | root_closeout.md 2026-10-29 记录 ROOT 收尾完成；2b61088 在 main |
| DU10 NEXT_HANDOFF 待办 vs ROOT_RECEPTION PASS | superseded | ROOT_RECEPTION 记 PASS / 0 未解决；ff2ba40 含清理提交；NEXT_HANDOFF 保留作中断恢复历史 |
| PLANNING_STATUS 10-04 指 `fcap@eb0af13` | superseded（历史） | 主线已重建为 main（11-10 reset 后经 MB-FF 等并线至 d4f35ca） |

## 4. 三个候选 ref 归因（步骤 3）

| ref | disposition | 核心依据 |
|---|---|---|
| `codex/ff-job-facade-01@154c292` | EVIDENCE_KEEP | 特性代码已被主线吸收：`scripts/ff_job.py` 与 main 逐字节一致（diff 为空）；contracts/runner/store 由主线 `57351d0`/`7d8392e` 重落并经 `c870ab7`（MB-FF 一次请求接线）演化超前。分支唯一内容 = `.planning/ff-job-facade-01/**` lane 收据（handoff 绑 release=eaf8a5e、复测 0 OPEN P1/P2、P3 F-08、验收 drill 证据）；11-10 reset 后这些收据不在主线历史 |
| `codex/dashboard-ff-b34-candidate@9be5587` | EVIDENCE_KEEP | 修复已吸收：`5ec54e0`（mid-import public lookup state）本身在 main（merge-base 验证）；`53285c2`（unknown publication）的全部改动行是主线 `d563b63` 的子集且主线扩展了参数化测试（sorted-line diff 无 “<” 行）。唯一内容 = `9be5587` 的 `.planning/dashboard-B34-source-candidate/**` 收据（handoff + evidence manifest，9 文件 +206 行） |
| `codex/transcript-companion@29085f7` | EVIDENCE_KEEP | 与当前 v2/DU11 处理比较后确认取代：原型 `transcript_companion.py`（旧 schema/路径假设，"Company-wiki owns … canonical writes"）与主线版本 758 行差异（193+/565-）；主线另有 `transcript_reuse_selection.py`（DU11 复用选择）与 `transcript_tool_transport.py`（DU11 子进程传输）。按 10-04 PWF 判断保留作历史材料，不适配、不 cherry-pick |

## 5. worktree 与目录 disposition 摘要（35 + 14，明细见 handoff.json）

- **ACTIVE_KEEP（1）**：主检出 `Projects/filing-fetch`。
- **DELETE_AFTER_OWNER_CONFIRMATION（worktree 20 + 目录 13）**：所有 clean 且分支/HEAD 已在 main、收据在主线（docs/plans/** 或 .planning/**）的 FF lane 工区——`.codex/worktrees/{du11-ff-reception,m3-acceptance-20261010,m3-acquisition-usage-20261010}`、`_harness_worktrees/cmrf-20261008/{ff-diagnostics,ff-permission-residue}`、`_harness_worktrees/w06/ff-contract-matrix-root`、`ffjf01`、13 个 `Projects/filing-fetch-*`。本卡作为 FF owner 的分类结论：可删（分支保留，无可删独有内容）；实际移除待确认无在途会话占用路径后执行（本卡未执行任何删除）。
- **UNCLASSIFIED_HOLD（worktree 14）**：
  - `.fcap-review/*`（6）：用户 FCAP 跨仓审查快照（detached，全部 HEAD 在 main、clean），owner 未在本仓 PWF 查清，原样保留。
  - `_harness_worktrees/dashboard-ff-job-20261109`（dirty）：`docs/ff-job-protocol.md` 未提交修改 = F-08 修复设计草案（owner-local OS lock 替代 O_EXCL pointer-first + `.submit.lock`）——在途 dashboard lane 工作，原样保留并上报。
  - `_harness_worktrees/dashboard-ff-job-release-20261109`（clean，7d8392e 已在 main）：dashboard 模块 lane 工区，归属 dashboard，原样保留。
  - `_harness_worktrees/w06/ff-contract-matrix`（dirty）：`.planning/w06-ff-matrix/{progress,task_plan}.md` +7/-4 与 untracked `docs/handoffs/w06-ff-matrix/input/`（lane 输入文档）——w06 lane 残留，保留。
  - `_harness_worktrees/w07/ff-matrix-efficiency`（dirty）：untracked `.planning/w07-ff-matrix-efficiency/**` 与 `.tmp/` 共 1,764 个文件——w07/harness lane 残留，保留。
  - `cwp-lanes-20261005/{ff-main-integration,ff-runtime-cleanup}`（clean，分支 211a56f/ab9ce33 已在 main）：目录属 CWP lanes 基建，跨 owner，保留。
  - `investment-dashboard/.worktrees/b34-ff-candidate`（clean）：位于 dashboard 仓 `.worktrees/` 内，跨 owner；分支 EVIDENCE_KEEP。

## 6. dirty exceptions（原样保留，不并入、不删除）

1. 主仓 untracked：`.ff_jobs/`、`.mimosa/`、`.workbuddy-ai/`、`config/FMP_API_KEY.txt`（运行状态/凭据；卡指定保留，密钥未读取）。
2. `_harness_worktrees/dashboard-ff-job-20261109`：M `docs/ff-job-protocol.md`（F-08 修复设计草案，owner=dashboard lane）。
3. `_harness_worktrees/w06/ff-contract-matrix`：M 两个 .planning 文档 + untracked input 目录（owner=w06 lane）。
4. `_harness_worktrees/w07/ff-matrix-efficiency`：untracked 1,764 文件（owner=w07/harness lane）。

以上均不与本卡写集合重叠（本卡只写 PLANNING_STATUS、根三件、W20/DU10 两 banner、本 review 目录）。

## 7. cleanup（精确）

本轮未执行任何删除：`paths: []`、`file_count: 0`、`bytes: 0`。清理动作按 §5 disposition 于"无在途会话确认"后另行执行；分支一律保留。

## 8. 测试（docs-only 门禁，卡指定）

| 命令 | 结果 |
|---|---|
| `python -I -c "import json;json.load(open(...ff-closeout-handoff.json))"` | exit 0，JSON 可解析 |
| `git diff --check <提交范围>` | 无空白错误 |
| Markdown 链接检查（新增/修改 md 的相对链接指向存在文件） | 全部通过 |

无代码改动，未跑 pytest/CI（卡：纯文档时按 JSON/link/`git diff --check` 检查）。

## 9. 自引用约定与推送确认

- `handoff.json.final.head` = 审查绑定候选 HEAD（含 handoff 文档的实际提交）；`final.remote_head` 同值（卡语义：收尾后远端 main HEAD）。由于提交无法包含自身 SHA，审查报告提交（仅追加报告 + JSON `independent_review`/`final` 字段更新）为最后一个 docs-only 提交；推送确认以 `git ls-remote origin refs/heads/main` 实测为准，结果记录于审查报告与交接会话。
- 流程：作者提交候选 → 独立 reviewer 审查绑定该 HEAD → PASS 后追加报告提交（reviewer 复核该提交仅追加报告/JSON 字段）→ 推送 → `git ls-remote` 确认远端 == 已审内容 tip。

## 10. Mimosa git-gate 事件披露

- 2026-11-14 提交候选时，Mimosa L3 git-gate（PreToolUse:Bash，拦截所有 Bash 调用，`--no-verify` 无效）以 9 项发现强制拦截提交。3 high：`tests/fixtures/public_operation_isolation/independent_service.py:189/318`、`tests/test_process_business_exit.py:180`；6 low：`docs/plans/du8-matrix-2026-10-16/fixtures/` 三个仿真夹具的 random、`scripts/fetch_filing.py:412` retry-backoff jitter、`tests/test_real_tool_conformance.py:181`。**全部为既有密封交付内容，不在本卡写集合。**
- 按钩子指令运行 Mimosa 密封扫描（deep）：scan-job-mwgfli7e-fabfd2aea2bd0a56 完成，scanId `scan-2026-11-14T13-18-59.787Z-e5e73baabdfa`，seal `sha256:db39d990d7e9458ebe9fa5ec1e38e9c9cf0cbb0a7da42e85fdb23f64b6cf3f2a`，findingCount=1；**但 git-gate 不采纳扫描结果，仍以同样 9 项拦截**。门禁判定逻辑在插件加密载荷内，无文档化解除条件或豁免机制。
- 性质初判：高危项为密封测试替身/测试代码按设计行为（fixture 提供样例文件、测试子进程写 pid 文件）；`fetch_filing.py:412` 的 random 用于重试抖动，非安全敏感。修复将变更密封收据绑定的文件字节。
- **结论：提交/推送被用户级安全门禁阻塞，需 owner/ROOT 裁决**：调整门禁拦截面（排除密封测试代码）或接受收据字节变更。事件与 scanId 已记入 handoff.json remaining_items。

## 11. remaining_items 与唯一下一步

remaining：
1. F-08（P3，ff-job/1）：dashboard lane 修复草案已在 dirty 工区；等待其并线 + FF job 受影响回归 + 一次完整 CI。
2. 3 个 dirty 工区残留（dashboard/w06/w07）：owner 各自 lane 处置。
3. 20 worktree + 13 目录的 DELETE_AFTER_OWNER_CONFIRMATION 实际移除：待无在途会话确认。
4. D4-05 stderr-window contract 的 ROOT ratification（bf7e1da 已在 main）：owner=ROOT。
5. 生产 `config/company_wiki.json` legacy 形态迁移：mb11 out-of-scope 记录。
6. Mimosa git-gate vs 密封收据冲突裁决：见 §10。

唯一下一步：等待 dashboard F-08 修复 lane 按正常流程并线 FF `main`（依赖：dashboard lane 交付修复 + FF job 受影响回归 + 完整 CI 绿）；FF 无其他待开工任务。
