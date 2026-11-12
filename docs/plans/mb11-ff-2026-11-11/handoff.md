# MB-FF 交接

## 1. 基线、提交与写集合

- 工区：`C:/Users/郑曾波/Projects/mb11-ff`；分支 `codex/mb11-ff`；目标主线 FF `main`。
- 实际代码基线：`ac798a250b2310e0c2714053b08246ad94fffd0c`（原仓 main）。
- 最终代码提交：`16f3ceb2120ce45a222d89eaff38f294f79af8a0`。分支已推 `origin/codex/mb11-ff`（`pushed: true`）。
- 本文档与 handoff.json/review.md 所在文档提交随分支一起推送；不追自引用 hash，`documentation_commit` 记 null。代码 tip 为 `16f3ceb`，分支 tip 以远端 `origin/codex/mb11-ff` 为准（推送后即包含本文档）。
- 最终代码 diff（相对基线，仅允许写集合）：

| 文件 | 变化 |
|---|---|
| `scripts/fetch_filing.py` | +39/−10：`resolve_filing` 新增 `request_context`/`context_out`；`complete_filing_v2`/`_resolve_v2_companion` 复用 context；`main` 注入 |
| `scripts/ff_request_context.py` | 新增 25 行纯值 `RequestContext` |
| `tests/test_public_operation_isolation.py` | 新增 741 行、24 个用例 |
| `tests/fixtures/public_operation_isolation/{README.md,independent_service.py,transcript_tool.py}` | 新增公开 wire 替身 |
| `tools/ci_tests.py` | +4：登记新测试与 statements 三个测试 |
| `docs/plans/mb11-ff-2026-11-11/**` | 本卡 PWF、A0 归档、证据 |

`git diff ac798a2..16f3ceb -- scripts/ff_job_runner.py` 为空。中间提交 `c00cfef` 曾接线 job engine，复审指出该文件不在写集合后，由 `16f3ceb` 回退；最终树无该文件 diff。

## 2. 卡要求逐项

| 要求 | 结果 | 根因 / 证明 |
|---|---|---|
| FF-01 六 operation 与 job/三表隔离；query hit 不启动 provider；miss→prepare→query 最多一次；单次 ensure；job reuse 不重下 | PASS（NO_CHANGE_PROVEN） | 现有 `WikiConnection.command_for` + `_run_bounded_json` 已满足；真实 CLI 子进程、空 cwd、无邻仓 PYTHONPATH、显式 fixture command 下验证；含 prepare 后仍 miss 不再 ensure 的负例。见 `evidence/a11-tests.log`、`a12-tests.log` |
| job reconcile 不重做下载 | PASS（NO_CHANGE_PROVEN，映射既有测试） | `tests/test_ff_job_facade.py` 的 unknown→reconcile / spend evidence 用例在本卡受影响集与完整 CI 中运行；本卡新增 job 用例覆盖 reuse/idempotent 不重下。见 `evidence/a12-tests.log`、`ci-full-r5.log` |
| FF-02 command/config 组装；一次请求配置归属 | PASS（CLI）；job 见范围外 | CLI 带 companion 时原为 2 次 `load_connection_root`（RED，`a1-tests.log`），新增 `RequestContext` 后为 1 次，并断言 companion transport 收到同一 connection 对象（`a9-tests.log`） |
| ET 独立 command/interpreter/cwd；legacy `.py` 路径兼容；import 失败保留已知 usage；unknown 不当零；坏 stdout 不触发 import | PASS（NO_CHANGE_PROVEN） | `transcript_tool_transport` 以 `sys.executable + tool path` 启动，cwd=tool.parent；`_last_provider_usage` 在失败投影中保留。见 `a9-tests.log` |
| statements 只调 CWP 公开三表；complete/partial/not_found/unavailable/request_error/错误版本；大诊断不遮 stdout | PASS（NO_CHANGE_PROVEN） | `ff_financial_statements` 只走 `financial_statements` command；`_valid_error_envelope` 透传；有界 stderr。见 `a9-tests.log` |
| 业务请求不得新增任意命令执行字段 | PASS（NO_CHANGE_PROVEN） | 三个公开 validator 的白名单拒绝；`a9-tests.log` |
| 无邻仓代码可见也能工作 | PASS | 隔离测试移除 `PYTHONPATH`，并用 poison `company_wiki` 包证明未 import；`a9-tests.log` |
| 真实交付 runtime 可运行 | PASS | canonical installer 安装根 + 空 cwd + 显式 config + poison 生产 config；`c-runtime4-tests.log` 24 passed |

