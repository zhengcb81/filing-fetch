# W20-FF-REPLAY 返工轮 R1 独立复审（2026-10-29）

- 复审者：independent return-R1 reviewer（与作者及此前两轮审查者无关）
- 工区：`C:\Users\郑曾波\Projects\filing-fetch-w20-replay`，分支 `codex/w20-ff-replay-20261028`
- 受审 HEAD：`ecc5a57`（`3747e4a` 后仅 docs/receipts 提交：`2802e73` run-receipts+handoff 字段、`b22cf4a` handoff.md R1 章节+cleanup-receipt、`ecc5a57` handoff.json 单字段哈希刷新，均无代码改动）
- 依据：ROOT `RETURN_FF.md`（FF-R1/P2、FF-R2/P2、FF-R3/P3）+ `ff-review.md/json` 复验边界 + 原卡 construction_card.md（R1-R8）
- 方法：只读审查 + 离线快速测试（未跑真实链矩阵、未跑全仓 404 秒、无网络、除本报告两文件外零写盘）

## 结论

**verdict：APPROVE。OPEN 为空。**

三项返工（FF-R1/R2/R3）全部实质修复且有可复核真链/单元证据；原卡 R1-R8 未被破坏；五条红线全部成立。下文第 7 节列出 6 条**非阻塞**观察（纯文书滞后/工区卫生，按 ROOT 自身"不为纯文书增加审批门"的校准不构成 OPEN），均已逐条核实不歪曲任何测试结果或证据哈希。

## 1. FF-R1 实质核验（durable 后中断独立确定性证明）— 通过

