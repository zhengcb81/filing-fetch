# FB-FF　下载、复用和作业反馈接线

施工状态：F4 持久作业和回告已验收并发布；后续定时 slot 的原批次只读冷查已在本仓交付（见 2026-11-24 节），短请求和其他偏差接入按余项继续。采集侧两张独立卡由 ET 和 SID 并行施工；全局另有 industry-research（IR）独立研究报告卡。唯一工作目录为 `C:/Users/郑曾波/Projects/filing-fetch`，主线 `main`，本次计划基线 `4c7f501b`。本仓 canonical PWF 是 [PLANNING_STATUS.md](../../../PLANNING_STATUS.md)。

## 2026-11-18 · 已实现的 F4 作业部分

- 启用专用旁路时，真实 FF owner 在运行前写 `action-started` 及匹配终态检查名，完成后分别写 `job-outcome` 和 `job-usage`。费用未知独立于业务结果；坏旁路不影响业务作业。
- `get_status` 加当前原作业的 `act reconcile --expected-attempt` 是总控唯一恢复链。恢复只查本地已入索引记录，保留原公司、市场、截至日和模式；不会再次发现、下载或调用伴随电话会。`latest_as_of` 的本地恢复不声称外部最新。原历史费用未知继续保留；当前未启动供应商的真实零费用仍按原重试合同。
- `scripts/ff_job_feedback.py --reports-dir … report|get-report` 在本仓记录原发现方复验和版本。重复按 action ID 读回同一收据。没有另建下载数据库。
- 作业、跨进程、公开隔离及消费回归 188 项与 8 个子例通过。ROOT 已验收 exact/latest 两个真进程强杀用例及 [F4 真宿主闭环](../../../../company-wiki/docs/plans/feedback-loop-2026-11-17/f4-acceptance.md)。强杀后同一作业恢复同原文，供应商请求、下载和新作业增量为零；旧费用未知保留。实际受审和复验版本为 `a9f9d6d1f3af139c08898a296dba14574dbf044d`。工程反馈短请求的更多偏差分类依原卡后续处理。

## 交付范围和现有依据

缺陷可能在上游提出请求时出现，最终在另一层得到具名拒绝。FF 只修自己的路由、限额透传、复用/下载分支、重试行为和结果信封。CWP 的验真与 provider 的实际计量继续由原 owner 提供。保留现有 `.ff_jobs/`、工具状态、生产配置和密钥文件；新用例使用 pytest tmp_path 与专用测试配置。

- [正式 T3 验收](../mb11-ff-2026-11-11/m3-t3-download-closeout-20261116.md) 中，旧 RF 周跑四例缺限额，供应商未启动。补全限额后正式三市场首取、复用和损坏件用例通过。使用历史失败及已通过的定向测试作为母例。
- [FF 作业协议](../../ff-job-protocol.md) 已有 command_id、owner_job_id、错误归属、correlation_id 和幂等请求，原生日志 `logs/<owner_job_id>.log` 为 JSONL。未知作业通过 `reconcile` 只读查询；挂起或用量不完整不证明费用为零。单次 `scripts/fetch_filing.py` 和持久作业 `scripts/ff_job.py` 都要覆盖。
- 编码写集合为 FF 内的反馈适配器、上述生产端必要的完成信号、`scripts/ff_job_runner.py`/现有持久作业接线、`skills/repair-filing-fetch-issue/SKILL.md`、定向测试、本计划及 canonical 链接。保留全部业务信封和 job 持久化语义。总调度只走公开 FF 作业请求或反馈文件。

## 与 ROOT 的交接格式

观察格式为 feedback-observation/1。一行一个独立对象。必填字符串字段为 schema_version、owner、run_id、attempt_id、step_id、check_id、expected、actual。expected 和 actual 是适用于该检查的稳定结果词。可选字段为 issue_key、evidence_ref、version、parent_step_id、details_ref、disposition、origin_owner。disposition 仅取 expected、deviation 或 unknown；issue_key 是有证据支持的责任仓规则签名。同一 run/attempt 并发处理多项同类任务时，step_id 或 check_id 带原生的稳定 invocation/item ID，以区分不同材料或子作业。重复投递复用原身份，另一次真实执行使用新 attempt_id；有新证据时可用 original_occurrence_id 关联首笔发生。引用使用各自产生方可解析的不透明标识：issue_ref 由责任仓解析，原始 evidence_ref/details_ref 与复验引用由出具证据的 owner 解析。跨仓方凭公开接口和引用访问证据，物理路径、凭据及可执行命令留在原仓。version 记录被观察运行的版本，交接报告另列被测代码版本。合法拒绝按实际预期归类。例子仅说明协议字段，运行时产生真实 ID 和版本。

