# W20-FF-REPLAY 返工轮 R2 独立复审（2026-10-29）

- 复审者：independent return-R2 reviewer（与作者及此前各轮审查者无关）
- 工区：`C:\Users\郑曾波\Projects\filing-fetch-w20-replay`，分支 `codex/w20-ff-replay-20261028`
- 受审 HEAD：`56b3db0`（代码止于 `aa49836`，与 handoff.json `tested_code_commit` 一致；其后 `56b3db0` 为 docs/receipts 哈希刷新，无代码改动）
- 依据：ROOT 第二轮返工单 `company-wiki/docs/plans/du11-source-closure-2026-10-18/review/w20-reception-r2-20261029/RETURN_FF.md`（FF-R2-1/P2 同一次采集 lost-reply、FF-R2-2/P2 probe 隔离三态）+ 同目录 ff-review.md + 原卡 construction_card.md
- 方法：只读审查 + 离线快速测试（未跑真实链矩阵、无网络；除本报告两文件外零写盘）

## 结论

**verdict：REJECT。OPEN 1 条（纯文书机器字段，10 分钟级修复）。**

两项 P2 技术修复（FF-R2-1 lost-reply 关键场景、FF-R2-2 探针隔离三态）**全部实质通过**：真链证据、断言反例、子进程隔离、RED 先行、267 项回归均由本复审独立复核成立，原卡红线全部保持。唯一 OPEN 是 ROOT 本轮收尾项"随收尾修旧9/新10计数"只执行了一半，而 handoff R2 章节声称"handoff 计数同步（supplemental 11、union 52）"已完成——`handoff.json`（当前态机器验收工件）仍带"恒9个补充 id"的失真不变量与失真的 remote_status。修复不涉及代码/测试/证据，无需重跑任何测试。

## 1. FF-R2-1 实质核验 — 通过