**attempt-2ebbf3d7be284304877137c80cf18226（单跑，`C:\Users\郑曾波\Projects\_w20-runs\out\`）**：`w20_call_kill_after_durable` result=**PASS**，oracle `{"pass": true, "findings": []}`，`required_cases` 恒 41，selection 如实标注 supplemental。

逐 run 核对（report.json actual.runs）：

| run | killed | GET（et_fixture_requests） | transcript 状态 | source_ref |
|-----|--------|------|----------|------------|
| run0 | False | 1 | `downloaded`（provider_calls=1） | `f1778c54…9ad9a9` |
| run1 | **True**（kill_reason="harness interruption at observed boundary"，exit=1） | **0** | 无 envelope（response 仅 `_unparsed_stdout`） | **无 source_ref** |
| run2 | False | **0**（adapter_fetch=0、provider_calls=0） | `unknown_publication`（重用路径） | `f1778c54…`（与 run0 相同） |

`verified_at_kill` 存在：document_id/source_id/content_sha256=`f1778c54ef796eaf7e0c14d3afc35aa17e440573b7cec06abf9ee9d43e9ad9a9`/byte_size=512/mime=application/json，**五个字段与 run0 响应自带 Ref 及 run2 重用 Ref 完全一致**（Ref/SHA 相同成立）。

**attempt-2a273f32a8034e4382ab43198f5d07d7（前序 4-case 顺序批）**：`w20_call_kill_after_durable` 在前序 case 之后仍 PASS，run 结构与单跑逐项相同（run0 1 GET downloaded / run1 killed 0 GET 无 Ref / run2 0 GET 同 Ref），同批 verified SHA 同为 `f1778c54…`。批内另两 case（before_durable、after_import）诚实 PARTIAL（具名 "absolute case deadline exceeded" 等负载原因，oracle 如实 `case_not_passed`），未冒充整批通过。

**断言代码拒绝两种代签（独立构造验证，`w20_case_specs.py` `w20_assertion_errors` post_durable 分支，行 368-400）**：我用内存 dict 直接调用 assertion_errors，除套件内 2 个正/反测试外额外构造 6 种报告，全部被正确拒绝：

1. 完好 post_durable 报告 → `[]`（接受）；
2. **run1 0 GET 但 verified 缺失**（ROOT 反例形态）→ 3 条错误（"a public-interface read-back proof must exist from BEFORE the kill" 等）；
3. **恢复 1 GET 重下载**（ROOT 反例形态）→ 2 条错误（"…must cost 0 GETs, got 1" 等）；
4. run1 killed 但携带成功 envelope → 拒绝；
5. verified SHA 与 run0 Ref 不一致（拿别人的 source 签本请求）→ 拒绝；
6. 恢复 Ref 字段与 verified 不一致 / run0 本身是 reuse 而非正常采集 → 均拒绝。

**RED 先行成立**：`git show 316842d:tools/offline_contract_matrix/w20_case_specs.py` 中 `w20_call_kill_after_durable` 出现次数为 0（该提交 17:30:56 早于修复提交 b7a649c 17:40:51），RED 测试在该树必失败。

## 2. FF-R2 实质核验（触发器绑定本请求）— 通过

- **测试**：`python -B -m pytest -q tests/test_w20_replay_return_r1.py` → **6 passed**（含 `test_trigger_ignores_preexisting_unrelated_period_originals`、`test_trigger_is_not_fooled_by_a_sidecar_only_appearance` 两个旧 sidecar 控制反例，以及 durable 断言拒绝 not_durable 代签的正反测试）。
- **触发器实现**（`w20_fault_cases.py`）：
  - durable case（行 496-555）：kill 前置条件=公开实读确认——`cwp_public_readback` 经与 FF 复用链相同的 provider-scoped transcript-lookup envelope（product `scripts/transcript_tool_transport.py:28` 的 `_LOOKUP_SCHEMA = "company-wiki-transcript-import-lookup-request/1"`，probe 用同一 schema）+ `SourceVersionReader.open_version` 字节级 SHA 比对 **run0 响应中的本请求 Ref**，有界重试（100×0.1s）后才进入 kill；handler 内预置 FY2037Q1 unrelated-period original 作内置控制反例（内容不同，永不能通过 SHA 比对）。若 probe 始终未确认，`verified_at_kill=None` 如实落报告 → 断言 FAIL，不代签。
  - mid-import case（行 453-493）：触发器=**本请求 receipt tag**（`{cid}.run1.result.json`，proxy 仅为本 run tag 落该文件；ET 完成、CWP 导入未始的确定窗口）；旧期次/前序 case 的 sidecar 与 receipt 文件名不同，永不能触发。
- **attempt-8a972aa642c545918d37df3b3cabfe4a（mid-import 单跑）**：result=**PASS**、oracle 0 findings；`interruption_phase=mid_import_observed`；**`durable_at_kill_public_readback=False`（公开接口观察，断言强制 False）**；run0 killed=True 且 trace 内存在本请求 ET result receipt（`w20_call_kill_after_import.run1.result.json`，et_fixture=1）；run1 恢复 `downloaded` 1 GET；run2 重用 0 GET 同 Ref（`4c73ce97…`）。
- **阶段一致性（单独/前序两种有限运行）**：before_durable 单跑 attempt-afb227f2 PASS（oracle 0 findings）；窗口 attempt-36e764e9 中 before_durable 与 after_import 的 run0/run1 阶段观察正确（killed[0]=True 于本请求触发、恢复恰好 1 次下载），仅第三段复用被 30s case 界截断（诚实 PARTIAL，复用段由各自单跑 PASS 证明；run-receipts.json `return_r1_runs` 如实记录，未追跑，符合 R8）。
- **窗口触发器缺陷的诚实修复闭环**：attempt-2a273f32（修复前）窗口内 after_import "interruption did not happen"（触发器不点燃——失败方向安全）；`3747e4a` 修复 receipt signal 文件名（去掉 group prefix，与 proxy 实际落盘名一致）；修复后 attempt-36e764e9 窗口内触发器正常点燃。RED→修复→窗口复验闭环完整。

## 3. FF-R3 实质核验（机器交接字段）— 通过

- **SHA 全量重算**：脚本逐条重算 handoff.json `files[]` 全部 **19/19 条 SHA，全部匹配当前工作树**（含刷新后的 run-receipts.json=`36d741d6…`、w20_case_specs.py、w20_fault_cases.py、test_w20_replay_return_r1.py 等）。ROOT 点名的那一条（run-receipts.json 旧 `a863cc93…`）已刷新。
- **tests[2]（全仓 pytest 行）**：`exit_code` 已改为 **`null`**，并附 `exit_code_note` 明确：真实退出码未在运行时记录、不重建；pytest 有失败必非 0、13 项基线失败已披露故 0 为假值；按返工指示填 null 而非编造；**全仓并非绿**。passed=1462/failed=13 原样保留。
- **13 项基线失败归因保留**：`receipts/baseline-preexisting-failures.txt`（12 项 + 第 13 项 fc501 在注释中单独说明）与 `receipts/branch-failures.txt`（完整 13 项）均在，归因结论（冻结基线 5396bd6 worktree 同命令复判全部基线既有、与 W20 零关联）未删改。

## 4. 未破坏既有 — 通过

- `python -B -m pytest -q tests/test_w20_replay_selection.py tests/test_w20_replay_faults.py tests/test_w06_case_authority.py` → **183 passed**。
- 全套 8 文件（+contract_matrix/matrix_runtime/du8_scheduling/du8_deadline_recovery/return_r1）→ **260 passed**（与作者"260 项回归全绿"一致；新增 28 = 12 selection + 10 faults + 6 return_r1，232 既有 + 28 = 260）。
- `case_specs.AUTHORITY_VERSION == "w06-cases/1"`、`len(case_specs()) == 41` 不变；w20 `AUTHORITY_VERSION == "w20-supplemental/1"`、套件 9→10（union 51），selection 测试同步更新且通过。
- `git log 5396bd6..HEAD -- scripts/` 为空（0 提交）；全量 diff 仅 tools/、tests/、docs/、delivery/ —— **产品零改动仍成立**。

## 5. 红线 — 全部成立

1. **required_cases 恒 41**：两份新 attempt report 均为 41；selection 收缩保护测试（required_cases_shrunk RED 向量）全绿。
2. **无产品 failpoint**：`scripts/` 零 diff；故障只注入 harness 自有边界（test-proxy 结果/回执流整形 + FF 自有 `ff_process_tree` 杀树语义）。
3. **probe 只走公开接口**：`cwp_public_readback` 仅 import `company_wiki.source_catalog` 的 `source_query_cli.main`、`SourceCatalog/load_catalog_config`、`SourceRef/SourceVersionReader`（均为产品自身使用的公开 owner 接口；product `transcript_tool_transport.py` 用同一 lookup schema 与同一 reader）；无 sqlite/DB 直读、无存储逻辑复制；字节级校验在 `open_version` 返回数据上完成；任何失败/缺失返回 None 不猜测。
4. **in-process sys.stdin 替换有 finally 恢复**：`w20_fault_cases.py:180-189`（saved_stdin → finally 恢复）；其余 sys.stdin 使用点均为既有模式。
5. **无跨仓写**：改动全部在本仓；CWP/ET 源码只经 `git archive` 只读构建视图（dependency-record.json manifest），本轮重建后再次删除——磁盘核实 `.w20-deps` 与 `_w20-runs/owned` 均不存在，`_w20-runs/out` 实测 7,657,936 字节与 cleanup-receipt `retained_evidence_bytes` 一致。

## 6. 证据链完整性抽验

attempt-2ebbf3d7 的 6 个 request/response 工件逐一重算 SHA，与 report 内 `request_sha256`/`response_sha256` 全部一致；被杀 run 的内嵌 response 与磁盘工件逐字节相等。报告未发现编造迹象。

## 7. 非阻塞观察（不构成 OPEN，仅记录）

1. `cleanup-receipt.json` 的 `return_r1` 块中 `w20_deps_view_deleted: false` / `owned_scratch_removed: false` 与同块 note（"then deleted again"）及磁盘实况（均已删除）字面相悖——应理解为"复验窗口期间的瞬时状态快照"，但字段命名易误读；实际清理状态经本复审磁盘核实为净。
2. handoff.json `requirements[1].evidence`（"9 case"）与 `compatibility[1]`（"恒9个补充id"）在套件 9→10 后未同步（handoff.md 返工章节与代码/测试已如实记录 9→10，报告内 `supplemental_cases` 实为 10）。
3. handoff.json `files[]` 相比上一轮独审清单移除了 handoff.md/final.md/final.json/baseline/branch-failures 的哈希条目（避免自引用/易变文件反复失配的务实取舍；这些文档的可追溯性现依赖 git 历史）。
4. handoff.json `tests[]` 未记录返工轮新增的两条命令结果（return_r1 6 测、260 回归）——已在 handoff.md 返工章节记录。
5. 工区根部遗留一个未跟踪调试脚本 `_debug_probe.py`（作者 R1 排查 probe 用，仅写 owned temp；未入提交，不影响交付物，建议随手清理）。
6. `new_original_matching_sha` 纯函数当前仅被测试引用（作为 FF-R2 契约锚点与 ROOT 探针反例的回归固化）；两个 live 触发器实际绑定 receipt tag 与公开实读，比该函数更直接地满足"绑定本请求"，无功能缺口。

## 证据索引

- FF-R1：`C:\Users\郑曾波\Projects\_w20-runs\out\attempt-2ebbf3d7be284304877137c80cf18226\report.json`（单跑 PASS）、`…\attempt-2a273f32a8034e4382ab43198f5d07d7\report.json`（前序窗口 PASS）
- FF-R2：`…\attempt-8a972aa642c545918d37df3b3cabfe4a\report.json`（mid-import 单跑 PASS）、`…\attempt-36e764e91ee94b53a23f15ee6915a4f9\report.json`（窗口阶段一致）、`…\attempt-afb227f21b334f31a14e127d189d4f44\report.json`（before_durable 单跑 PASS）
- 断言：`tools/offline_contract_matrix/w20_case_specs.py`（post_durable 分支行 368-400）；触发器/probe：`tools/offline_contract_matrix/w20_fault_cases.py`（`new_original_matching_sha` 行 71-90、`cwp_public_readback` 行 126-227、`case_call_kill_after_durable` 行 496-555、`case_call_kill_after_import` 行 453-493）
- 回归：tests/test_w20_replay_return_r1.py（6）、test_w20_replay_selection.py（12）、test_w20_replay_faults.py（10）、既有矩阵套件 232
- 机器字段：delivery/w20-ff-replay/handoff.json（files[] 19/19 SHA 实测匹配、tests[2].exit_code=null+note）、docs/plans/w20-ff-replay-2026-10-28/receipts/{run-receipts.json（return_r1_runs 新增）, baseline-preexisting-failures.txt, branch-failures.txt, cleanup-receipt.json}