~~~json
{"schema_version":"feedback-observation/1","owner":"filing-fetch","run_id":"run-example","attempt_id":"try-1","step_id":"step-1","check_id":"local-reuse-provider-start","expected":"not_started","actual":"started","disposition":"deviation","issue_key":"reuse-started-provider","evidence_ref":"case-example","version":"fixture-v1"}
~~~

实现和校验 owner 只在本仓完成。ROOT 从公开交接文件读取，负责派工、跨仓原场景复验与公司池调度。ROOT 计划位于公司总控仓 docs/plans/feedback-loop-2026-11-17/task_plan.md，当前文档已包含单仓实施所需接口，允许独立并行开工。

总调度与各 owner 约定三个可选环境量。RESEARCH_FEEDBACK_OUT 提供本次独占 sidecar 路径，RESEARCH_FEEDBACK_RUN_ID 和 RESEARCH_FEEDBACK_ATTEMPT_ID 提供父运行及尝试编号；独立 E2E 可自建编号。输出位置通过宿主配置或测试入口注入，避免把任意写路径暴露给财报正文或网络输入。业务协议允许省略这些诊断字段。父进程启动子 worker 时分配不同的输出文件，或清除其 OUT 并由父进程记录该子调用的公开结果，确保每个文件只有一个写者。已写入的事件重放时复用原 ID。另一次真实尝试要单独设置 attempt_id。

## 实施顺序与责任

1. **TDD 定位 FF 责任。** 新增 `tests/test_feedback_observation.py`，组合 spy adapter 与 FF 自有 launcher，产生首取、复用不启 provider、损坏件正常拒绝、缺限额造成合同偏差四种证据。以 M3 四例的旧公开请求作取样，记录新观察器/错误归因的 RED。重复归集同一根因保留四个出现位置；损坏件预期拒绝只作预期结果。
2. **只装配 FF owner 投影。** 从业务返回和 job 原生事件记录 submit/start、查库、路由、ensure、复用/本次启动、用量是否已知及结束。关联 command_id、owner_job_id、correlation_id。公开单次短请求缺 job ID 时直接保留本次上下文。在 CWP 已拒绝且 provider_started=false 时记录未启动；原生没有证据时标为 unknown。候选为空与事实归属未证实分别标识。
3. **恢复与技能。** ROOT 分配一个已启动但丢最终收据的作业到 FF。在 FF owner 内通过原生只读 reconcile 检查是否已落库；验证供应商调用数不增加、费用仍 unknown。相同提交下让相同原生事件重复到达，work item 只修一次。技能复现旧失败、运行最小案例再更新本仓 PWF；将外仓原因连回 origin 引用。
4. **跨仓验收。** FF 独审完成后，向 ROOT 交公开观察、版本及两类测试样本。ROOT 把 RF 周跑、FF 记录、CWP 的 provider_started/已用量及各自的历史版本串起来。断掉 sidecar 输出；FF 输出、已发生费用和重试行为一致。正式下载只在已有有限业务计划相应大节点发生，原文原址及已有收据可回查。

## 本仓实施与修理技能

把观察分为动作开始和动作结果。记录公开操作、时间、原生请求或作业编号、结果、是否有重试或复用、错误的稳定类型和原因链。开始后中断而没有终态时保留未知，新的尝试沿用运行编号并更换 attempt。诊断明细按需保存在本次运行目录，敏感头、凭据、原文正文、原始响应、未脱敏的异常文本和物理绝对路径留在反馈数据之外。成功日志短期轮转；开放问题绑定可随仓复现的小样本或现有永久来源引用。原件和正式运行产物继续由原 owner 保存。

每个外部参加联调的值仅通过文件内容公开。启用反馈的实际运行及模块 E2E 在原生步骤完成时自动产出观察。独立用例自行提供运行编号，调用方有上下文时继承其运行编号。由调用环境指定独占输出位置，每次调用由一个写者写一份 UTF-8 JSONL。观察不混入业务 stdout/stderr。写入失败由现有测试/作业记录报告诊断不完整，业务退出码、返回值、已有费用、原件和重试行为保持原合同。

