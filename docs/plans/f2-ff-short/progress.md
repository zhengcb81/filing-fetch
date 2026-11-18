# 进度

## 2026-11-18 · 短请求反馈接线

1. **基线**：本工作树 `codex/f2-ff-short`（`92e52b5`）干净。四个既有文件 **174 passed, 8 subtests passed**，22.92 秒。
2. **RED**：新增 `tests/test_feedback_observation.py` 和 `tests/fixtures/short_feedback/connector.py`，在未接线时收集失败 `ModuleNotFoundError: ff_short_feedback`。
3. **实现**：新建 `scripts/ff_short_feedback.py`；在 `scripts/fetch_filing.py` 的 `main(argv)` 业务请求边界写 `action-started`，三条返回路径写 `request-outcome`、`provider-start`、`provider-usage`、`download-receipt`，有伴随电话会时另写 `transcript-provider-usage`。CLI 读取运行上下文后清除三个环境量，子进程实测未继承。
4. **GREEN**：`tests/test_feedback_observation.py` **30 passed**。定向五文件 **204 passed, 8 subtests passed**。相邻回归（加 `test_fetch_filing`、`test_public_operation_isolation`、`test_s3_install_surface`、`test_architecture_quality`）**392 passed, 1 skipped, 46 subtests passed**；跳过为既有“production security-master snapshots not present”。
5. **静态检查**：`ruff check scripts tests/test_feedback_observation.py tests/fixtures/short_feedback/connector.py` 通过；`mypy scripts/filing_contracts.py scripts/fetch_filing.py scripts/ff_short_feedback.py` 通过；host assumption guard `new=0`。
6. **已知基线差异**：`tests/test_provider_diagnostics_cli.py::test_real_cli_config_error_has_no_upstream_cause` 在本机基线上同样失败（期望 `config_error`，实得 `fatal`），与本卡改动无关，未计入定向集。

```powershell
python -B -m pytest -q -p no:cacheprovider --basetemp=C:/tmp/ff-f2-short-final tests/test_feedback_observation.py tests/test_ff1_envelope_candidates.py tests/test_failure_usage_continuity.py tests/test_m3_acquisition_usage_ff.py tests/test_ff_job_facade.py
```

## 独审与交接

- 独立 agent 在 `5575791` 审查生产入口、异常分支、v1/v2 兼容、诊断写失败、未知费用、合法拒绝与下载计数、测试隔离及发布闭包；结论“可合入，无阻断项”，提出 5 项次要问题（重复导入断言空转、环境 docstring、证据口径注释、三处覆盖缺口、`begin_observation` 理论抛出）。
- 逐项修复后提交 `09eadf0`；审查者在最终 SHA 复验，5 项全部关闭并确认可合入。
- `handoff.md` 已写（正文 + 尾部机器摘要 JSON）。本地分支未推送，ROOT 负责组合与并入主线。
- 剩余：ROOT 跨仓组合（RF 周跑 / FF 侧车 / CWP 计量 / ET 用量）；F4 作业路径子进程继承 OUT 的边界观察属 F4 范围。