**attempt-dd7884e11bd74adcb3d911736c893ca2（`C:\Users\郑曾波\Projects\_w20-runs\out\`）**：`w20_call_lost_reply_after_durable` result=**PASS**；本复审用 `oracle.audit()` 对 report.json 独立重跑 → **0 findings**；`required_cases` 恒 41、selection 如实标注（selected/completed=该 case，其余 51 具名 NOT_RUN）、52 行齐全。

逐 run 核对（report.json actual.runs）：

| run | killed | GET（et_fixture_requests / fixture_requests） | transcript 状态 | source_ref |
|-----|--------|------|----------|------------|
| run0 | False | **1**（provider_requests=1） | `downloaded` | `976a43b9…4ef61`（512B, application/json） |
| run1（首次恢复） | False | **0 / 0**（provider_calls=0） | `unknown_publication`（filing `reused_existing`） | 同 run0 |
| run2（复用） | False | **0 / 0** | `unknown_publication` | 同 run0 |

- **同一采集身份贯穿**：`verified_at_reply_loss` 与 run0 自带 Ref 在五键（document_id/source_id/content_sha256/byte_size/mime_type）上**完全一致**；run1/run2 Ref 亦一致（probe_state=confirmed，probe_error=null）。
- **截留标记**：run0 trace `reply_intercepted=True`，case expected/actual 均声明 `reply_intercepted=true`；envelope 作为证据消费、不作成功交付——这正是 ROOT 明示允许的"服务端已处理完、响应传输层丢失"形态（harness 自有 transport 边界：FF stdout 由 harness 落盘解析，无其他客户端）。
- **对照保留**：attempt-248e9d19 `w20_call_kill_after_durable` **PASS**（oracle 0 findings，probe confirmed；run0 正常交付 1 GET、run1 killed 0 GET、run2 0 GET 复用），scope 明示 **CONTROL ONLY**，与关键场景分工诚实。

**断言权威独立构造验证**（内存 dict 直接调 `w20_case_specs` `w20_assertion_errors` lost-reply 分支，w20_case_specs.py:420-455）：

1. 完好截留形态 → `[]`（接受）；
2. **ROOT 反例：run0 已交付成功（无截留标记）+ run1 空杀** → **5 条错误拒绝**（含 "run 0 must be the intercepted acquisition itself… not an already-delivered earlier run"）；
3. 伪造者在 case 级补 `reply_intercepted=True` 但 run0 仍无逐 run 标记 → **4 条错误拒绝**（逐 run 标记被强制，不可代签）；
4. **Ref 漂移**（恢复 Ref ≠ 截留 Ref）→ 拒绝；
5. proof 漂移（verified_at_reply_loss ≠ run0 Ref）→ 拒绝；
6. 恢复再下载 1 GET（not-durable 代签）→ 拒绝（"must reuse with ZERO extra GETs"）。

真实 report.json 的 case 数据回代同一断言 → `[]`，与 PASS 自洽。

**RED 先行成立**：`git show 28f4664` 仅新增 205 行/7 测的测试文件；该提交树中 `w20_case_specs.py` 无任何 `lost_reply` 引用（grep=0），RED 必失败，随后 `aa2ff69` 实现、`48362b7` 修 envelope。工件 SHA 抽验：3 个 run 的 request/response/fixture 共 9/9 与 report 记录一致。

## 2. FF-R2-2 实质核验 — 通过

- **`cwp_readback_probe.py`（子进程体）**：stdin JSON 进、stdout JSON 出；经 **provider-scoped lookup envelope**（`company-wiki-transcript-import-lookup-request/1`，与产品 `transcript_tool_transport.py` 复用链同 schema）调公开 `source_query_cli`，再 `SourceVersionReader.open_version` **字节级** SHA+size 比对。三态显式：`confirmed` / `not_found`（查询正常应答但非本 Ref，含 sha mismatch / status 或 matches 不符）/ `probe_error`（自身失败，**永不可当 not-durable 负证据**）；任何异常归本调用并带具名 error。
- **`w20_fault_cases.probe_catalog`**：**每次调用一个有界子进程**（`subprocess.run` + capture_output + 30s timeout）；父进程 `sys.stdin/stdout` 零触碰；返回码非 0、未知 state、异常一律归一为 `probe_error`。模块级仅常量（POLL/KILL_WAIT/_ACCEPTED），**无模块级共享 last_error**（旧 `_CWP_PROBE_LAST_ERROR` 已随 aa2ff69 删除，grep 证实仅 runtime.py 清理函数的局部变量同名）。
- **修复史与排障记录相符**：R1 版（a693e10）确为进程内 sys.stdin 替换 + redirect_stdout + 模块级 last_error（ROOT 原发现）；aa2ff69 重做子进程版；48362b7 diff 恰为"plain query → provider-scoped lookup envelope + 矩阵合成子进程环境"，与 handoff R2 排障记录（plain query 的 as-of 资格排除隐藏未来期次已存原件 → no_local_match）逐字对应。
- **测试**：`python -B -m pytest -q tests/test_w20_replay_return_r2.py` → **7 passed**（5.03s），含：两公司/两资料根真 catalog 并发（ThreadPoolExecutor）不串且各自 confirmed、catalog 不可用=probe_error（非 not_found）、丢失 wiki=probe_error 且带自身 error、父进程 stdio 不变。

## 3. 红线 — 全部成立

- `python -B -m pytest -q tests/test_w20_replay_selection.py tests/test_w20_replay_faults.py tests/test_w06_case_authority.py` → **183 passed**。
- 九文件全套回归（selection+faults+return_r1+return_r2+w06_contract_matrix+w06_matrix_runtime+w06_case_authority+du8_scheduling+du8_deadline）→ **267 passed**（11.5s），与 handoff 声称的 267 一致。
- 权威不变：`case_specs.case_specs()`=**41**、`w20_case_specs.w20_case_specs()`=**11**、`case_registry.union_entries()`=**52**；report `required_cases` 恒 41。
- `git log 5396bd6..HEAD -- scripts/` 为空（产品 FF 源码零改动）；工作树 clean，无遗留 debug 脚本。
- handoff.json `files[]` **26/26 条 SHA 全部**与当前工作树一致（远超抽验 ≥6 条要求）。
- 两 attempt oracle 独立重跑均 0 findings；attempt 时间线（19:45/19:46）与修复提交（19:46:42） coherent，两运行均用修复后 probe（probe_state=confirmed 依赖 envelope 修复）。

## 4. 诚实性核验

- **排障记录与实际 diff 相符**：见第 2 节，envelope 丢失根因（R1 envelope 包装丢失）与 48362b7 diff 一致；诊断 wrapper 未入 git 且已删（磁盘无 debug 文件）。
- **cleanup-receipt 歧义修复成立**：return_r1 块布尔字段已加 `*_meaning` 显式含义并改写 note；return_r2 块新增且 `debug_keep_scratch_removed: true` 与磁盘状态（无 debug 残留、`_w20-runs/owned` 不存在、`.w20-deps` 不存在）相符。
- **run-receipts `return_r2_runs`** 与两 attempt 工件逐项相符；无假成功表述——lost-reply PASS 的每个字段都可在 report.json/工件中复现。
- **未同步项（→ OPEN-1）**：见下。

## 5. OPEN 发现

**OPEN-1（P3，纯文书机器字段；ROOT 本轮点名收尾项未完成而 handoff 声称完成）**：ROOT RETURN_FF 收尾要求"随收尾修旧9/新10计数及cleanup false字段歧义"。cleanup 歧义已修（见上），但**计数同步只落在新增的 R2 章节与 run-receipts note，ROOT 上轮点名、本轮点名要求修正的旧"9"引用仍原样保留**，且 `handoff.json` 作为当前态机器工件含失真断言：

1. `handoff.json` requirements[1].evidence 仍写 **"w20_case_specs.py 9 case"**（实际 11）；
2. `handoff.json` compatibility[1] 仍写 **"supplemental_cases(恒9个补充id, 只增不改既有键)"**——"恒9"对当前树为假（attempt-dd7884e1 report.json 的 supplemental_cases 实测 11 个 id；"只增不改"性质本身未破坏）；
3. `handoff.md` §1 仍写 **"supplemental_cases（恒为 9 个补充 id…）"** 与 **"W20 补充故障套件（9 case…）"**（§1 是"交付了什么"的当前态描述，无历史标注），§3 "9 个补充 case 每个都有至少一次真实链整链 PASS" 按当前态读亦不完整（新 2 case 的真链 PASS 证据在 R1/R2 章节）；
4. `handoff.json` remote_status 仍声称 "the branch head on origin is the final handoff commit containing this file"，而 origin 实际停在 `a693e10`，R2 的 5 个提交（28f4664→56b3db0）未 push——随本轮收尾一并刷新/push 即可。

修复建议：上述字符串按 11/52 与实际 push 状态刷新（handoff.md 可用"原始交付 9，R1→10，R2→11"的显式历史标注），不改任何代码/测试/报告；无需重跑测试。

## 6. 非阻塞观察

1. cleanup-receipt return_r2 块 `view_rebuilt_and_deleted: false` 沿用了"True=落盘缺席"语义但字段名读作复合动作断言，R2 块未像 R1 块那样附 `*_meaning` 说明；建议随 OPEN-1 一并补一行含义。
2. 本复审复跑 R2 测试时 `.w20-deps` 已按 cleanup 删除，probe 子进程经宿主 site-packages 解析 `company_wiki`（live CWP main）而非冻结 618df92 视图——行为结论不受影响（probe 只依赖公开 query CLI + reader 接口），且作者真链证据的 code_binding verified=true 证明其用冻结视图运行；此差异仅属本复审复跑环境。
3. probe 子进程内部对**自身** sys.stdin 的替换与 finally 恢复是子进程局部行为，父进程零触碰已由测试与代码阅读双重证实，不构成 ROOT 所指的全局 I/O 冲突。

## 7. 复审命令与核验清单

- `python -B -m pytest -q tests/test_w20_replay_return_r2.py` → 7 passed
- `python -B -m pytest -q tests/test_w20_replay_selection.py tests/test_w20_replay_faults.py tests/test_w06_case_authority.py` → 183 passed
- 九文件全套 → 267 passed
- `w20_case_specs.w20_assertion_errors` 内存 dict 构造 → 6 类构造：反例全拒、良构接受
- `oracle.audit()` 对 attempt-dd7884e1 / attempt-248e9d19 独立重跑 → 各 0 findings
- handoff.json files[] SHA 逐条重算 → 26/26 match
- attempt 工件（3 run × request/response/fixture）SHA 抽验 → 9/9 match
- `git log/diff 5396bd6..HEAD -- scripts/` → 空；`git rev-list origin..HEAD` → 5（OPEN-1 第 4 点）
- 计数核验：41 / 11 / 52；report required_cases=41
