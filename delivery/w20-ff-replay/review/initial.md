# W20-FF-REPLAY 初审报告（review/initial.md）

- 审查者：独立审查 agent（与作者无关；本文件为初审唯一产物，由审查者直接写入）
- 日期：2026-10-28
- 工区：`C:\Users\郑曾波\Projects\filing-fetch-w20-replay`
- 分支：`codex/w20-ff-replay-20261028`；受审 HEAD：`eadb10c`；基线：`5396bd688e5b775e746fe3290852f0532d4548f8`（与卡一致，working tree clean）
- 输入：施工卡、`delivery/w20-ff-replay/handoff.md`、`git diff 5396bd6..HEAD`、`docs/plans/w20-ff-replay-2026-10-28/receipts/*`、`C:\Users\郑曾波\Projects\_w20-runs\out`（17 个 attempt 实际报告字节）、新增/修改源码与测试
- 方法：逐项对照 R1-R8；实际重放可离线验证的测试与计数；用报告字节复核收据声明（report sha256 逐一比对）；只读检查，未修改任何文件（本文件除外）

## 0. 实际执行的验证命令与结果

| 检查 | 结果 |
|---|---|
| `python -B -m pytest -q tests/test_w20_replay_selection.py tests/test_w20_replay_faults.py tests/test_w06_contract_matrix.py tests/test_w06_case_authority.py` | **203 passed** (16.2s) |
| `python -B -m pytest -q` 5 个既有矩阵文件（contract_matrix/matrix_runtime/case_authority/du8_scheduling/du8_deadline_recovery） | **232 passed** (9.1s)，与交接稿声明一致 |
| `case_specs.AUTHORITY_VERSION` / base 计数 / union | `w06-cases/1`、**41**、supplemental **9**（`w20-supplemental/1`）、union **50**、两 registry id 无交集；9 个补充 spec metadata 自检通过 |
| attempt 报告 sha256 vs `run-receipts.json` | 抽验 b9d326/3bb0a6b/17a4c68 **全部一致** |
| `_w20-runs/out` 目录 | 17 个 attempt 目录 = 收据 17 条；实测 **4,685,224 字节** = cleanup-receipt `retained_evidence.bytes`（分毫不差） |
| `.w20-deps/` | **不存在**（cleanup-receipt deleted=true 属实） |
| `_w20-runs/owned/` | **不存在**（cleanup-receipt removed=true 属实） |
| `_w20-runs/full-suite-final.log` | 尾行 `13 failed, 1462 passed, 16 skipped` = branch-failures.txt 声明；抽跑 `test_policy_containment_fc501.py` 在 HEAD 复现 FAILED（基线既有归因抽样属实） |
| 产品代码改动 | `git diff 5396bd6..HEAD --stat -- scripts/` 及 FF 薄 adapter 路径为**空**：产品零改动属实（no-code 结论成立） |
| 限额常量 | `run.py` 在 diff 中零改动：`CASE_TIMEOUT=30`、`BATCH_DEADLINE=180`、`WORKERS=2`、`PROOF_RESERVE_SECONDS=10` 未动（R6 不增额属实）；`Deadline.case` 为绝对截止不续期 |
| 环境变量后门 | 新增模块无 `environ/getenv` 读取；`W06_MATRIX_STATE` 为基线既有 harness↔子进程边界变量，消费方仅 matrix 自有的 `et_transcript_proxy.py`/`fixture_provider_adapter.py`，产品 `scripts/` 不读 |
| DU6 replay 兼容 | `cli_main.py:342` `complete_matrix` 要求 rows == base 41 且全 PASS：含 NOT_RUN/50 行的选择报告永不可认证（交接稿兼容声明属实） |

## 1. R1-R8 逐项核查

**R1（测试边界注入、无产品 failpoint 后门、失败带实际阶段/次数/Ref）— PASS**
- A 阶段既有覆盖/缺口映射记录于 `findings.md`（R2 映射表）；注入只落在两处 harness 自有边界：`et_transcript_proxy._apply_result_fault/_apply_usage_fault`（对真实 ET supervisor/worker 链的真实输出流做边界后处理）与 `launch_ff_run` 对真实 FF 子进程树的 kill（`scripts/ff_process_tree.py` Windows Job/KILL_ON_JOB_CLOSE，FF 自有语义只读复用）。产品零 diff，无 failpoint、无新环境变量。
- 失败/中断 trace 携带 `killed/kill_reason/exit_code/et_fixture_requests/adapter_fetch_requests/request_ref+sha/response_ref+sha/et_*_receipt+sha/expected_original_content_sha256`（`w20_fault_cases.launch_ff_run`），oracle 的 `_bound_evidence` 对字节逐一复核；断言失败诊断带实际数字（如 "interrupted run expected 1 in-flight GET, got 0"）。