当相同已判定根因跨运行出现时，把新的运行和证据引用挂到同一张本仓问题卡。原生观察保留原始 attempt，根因可以待定；只在有区分证据时分拆或合并。第一版沿用本仓存放回归用例的 Git 与本计划，需修理的共因可登记在本计划下的 issues/，一因一卡。开发用的缺陷编号与真实运行证据相链。重复导入同一次观察应为零新增，同一个错误码下不同根因保持可分，临时外部条件写恢复条件。

修理技能从本仓 issue 或给定运行引用出发。先核预期、实际、代码/配置版本及真实输入来源，从公开入口复现第一次偏离合同的位置，再查同类入口和相似合法对照。业务错误、测试夹具、部署环境和外部条件分别归因。可在本仓实施的修复及其测试写进 canonical PWF；属于邻仓的偏差交 ROOT 提供公开输入输出和证据。依据旧错误和对照先写 RED，再修共同责任层，在定向 GREEN 后用原场景复验。记录修复版本、回归用例、消费者待验或已验状态。相同版本、相同输入和同一失败不触发循环重跑。技能放在本仓 skills/ 下，只消费本仓受控的回放入口和不可执行的证据引用。

## 定向验证入口

在 FF 独占 tmp_path 提供 --jobs-dir、隔离的 CWP 配置及原生 wire fixtures。首轮只重放现有失败收据与假下载；大节点按已验收历史 T3 的 50 MiB / 180 秒 / $0 用例限额走既有 T3。真实采集时遵守已有 Windows 隔离运行时约定，记录实际使用与新建目录清理。不重新生成黄金文件来消除 RED。

~~~powershell
& 'C:/Miniconda/python.exe' -B -m pytest -q tests/test_feedback_observation.py tests/test_ff_job_facade.py tests/test_ff_job_cross_process.py tests/test_failure_usage_continuity.py tests/test_ff1_envelope_candidates.py
~~~

FF 与 ROOT 在原版与修复版分别取一份 job 和短请求的脱敏样本，核计重复导入、合法拒绝、未知用量以及异常丢失。仅以本次测试配置、模拟响应和隔离作业目录作为测试输入。

## 独审、清理与交接

先让独立审查 agent 在未获知作者预期结论的情况下，仅凭本卡和可复现样例验证一次完整性、质量、协议兼容、误开单、重放和恢复。审查覆盖整段生产路径及故障路径，逐项修复并在最终源码上复核。正常 hooks 提交；远端发布前核本仓主线和并行变动，只发布本卡文件。业务链的跨仓再验交给 ROOT。

在本目录交 handoff.md（含一段 JSON），字段如下。记录实际事实，尚未运行的现场测试写明条件。git status 逐路径区分开工遗留和本卡变化，测试临时目录在采集必要证据后恢复原样。不要提交运行目录、整份业务产物或调试副本。

~~~json
{"lane":"FB-FF","owner":"<owner>","base":"<开工 SHA>","reviewed_commit":"<最终受审源码 SHA>","published_commit":"<实际发布 SHA 或本地说明>","status":"<完成或具体缺口>","tests":[{"command":"<定向命令>","result":"<通过数/失败/跳过及原因>"}],"native_refs":["<原生收据或测试标识>"],"sample_refs":["<可重放的观察样本>"],"review":"<独审范围/版本/复验和余项>","cleanup":"<仅本轮临时目录及结果>","remaining":["<组合验收归属>"]}
~~~


### 2026-11-24 定时 slot 原批次冷查

总控派发 [F4-FF-SLOT-LOOKUP](../../../../company-wiki/docs/plans/feedback-loop-2026-11-17/owner-cards/F4-FF-SLOT-LOOKUP.md) 已在本仓完成。基线 `15c4614`，`4190c03` 实现、`0ba5aa9` 修复独审发现。本仓子计划、接口映射、边界与清理见 [f4-slot-lookup.md](../f2-ff-short/f4-slot-lookup.md)，机器收据见 [f4-slot-lookup.json](../f2-ff-short/evidence/f4-slot-lookup.json)。

