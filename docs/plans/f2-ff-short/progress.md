# 进度

## 2026-11-18 · 短请求反馈接线

1. **基线**：本工作树 `codex/f2-ff-short`（`92e52b5`）干净。四个既有文件 **174 passed, 8 subtests passed**，22.92 秒。
2. **RED**：新增 `tests/test_feedback_observation.py` 和 `tests/fixtures/short_feedback/connector.py`，在未接线时收集失败 `ModuleNotFoundError: ff_short_feedback`。
3. **实现**：新建 `scripts/ff_short_feedback.py`；在 `scripts/fetch_filing.py` 的 `main(argv)` 业务请求边界写 `action-started`，三条返回路径写 `request-outcome`、`provider-start`、`provider-usage`、`download-receipt`，有伴随电话会时另写 `transcript-provider-usage`。CLI 读取运行上下文后清除三个环境量，子进程实测未继承。
4. **GREEN**：`tests/test_feedback_observation.py` **30 passed**。定向五文件 **204 passed, 8 subtests passed**。相邻回归（加 `test_fetch_filing`、`test_public_operation_isolation`、`test_s3_install_surface`、`test_architecture_quality`）**392 passed, 1 skipped, 46 subtests passed**；跳过为既有“production security-master snapshots not present”。
5. **静态检查**：`ruff check scripts tests/test_feedback_observation.py tests/fixtures/short_feedback/connector.py` 通过；`mypy scripts/filing_contracts.py scripts/fetch_filing.py scripts/ff_short_feedback.py` 通过；host assumption guard `new=0`。
6. **已知基线差异**：`tests/test_provider_diagnostics_cli.py::test_real_cli_config_error_has_no_upstream_cause` 在本机基线上同样失败（期望 `config_error`，实得 `fatal`），与本卡改动无关，未计入定向集。

```powershell
python -B -m pytest -q -p no:cacheprovider --basetemp=<short-temp-root> tests/test_feedback_observation.py tests/test_ff1_envelope_candidates.py tests/test_failure_usage_continuity.py tests/test_m3_acquisition_usage_ff.py tests/test_ff_job_facade.py
```

## 独审与交接

- 第一轮独立 agent 在 `5575791` 审查生产入口、异常分支、v1/v2 兼容、诊断写失败、未知费用、合法拒绝与下载计数、测试隔离及发布闭包；结论“可合入，无阻断项”，提出 5 项次要问题。逐项修复后提交 `09eadf0`，审查者在最终 SHA 复验关闭。
- 第二轮由另一位未获知前轮结论的独立审计者对照卡面逐条找遗漏，提出 v1 gap 下载字段、五场景启用/禁用逐字节对照、受审 SHA 落后、精确 reuse 启动判定、RED 可复验性等项。修复后提交 `321c455`、`eb2ee5c`，并在 `eb2ee5c` 复验：侧车 30 passed、五文件 204 passed + 8 subtests、九文件 392 passed + 1 skipped + 46 subtests、ruff 通过。
- `handoff.md` 已写（正文 + 尾部机器摘要 JSON），`implementation` / `reviewed_commit` 均为 `eb2ee5c`。本地分支未推送，ROOT 负责组合与并入主线。
- 剩余：ROOT 跨仓组合（RF 周跑 / FF 侧车 / CWP 计量 / ET 用量）；F4 作业路径子进程继承 OUT 的边界观察属 F4 范围；测试根因环境批量删除保护未删除，已在交接中如实记录。

## ROOT 验收（2026-11-19）

- 已复跑作者定向五文件基线，204 项及 8 子例通过。ROOT 独审发现非法数组或对象请求在旁路丢终态，隔离真实 CLI 两例先红后绿。修复保留原回执、退出码与零原生调用。最终组合与发布状态关联 company-wiki 总控 F4 收据。