**R2（六类故障覆盖映射）— PASS**
provider返回后导入前失败 → kill_before_durable / et_truncated / et_exit_nonzero / hash_lie；导入已持久但返回中断 → kill_after_import（durable-at-kill 分支由恢复运行事后判定，run2 reused+0 GET 或 downloaded+1 GET 皆可、但必须与分支标签一致，见 `w20_case_specs.assertion_errors`）；ET 子进程退出/截断 JSON → et_truncated/crash_after_result；错误身份/期间/材料hash → 基线既有 wrong_quarter/wrong_identity 矩阵 case + 新增 hash_lie + cross_company 绑定；旧/部分回执 → receipt_binding（request_id 换绑/截断）；再次请求与并发同期次 → 每例第 3 段复用 + concurrent_same。上游事务/锁只核效果（观察 sidecar/original 差集与恢复运行分支），未在 FF 造第二状态库/锁。

**R3（durable 后复用、不假承诺 exactly-once、失败不混成功）— PASS**
- durable 后重试经真实 FF CLI→CWP query/ensure：复用段观测 `status∈{reused,unknown_publication}` + `source_ref` 相同 + GET=0，且 oracle `source_bytes_not_verified` 检查强制 SourceVersionReader 实读（source_versions==1、physical_originals==1、content_sha256 绑定）。`unknown_publication` 为 FF 产品既有状态（`transcript_companion.py:104`），非 harness 造词。
- 不假承诺：concurrent_same 的 expected/scope 明示"并发窗口不承诺 exactly-once 下载"；断言只要求 ≥1 次真实 GET、恰一持久版本、回放 0 请求。
- 未 durable 的失败：`durable_at_kill/durable_after_fault is False` 显式断言，中断 run 不得报成功或 source；ET 拒绝后必须 nothing durable。

**R4（非年报、三表说明）— PASS**
电话会（原语言 TXT，US Apple 合成身份，oracle `translated_or_changed_text` 钉住原文 SHA）+ CN 发行材料（prospectus kill 恢复）+ CN/HK 同年年报并发跨公司。三表（W19）为独立 CWP 数据服务、无 FF 侧下载/导入状态，按卡"说明而不强加 case"处理，记录于 README/handoff/findings。

**R5（显式源码根/合成环境/真实链/不读密钥）— PASS**
- `.w20-deps` 视图从冻结 commit `git -c core.autocrlf=false archive | tar -x` 构建（DU10 配方），`dependency-record.json` 记录两仓 fixed commit + cat-file 全量字节核验 0 mismatch；**明确拒绝复用绑旧 `900dbf6489` 的 `.du10-deps`**（R7 关键点属实）。
- 全部 case 走真实 FF CLI 子进程 → 真实 ET supervisor/worker（HTTP 边界 fixture）→ 真实 CWP import → SourceVersionReader 实读 → 新进程复用；provider 描述为 fixture 替身（scope 字段明示），attempt 报告 `scope.network_attempts_denied==0` 强制离线；无密钥读取（`with_fmp_key` 为合成 env 元数据旗标，基线既有机制）。

**R6（时限/并发/proof reserve 不增额、小范围补跑、partial 保留）— PASS**
常量未动；`--cases` 为通用显式过滤（union registry，无 W20 专属硬编码分支）；`seed_all` 按 `ctx.seed_cases`（本组实际 case）派生 warm seeds，不为补跑整批重跑 41；失败 attempt 的 partial/已完成 case 全部保留在各自 report.json（17 attempt 全存）；未追全域重跑（改以 baseline/branch 失败归因收据交代全量状态）。
备注（见 F7）：concurrent 类 case 在单组内短暂并发 2 个 FF 子进程——这是被测故障本身（R2 并发反证），非调度额度上调，但 handoff 宜明说。