`ff_job_feedback.py reconcile` 扩展 `ff-scheduled-refresh/1/<run_id>` 引用：从 `--jobs-dir` 原状态根只读查同一次 run 的收据、原尝试、派发与逐项用量；把原生 `partial` 投影为合同支持的 `failed` / `unconfirmed` / `cancelled` / `succeeded`，未知或待续保持 `cost_unknown`。`ff-job/1` 回答逐字节不变；没有第二套定时账本、下载、供应商调用或费用。两个真实历史 slot 均查回 `done` / `cost_unknown` / `unconfirmed` / `cost_state=unknown`，原生 `partial` 与聚合原因仍可查；生产账本 18 文件哈希前后一致。

新增 8 例公开 CLI 红/绿测（含原结构脱敏两场景、缺原 slot、另一轮、运行中、合法跳过、损坏邻居、单项绑定、`ff-job/1` 对照与独审 F1 回归）已登记 CI 清单。独立审查 141 对抗探针零违规，唯一 Medium 发现已修复复验。剩余短请求 ET 用量归属、观察 ACK 与是否停止旧包重复扫描由 ROOT 对照实际证据确认。

## 2026-11-21 日常运行失败覆盖整改

总控负责实施本仓的日常下载、作业与定时器。故障调查基线为 006725a0。

| 原失败清单中的步骤与根因签名 | 普通入口实测 |
|---|---|
| public-start / native-failure-not-forwarded；failed-job / business-failure-classified-expected | 普通 fetch 与短请求在建立日志前做日期、输入及限额判断，故障探针八例中六例没有条目。原生 failed/config_error 作业只执行一次，F4 却出现三条 expected。Windows 登录补跑直接启动 tick，标准流被重定向，原 slot 曾保存 partial。 |

1. 从本仓普通入口先复现。总控仓 company-wiki 的 `docs/plans/feedback-loop-2026-11-17/probes/filing_fetch.py` 提供原探针。
2. 从 fetch_filing、ff_job_cli、ff_scheduled_refresh 的命令入口使用同一运行上下文。解析错误留原生原因，保持 CLI 返回协议。在作业和 slot 完成时分别投递逐项业务终态与尝试，短请求的费用、拒绝是否合理、下载/复用分别保存。定时任务先以原 slot/job 查回，取不到用量也能登记已知业务失败。
3. 隔离日期无效、配置错误、部分成功，各与合法复用和预期限额拒绝对照。关闭反馈环境变量，从同一公司/期次/slot 原生记录和新进程 F4 对账。第二次恢复执行次数、HTTP 下载、费用均不增长。Windows 定时 CLI 使用临时时钟/数据根，不触发正式任务。

普通运行先保留 owner/run/attempt/step，原生账本负责已发送、已付、未发送决策。每个步骤只记录复现所需的输入引用、版本、原因码、脱敏异常层次及代码位置。可选日志不能改变业务退出或结算。每次拒绝先记录，区分合理拒绝、可删的门禁与执行错误。

走现有 feedback-observation/1。显式 RESEARCH_FEEDBACK_OUT 保留；独立启动在所属模块已配置状态目录的 observations 自动落盘，可用 RESEARCH_FEEDBACK_DIR 指定测试目录。先发布完整 feedback-<32位uuidhex>.jsonl，再发布同名 .ready（包括 owner、run_id、attempt_id、step_id）。重复冷读按原发生身份去重。原生失败作分母，逐个对照 F4；登记和分诊不重新执行业务。上报实际部署入口、可用 outbox 位置、版本、独立测试结果和临时目录清理情况。


### 日常公开入口验收记录

责任范围为 FF 的短报表、短原文、持久作业、定时扫描与 Windows 登录启动器。原测试覆盖受监督的显式日志，正常直启在参数解析和费用准备阶段可以完全没有日志。旧 job 投影把“函数正常返回一次”当成“业务符合预期”，丢失了原生 `failed/config_error`。定时器只打整个 slot 的总标记，除非遇到相同问题重跑，很难定位具体失败文档。

实现时保留原 CLI 的 JSON、标准流和退出语义，按原尝试分别投递业务终态、明确限额拒绝和费用状态。校验门先审视其用途。本轮保留真实采集额度、原作业幂等、明确的输入结构校验。普通代码错误、无配置、读取失败和进程失联进入修复队列。来源缺失与可证明的零发送或费用未知分别保留。下游只收到业务请求，在自己的状态根发布反馈。未启动生产定时任务。

