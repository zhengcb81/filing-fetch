# MB-FF 工作计划（本仓 PWF）

- 工区：`C:/Users/郑曾波/Projects/mb11-ff`，分支 `codex/mb11-ff`，目标主线 FF `main`。
- 实际基线：`ac798a250b2310e0c2714053b08246ad94fffd0c`（原仓 main，2026-11-11 CI 接线提交）。
- 总控：`C:/Users/郑曾波/Projects/company-wiki/docs/plans/module-boundaries-2026-11-11/`。本卡与 interfaces/acceptance/runtime_verification/handoff_contract 已复制到 `inputs/`。
- 可用解释器：`C:/Miniconda/python.exe`（Python 3.13.9，pytest 9.1.1，离线）。默认 `python` 无 pytest，测试统一用 `PY`。
- 写入范围只限本工区：PWF、卡内列出的测试/fixture、`tools/ci_tests.py` 登记，以及确有 RED 的 owner 源码（见 findings.md）。不改生产 `config/company_wiki.json`、密钥、`.ff_jobs`、job 持久化语义、ET/CWP/SID 源码、全局 skill、ROOT 总 PWF。

## A0 — 旧材料接收状态与归档（本卡开工前）

按 `reconciliation.md` 与 `review/repo_reconciliation_20261111/acquisition_review.md` §3/4/5：

- B34 显式 null 发布日期修复已由 ROOT 接收为 `d563b630…`，CI 清单接线 `ac798a250…`；不重做、不 cherry-pick 旧 `53285c2`。
- `codex/ff-job-facade-01` 的 7 个 cherry+ 已由 `57351d0`/`7d8392e` 吸收；6 个重复源码/测试已 restore；旧 job 协议两处语义已吸收。`codex/transcript-companion` 原型由正式 ET transport 替代，不带回猜目录逻辑。
- A0 已完成归档：旧 job 协议差量（文件 + dirty diff）、W06 两份过期 PWF（文件 + dirty diff）与六份 input、W07 六份基线输入与 `.tmp` 中 6 组唯一首失败/最终/时序收据（18 个 report/restore/guard-events + manifest）。归档在 `inputs/a0-archive/`，回收清单在 `inputs/a0-archive/RECYCLE_LIST.md`。**只用旧材料说明出处，不覆盖 ROOT 后续 41-case 证据、不重建第二 job 库、不扩成产品许可。**
- `.ff_jobs` 是业务作业状态，配置密钥、工具状态与记忆保留，不作垃圾、不读写其内容。

## A — 行为/隔离测试先行

1. 新增 `tests/test_public_operation_isolation.py` 与 `tests/fixtures/public_operation_isolation/**`：在一个新临时根里放"独立服务"脚本，配置 `connection.commands` 指向它；移除邻仓 PYTHONPATH，清空继承的 `company_wiki.json`/凭据环境，子进程 cwd 为空临时目录。真实 subprocess 启动 filing/statements/job 公开入口；六个 operation 各走自己那条命令，缺项具名失败且不猜目录。
2. query hit 不启动 provider/ensure；miss → local_prepare → 再 query 最多一次；单次 ensure 只发一次；statements 只调 CWP 公开三表。
3. 独立 ET command/interpreter/cwd：ET 工具是 tmp 内 `.py` 文件，用当前解释器在自身 cwd 启动，与 CWP 连接无关；验证请求 context 对同一部署配置只解析一次连接；旧 `earnings_transcripts_tool` `.py` 路径配置仍兼容；业务请求里出现任意命令字段应被公开 validator 拒绝。
4. ET usage 即使 import 失败仍保留已知消耗、unknown 不当零；成功/partial/gap/错误版本语义保持；可选大诊断不遮业务 stdout；job reuse/reconcile 不重做下载。
5. 记录每项 RED（真实越界/能力错误）或已满足证明；fixture/缺依赖/沙箱失败不冒作产品 RED。

## B — owner 根因修复（仅在 RED 成立时）

- 允许改：`scripts/ff_company_wiki_connection.py`、`ff_configuration.py`、`fetch_filing.py`、`ff_financial_statements.py`、`transcript_tool_transport.py`、`transcript_companion.py`，以及确需的本仓纯端口/请求 context 模块。
- 保留公开 CLI、wire、schema、旧配置；不整体搬 scripts，不新增业务请求中的命令执行字段。
- 公开协议真需要改时把失败例与最小兼容方案写入 PWF 交 ROOT 协调，继续其余独立工作。

## C — 模块验收与交付

1. 用 canonical installer `tools/sync_installs_b3.py --install/--check --dest <scratch>/skills --json` 建实际安装根，从安装根脚本入口以空 cwd 跑同一 suite；不新建 wheel、不改安装体系。
2. 按 `tools/ci_tests.py` 跑一次必要包级 CI；测试目录恢复、原件/配置/WIP 不变。
3. 独立审查 agent 审完整度、架构归属、回归、全部新增测试；修复本卡可行动问题并复核。
4. 提交并推送 `codex/mb11-ff`；交付 `handoff.md/json`、`review.md`、测试与恢复证据索引。作者不合并 main、不改 ROOT 总 PWF。

## 状态

- [x] A0 归档与工区建立
- [x] A 测试（六 operation/ET/statements/job；真实 subprocess、空 cwd、无邻仓 PYTHONPATH）
- [x] B 修复（一次请求 `RequestContext` 注入；其余边界 `NO_CHANGE_PROVEN`）
- [x] C 验收、独审、交付（runtime5 26 passed；受影响集 197 passed；完整 CI r5 1012 passed/2 skipped；独审 PASS_WITH_FINDINGS 已闭环，handoff/review/evidence index 已写，代码 tip 与文档提交随分支推送）

## Status

CLOSED（2026-11-12）。代码 tip `16f3ceb`；文档提交随 `codex/mb11-ff` 分支推送。
