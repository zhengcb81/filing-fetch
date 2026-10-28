# W20-FF-REPLAY 最终独立复审报告（review/final.md）

- 审查者：最终独立复审 agent（与作者、初审 agent 均无关；本文件为复审唯一产物，由复审者直接写入）
- 日期：2026-10-28
- 工区：`C:\Users\郑曾波\Projects\filing-fetch-w20-replay`，分支 `codex/w20-ff-replay-20261028`
- 受审树：HEAD `038eac5`（= 初审修复提交 `e07b424` + 仅 handoff.json 新增；作者申报 tested=reviewed=`e07b424`，经核实 `git diff e15640c..e07b424` 对 Python 源码为零改动，申报成立）
- 基线：`5396bd688e5b775e746fe3290852f0532d4548f8`（与卡一致）
- 输入：施工卡、`handoff.md`/`handoff.json`、`review/initial.md`（F1-F9）、receipts 5 件、`C:\Users\郑曾波\Projects\_w20-runs\out`（17 attempt 实际报告字节）、当前源码与测试
- 方法：逐条对照 initial.md 的 F1-F9 与当前文件字节；实际重跑快速离线测试；逐一重算 handoff.json files[] sha256；抽开 attempt 报告核对收据指针；只读检查（本目录两文件除外）

## 0. 实际执行的验证命令与结果

| 检查 | 结果 |
|---|---|
| `python -B -m pytest -q tests/test_w20_replay_selection.py tests/test_w20_replay_faults.py tests/test_w06_case_authority.py` | **183 passed** (5.6s)，全绿 |
| `python -B -m pytest -q tests/test_w20_replay_selection.py tests/test_w20_replay_faults.py`（handoff.json tests[0] 原命令） | **22 passed** (0.95s)，与 handoff.json 数字一致 |
| `python -B -m pytest -q tests/test_w06_contract_matrix.py tests/test_w06_matrix_runtime.py tests/test_w06_case_authority.py tests/test_du8_matrix_scheduling.py tests/test_du8_matrix_deadline_recovery.py`（tests[1] 原命令） | **232 passed** (8.9s)，与 handoff.json 一致 |
| `ruff check tools/offline_contract_matrix/ tests/test_w20_replay_selection.py tests/test_w20_replay_faults.py` | **All checks passed**（handoff.md "ruff 全绿"属实） |
| `case_registry`：base/supplemental/union/交集 | **41 / 9 / 50 / 0**；`AUTHORITY_VERSION="w20-supplemental/1"` 未变 |
| `git diff e15640c..HEAD -- tools/ tests/` | **仅 README.md 1 行**（F5 修复行），无其他源码/测试改动 |
| `git diff 5396bd6..HEAD --stat -- scripts/` | **空**：产品 FF 源码零改动（在最终 HEAD 复证） |
| handoff.json `files[]` sha256 vs 实际字节 | **20/20 全部一致**（含 w20_case_specs.py、handoff.md、initial.md、5 份 receipts） |
| run-receipts.json 14 个 `report_sha256` vs `_w20-runs/out` 实际字节 | **14/14 全部一致** |
| attempt-465ac1a `w20_call_kill_before_durable`（F1 实证） | result=**PASS**、`killed=[True,False,False]`、`et_fixture_requests=[1,1,0]`、adapter=[0,0,0]、`durable_at_kill=false`、diagnostics="all supplemental assertions observed" |
| hash_lie 各 attempt 结果（F2 实证） | 465ac1a / d163ba8 / 3bb0a6bc 均 **PASS**；b9d326 为 FAIL（与收据史一致） |
| b9d326 逐 case（F3 实证） | 5 PASS + 2 FAIL（hash_lie、kill_before_durable），与更正后叙述一致 |
| 465ac1a/d163ba8 逐 case | 各 7 PASS + 2 FAIL（et_truncated/et_exit_nonzero，当期断言缺陷）；handoff.md "各 7 PASS（其余为当时未修断言/负载）"属实 |
| 清理盘面 | `.w20-deps` 不存在 ✓；`_w20-runs/owned` 不存在 ✓；保留证据实测 **4,685,224 字节** = cleanup-receipt（分毫不差）；17 attempt 目录与收据一致 |
| 环境变量后门 | 新增 4 个模块 + 2 个测试文件无 `environ/getenv` 读取（仅注释提及）；`W06_MATRIX_STATE` 仍为基线既有 harness↔子进程边界变量，消费方仅矩阵自有 proxy/adapter；`run.py` 零改动（30s/180s/≤2/proof reserve 不变） |
| required_cases 红线 | 选择运行报告内 `required_cases` 为完整 41 id 列表（逐一列出核对）；oracle `required_cases_shrunk` 守卫在位；`scope.selection.certifies="selected cases only; …never certifies the full required-case matrix"` |
| handoff.json tests[2]（全量 1462/13） | 未重跑（约 7 分钟、超出快速离线范围）；branch-failures.txt（13 行）与 baseline-preexisting-failures.txt 的 13 项失败清单一致，归因注释如实；自 e15640c 起测试/源码零改动，初审对同一源码态的抽跑复验（fc501 FAILED）继续有效 |

