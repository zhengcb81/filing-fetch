# 调查依据

## 基线与 RED

- ROOT 预检与本轮复跑：`tests/test_ff1_envelope_candidates.py`、`tests/test_failure_usage_continuity.py`、`tests/test_m3_acquisition_usage_ff.py`、`tests/test_ff_job_facade.py` 共 **174 passed, 8 subtests passed**，22.92 秒（`--basetemp=C:/tmp/ff-f2-short-baseline`）。
- RED：先提交 `tests/test_feedback_observation.py` 与受控夹具，移除 `scripts/ff_short_feedback.py` 和 `scripts/fetch_filing.py` 的接线后，收集阶段即 `ModuleNotFoundError: No module named 'ff_short_feedback'`。实现接线后同一文件 **24 passed**（独审后补坏 JSON、v2 gap、v1 错误携带 observation 三例）。RED 证明侧车不是测试自证；业务信封对照另有逐字节断言。

## 证据来源（只读现有 owner 投影）

| 侧车事实 | 现有来源 |
|---|---|
| 业务终态 | v2 `status` + `filing.resolution_outcome`；v1 `capture_ready` + `handle.resolution_envelope.outcome`；v1 `gap`；错误码后附闭集原因（`request_diagnostic` / cause / receipt code） |
| provider 启动 / 计量完整性 | `ff_provider_cause.validated_acquisition_observation`、`validated_acquisition_failure`、`validated_cause`；v1 错误从类型化异常读取同对象 |
| 本地准备未启动 | `ff_local_preparation_observation.validated_local_preparation_observation` |
| 目录阶段无 provider | 与 `ff_job_runner._observation_of` 相同的 `identify/query/local_prepare/resolve` 判定；显式 producer 证据优先 |
| 下载计数 | v2 `downloads` / `filing.download_events`；v1 `downloads` / `resolution_envelope.download_events`；v1 `gap` 按元数据计划记 0 |
| 伴随电话会 | v2 `transcript` 的 `provider_started` / `provider_requests` / `provider_usage_complete`；不借用主财报收据 |

## 关键判定

- **费用维度**：`reuse_only`（非 `latest_as_of`）没有 provider 费用维度，记 `not_applicable`；`latest_as_of` 和 `fetch_if_missing` 有维度。`calls=0` 的启动前拒绝可证零；`downloads=0` 不证明未访问供应商，`latest_as_of` 无原生观察时保持 `unknown`。
- **启动前拒绝**：v2 `fetch_if_missing` 缺 `acquisition_limits` 在 `validate_request` 即被拒，零子进程，`provider-start=not_started`、`provider-usage=known`、`download-receipt=0`。这是合法拒绝，`disposition=expected`；调用方漏带限额的偏差由调用方凭公开 `request_diagnostic` 另发。
- **两范围**：主财报 `provider-usage=known` 与电话会 `transcript-provider-usage=unknown` 分行保留，`step_id` 分别为 `short-filing/<op>` 与 `short-filing/<op>/transcript`，整笔不可读成零。
- **身份**：`operation_id` 每次真实执行新生成；同一 run/attempt 的两次执行靠 `evidence_ref` / `step_id` 区分，run/attempt 继承调用方。重复读取侧车零新增；未重写已写行。
- **单写者**：CLI 读取三个环境量后从自身环境移除，随后启动的 CWP/ET 子进程在夹具中实测 `RESEARCH_FEEDBACK_OUT/RUN_ID/ATTEMPT_ID` 均为空。
- **v1 兼容**：v1 错误/缺口缺少用量字段时记 `unknown`；v1 `gap` 信封本就没有 `calls/downloads`，侧车不补造，下载按缺口合同记 0。
- **写失败**：路径不可写时静默保留业务 stdout/stderr/退出码；测试用目录和不存在父目录两种坏路径对照，均与禁用侧车逐字节一致。

## 真实 CLI 样本

`samples/` 下 6 份 JSONL 由真实 `scripts/fetch_filing.py` 在受控 mock connector 上逐场景执行产出；`samples/manifest.json` 记录请求、退出码、业务摘要、stub 操作序列与调用次数、行数、检查名、证据引用和子进程环境检查。`first_import_rows=27` / `second_import_rows=0` 表示按协议身份 `(run_id, attempt_id, step_id, check_id)` 重复导入零新增。生成步骤与复现片段见 `samples/README.md`。

## 未开问题卡

本轮未发现须在本仓修复的新缺陷。以下两点是已存在的边界观察，不构成本卡修复项：

- v1 `gap` 信封不携带 `calls/downloads`，旧响应无法给出下载计数以外的计量证据；侧车按 `unknown` 处理，符合“未提供字段记 unknown”。
- F4 持久作业路径（`ff_job_runner` → `resolve_filing`）直接调用库入口，不经过短请求 CLI 的 `begin_observation`，其子进程仍会继承调用方的 `RESEARCH_FEEDBACK_OUT`。当前 CWP/ET 不写该协议；若未来它们也具备输出能力，需由 F4/ROOT 决定分配不同路径或清理子进程环境。属 F4 写范围外，记入交接余项。

## 清理

- 测试只用 `--basetemp=C:/tmp/ff-f2-*` 与 pytest `tmp_path`；本轮测试根在收尾时删除。
- 未触碰主工区运行目录、生产配置、密钥、原件和 `.ff_jobs/`。
