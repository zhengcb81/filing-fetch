# FF-PLAN-WORKTREE-CLOSEOUT 独立审查报告

- **审查者**：未参与实施的独立 reviewer（ZCode final-review agent）
- **审查日期**：2026-11-14
- **绑定 HEAD**：`27babced4ab1e78fd0778b424c2535c343830b32`（`main`，本地领先 `origin/main` 2 个提交：`ca57e14` 修复+文档落地、`27babce` 交接证据更新；基线 `d4f35ca` = `origin/main`，经 `git ls-remote` 实测确认）
- **审查依据**：owner card `company-wiki/docs/plans/module-pwf-reconciliation-2026-11-14/owner_cards/ff_closeout.md`；交付物 `ff-closeout-handoff.md` / `ff-closeout-handoff.json`（均位于本 HEAD）
- **审查范围**：卡片全部执行步骤与完成条件；diff `d4f35ca..27babce` 全量；52 条 disposition 抽样核验（含全部 3 个 ref）；PWF landing；Mimosa 授权修复记录；handoff.json schema/计数；定向测试复跑。审查为只读，未改动除本报告外的任何文件，未读取 `config/FMP_API_KEY.txt` 内容。

## 1. 分项审查结果

| # | 审查项 | 结果 | 关键证据 |
|---|---|---|---|
| 1 | 卡片执行步骤 1（PWF landing） | PASS | `PLANNING_STATUS.md` 新增 2026-11-14 checkpoint：唯一主线、owner、无未结产品 lane（closeout 为唯一在办）、已完成 lane 索引、F-08 未决项、唯一下一步；10-04 checkpoint 移入"历史快照入口"节并标注取代关系。当前 HEAD 表述为基线 `main@d4f35ca`（自引用约束，交付链由 handoff §6/§9 记录，见观察 O-1） |
| 2 | 卡片执行步骤 2（冲突逐条标记） | PASS | W20 banner（READY → superseded/completed，引用 root_closeout.md 实存且日期 2026-10-29、"7 参数化真实 RED=6失败1控制通过；短包 203 通过"逐字核对）、DU10 banner（引用 ROOT_RECEPTION.md 实存且明示"状态：PASS"，`ff2ba40` 已在 main）、MB-FF `d4f35ca` 记录、10-04 `fcap@eb0af13` 历史化；未删除任何历史证据 |
| 3 | 卡片执行步骤 3（35 worktree + 14 目录 + 3 ref 逐项处置） | PASS | handoff.json 52 条 = 35 worktree + 14 directory + 3 branch；全部 4 worktree HEAD 不在 main 的恰为 154c292×2、29085f7、9be5587（逐一 sweep 核实）；dirty/untracked/跨 owner 项均 HOLD，未凭名字或 dirty 单独判删 |
| 4 | 3 个 ref 归因证据 | PASS | ff-job：`git diff 154c292 27babce -- scripts/ff_job.py` 为空；`.planning/ff-job-facade-01` 不在 main 工作树且不在 main 历史；`git grep F-08 154c292` 命中 handoff.json；`git cherry` 7 提交均不在主线；reflog 核实 11-07 快进 154c292、11-10 reset f65e6ca。B34：`5ec54e0` 是 main 祖先；53285c2 非 main 祖先但其全部 +/- 行是 `d563b63`（main 祖先）diff 行的子集（comm 为空）；9be5587 仅新增 9 个收据文件 +206 行。transcript：`transcript_companion.py` 差异 193+/565-（758 行）；main 另有 `transcript_reuse_selection.py`、`transcript_tool_transport.py`；两版 docstring 与 handoff 描述一致 |
| 5 | 吸收类 disposition 抽查 | PASS | `ff2ba40`（DU10）、`2b61088`（W20）、`8c7aded`（W07）均为 main 祖先；对应 worktree `filing-fetch-du10-41-matrix`、`filing-fetch-w20-replay`、`ffjf01` 实测 clean |
| 6 | dirty exceptions（4 项） | PASS | 主仓 untracked 恰为 `.ff_jobs/`、`.mimosa/`、`.workbuddy-ai/`、`config/FMP_API_KEY.txt`（密钥仅出现在 status 列表，内容未读取）；`dashboard-ff-job-20261109` 仅 `M docs/ff-job-protocol.md`；`w06/ff-contract-matrix` 为 2 个 .planning 修改 + untracked input 目录；`w07` 为 untracked .planning/** + .tmp/（声明 1,764 文件，实测现值 1,787，运行态目录漂移，见 O-2） |
| 7 | cleanup | PASS | `paths: []`、`file_count: 0`、`bytes: 0`；本 diff 未删除任何文件（10 个文件全部为新增/修改） |
| 8 | diff 写集合边界 | PASS | `git diff d4f35ca..27babce --stat`：恰 10 个文件 = 8 文档（PLANNING_STATUS、根三件、W20/DU10 两 banner、handoff.md/json）+ 2 测试代码（`tests/test_process_business_exit.py`、`tests/fixtures/public_operation_isolation/independent_service.py`）。无 CWP/RF/ET 文件、无 scripts/ 生产源码改动、`config/FMP_API_KEY.txt` 未触碰 |
| 9 | Mimosa 授权修复记录（handoff.md §10） | PASS | 与 git 证据一致：ca57e14 含两修复文件（reflog 显示 38562c2→67cfea5→ca57e14 amend 链，与"首轮修复遗漏入库后补齐"叙述吻合）；修复内容与 §10 描述逐条对应（子进程 pathlib 写字面量 `child.pid` + `cwd=tmp_path`；fixture `_harness_log_path()` 归一化 + 二次校验）；SHA 绑定声明核实——mb11 收据及全部 docs/plans 中无任何 sha256 行绑定两修复文件，DU11 `transcript_tool_transport.py` 有 sha256 绑定（handoff.json source_freeze_sha256）且未在 diff 中触碰；6 个 low 逐项披露且不在授权范围 |
| 10 | handoff.json schema 与计数 | PASS | `python -I` 解析通过（裸 JSON）；顶层键与卡片 13 个固定键完全一致；`schema_version="1"`；dispositions 52 条（35/14/3），每条恰含 kind/path/status/reason/evidence；状态计数 33 DELETE_AFTER_OWNER_CONFIRMATION / 14 UNCLASSIFIED_HOLD / 3 EVIDENCE_KEEP / 2 ACTIVE_KEEP；cleanup 零值；tests 5 条均含 command/result；independent_review 四字段齐全 |
| 11 | `final.head` / `independent_review` 占位符 | PASS（有约定） | `PENDING_REVIEW_COMMIT` / `PENDING` 占位由 handoff.md §9 明文记录的自引用约定覆盖（提交无法包含自身 SHA；审查报告提交为最后 docs-only 提交，仅追加报告 + JSON `independent_review`/`final` 更新）——符合卡片"独立 review Markdown 记录绑定 HEAD 与 PASS/FAIL"的设计 |
| 12 | docs-only 门禁 | PASS | `git diff d4f35ca..27babce --check` 无空白错误；本报告抽查新增链接目标（TERMINAL_NOTICE.json、ROOT_RECEPTION.md、root_closeout.md）均存在；handoff.md 无相对链接（路径均为行内代码） |
| 13 | 推送时序 | PASS（按卡未推送） | `git ls-remote origin refs/heads/main` = d4f35ca；卡片规定 PASS 后才推送并确认远端 = 已审内容 tip，当前状态符合流程 |

## 2. 定向测试复跑（reviewer 实测）

```
/c/Miniconda/python.exe -B -m pytest tests/test_process_business_exit.py tests/test_public_operation_isolation.py -q -p no:cacheprovider --basetemp=C:/Users/郑曾波/Projects/.ff-closeout-scratch/btR1
=> 48 passed in 33.81s
```

与 handoff 声明（48 passed）一致。完整 CI（1012 passed / 2 skipped / 44 subtests）按审查约束未复跑；其数字与 mb11 收据 `ci-full-r6`（mb11 handoff.md 明载 1012/2/44）一致，且本 diff 仅触及 2 个测试文件，风险可控。

## 3. 发现清单

| 编号 | 严重度 | 状态 | 描述 |
|---|---|---|---|
| F-1 | P3 | OPEN | handoff.md §5 汇总计数笔误：`.fcap-review/*（6）`，实际为 7（`git worktree list` 实测 7 个 fcap worktree；handoff.json 正确记录 7 条且总计 14 正确）；同节 "ACTIVE_KEEP（1）" 与 JSON 的 2 条 ACTIVE_KEEP（worktree+directory 同路径各一条）口径不一致。JSON 为权威数据，仅 md 汇总文字有误 |
| F-2 | P3 | OPEN | B34 分支 disposition 证据路径不准确：handoff.md §4 与 handoff.json 均写 `.planning/dashboard-B34-source-candidate/**`，实际位置为 `docs/handoffs/dashboard-B34-source-candidate/**`（9 文件 +206 行数字正确；`git show 9be5587 --name-status` 核实）。EVIDENCE_KEEP 结论不受影响 |
| F-3 | P3 | CLOSED（erratum） | handoff.md §2 称 10-04 checkpoint "原文逐字保留"，实际首条 bullet 有两处时态改写（"当前 FF 主线为"→"当时 FF 主线记录为"、"与 live"→"与当时 live"），其余 bullets 逐字保留。实质内容完整，仅表述略有过称 |
| O-1 | 观察 | 接受 | PLANNING_STATUS 2026-11-14 checkpoint 将"当前 HEAD"记为基线 `main@d4f35ca` 而非 tip：提交无法内嵌自身 SHA，交付链由同树 handoff §6/§9 与 checkpoint 内的 closeout 交付指针覆盖，属已文档化的自引用约定；PASS 后作者最后 docs-only 提交更新 JSON `final.head`，推送确认以 `git ls-remote` 实测记录 |
| O-2 | 观察 | 接受 | w07 untracked 文件数声明 1,764，审查时实测 1,787（`.tmp/` 为在跑 harness 运行态，交接后自然漂移）；UNCLASSIFIED_HOLD 处置不受影响 |
| O-3 | 观察 | 接受 | 完整 CI 未由 reviewer 复跑（审查约束禁止）；以 mb11 ci-full-r6 收据交叉核对数字一致性，并以定向复跑 48 passed 补强 |

P3 发现均为交接文档的计数/路径/表述精度问题，不触及处置结论、Git 证据或代码正确性；可在 PASS 后的最后 docs-only 提交中顺手修正（或记录为本报告 erratum），不构成阻塞。

## 4. 卡片完成条件核对

- 最终 PWF 单一入口回答当前 HEAD/owner/已完成/未完成/下一步：满足（见 §1 项 1；HEAD 表述按 O-1 约定接受）。
- 3 refs、35 worktree、14 顶层目录逐项有处置：满足（52 条，逐项 kind/path/status/reason/evidence）。
- 未跟踪敏感/运行状态原样保留：满足（4 项原样，密钥未读取）。
- 代码改动时完成 FF 定向套件 + 一次相关完整 CI：满足（48 passed reviewer 复跑一致；完整 CI 1012/2/44 有收据记录且与 mb11 基线一致）。
- 独立 reviewer 结论绑定已提交候选 HEAD：本报告绑定 `27babce`，结论 PASS。
- 通过后推送并确认远端 = 已审 tip：待 PASS 后执行（当前 origin/main = d4f35ca，符合卡定时序）。

## 5. 结论

审查未发现任何 P1/P2 问题；3 个 P3 均为文档精度问题且不阻塞。候选 HEAD `27babce` 满足卡片全部执行步骤与完成条件，Mimosa 授权修复记录与 git/测试证据一致，handoff.json 符合卡片 schema 约定。

VERDICT: PASS