**R7（冻结 commit 视图 + manifest + 测试后删除；不用 DU10 旧视图）— PASS**
CWP `618df929ffa8842…`（=卡面冻结 commit）、ET `2584b7eed062…`（A 阶段只读解析的已提交 main HEAD，= DU11 冻结 commit，origin 注明）；manifest 字节级核验；两仓 `repo_head_now` ≠ checked-out（未动别仓 git 状态）；视图与 owned scratch 已删除且与实测一致。收据内部小瑕疵见 F6。

**R8（部分运行不冒充 41 例完整、required_cases 不缩小、NOT_RUN 明示、exit 语义）— PASS**
- `required_cases` 恒为 base 41（实测 3 份 attempt 报告均为 41），缩小即被 oracle `required_cases_shrunk` 拒绝（RED 测试钉住）。
- 未选 case 全部具名 NOT_RUN（"not selected — …"），oracle 校验行缺失/重复/标签错置；`scope.selection` 带 selected/completed/skipped/selected_not_executed/certifies。
- 选择运行 exit 0 仅当所选全 PASS 且 oracle 无 findings 且无 error（`cli_main.py` selection 分支）；全量路径 exit 语义不变。
- 全部 17 个 attempt 报告均如实带 FAIL/PARTIAL/NOT_RUN，从未伪称 41/41；最终批 5 PASS + 4 PARTIAL 全部具名 "absolute case deadline exceeded"。

## 2. 代码质量

- 无公司/期间/路径特判：断言全部是 case 级通用语义（计数/状态/ref 绑定），实体复用基线合成身份集（宁德时代/AAPL/騰訊控股），无金标整句、无页码特判。
- 无跨仓写入：CWP/ET 仅只读 archive；`ff_process_tree` 为 import 复用。
- 无第二状态库：harness 观测只用 CWP owned storage 的差集与 ctx 自有文件（proxy_state 每-run 私有 state 文件，解决了并发子进程计数竞态——设计合理）。
- 无 mock 冒充真实：单元（FakeCWP seam，诚实标注 dual-path）与真实链（17 attempt）分层清晰；`_result` 的 PASS 只由固定断言产生，diagnostics 如实。
- oracle 选择模式实现正确（coverage 分支切换 + 6 类一致性 finding + killed-run 回执豁免仅在 `key not in run and killed is True` 时生效，GET 计数与请求/响应/fixture 字节绑定照常审计——豁免面最小）。
- `runtime._rmtree_bounded`：有界耐心（20×1s），耗尽如实 raise/restored=false，不假报恢复。

## 3. 测试真实性

- `test_w20_replay_selection.py`（12 测）：RED 向量真实（缩 required_cases→finding、重标签→finding、缺行→finding、无 selection 恢复 coverage_gap），oracle 断言可从构造报告字节复核。
- `test_w20_replay_faults.py`（10 测）：复用 DU11 既有 seam，钉住双路径退出分类（seam=`provider_tool_failed`、真子进程 ChildFailed=`provider_result_oversized`，后者明示"如实钉住而非隐藏"）、hash 谎报、旧/截断回执 null-not-0、proxy 纯函数成形。
- 真实子进程/真入库证据在矩阵 attempt：抽验 b9d326 kill_after_import PASS——run0 exit=1/killed=True/1 GET/无状态、run1 downloaded/1 GET、run2 unknown_publication/0 GET/同 ref，artifacts 内 request/response/fixture/stdout/stderr 文件齐全；oracle 0 findings 的 attempt（17a4c68、90ecdbd、e734dc7）为真绿。杀树机制为真 Popen+Job 对象。

## 4. 数据/角色/期间/数字

- 合成身份、合成内容字符串（"Synthetic W20 …"），无真实公司原件/密钥/reasoning 入仓；attempt 证据全部在仓外 `_w20-runs`（cleanup-receipt 如实记录保留 4.69MB 小 JSON 工件）。
- 计数语义诚实：stale/truncated 回执 → `provider_requests is None` + `provider_usage_complete is False`（null 不代 0），单元与矩阵断言双重钉住。
- 收据计数：run-receipts 17 条与 out 17 目录一致；单例结果计数经报告字节复核一致（例外见 F1/F2/F3 的叙述性错误）。