## 3. 公开接口变化

- 默认 none：CLI 参数、request/response schema、六 operation 名称、旧配置字段、错误/usage 语义均未变。
- 新增可选 keyword-only：`resolve_filing(..., request_context=None, context_out=None)`、`complete_filing_v2(..., request_context=None)`。默认 `None` 保持旧 library 行为；`context_out` 只在内存传递，不进入任何 envelope。
- `complete_filing_v2` 同时收到 `config_path` 与 `request_context` 时，context 优先。
- 供 ROOT 组合的公开小样例：`tests/fixtures/public_operation_isolation/samples/`，含 `source_ref.json`、`source_candidate.json`、`query_found/not_found.json`、`local_prepare_ready.json`、`operation_completed/gap.json`、`transcript_import_response.json`、`transcript_usage_known/unknown.json`、`error_envelope.json`；均为公开 wire、无物理路径。样例由同一 fixture 常量生成，并有字段校验用例防止漂移。
- fixture 命令替身：`independent_service.py`（六 operation）与 `transcript_tool.py`（ET）；运行命令见第 4 节。测试/恢复证据索引见 `evidence/INDEX.md`。

## 4. 实际测试

解释器：`C:/Miniconda/python.exe`（Python 3.13.9，pytest 9.1.1）。所有 pytest 使用仓外新 `--basetemp`（宿主 safe-delete 对默认 pytest garbage 目录会误报，非产品失败）。

| 命令 | 结果 | 耗时 | 日志 |
|---|---|---|---|
| 卡片指定 9 文件（基线，改动前） | 164 passed + 6 subtests，exit 0 | 19.79s | `evidence/baseline-tests.log` |
| `python -B -m pytest tests/test_public_operation_isolation.py -q -p no:cacheprovider` | 26 passed，exit 0 | 42.33s | `evidence/a11-tests.log` |
| 基线 9 文件 + 新测试 + `test_fc802_gap_orchestration.py` | 197 passed + 6 subtests，exit 0 | 47.23s | `evidence/a12-tests.log` |
| `python tools/ci_tests.py`（完整 CI） | 1012 passed / 2 skipped / 44 subtests，exit 0 | 150.64s | `evidence/ci-full-r5.log` |
| `ruff check scripts tests/... tools/ci_tests.py` | All checks passed | — | 本次交接命令 |
| `mypy scripts/fetch_filing.py scripts/ff_request_context.py` | Success | — | 本次交接命令 |
| canonical installer `--install` / `--check --dest <scratch>/skills` | 30 files，exit 0 / exit 0 | — | `evidence/install5*.json` |
| 安装根内运行同一 suite（`ROOT`=安装根，poison config，空 cwd） | 26 passed，exit 0 | 32.46s | `evidence/c-runtime5-tests.log` |

测试/恢复证据索引：`evidence/INDEX.md`（含关键日志 SHA256、A0 归档索引、中间轮说明、恢复状态）。

未执行：真实网络/下载/收费 provider、生产配置迁移、全局 skill 部署、跨仓 E01–E09 组合（ROOT 负责）。2 个 skip 是既有条件：production security-master 缺失、Windows symlink 不支持。

## 5. 独立审查

