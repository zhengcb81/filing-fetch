# F2-FF-SHORT 交接

## 交付标识

| 项目 | 值 |
|---|---|
| lane / owner | F2-FF-SHORT / filing-fetch |
| 工作目录 | `C:/Users/郑曾波/Projects/_harness_worktrees/f2f/ff` |
| 分支 | `codex/f2-ff-short` |
| 卡面基线 | `d5fa32c635c2d7d3690d90ea32f39964f2460e22`（`origin/main`） |
| 计划提交 | `92e52b5`（本卡 PWF 开卡） |
| 首个实现提交 | `5575791e5f33915c91cf76890397efdd07b5b83f` |
| 最终受审提交 | `09eadf04b6a139ffef03d0c87414626e31dbaefb` |
| 提交位置 | 本地分支，未推送；ROOT 负责组合与并入主线 |

改动文件：`scripts/fetch_filing.py`（CLI 接线与 locals 预初始化）、`scripts/ff_short_feedback.py`（新适配器）、`tests/test_feedback_observation.py`、`tests/fixtures/short_feedback/connector.py`、`skills/repair-filing-fetch-issue/SKILL.md`、本卡 `findings.md` / `progress.md` / `samples/`。

## 测试

本机以 Miniconda Python 3.13.9（pytest 9.1.1）执行；命令中的 `python` 指该解释器。

| 命令 | 结果 |
|---|---|
| `python -B -m pytest -q -p no:cacheprovider tests/test_feedback_observation.py` | **30 passed**，51.98 秒 |
| 计划指定五文件（新测试 + `test_ff1_envelope_candidates` + `test_failure_usage_continuity` + `test_m3_acquisition_usage_ff` + `test_ff_job_facade`） | **204 passed, 8 subtests passed**，70.95 秒 |
| 相邻回归（五文件 + `test_fetch_filing` + `test_public_operation_isolation` + `test_s3_install_surface` + `test_architecture_quality`） | **392 passed, 1 skipped, 46 subtests passed**，135.15 秒 |
| `ruff check scripts tests/test_feedback_observation.py tests/fixtures/short_feedback/connector.py` | All checks passed |
| `mypy scripts/filing_contracts.py scripts/fetch_filing.py scripts/ff_short_feedback.py` | Success: no issues found in 3 source files |
| `tools/host_assumption_guard.py --roots tests tools scripts e2e` | `new=0` |

- 跳过：`tests/test_fetch_filing.py:2020` 的既有 “production security-master snapshots not present”。
- 基线差异（未改代码同样失败，与本卡无关）：`tests/test_provider_diagnostics_cli.py::test_real_cli_config_error_has_no_upstream_cause` 期望 `config_error`、本机实得 `fatal`。
- RED：未接线时新测试收集失败 `ModuleNotFoundError: ff_short_feedback`；接线后 24 项通过。

## 独审与逐项关闭

独立 agent（未参与实现）在 `5575791` 审查完整生产入口、异常分支、v1/v2 兼容、诊断写失败、未知费用、合法拒绝与下载计数、测试隔离及发布闭包，结论“可合入，无阻断项”，提出 5 项次要问题；修复后在 `09eadf0` 复验，全部关闭并确认可合入。

| # | 发现 | 关闭方式 | 复验 |
|---|---|---|---|
| 1 | “重复导入零新增”只比对文件字节，断言空转 | 测试改为按 `(run_id, attempt_id, step_id, check_id)` 导入两次；manifest 记录 `first_import_rows=27`、`second_import_rows=0` | 已关闭 |
| 2 | `OUT` 为空时提前返回，`RUN_ID`/`ATTEMPT_ID` 仍被继承，与 docstring 不符 | 模块与函数 docstring 改为“启用时清除三个变量、无路径时不动环境” | 已关闭 |
| 3 | v1 `reuse_only` 的 `not_started`/`not_applicable` 与 v1 gap 的 `downloads=0` 未区分合同与证据 | 在 `_usage_state`、`_v1_facts`、`_start_state` 补注释 | 已关闭 |
| 4 | 缺坏 JSON、v2 gap、v1 错误携带 observation 的覆盖 | 新增 3 例并通过 | 已关闭 |
| 5 | `begin_observation` 理论抛出会落入业务 fatal | `fetch_filing.main` 用局部 `try/except Exception` 兜住并置 `None` | 已关闭 |

## 真实 CLI 样本

`samples/` 下 6 份 JSONL 均由真实 `scripts/fetch_filing.py` 在受控 mock connector + 独占临时目录上执行产出；生成步骤与复现片段见 `samples/README.md`，逐样本请求、退出码、业务摘要、stub 序列、行数、检查名与证据引用见 `samples/manifest.json`。

| 样本 | 场景 | 退出码 | 关键行 |
|---|---|---:|---|
| `samples/sample-1-reuse-hit.jsonl` | 精确本地命中 | 0 | `provider-start=not_started`；`provider-usage=not_applicable`；`download-receipt=0` |
| `samples/sample-2-missing-limits.jsonl` | 缺限额启动前拒绝 | 2 | `request-outcome=request_error/acquisition_limits_invalid`；`provider-start=not_started`；`provider-usage=known` |
| `samples/sample-3-latest-unknown-usage.jsonl` | latest 元数据发现后复用 | 0 | `source_candidate/reused_after_discovery`；`provider-usage=unknown` |
| `samples/sample-4-download.jsonl` | 受控首取 | 0 | `source_candidate/downloaded_new`；`provider-usage=known`；`download-receipt=1` |
| `samples/sample-5-corrupt-rejection.jsonl` | 损坏件预期拒绝 | 2 | `upstream_error/canonical_import_failed`；`provider-usage=known`；`download-receipt=0` |
| `samples/sample-6-companion-scopes.jsonl` | 主财报零 + 电话会未知 | 0 | `provider-usage=known` 与 `transcript-provider-usage=unknown` 两个 `step_id` |

