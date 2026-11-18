# F2-FF-SHORT · filing-fetch 短请求反馈

**可开工。** 补齐 `fetch_filing.py` 单次请求的可重放反馈。持久 `ff_job` 的 F4 作业续接、计量与回告由已有端口处理。

| 项目 | 值 |
|---|---|
| 工作目录 | C:/Users/郑曾波/Projects/_harness_worktrees/f2f/ff |
| 分支 | `codex/f2-ff-short` |
| 已核基线 | `d5fa32c635c2d7d3690d90ea32f39964f2460e22`（`origin/main`） |
| PWF 选择器 | PowerShell 下设置 `$env:PLAN_ID='f2-ff-short'`、`$env:PWF_PLAN_ROOT='docs/plans'` |
| 原计划 | [FB-FF](../feedback-loop-2026-11-17/FB-FF.md) · [T3 样本与验收](../mb11-ff-2026-11-11/m3-t3-download-closeout-20261116.md) |

## 入口、写范围与目标

- 入口 `scripts/fetch_filing.py` 的 `main(argv)`，覆盖 stdin 和 `--request-file`。现有 v1/v2 success/error JSON、退出码、限额、分派、Provider、CWP 原文验真和短请求与持久作业边界沿用现行合同。不新造 job、计量、下载或许可 API。
- 写 `scripts/fetch_filing.py` 的 CLI 观察接线、新建必要的短请求反馈适配器、`tests/test_feedback_observation.py`、`skills/repair-filing-fetch-issue/SKILL.md` 和本卡 PWF。原有 owner 或协议文件供只读参考。与 Dashboard FF-1 候选路径和已验收 F4 的交叉位置只限消费公开结果。FF job 源码、`ff_v2_envelope.py`、`filing_contracts.py`、`ff_source_candidate.py`、发布分支、全局技能副本、CWP/RF/Dashboard 均在本卡范围外。
- 原主工区运行目录与本机配置、密钥和原件按现有状态留在原处。夹具使用本仓独占短临时目录和受控 mock connector。无需接通真实下载或模型端口。真实 acquisition_limits 使用本仓已有请求结构和正反 fixtures。

## 输出接口

可选 `RESEARCH_FEEDBACK_OUT` 指向进程独占 UTF-8 JSONL。用 `RESEARCH_FEEDBACK_RUN_ID` 和 `RESEARCH_FEEDBACK_ATTEMPT_ID` 继承运行上下文，未提供可生成操作 ID。父流程若启动另一个有输出能力的进程，路径由调用方区分，或清除子进程的 OUT。启用或写入失败仍保留原业务 stdout/错误信封、stderr 和退出码。输出旁路不重试业务请求。可用已有独立本地诊断通道说明写失败，保留业务 stdout/stderr 内容。

每行 `schema_version=feedback-observation/1`，必填字符串 `owner, run_id, attempt_id, step_id, check_id, expected, actual`。`owner=filing-fetch`，本仓作为发现方时 `origin_owner=filing-fetch` 或省略。原请求不带可信调用方归属时不从公司、命令行或措辞推断外仓责任。一个短调用从已有 CLI 边界发出 `action-started` 与相同 scope 的 `request-outcome`，前者 `terminal_check_id=request-outcome`。使用独立 `provider-usage` 和必要的具名责任检查。`disposition` 为 `expected/deviation/unknown`。证据引用如 `ff-short/1/<operation-id>`，重投已写好的侧车时保留身份，每次真实执行区分操作和尝试。只有原生作业才能使用 `ff-job/1` 引用。未查得原生终态时总控保留 unknown。示例：

```json
{"schema_version":"feedback-observation/1","owner":"filing-fetch","run_id":"offline-run","attempt_id":"a1","step_id":"short-filing/42","check_id":"provider-usage","expected":"accounted","actual":"unknown","disposition":"unknown","evidence_ref":"ff-short/1/42"}
```

原生已证实的请求校验拒绝、纯本地命中、找不到资料、损坏件拒绝、元数据发现和实际下载分别观察。`calls` 不是付费次数；`downloads=0` 对 `latest_as_of` 不证明未访问供应商。原生确认前置限额缺失且未发请求时标为已知未启动；完成后的费用从维护该信封的现有验证器读取，缺证据保持 unknown。主财报为已知零、伴随电话会费用未知时，分别保留两个范围的观测，整笔不得记成零。预期的合法拒绝不打开问题；若调用方应带限额但遗漏，调用方可用公开错误另发有证据的偏差。侧车只留下具名阶段、原因、状态和引用。

