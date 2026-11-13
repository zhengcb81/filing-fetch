# MB-FF 交接

## 1. 基线、提交与写集合

- 工区：`C:/Users/郑曾波/Projects/mb11-ff`；分支 `codex/mb11-ff`；目标主线 FF `main`。
- 实际代码基线：`ac798a250b2310e0c2714053b08246ad94fffd0c`（原仓 main）。
- 最终代码提交：`c870ab78f14c4f7d458de87e907e311e7fc5eb5a`（含 26 个隔离用例、公开样例与 job engine 一次请求接线）。分支已推 `origin/codex/mb11-ff`（`pushed: true`）。
- 本文档与 handoff.json/review.md 所在文档提交随分支一起推送；不追自引用 hash，`documentation_commit` 记 null。代码 tip 为 `c870ab7`，分支 tip 以远端 `origin/codex/mb11-ff` 为准（推送后即包含本文档）。
- 最终代码 diff（相对基线，仅允许写集合）：

| 文件 | 变化 |
|---|---|
| `scripts/fetch_filing.py` | +39/−10：`resolve_filing` 新增 `request_context`/`context_out`；`complete_filing_v2`/`_resolve_v2_companion` 复用 context；`main` 注入 |
| `scripts/ff_request_context.py` | 新增 25 行纯值 `RequestContext` |
| `scripts/ff_job_runner.py` | +3：`_run_filing_engine` 用 `context_out` 取回并传递同一 `RequestContext`（按用户指令闭合一次请求配置归属；未改 job 语义） |
| `tests/test_public_operation_isolation.py` | 新增 801 行、26 个用例 |
| `tests/fixtures/public_operation_isolation/{README.md,independent_service.py,transcript_tool.py}` | 新增公开 wire 替身 |
| `tests/fixtures/public_operation_isolation/samples/**` | 11 个 source/ref/usage/error 公开小样例 + README |
| `tools/ci_tests.py` | +4：登记新测试与 statements 三个测试 |
| `docs/plans/mb11-ff-2026-11-11/**` | 本卡 PWF、A0 归档、证据 |

`scripts/ff_job_runner.py` 原不在卡片写集合；按用户 2026-11-12 “做到清单要求完成”的指令，最终增加 3 行 composition-root 接线，未改 job 持久化/幂等/重试/费用语义。中间提交 `c00cfef` 曾接线、`16f3ceb` 按写集合回退，`c870ab7` 再按用户指令恢复；最终 diff 见上表。

## 2. 卡要求逐项

| 要求 | 结果 | 根因 / 证明 |
|---|---|---|
| FF-01 六 operation 与 job/三表隔离；query hit 不启动 provider；miss→prepare→query 最多一次；单次 ensure；job reuse 不重下 | PASS（NO_CHANGE_PROVEN） | 现有 `WikiConnection.command_for` + `_run_bounded_json` 已满足；真实 CLI 子进程、空 cwd、无邻仓 PYTHONPATH、显式 fixture command 下验证；含 prepare 后仍 miss 不再 ensure 的负例。见 `evidence/a13-tests.log`、`a14-tests.log` |
| job reconcile 不重做下载 | PASS（NO_CHANGE_PROVEN，映射既有测试） | `tests/test_ff_job_facade.py` 的 unknown→reconcile / spend evidence 用例在本卡受影响集与完整 CI 中运行；本卡新增 job 用例覆盖 reuse/idempotent 不重下。见 `evidence/a14-tests.log`、`ci-full-r6.log` |
| FF-02 command/config 组装；一次请求配置归属 | PASS（CLI + job） | CLI 带 companion 时原为 2 次 `load_connection_root`（RED，`a1-tests.log`），新增 `RequestContext` 后 CLI 与 job engine 均为 1 次，并断言 companion transport 收到同一 connection 对象（`a13-tests.log`） |
| ET 独立 command/interpreter/cwd；legacy `.py` 路径兼容；import 失败保留已知 usage；unknown 不当零；坏 stdout 不触发 import | PASS（NO_CHANGE_PROVEN） | `transcript_tool_transport` 以 `sys.executable + tool path` 启动，cwd=tool.parent；`_last_provider_usage` 在失败投影中保留。见 `a13-tests.log` |
| statements 只调 CWP 公开三表；complete/partial/not_found/unavailable/request_error/错误版本；大诊断不遮 stdout | PASS（NO_CHANGE_PROVEN） | `ff_financial_statements` 只走 `financial_statements` command；`_valid_error_envelope` 透传；有界 stderr。见 `a13-tests.log` |
| 业务请求不得新增任意命令执行字段 | PASS（NO_CHANGE_PROVEN） | 三个公开 validator 的白名单拒绝；`a13-tests.log` |
| 无邻仓代码可见也能工作 | PASS | 隔离测试移除 `PYTHONPATH`，并用 poison `company_wiki` 包证明未 import；`a13-tests.log` |
| 真实交付 runtime 可运行 | PASS | canonical installer 安装根 + 空 cwd + 显式 config + poison 生产 config；`c-runtime6-tests.log` 26 passed |

