# MB-FF 独立审查记录

审查 agent：`agent-d9d86973-09d1-4483-87dd-c8a15732311c`（独立上下文，只读审查；未修改仓库）。三轮均要求审完整度、架构归属、回归与全部新增测试。

## R1 — tip `652478f69d2fa3076106e67c4afff34ab51b3c00`

结论：**PASS_WITH_FINDINGS**。

| 级别 | 发现 | 处理 |
|---|---|---|
| 阻断（流程） | 缺 handoff.md/json、review.md；分支未推送 | 本轮后补（见 handoff） |
| 高 | `ff_job_runner._run_filing_engine` 未传 context，job+companion 会二次加载；findings 自相矛盾 | 先接线，R2 再按写集合回退（见下） |
| 高 | 生产 `config/company_wiki.json` 仍是 legacy root；隔离测试只覆盖 `connection.commands` | handoff 明示限制，不声称生产已隔离 |
| 中 | progress 数字过期（184/1005+1）；task_plan 未勾选 | 更新为最终证据 |
| 中 | 只数加载次数，未断言 companion 收到同一 connection；C 阶段 import 可能来自 checkout | 增加对象 identity 断言与 `__file__` 校验；C 改为安装根内复制测试运行 |
| 中 | 缺 job+companion、poison、显式 context 用例；`poison_company_wiki` 参数未使用 | 新增 4 个用例 |
| 低 | CI 多登记 statements 测试；`context_out` 为 dict 出参 | 确认 `test_fetch_statements.py` 确在卡片测试入口点名，保留；`context_out` 不落 wire 写入 handoff |

已核对：A0 归档 SHA/逐字节一致、原 worktree 未删；新 suite 20 passed；`fc802`/job/transcript 64 passed；statements 35 passed；`ci-full-r2` 1006 passed/2 skipped；`c-runtime2` 20 passed；写集合仅允许文件；公开 CLI/wire 未变。

## R2 — tip `c00cfef850dddbbefd65a342bfd4962013a9f408`

结论：**PASS_WITH_FINDINGS**。

- 高 1/2 行为已解决；job+companion 实测 `loads=1`。
- 高（写集合）：`scripts/ff_job_runner.py:196-208` 不在 `inputs/MB-FF.md` 写集合，需 ROOT 扩权或回退。
- 中：findings 仍引 a2 20 passed；重复空 F5；progress 未写 1010；task_plan 仍“复审进行中”；job 用例名过宽。
- 低：“5 行”实际 3 行；`context_out` 优先级需 handoff 写明。

处理：回退 `ff_job_runner.py` 到基线（最终树无 diff），job 用例改为断言“两次加载得到相等连接，非不同连接”；findings/progress/task_plan 修正；C 改为安装根内复制同一测试+fixtures 运行。

## R3 — tip `16f3ceb2120ce45a222d89eaff38f294f79af8a0`

结论：**PASS_WITH_FINDINGS**，无代码阻断。

剩余必须修（文档）：

1. `findings.md:43` 标题“一次请求只解析一次 deployment config”过宽；job engine 仍 2 次加载。→ 改为“CLI 一次请求…（job 见 F5）”。
2. `findings.md:30` 仍写“一次 v2 带 companion 会解析两次连接”，对 CLI 已不成立；行号过期。→ 限定 CLI 已收敛、job 两次等价加载。

已核对：

- `git status --short` 空；`git diff ac798a2..HEAD --name-only` 仅 `fetch_filing.py`、`ff_request_context.py`、tests/fixtures、`test_public_operation_isolation.py`、`tools/ci_tests.py` + PWF；`ff_job_runner.py` diff 为空。
- 新 suite 24 + fc802 + job facade = 70 passed + 6 subtests；runtime4 安装根 24 passed（脚本/测试/fixtures 与 tip 字节一致、config poison）。
- 证据：a9 24、a10 195+6、c-runtime4 24、ci-full-r4 1010/2 skipped/44 subtests。
- `test_one_request...` 断言 `fetch_filing.__file__` 与同一 connection 对象；`test_job_engine...` 断言 len==2 且两次相等；`context_out` 仅内存、未进 envelope；CLI/wire/六 operation 未变。

文档修正已在最终文档提交中完成；未再改变代码，故不触发代码复审。

## R4 — 对照卡与 handoff_contract 审计（tip `e1c4be2`）

结论：**AUDIT_WITH_FINDINGS**。

| 级别 | 发现 | 处理 |
|---|---|---|
| 交付前必须修 | handoff/progress/task_plan 称已推送，但 `e1c4be2` 相对远端 `d82a64b` ahead 1 | 本轮修正文档后推送 `e1c4be2`，`pushed: true` 随后成立 |
| 交付前必须修 | `handoff.md` diff 表仍写 741 行/24 用例，漏 samples；正文仍引 a9/c-runtime4/r4 | 改为 805 行/26 用例、补 samples 行、统一 a11/c-runtime5/r5 |
| 交付前必须修 | samples 声称“由同一常量生成、不能漂移”，但仓库无生成脚本，测试只校验必填键 | 改为“人工对齐快照 + 字段级守卫”，明确常量变化需同 commit 更新；不声称全值相等 |
| handoff 写明即可 | review 只记三轮，未记本轮审计 | 本节补 R4 |

已核对：新 suite 26 passed；a12 197+6；c-runtime5 26；ci-full-r5 1012/2 skipped/44 subtests；W07 main 收据索引 6/6 SHA 匹配；A0 41-case 不覆盖、job reconcile 映射、PWF CLOSED 均已写入；`handoff.json` test_runs 数字正确。修正后仅剩推送动作。

## R5 — 用户“做到清单要求完成”后的 job engine 复核（tip `c870ab7`）

用户要求把“一次请求配置归属”完全闭合。作者将 `scripts/ff_job_runner._run_filing_engine` 接入同一 `RequestContext`（3 行 composition-root 接线，未改 job 持久化/幂等/重试/费用语义），并把测试改为 `test_job_engine_uses_one_connection_snapshot`，断言 job+companion 只加载一次。

复核：

- 新 suite **26 passed**（`a13`）；受影响集 **197 passed + 6 subtests**（`a14`）；runtime6 **26 passed**；完整 CI r6 **1012 passed / 2 skipped / 44 subtests**。
- `ff_job_runner.py` 最终 diff 为 +3；未改公开 job 协议/状态语义。
- 写集合扩权来源为用户 2026-11-12 指令，已在 handoff §1/§8 与 `out_of_scope_findings` 注明；ROOT 如认为需另案可回退这 3 行（会回到两次等价加载）。
- 结论：**PASS**。唯一剩余限制是生产 legacy `config/company_wiki.json` 未迁移（卡片明确不改）与远端 Actions 未核验（非本卡要求）。

## 最终结论

- 代码/测试/证据：**PASS**（无本卡可行动代码问题）。
- 交付前文档修正：R3 两项 + R4 三项 + R5 job engine 复核已完成；推送后 `pushed: true` 成立。
- 开放项：无本卡 in-scope finding；out-of-scope 见 `handoff.md` §8 与 `handoff.json.out_of_scope_findings`。