## 5. 清理

`.w20-deps` 不存在 ✓；`_w20-runs/owned` 不存在 ✓；保留证据字节数与收据完全一致 ✓；17 attempt 与收据一一对应 ✓。restore=false 的 3 个 attempt（39d8467/3bb0a6b/465ac1a）在收据中如实保留并经 findings.md §C.5 归因（Windows 共享锁瞬态 + e15640c 加固），末态已清。

## 6. handoff.json —— **缺失，必须补**

`delivery/w20-ff-replay/handoff.json` 不存在（handoff.md §7 已预告 review/* 亦未落盘——review/initial.md 由本审查产出，initial.json/final.* 由作者后续按本报告生成）。按卡固定接口，handoff.json 至少须包含（全部实测值，未测为 null 并解释）：

- `card_id`（"w20-ff-replay-2026-10-28"）、`status`（"READY_FOR_ROOT_REVIEW"）
- `workdir`、`branch`、`base_commit`（"5396bd688e5b775e746fe3290852f0532d4548f8"）
- `implementation_commits`：`["f255321","38e59ff","3dd6eb1","bebd009","4f016cf","2ad2677","c6a10d2","3e8d1be","e15640c","eadb10c"]`（eadb10c 为 docs；若 tested/Reviewed 绑 e15640c 需说明其后仅 handoff/receipt 文档变化、源码无 diff）
- `tested_code_commit` / `reviewed_code_commit`：建议均填 `e15640c`（最终源码态；eadb10c 仅加文档/收据）
- `files`：每个交付相对路径 + 最终字节 sha256（tools/offline_contract_matrix 10 个文件、tests 2 个、receipts 5 个、handoff.md/json、README 等）
- `requirements`：R1-R8 逐条 `{"id","evidence","status"}`（可引用本报告章节）
- `tests`：完整命令 + exit_code/passed/failed/seconds/scope（本报告 §0 的两组 pytest 实测可直接引用；真实链运行以 run-receipts.json 17 attempt + report sha256 为 scope 证据）
- `review`：`{"agent_id":…, "report":"delivery/w20-ff-replay/review/initial.md", "open_findings":[F1..F7 修复后置空]}`
- `cleanup`：before/after 收据路径、`restored:true`、`bytes_added`（保留证据 4,685,224 + 仓内新增源码字节，需实测）
- `compatibility`、`limitations`、`root_followups`、`remote_status`（当前远端已配置 origin 但**卡分支未推送**——见 F8，须填实际状态）

## 7. Findings 列表

| # | 严重度 | 位置 | 问题 | 建议修复 |
|---|---|---|---|---|
| F1 | **P2** | `receipts/run-receipts.json` `single_case_green_map.w20_call_kill_before_durable`；`handoff.md` §3/§5 | 收据称"best single attempt PARTIAL"、handoff 称"第 3 段复用在**所有**全批窗口被负载阻断"。**实测为假**：attempt-d163ba8 与 attempt-465ac1a 中该 case 为完整 3 段 **PASS**（kill→恢复 1 GET 下载→复用 0 GET，diagnostics="all supplemental assertions observed"），且 `w20_case_specs.py` 与 kill_before_durable handler 自 2ad2677（该两 attempt 所在代码态）至 HEAD 零改动（`git diff 2ad2677..HEAD -- w20_case_specs.py` 为空；`w20_fault_cases.py` 仅改 et_fault/hash_lie 的 delta）。属"少报"而非虚报，但交接证据地图错误，且使 root_followup(2)（建议 ROOT 重跑）失去必要性。 | 改写 single_case_green_map 该行与 handoff.md §3/§5：整链 PASS 见 d163ba8/465ac1a（同批含当时未修的 et-fault 断言缺陷，但本 case 断言与最终代码一致）；root_followup(2) 降级为可选 |
| F2 | **P2** | `receipts/run-receipts.json` `single_case_green_map.w20_call_hash_lie` | 指向 "attempt-b9d326 (PASS)"，但该 attempt 中 hash_lie 实为 **FAIL**（诊断："a lying payload sha must surface as a named rejection, never a success"；当时预期 reason 表未收 `transcript_import_failed`，2ad2677 修正）。真实绿见 465ac1a/d163ba8/3bb0a6b。证据指针错误，损害可追溯性。 | 指针改为 465ac1a/d163ba8/3bb0a6b 任一 |
| F3 | **P3** | `handoff.md` §3 | "attempt-b9d326 6/7 PASS" 与实测不符：该批 7 例为 **5 PASS + 2 FAIL**（kill_before_durable、hash_lie FAIL）。 | 更正为 5/7 |
| F4 | **P3** | `handoff.md` §1 | "无 `--cases` 路径行为**字节级**不变"过度声明：`cli_main.py` 的 `report.update(...)` 现无条件附加 `supplemental_cases`（9 id）顶层键，全量报告字节并非逐字节不变（schema/语义/exit/DU6 兼容确实不变，且为纯附加键）。 | 改述为"语义与兼容不变；全量报告新增附加键 supplemental_cases" |
| F5 | **P3** | `tools/offline_contract_matrix/README.md` W20 表 `w20_call_et_exit_nonzero` 行 | 反证列写 `provider_tool_failed`（seam 路径）；矩阵 case 权威（真实子进程路径）预期是 `provider_result_oversized`（`w20_case_specs.W20_METADATA`）。双路径在 spec/单测中已诚实解释，但 README 单列 seam 理由会误导复现者。 | 表格改为"真实子进程 `provider_result_oversized`（seam 路径 `provider_tool_failed`）" |
| F6 | **P3** | `receipts/dependency-record.json` et 块 | 内部不一致：`files_total: 8` vs `files_compared: 12` vs `paths` 列 12 项但缺 `retrieval_worker.py`（`retrieval_worker_note` 自称已加入闭包）。manifest 应能独立重放实际提取集合。 | paths 列全 12（或实际提取数）个文件，files_total 对齐 files_compared |
| F7 | **P3** | `handoff.md`（缺声明） | concurrent 类 case 单组内短暂并发 2 个 FF 子进程（`ThreadPoolExecutor(max_workers=2)`），叠加另一 worker 组时全批瞬时子进程可 >2。这是被测故障本身、非 `--workers` 调度额度（保持 ≤2）上调，但 handoff 未说明，易被读作"并发增额"违 R6。 | handoff limitations 或 compatibility 中明示一句 |
| F8 | **P3** | 仓库/`handoff.json`（缺失） | 卡要求"存在已配置远端就推本卡分支"：origin 已配置（github.com/zhengcb81/filing-fetch.git）但 `codex/w20-ff-replay-20261028` 未推送（`git ls-remote` 无此 head）。 | 推送本卡分支，或在 handoff.json `remote_status` 如实记录未推送及原因 |
| F9 | **P3** | `delivery/w20-ff-replay/handoff.json` | 文件缺失（卡固定接口要求 handoff.md **和** handoff.json；review/initial.json 亦须由作者依本报告生成）。 | 按 §6 字段清单补齐，全部填实测值 |

未发现 P1 级问题：无产品缺陷被掩盖、无虚报成功、无权限/后门/跨仓写入、无数据造假。F1/F2 属交接证据链准确性问题（作者已修复断言缺陷本身，只是收据叙述未跟上），修复成本低。

## 8. 总体判定

**APPROVE_WITH_FIXES。**

实现本体（case_selection/case_registry/w20_case_specs/w20_fault_cases、oracle 选择审计、proxy 边界故障、runtime 清理加固、通用 `--cases`）满足 R1-R8，测试真实、收据与盘面一致、产品零改动、清理彻底。批准条件：修复 F1-F9（核心为 F1/F2 收据更正与 F9 handoff.json 补齐），随后由另一独立 agent 复审，OPEN 清空后方可交接 ROOT。

## 附：审查者实测快照（供复审复核）

- 最终批 attempt-3bb0a6bc：5 PASS / 4 PARTIAL（具名 deadline）；hash_lie、kill_after_import、et_truncated、concurrent_same、filing_concurrent_cross_company PASS。
- kill_before_durable 整链 PASS 实证：`attempt-d163ba8/report.json` 与 `attempt-465ac1a/report.json`（runs: killed=True/1 GET → downloaded/1 GET → unknown_publication/0 GET，durable_at_kill=False）。
- 受审代码：`eadb10c`（源码与 `e15640c` 一致，eadb10c 仅 docs/receipts）。