## 实施和验收

0. ROOT 在本工作树预检了命令中四个现有测试文件，**174 项和 8 个子例通过**。后续加测新的 CLI 旁路，使用新建的短独占 `--basetemp`，收尾只清理本轮测试根。
1. 以 T3 旧周跑请求、`tests/test_ff1_envelope_candidates.py` 和 `tests/test_failure_usage_continuity.py` 为参考先写 RED。实际通过 CLI 观察边界或 `main(argv)` 加既有夹具入口，确保 __main__ 也确实接线。至少一组公开 CLI 的离线 smoke 采用真实 UTF-8 stdin 或请求文件。对比启用前后原信封和退出码。
2. 只在当前错误和成功路径已有证据处组装旁路。复用本仓 v2 acquisition/companion usage 验证和安全的具名诊断输出，计量状态与下载/业务结果分开。成功返回 gap、未知用量、无法确认是否启动时按实际分类。对 v1 旧响应保留兼容，未提供字段记 unknown。
3. 定向覆盖 exact 本地命中、latest 元数据发现后复用、受控首取下载、missing limits 启动前具名拒绝、损坏件预期拒绝、缺原生计量（独立于成功/失败）、主财报已知零而伴随电话会未知、同 run/attempt 有两份内容身份、坏 sidecar 与禁用 sidecar 对照。记录 stub 下载/启动次数；重读侧车与重复导入应零新增。
4. 把原始问题、最小脱敏回放、真正归属、定向测试、原场景和合法场景写给本仓修复技能。若发现须修的具体问题，在本 PWF 的 `issues/` 留最小脱敏复现、责任、实际修复和复验版本。更新本卡 findings/progress。针对启用状态测试可发布闭包包含新模块，若依赖只读内部辅助则由 FF 自身正常包范围确认。跨仓组合交 ROOT。

```powershell
python -B -m pytest -q -p no:cacheprovider tests/test_feedback_observation.py tests/test_ff1_envelope_candidates.py tests/test_failure_usage_continuity.py tests/test_m3_acquisition_usage_ff.py tests/test_ff_job_facade.py
```

## 独审与交接

实现和定向测试结束后，请一位未参与实现的独立 agent 审查完整生产入口、异常分支、v1/v2 兼容、诊断写失败、未知费用、合法拒绝与下载计数、测试隔离及发布闭包。逐项修复后让审查者在最终实现 SHA 复验。交付时 `handoff.md` 给出：

- lane、owner、工作目录与分支、base SHA、implementation SHA、reviewed SHA、提交位置。测试命令、通过/失败/跳过数，独审发现和逐项关闭记录。
- 来自真实 CLI 或生产 main fixture 的最小脱敏 JSONL（短请求结果、预期拒绝、未知用量及开始/终态配对），样本生成步骤、稳定引用、前后产物或退出状态、stub 计数、重复导入的零新增。手写样例可附，不能替代实际输出。
- 清理收据和未触碰的主目录边界，列实际剩余组合验收事项。Windows 和 Linux 的路径、凭据和正文不进入公共 JSONL 或提交。

`handoff.md` 尾部用一段 JSON 给机器摘要，详细证据放正文。路径相对本工作树，引用必须能让 ROOT 独立复验。

```json
{"lane":"F2-FF-SHORT","owner":"filing-fetch","base":"BASE_SHA","implementation":"IMPLEMENTATION_SHA","reviewed_commit":"REVIEWED_SHA","branch":"codex/f2-ff-short","review_ref":"REVIEW_FILE","tests":[{"command":"ACTUAL_COMMAND","result":"PASS_COUNT_AND_OTHER_OUTCOMES"}],"sample_refs":["TEST_EMITTED_JSONL"],"cleanup":"ACTUAL_CLEANUP","remaining":["ROOT_COMPOSITION"]}
```

在本分支正常 hooks 提交代码、测试和交接，可推同名施工分支。ROOT 负责实际组合与并入主线。