## 1. F1-F9 逐条核验

| # | 初审严重度 | 判定 | 复核证据 |
|---|---|---|---|
| F1 | P2 | **已修复（字节级实证）** | `run-receipts.json` green map 该行改为 "attempt-465ac1a… and attempt-d163ba8…（full-chain PASS: killed->1-GET recovery->0-GET reuse）"；实测 465ac1a 报告该 case PASS、killed=[T,F,F]、gets=[1,1,0]（d163ba8 收据同为 7 PASS+2 FAIL 且 map 一致）。handoff.md §3/§5 旧表述（"第 3 段在所有全批窗口被负载阻断"、root_followup 建议重跑）已删除，§5 改为指向单例绿地图 |
| F2 | P2 | **已修复** | hash_lie 指针改为 465ac1a/d163ba8/3bb0a6b，三者实测 PASS；b9d326 FAIL 不再被引用 |
| F3 | P3 | **已修复** | handoff.md §3 "attempt-b9d326 5 PASS + 2 FAIL（当次断言缺陷，2ad2677 修复）" 与收据及逐 case 实测一致 |
| F4 | P3 | **已修复** | handoff.md §1 改述为"语义/兼容不变…全量报告现无条件新增顶层附加键 `supplemental_cases`（恒 9 个，只增不改既有键），字节因此非严格不变"；handoff.json compatibility[1] 同步；cli_main.py:577 证实无条件附加 |
| F5 | P3 | **已修复** | README 表行改为"真实子进程路径 `provider_result_oversized`（共享传输失败总类；seam 路径 `provider_tool_failed`）"；此为 e15640c..HEAD 唯一 tools/tests 改动 |
| F6 | P3 | **已修复** | dependency-record et 块：paths=13 项（含 `retrieval_worker.py`）、删除 `files_total`、`files_compared=13`、closure 说明完整，内部一致、可独立重放 |
| F7 | P3 | **已修复** | handoff.md §1 concurrent_same 条目明示"单组内有意同时运行 2 个 FF 子进程——故障本体，非调度增额（`--workers` 仍 ≤2）"。（备注：该说明落在 handoff.md §1 而非 handoff.json 的 limitations/compatibility，语义已覆盖，不算缺陷） |
| F8 | P3 | **部分修复，残留**（→ OF3） | `origin/codex/w20-ff-replay-20261028` 已存在且指向 **e07b424**（受审树已推送）；但本地 HEAD **038eac5**（handoff.json 提交本身）领先远端 1 个提交未推送，且 `remote_status` 写 "pushed: origin/…" 未限定 commit，按当前状态读有歧义 |
| F9 | P3 | **大部分修复，残留**（→ OF2） | handoff.json 已存在且卡面接口字段**全数齐备**（card_id/status/workdir/branch/base_commit/implementation_commits/tested/reviewed/files/requirements/tests/review/cleanup/compatibility/limitations/root_followups/remote_status），20 个文件 sha256 全部实测一致；但卡固定接口要求 `review/initial.md/json` 成对，**review/initial.json 仍缺失**（handoff.md §7 亦引用了它） |

## 2. 修复过程未破坏实现（抽查）