- 默认 outbox 为对应 FF 运行副本下的 `.ff_jobs/observations`，作业、定时器优先使用调用的 `--jobs-dir/observations`。显式 `RESEARCH_FEEDBACK_OUT` 继续支持。可用 `RESEARCH_FEEDBACK_DIR` 隔离临时目录。给 F4 的 `.ready` 最后发布；独立的开始与终态文件避免旧 ACK 抹掉同时落盘的新终态。
- 作业在执行前持久保存原 run、attempt；原生终态和异常保存在相同 ledger。冷读 `get_status` 可从原状态补投，已 ACK 的相同作业不再投递。费用不确定的失败同时保留原失败，不自动再采集。每日运行逐项摘要保留 stage、业务原因和同一文档的引用摘要。
- 脱敏诊断不含输入正文、任意异常消息或绝对来源路径。普通 CLI 可以从另一进程还原类型、异常链、代码位置、对应源码字节 SHA 和 JSON 解析位置。专用读口为 `python scripts/ff_job_feedback.py get-diagnostic <details_ref> --jobs-dir <既有状态根>`，也可用 `--observations-dir <独立outbox>`。已有 job 原错误仍可从 `ff_job.py get_status` 读回。
- 基线 5126876e 的 10 例均是 RED；实现后 16 个新增测试通过。独立进程覆盖非法参数/JSON、真实 CLI 启动、坏传输、作业配置失败、强制终止后两次冷读、预期费用拒绝、合法数据未下载、三市场一时段两项失败/一项成功及重复 tick 零新增调用。相邻六套旧、新联合回归 90 例通过，Ruff 全仓通过。全部使用临时目录／离线 owner；未访问外部服务或产生费用。历史上只有总体 partial 的旧 slot 不追写伪造的单项原因。
- 定向复验 `python -B -m pytest -q tests/test_feedback_ordinary_failures.py`。总控探针 `company-wiki/docs/plans/feedback-loop-2026-11-17/probes/filing_fetch.py <FF checkout>` 仍按原格式检查显式 sidecar，独立启动的无 OUT 用例依据本仓原生 outbox 实测。
- 479a06c1 为初次独审候选。复核反例以及对应的修复进度见下节。

### 2026-11-23 复核修复

独审在 479a06c1 的真实进程入口查出两种漏报。两个市场的定时发现失败写进了原始 slot，但收件箱当时不可写。恢复后读取历史也收不到任何一项。新浪三表接口正确返回 HTTP 用量与各表结果，反馈端只记了顶层 unavailable。

- 定时运行在结算同一次状态更新中保存尚待反馈的 slot ID、原 run/attempt 和各项原因。status、runs 或 tick 恢复时从原收据补投，有消费回执的项保持已交付。覆盖三市场两项失败一项成功，以及跨两个日期同时积压、原费用未知、修好收件箱后冷读和消费后的重复访问。复读复用了冻结运行，采集次数保持原值。
- 三表短命令与持久作业共用 financial-statements-response/1 的原因投影。读取原表名、状态、来源提供的错误码、覆盖终止原因、可核对的用量。正文和报表数据保留在业务输出，由原始来源提供。部分返回里的缺表、来源失败和用量未知各自记录。已有实际零美元收据时保留原金额，缺用量写 unknown。
- 精确反例在 tests/test_feedback_ordinary_failures.py 的 mixed_document、multiple_outstanding 以及 tests/financial_statements/test_fetch_statements_subprocess.py 的 diagnostics_recover、durable_statement。旧版异常期定时回执冷读 0/2，三表四种反例均缺逐表记录。修复版 8 项本地端到端通过，涵盖两次新进程查看同一份资料、已有回执 ACK、不可写收件箱恢复、对应子进程只执行一次。所有公司服务使用独立临时目录内的公开协议替身。

11 月 23 日源码 `32cf33e6553b797231f54d0df142115d57a33b8c` 已经独审并快进推送 GitHub main。独立审查从 Git 归档在独立临时根重放 CN/HK/US 定时扫描，两个失败恢复原 run/attempt，同一轮的六次实际子调用在反复 status、runs、tick 和 ACK 之后仍为六次。新浪夹具中资产负债表的 provider_unavailable、315 响应字节、1 次请求、原始零美元费用与其他缺表记录可区分，缺用量保留未知。七组回归共 135 项通过，总控原始探针 12 个场景复现 8 类失败，原生直启的失败也可以读回。Ruff、mypy、本机宿主检查和 pre-push 固定冒烟通过。