开始/终态配对形状（`sample-2` 的实际输出见文件；下例 ID 已脱敏为占位）：

```json
{"schema_version":"feedback-observation/1","owner":"filing-fetch","run_id":"sample-run","attempt_id":"a1","step_id":"short-filing/<operation>","evidence_ref":"ff-short/1/<operation>","check_id":"action-started","expected":"started","actual":"started","disposition":"expected","terminal_check_id":"request-outcome"}
{"schema_version":"feedback-observation/1","owner":"filing-fetch","run_id":"sample-run","attempt_id":"a1","step_id":"short-filing/<operation>","evidence_ref":"ff-short/1/<operation>","check_id":"request-outcome","expected":"terminal","actual":"request_error/acquisition_limits_invalid","disposition":"expected"}
```

两范围形状（`sample-6` 的实际输出见文件；下例 ID 已脱敏为占位，`step_id` 分别带与不带 `/transcript`）：

```json
{"check_id":"provider-usage","expected":"accounted","actual":"known","disposition":"expected","step_id":"short-filing/<operation>"}
{"check_id":"transcript-provider-usage","expected":"accounted","actual":"unknown","disposition":"unknown","step_id":"short-filing/<operation>/transcript"}
```

- stub 计数：`sample-4` 的 ensure 恰好 1 次；`sample-6` 的 ET 恰好 1 次；`sample-2` 零子进程。
- 重复导入：6 份样本共 27 行，首次导入 27，第二次 0；读取前后文件字节不变。
- 子进程环境：connector 调用日志中 `RESEARCH_FEEDBACK_OUT/RUN_ID/ATTEMPT_ID` 全为 `None`。
- 前后对照：`sample-1` 以及 latest/download/gap/corrupt/companion 五场景均以参数化用例对照禁用侧车，stdout/stderr/退出码逐字节相同；坏路径（目录、不存在父目录）同样逐字节相同。

## 清理与未触碰边界

- 测试只用 `--basetemp=C:/tmp/ff-f2-*` 与 pytest `tmp_path`。环境的安全删除策略对批量目录要求确认，`C:/tmp/ff-f2-*` 测试根未执行删除，原样留在系统临时目录；仓库内无运行目录、`.pytest_cache`、`__pycache__` 或调试副本（`git status` 干净）。
- 未触碰主工区 `C:/Users/郑曾波/Projects/filing-fetch`、生产 `config/company_wiki.json`、`FMP_API_KEY.txt`、`.ff_jobs/`、CWP/ET 仓库或任何原件。
- 样本与提交不含本机绝对路径、凭据、财报正文；只含闭集状态词、`urn:` 与 `ff-short/1/...` 引用。

## 剩余组合验收

1. ROOT 把 RF 周跑、FF 短请求侧车、CWP `provider_started`/已用量、ET 用量串起来，做真实请求的跨仓复验；本卡只交公开观察、版本与可复验引用。
2. F4 持久作业路径直接调用库入口，不经过短请求 CLI 的 `begin_observation`；其子进程仍会继承调用方的 `RESEARCH_FEEDBACK_OUT`。当前 CWP/ET 不写该协议；若未来它们具备输出能力，需由 F4/ROOT 分配不同路径或清理子进程环境。属 F4 写范围外，本卡未改。
3. 本卡未发现须修复的新缺陷，未开 `issues/` 卡。

```json
{"lane":"F2-FF-SHORT","owner":"filing-fetch","base":"d5fa32c635c2d7d3690d90ea32f39964f2460e22","implementation":"09eadf04b6a139ffef03d0c87414626e31dbaefb","reviewed_commit":"09eadf04b6a139ffef03d0c87414626e31dbaefb","branch":"codex/f2-ff-short","review_ref":"docs/plans/f2-ff-short/handoff.md","tests":[{"command":"python -B -m pytest -q -p no:cacheprovider tests/test_feedback_observation.py","result":"30 passed"},{"command":"python -B -m pytest -q -p no:cacheprovider tests/test_feedback_observation.py tests/test_ff1_envelope_candidates.py tests/test_failure_usage_continuity.py tests/test_m3_acquisition_usage_ff.py tests/test_ff_job_facade.py","result":"204 passed, 8 subtests passed"},{"command":"python -B -m pytest -q -p no:cacheprovider tests/test_feedback_observation.py tests/test_ff1_envelope_candidates.py tests/test_failure_usage_continuity.py tests/test_m3_acquisition_usage_ff.py tests/test_ff_job_facade.py tests/test_fetch_filing.py tests/test_public_operation_isolation.py tests/test_s3_install_surface.py tests/test_architecture_quality.py","result":"392 passed, 1 skipped, 46 subtests passed"}],"sample_refs":["docs/plans/f2-ff-short/samples/sample-1-reuse-hit.jsonl","docs/plans/f2-ff-short/samples/sample-2-missing-limits.jsonl","docs/plans/f2-ff-short/samples/sample-3-latest-unknown-usage.jsonl","docs/plans/f2-ff-short/samples/sample-4-download.jsonl","docs/plans/f2-ff-short/samples/sample-5-corrupt-rejection.jsonl","docs/plans/f2-ff-short/samples/sample-6-companion-scopes.jsonl"],"cleanup":"repo clean: no run directory, cache or debug copy; C:/tmp/ff-f2-* test roots remain because the environment's bulk-delete guard required confirmation; main worktree, production config, keys, originals and .ff_jobs untouched","remaining":["ROOT cross-repo composition with RF weekly run, CWP provider_started/usage and ET usage","F4 job lane child-process RESEARCH_FEEDBACK_OUT inheritance is outside this card"]}
```
