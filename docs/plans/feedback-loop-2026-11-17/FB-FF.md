# FB-FF　下载、复用和作业反馈接线

施工状态：F4 持久作业和回告已验收并发布；短请求和其他偏差接入按余项继续。采集侧两张独立卡由 ET 和 SID 并行施工；全局另有 industry-research（IR）独立研究报告卡。唯一工作目录为 `C:/Users/郑曾波/Projects/filing-fetch`，主线 `main`，本次计划基线 `4c7f501b`。本仓 canonical PWF 是 [PLANNING_STATUS.md](../../../PLANNING_STATUS.md)。

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