部署预演发现两个较早的全局安装仅有 19 个脚本。仅同步本次变更的 16 个运行文件会使四个入口缺少依赖。导入图查得 12 个所属依赖也需要同步，组合预演通过后，仅定点同步这 28 个本仓源码文件。两个物理目标选定文件均为零漂移。四个实际位置分别启动五个正常入口，各产生三次预期失败，每次使用新进程读回三份诊断。正式运行中原文件、配置、作业和费用均保留。安装器的全包比较另报一份既存 SKILL.md 文案差异。

| 实际运行入口 | 原生 outbox |
|---|---|
| 项目 main，Windows 任务 FilingFetch-ScheduledRefresh-Pilot 的显式 jobs-dir | `C:/Users/郑曾波/Projects/filing-fetch/.ff_jobs/observations` |
| Agents 与 Claude 技能，两个路径指向同一物理目录 | `C:/Users/郑曾波/.agents/skills/filing-fetch/.ff_jobs/observations` |
| Codex 技能 | `C:/Users/郑曾波/.codex/skills/filing-fetch/.ff_jobs/observations` |

FF 下游子进程各写自己的业务账和 outbox。父步骤只在自己的原始发生记录里冻结 RESEARCH_FEEDBACK_RUN_ID 和 RESEARCH_FEEDBACK_ATTEMPT_ID。定时调用通过原 slot 的 usage.acquisition_jobs、usage.reading_runs 原始 ID 归属子作业；下载作业公开结果可按 owner_job_id 与 source_ref 定位。上游未返回子作业或来源 ID 的早期短拒绝，只能按 FF 记录的原 cause、stage 与本地证据查询；不同进程的发生身份各自保留。额外关系需要由公开协议提供。本轮只用离线公开替身及正式 CLI 的无网络错误和读口验收，生产定时任务按原配置运行。