- 审查 agent：`agent-d9d86973-09d1-4483-87dd-c8a15732311c`，三轮只读审查。
- 第一轮（`652478f`）：PASS_WITH_FINDINGS；指出 job+companion 双载、C 阶段 import 可能来自 checkout、缺 identity/poison/显式 context 用例、文档数字过期。
- 第二轮（`c00cfef`）：确认行为修复，但指出 `ff_job_runner.py` 不在写集合；要求回退或 ROOT 扩权。
- 第三轮（`16f3ceb`）：PASS_WITH_FINDINGS，无代码阻断；要求修正两处文档措辞（`findings.md` 的“一次请求”范围与 ACQ-S2 描述）。已在文档提交中修正。详见 `review.md`。

## 6. 隔离与恢复

- 测试目录初始状态：开工前无 `mb11-ff` 工区、无 `mb11-ff-scratch`；结束状态：仓内工作树 clean，`C:/Users/郑曾波/Projects/mb11-ff-scratch/**` 为仓外 lane 私有测试根（可删除，重建命令见 §8.3）。
- 未修改：生产 `config/company_wiki.json`、`config/FMP_API_KEY.txt`、`.ff_jobs/**`、`.mimosa/**`、`.workbuddy-ai/**`、CWP/ET/SID/Dayu 源码、全局 skill。
- 未读取/复制密钥；未执行真实下载、网络或收费调用。`network_calls: 0`，`model_calls: 0`（独立审查是 harness agent，不是 FF 产品调用）；费用：无付费调用，费用 unknown 不适用（未把未知写成 0）。
- A0 归档为只读复制；未删除/重置任何旧工区、分支或未提交文件；回收清单见 `inputs/a0-archive/RECYCLE_LIST.md`。归档只作出处，不用旧 16-case 完成声明覆盖 ROOT 后续 41-case 证据；main 已跟踪的 W07 收据索引见 `inputs/a0-archive/w07/main-evidence-index.json`。

## 7. 安装/CI/合并状态与 ROOT 下一步

- 安装：仅在 scratch 安装根验证；未部署全局 skill。
- CI：本地完整 CI r4 通过；远端 GitHub Actions 未核验。
- 合并：作者未合并 `main`，未修改 ROOT 总 PWF。
- ROOT 下一步（一条命令，使用本卡交接与 fixture）：

```powershell
python -B -m pytest tests/test_public_operation_isolation.py -q -p no:cacheprovider
```

在集成后的 FF 树集中运行本卡受影响 suite 一次；若冲突解决改变源码，测试与独审绑定最终代码 tip。实际 SHA/测试/状态由 ROOT 写入总控 reconciliation。

## 8. 必须写明的限制 / out-of-scope

1. `ff_job_runner.py` 不在写集合，未改；中间提交 `c00cfef` 曾接线 job engine，复审指出写集合后由 `16f3ceb` 回退，最终树无该文件 diff。job+companion 仍按 library fallback 每阶段加载一次同一 config，两次得到相等的 `WikiConnection`（不是不同连接）；已由 `test_job_engine_reloads_equivalent_connection_not_a_different_one` 证明。ROOT 如批准 3 行接线，可进一步收敛为一次加载。
2. 仓库内生产 `config/company_wiki.json` 仍是 legacy `company_wiki_root` 形态；本卡只证明 `connection.commands` 部署形态，未迁移生产配置，也不声称生产已隔离。
3. C 阶段精确做法：canonical installer 安装到 scratch；把同一测试文件+fixtures 复制进安装根 `tests/`；`config/company_wiki.json` 换成无 commands 的 poison；空 cwd、显式 config、`pythonpath=<install>/scripts` 运行。
4. 中间证据 `a1/a2/a3/a5/a6/a7/a8/a9/a10/r2/r3/r4/runtime*/install*` 仅迭代记录，最终只引 `a11/a12/c-runtime5/ci-full-r5/install5`；`a1` 的失败断言与 `a6` 的断言错误保留原文，不裁失败段。
5. `context_out` 不落 wire；`complete_filing_v2` 同时收 `config_path`+`request_context` 时 context 优先。
6. 分支已推送；handoff/review 为文档提交。scratch 目录归本 lane，可删除；测试/恢复索引见 `evidence/INDEX.md`。