## 3. 公开接口变化

- 默认 none：CLI 参数、request/response schema、六 operation 名称、旧配置字段、错误/usage 语义均未变。
- 新增可选 keyword-only：`resolve_filing(..., request_context=None, context_out=None)`、`complete_filing_v2(..., request_context=None)`。默认 `None` 保持旧 library 行为；`context_out` 只在内存传递，不进入任何 envelope。
- `complete_filing_v2` 同时收到 `config_path` 与 `request_context` 时，context 优先。
- 供 ROOT 组合的公开小样例：`tests/fixtures/public_operation_isolation/samples/`，含 `source_ref.json`、`source_candidate.json`、`query_found/not_found.json`、`local_prepare_ready.json`、`operation_completed/gap.json`、`transcript_import_response.json`、`transcript_usage_known/unknown.json`、`error_envelope.json`；均为公开 wire、无物理路径。样例为人工对齐快照，字段级校验防缺字段；fixture 常量变化时需同 commit 更新（仓库不存生成脚本）。
- fixture 命令替身：`independent_service.py`（六 operation）与 `transcript_tool.py`（ET）；运行命令见第 4 节。测试/恢复证据索引见 `evidence/INDEX.md`。

## 4. 实际测试

解释器：`C:/Miniconda/python.exe`（Python 3.13.9，pytest 9.1.1）。所有 pytest 使用仓外新 `--basetemp`（宿主 safe-delete 对默认 pytest garbage 目录会误报，非产品失败）。

| 命令 | 结果 | 耗时 | 日志 |
|---|---|---|---|
| 卡片指定 9 文件（基线，改动前） | 164 passed + 6 subtests，exit 0 | 19.79s | `evidence/baseline-tests.log` |
| `python -B -m pytest tests/test_public_operation_isolation.py -q -p no:cacheprovider` | 26 passed，exit 0 | 42.86s | `evidence/a13-tests.log` |
| 基线 9 文件 + 新测试 + `test_fc802_gap_orchestration.py` | 197 passed + 6 subtests，exit 0 | 54.55s | `evidence/a14-tests.log` |
| `python tools/ci_tests.py`（完整 CI） | 1012 passed / 2 skipped / 44 subtests，exit 0 | 161.96s | `evidence/ci-full-r6.log` |
| `ruff check scripts tests/... tools/ci_tests.py` | All checks passed | — | 本次交接命令 |
| `mypy scripts/fetch_filing.py scripts/ff_request_context.py` | Success | — | 本次交接命令 |
| canonical installer `--install` / `--check --dest <scratch>/skills` | 30 files，exit 0 / exit 0 | — | `evidence/install6*.json` |
| 安装根内运行同一 suite（`ROOT`=安装根，poison config，空 cwd） | 26 passed，exit 0 | 37.56s | `evidence/c-runtime6-tests.log` |

测试/恢复证据索引：`evidence/INDEX.md`（含关键日志 SHA256、A0 归档索引、中间轮说明、恢复状态）。

未执行：真实网络/下载/收费 provider、生产配置迁移、全局 skill 部署、跨仓 E01–E09 组合（ROOT 负责）。2 个 skip 是既有条件：production security-master 缺失、Windows symlink 不支持。

## 5. 独立审查

- 审查 agent：`agent-d9d86973-09d1-4483-87dd-c8a15732311c`，五轮只读审查。
- 第一轮（`652478f`）：PASS_WITH_FINDINGS；指出 job+companion 双载、C 阶段 import 可能来自 checkout、缺 identity/poison/显式 context 用例、文档数字过期。
- 第二轮（`c00cfef`）：确认行为修复，但指出 `ff_job_runner.py` 不在写集合；要求回退或 ROOT 扩权。
- 第三轮（`16f3ceb`）：PASS_WITH_FINDINGS，无代码阻断；要求修正两处文档措辞（`findings.md` 的“一次请求”范围与 ACQ-S2 描述）。已在文档提交中修正。
- 第四轮（`e1c4be2`）：对照卡与 handoff_contract 审计，AUDIT_WITH_FINDINGS；指出 handoff 过期引用、样例防漂移表述、diff 行数；本轮已修（样例改为“人工对齐快照 + 字段级守卫”）。
- 第五轮（`c870ab7`）：确认 job engine 已按用户指令接入同一 `RequestContext`，job+companion 1 次加载；最终复核 PASS。详见 `review.md`。

## 6. 隔离与恢复