- `git diff e15640c..HEAD -- tools/ tests/` = README 1 行（F5）；其余修复全部落在 receipts/handoff 文档。实现与初审受审源码态逐字节一致。
- 三组离线测试全绿（183 / 22 / 232）；ruff 全绿；41/9/50 计数、两 registry 无交集、`AUTHORITY_VERSION="w20-supplemental/1"` 全部不变。
- 14 份 attempt 报告 sha256 与收据逐一吻合——修复提交未触碰任何运行证据字节。
- 清理盘面与收据分毫不差（4,685,224 B 保留证据实测复核）。

## 3. handoff.json 真实性

- `files[]` 20/20 sha256 与当前实际文件字节一致（含 w20_case_specs.py 与 handoff.md 本身）。
- `tests[]`：第 1、2 条命令原样重跑，22 passed / 232 passed 与申报完全一致；第 3 条（全量 1462/13）按快速离线范围未重跑，其 13 项失败清单与基线归因收据一致、源码态未变，采信初审抽验；第 4 条（真实链 17 attempt）以 run-receipts + 全量 report sha256 核验代替，`passed/failed/seconds` 按卡如实填 null。
- `requirements[]` 全部 10 条的 evidence 指向文件均存在；R6 常量零改动、R8 required_cases=41、R7 视图删除等关键声明均经独立复测。
- `cleanup.bytes_added=4,685,224` 与盘面实测一致；`restored=true` 属实。
- 无"假成功"表述：PARTIAL/FAIL 全部具名保留；"全绿"字样仅用于 232 套件与 ruff（两者均实测为真）；`scope.selection.certifies` 明示不认证全量。

## 4. 红线终检

1. `required_cases` 恒 41：选择报告内为完整 41 id 列表，oracle 缩小守卫在位 — **未缩小** ✓
2. 产品 `scripts/`（及 FF 薄 adapter）零 diff（基线→HEAD）✓
3. 无测试环境变量进入产品：新增代码无 env 读取，run.py 零改动 ✓
4. 证据无假成功：负载 PARTIAL、当期断言 FAIL、基线 13 失败全部如实具名 ✓

## 5. 复审新发现（OPEN，全部 P3 文档/接口级）

| # | 位置 | 问题 | 建议修复 |
|---|---|---|---|
| OF1 | `receipts/run-receipts.json` `single_case_green_map.w20_call_et_truncated` | 修复提交 e07b424 改写 green map 时在该行追加了 "； also 465ac1a/d163ba8"，但这两个 attempt 的 et_truncated 实测为 **FAIL**（诊断 "a rejected ET result must leave nothing durable"，当期 et-fault 断言缺陷；eadb10c 原行仅指 17a4c68，是对的）。主指针仍正确，"9/9 case 至少一次整链 PASS"的总声明不受影响。 | 删去 "； also 465ac1a/d163ba8"（或改为正确的 90ecdbd/3bb0a6bc） |
| OF2 | `delivery/w20-ff-replay/review/initial.json` | 缺失。卡固定接口要求 `review/initial.md/json` 成对，handoff.md §7 已引用该文件名。 | 由作者按 initial.md 生成机器可读副本（初审判定/ findings 列表） |
| OF3 | 仓库远端 / `handoff.json.remote_status` | 受审树 e07b424 已在 origin，但含 handoff.json 的最终提交 038eac5（及后续交接文件）未推送；`remote_status="pushed: origin/…"` 未限定 commit。 | 将最终交接提交（含 review/final.* 与 OF1/OF2 修复）推送，并将 remote_status 精确到 commit |

非阻塞备注：`docs/plans/w20-ff-replay-2026-10-28/receipts/implementation-files.json` 为未跟踪工作稿（内容与 handoff.json files[] 同源，sha256 逐一相符）；随最终提交一并入库或删除均可。

## 6. 总体判定

**APPROVE。**

初审 F1-F9 中：F1-F7 全部真实修复且经字节级复核；F8/F9 主体完成但各留一处 P3 残留（推送尖端、initial.json），且修复过程引入一处新的单句证据指针误差（OF1）。三项 OPEN 均为 P3 文档/接口级，不涉及实现、数据、测试或红线；实现本体相对初审受审源码零变化，全部快速离线复测通过。按卡"最终 OPEN 必须为空方可交接 ROOT"：作者关闭 OF1-OF3（纯文书+一次推送，无需再次独立复审）后即可交接。