远端 32cf33e 的 quality 检查报错，ROOT 正在检查 [GitHub Actions 记录](https://github.com/zhengcb81/filing-fetch/actions/runs/45269509430)。

### 2026-11-23 Linux CI 复验

远端 `45269509430` 唯一失败用例在 Ubuntu Python 3.12 复现，原带重试的错误响应显示 0 次尝试，测试期望 2。原因是旧测试替换了全进程的 `time.monotonic`，新的原生反馈在业务开始前写盘时也消费了测试预设的时钟值。三组下载与来源测试统一将时钟替身限定在 `fetch_filing` 模块。CI 和日常 smoke 都使用自有的隔离收件目录和临时测试目录，清理时一起删除。原重试、调用次数、下载次数继续逐一断言。本机 Ubuntu 3.12 重测 209 项通过、1 项旧平台跳过、46 个子检查通过。配置与业务文件使用原有契约。

### 2026-11-23 真实宿主接续

总控 Windows 任务已从四次历史业务登记 22 条观察。两个电话会费用记录仍未知。首次正式接续还保留了原定时批次 `sr-20261123T073000Z-e74674c4b5` 的 `partial` 及费用未知两条观察。用公开 `runs` 读回原批次，原候选 1、失败 2、待续 1、下载 0，两个采集作业分别为已知 $0 与费用未知。历史原因包括 `incremental_discover_unavailable`、`discovery_failed:unsupported_sec_form` 和 `upstream_error`。先用原作业的实际 SEC 表型和来源适配器能力核对拒绝由来，具备正确来源路径的表型可消除误拒，确实不支持的类型应如实说明。本次接续没有执行 tick 或产生新下载。[正式 CI](https://github.com/zhengcb81/filing-fetch/actions/runs/45271185608)

### 2026-11-26 只读作业查询发生的派发证据

收口时在当前部署的公开入口冷读了八个历史发生。六次查询拒绝的脱敏调用链通过原源码哈希绑定到 `_cmd_get_status` 打开账本前的作业 ID 形状检查。这六次查询没有派发。旧日志未保存原调用方或参数，因此先保留原问题和目标作业费用未知。另两次是正式周调度的原批次，具有相同 run 与 attempt 的原回执，均为失败 2 项、待续 1 项、下载 0 次。现有 `reconcile` 仍回报业务未全确认、费用未知。八份指定原证据读前读后字节相同。

- 本次修正覆盖 `get_status`、`allowed_actions` 和 `list_jobs` 的失败路径。命令注册处声明只读能力，沿现有原生发布同时保存失败原因、异常链、`provider-start=not_started` 与 `provider-usage=not_applicable`。这两个检查点只对当次查询负责，目标作业原费用继续由自己的收据核对。
- 直跑 pytest 每个用例使用临时反馈目录并清除继承的发生和显式输出路径。涉及持久作业、定时器或读入失败路径的测试继续传自己的状态根。正式入口沿用现有回退配置。需要模拟回退的短命令测试从隔离代码副本启动。
- 先用正式 CLI 写回归。三种只读失败缺派发和费用收据，手动 pytest 缺隔离，共四个红例。带派发能力的 `run`、`act` 两个反例沿原规则通过。修正后同时检查业务 stdout、退出码、原账本字节、原生日志与观察绑定。
- Windows 离线回归覆盖普通入口、原作业冷读、定时批次、跨进程、运行期恢复和 CI 启动器六个测试文件。85 项初次通过。一个 CI 测试的临时子项目拾取了上层仓库配置，补独立 pytest 配置后与新增六例同轮复跑，7 项通过。Ruff 和 diff 检查通过。
- 远端候选 `dbf5434` 的唯一失败在 T3 最新收据 I/O 测试。新增的 pytest 夹具把正确的诊断日志写进了测试指定的收据目录，触发原有的无新收据断言。同一业务代码用基线的独立日志目录通过。改用每个用例自己的同级反馈目录，隔离收据和日志，保留原 T3 断言及日志。用短独立临时根复验 T3 全文件及六个新增用例，22 项通过。 [候选 CI](https://github.com/zhengcb81/filing-fetch/actions/runs/45783754885)
- 当时正式宿主已有查账和回告入口。六次查询可用 `get-diagnostic` 取原原因，两次定时可用 `reconcile` 取聚合事实。原调用和逐项证据补齐前保留其未结状态。

### 2026-11-26 原生分诊回执与中断恢复

本仓新增 `triage` 和 `get-triage`。接线从正式 `report` 的 Python、脚本和 `--reports-dir` 参数复用，提交动作尾接 `triage --jobs-dir <owner-state>`。按需要为每个已登记的本仓状态根重复传 `--jobs-dir`。可另传 `--observations-dir` 指向已有的独立观察目录。冷恢复动作尾接 `get-triage <action_id>`，其中 action ID 由总控追加。两个动作沿既有 `owner-json` 协议。

- CLI 失败通过原发生、尝试、步骤、原原因和原脱敏诊断引用绑定。按原 packet 中的派发和用量证据表达查询本次用量。历史未记同行费用保留未知，目标作业费用另计。已有版本的源码验真保留为旁证。需要审视拒绝时把缺调用方与入参写入 `gate_review`。
- 部分完成定时任务通过既有 `reconcile` 读同一原 slot，分别记录批次终态、聚合原因、计数、未确认子项及账款。没有同号原证据时保持 `original_evidence_unavailable`，不创建已完成动作。
- 首次结论按 action ID 在原报告根下的 `triage` 子目录原子落盘，含原提交和结果。进程丢失回复后可用原 action ID 冷读，重复提交同一动作返回已持久记录。当前可确认的故障和所需证据都留在 `needs_evidence`；消费复验报告仍使用原 `report`。
- 独立目录使用 8 份原发生的逐字节副本，实跑分诊与冷恢复。6 次查询、2 个原周批次均保存 `needs_evidence`。23 份原文件 SHA 一致。临时状态清理后只留验收摘要，未启动采集、模型或付费请求。
- 基线 5 个分诊用例先红。正式入口复验三个相关测试文件共 51 项通过，另有 1 项原 report 回执兼容通过。覆盖持久化后进程强退、冷读、重复提交、冲突、错尝试、假原原因、已知零与费用未知的定时批次。Ruff 和 diff 检查通过。

部署按总控实际配置接入并核对原 action 与 owner 记录。本节验收使用隔离 worktree 和临时状态。