- 测试目录初始状态：开工前无 `mb11-ff` 工区、无 `mb11-ff-scratch`；结束状态：仓内工作树 clean，`C:/Users/郑曾波/Projects/mb11-ff-scratch/**` 为仓外 lane 私有测试根（可删除，重建命令见 §8.3）。
- 未修改：生产 `config/company_wiki.json`、`config/FMP_API_KEY.txt`、`.ff_jobs/**`、`.mimosa/**`、`.workbuddy-ai/**`、CWP/ET/SID/Dayu 源码、全局 skill。
- 未读取/复制密钥；未执行真实下载、网络或收费调用。`network_calls: 0`，`model_calls: 0`（独立审查是 harness agent，不是 FF 产品调用）；费用：无付费调用，费用 unknown 不适用（未把未知写成 0）。
- A0 归档为只读复制；未删除/重置任何旧工区、分支或未提交文件；回收清单见 `inputs/a0-archive/RECYCLE_LIST.md`。归档只作出处，不用旧 16-case 完成声明覆盖 ROOT 后续 41-case 证据；main 已跟踪的 W07 收据索引见 `inputs/a0-archive/w07/main-evidence-index.json`。

## 7. 安装/CI/合并状态与 ROOT 下一步

- 安装：仅在 scratch 安装根验证；未部署全局 skill。
- CI：本地完整 CI r6 通过（1012 passed / 2 skipped / 44 subtests）；远端 GitHub Actions 未核验。
- 合并：作者未合并 `main`，未修改 ROOT 总 PWF。
- ROOT 下一步（一条命令，使用本卡交接与 fixture）：

```powershell
python -B -m pytest tests/test_public_operation_isolation.py -q -p no:cacheprovider
```

在集成后的 FF 树集中运行本卡受影响 suite 一次；若冲突解决改变源码，测试与独审绑定最终代码 tip。实际 SHA/测试/状态由 ROOT 写入总控 reconciliation。

## 8. 必须写明的限制 / out-of-scope

1. `ff_job_runner.py` 原不在卡片写集合；按用户 2026-11-12 “做到清单要求完成”的指令，最终增加 3 行 composition-root 接线（`c870ab7`），未改 job 持久化/幂等/重试/费用语义。job+companion 由 `test_job_engine_uses_one_connection_snapshot` 证明只加载一次。若 ROOT 认为该扩权需另案，可回退这 3 行，job 会回到两次等价加载（非不同连接）。
2. 仓库内生产 `config/company_wiki.json` 仍是 legacy `company_wiki_root` 形态；本卡只证明 `connection.commands` 部署形态，未迁移生产配置，也不声称生产已隔离。
3. C 阶段精确做法：canonical installer 安装到 scratch；把同一测试文件+fixtures（含 samples）复制进安装根 `tests/`；`config/company_wiki.json` 换成无 commands 的 poison；空 cwd、显式 config、`pythonpath=<install>/scripts` 运行。
4. 中间证据 `a1/a2/a3/a5/a6/a7/a8/a9/a10/a11/a12/r2/r3/r4/r5/runtime*/install*` 仅迭代记录，最终只引 `a13/a14/c-runtime6/ci-full-r6/install6`；`a1` 的失败断言与 `a6` 的断言错误保留原文，不裁失败段。
5. `context_out` 不落 wire；`complete_filing_v2` 同时收 `config_path`+`request_context` 时 context 优先。
6. 分支已推送；handoff/review 为文档提交。scratch 目录归本 lane，可删除；测试/恢复索引见 `evidence/INDEX.md`。


## 9. ROOT 主线并入记录（2026-11-13）

- filing-fetch 主线已快进并推送到 41acdc8ea991d0d0b60037ef253c5b16c9492195；交付代码 c870ab78 及之后的 PWF 文档提交均在该主线历史中。
- ROOT 在真实主线运行隔离套件：26 passed / 0 failed / 0 skipped，25.57s；交付分支完整 CI 仍为 1012 passed / 2 skipped（161.96s），详见 evidence/ci-full-r6.log。
- 旧 §7 “作者未合并 main / ROOT 下一步运行隔离套件”是交付时状态，现由本节和 handoff.json.root_integration 更新为已完成。
- 原仓 .ff_jobs/、.mimosa/、.workbuddy-ai/ 与 config/FMP_API_KEY.txt 保留；未读取密钥、未改生产配置或原始资料。


## 10. 临时工区回收（2026-11-13）

- MB-FF 专用交付 worktree 与 ROOT 集成 worktree 均已确认 clean 后回收；Git 分支及远端证据保留。
- handoff 指定的仓外 scratch 根 mb11-ff-scratch 已删除。删除前确认只包含 pytest、review1–5、runtime1–6 的 lane 测试产物，共 5,030 个文件、18,119,347 字节；测试与审查日志在仓内 evidence 中保留，可按索引重建。
- 原仓 .ff_jobs、配置密钥路径、.mimosa 与 .workbuddy-ai 未动；密钥未读取。无其他清理。
