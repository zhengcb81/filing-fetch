---
name: repair-filing-fetch-issue
description: 从本仓问题卡或 feedback-observation/1 运行引用出发，复现并修复 filing-fetch 短请求/持久作业的合同偏离。用于判定 FF、CWP、ET 的真实责任，先写 RED，再修共同责任层并用原场景复验。
---
# 修复 filing-fetch 问题

本技能只处理本仓（filing-fetch）能负责的偏离：路由、限额透传、复用/下载分支、重试行为和结果信封。CWP 的验真、目录与 provider 计量，ET 的 provider 调用与费用，分别由原 owner 负责；本仓只消费它们的公开结果和引用。

## 输入

从以下任一入口开始，不要求原始正文、凭据或物理路径：

- 本计划下的问题卡：`docs/plans/<plan>/issues/<issue>.md`。
- 一次真实运行的 `feedback-observation/1` JSONL（短请求为 `ff-short/1/<operation-id>`，持久作业为 `ff-job/1/<owner_job_id>`）。
- ROOT 给的公开复现引用（公司、市场、期次、请求结构、退出码、脱敏信封）。

先确认三件事，再动手：

1. **预期**：请求合同、`filing_intent`、限额、模式（`exact` / `latest_as_of`）和调用入口（`scripts/fetch_filing.py`、`scripts/ff_job.py`）。
2. **实际**：`request-outcome` 的实际词、`provider-start` / `provider-usage` / `download-receipt` 的取值与 `disposition`。
3. **版本与输入来源**：实现 SHA、请求是真实输入还是夹具、部署配置是否被改动。

## 读观察行

短请求侧车每次调用至少两行：`action-started`（带 `terminal_check_id=request-outcome`）和 `request-outcome`。其余为具名检查：

| check_id | expected | actual | 含义 |
|---|---|---|---|
| `request-outcome` | `terminal` | 业务终态词 | `source_candidate/<outcome>`、`capture_ready/<outcome>`、`gap`、`not_found/<reason>`、`request_error/<reason>`、`upstream_error/<reason>`、`fatal` 等；`reason` 来自闭集诊断或 producer 原因码，不是错误正文 |
| `provider-start` | `not_started` | `not_started` / `started` / `unknown` | 只在合同可判定时出现：精确 `reuse_only`，或启动前被拒的 `request_error` |
| `provider-usage` | `accounted` | `known` / `unknown` / `not_applicable` | 费用维度是否已结清；`not_applicable` 表示本次请求没有费用维度 |
| `download-receipt` | `accounted` | `0` / `1` / `unknown` | 下载结果，和费用分开；`0` 不证明未访问供应商 |
| `transcript-provider-usage` | `accounted` | `known` / `unknown` | 伴随电话会自己的范围，`step_id` 以 `/transcript` 结尾 |

`request-outcome` 的 `disposition` 只表示“终态检查是否成立”：已知终态（包括 `upstream_error` / `fatal`）记 `expected`，终态本身未知才记 `unknown`。失败由 `actual` 的具名原因表达，不在这里重复判责。

判定规则：

- 只有 `action-started`、没有 `request-outcome`：终态未知。先查同一请求的本地复用结果，不要直接重跑下载。
- `provider-start` 为 `deviation` 且带 `issue_key=reuse-started-provider`：复用分支启动了 provider，是 FF 路由问题。
- `provider-usage=unknown`：缺原生计量。不要把它记成 0，也不要拿 `downloads=0` 代替。
- `latest_as_of` 的 `downloads=0` 只证明没有下载，不证明没有元数据访问；费用仍看 `provider-usage`。
- 主财报 `known`、伴随电话会 `unknown`：两个范围分别保留，整笔不是零。
- `request_error` 且 `provider-start=not_started`：请求在启动前被合法拒绝。若调用方本应携带限额，由调用方凭公开错误另发偏差；FF 侧保持 `expected`。

## 最小脱敏回放

只用本仓的受控入口和一次性临时目录，不接通真实 provider、不读取原件、不使用生产配置：

```powershell
python -B -m pytest -q -p no:cacheprovider --basetemp=<本轮短临时根> tests/test_feedback_observation.py
```

现有母例（`tests/test_feedback_observation.py` + `tests/fixtures/short_feedback/connector.py`）：

| 场景 | 观察到的合同 |
|---|---|
| `reuse_hit` | 精确本地命中：只跑 `identify` + DB-only `query`，`provider-usage=not_applicable` |
| `query_miss` | 本地 `local_prepare` 后仍缺：`not_found`，查询阶段 `provider_started=false` |
| `latest_reuse` | `latest_as_of` 元数据发现后复用：无原生计量时 `provider-usage=unknown` |
| `download` | 受控首取：`downloaded_new`、`provider-usage=known`、`download-receipt=1`，ensure 恰好一次 |
| `corrupt` | 损坏件：`upstream_error` + `canonical_import_failed`，provider 未启动、零下载，合法拒绝 |
| `zero_companion` | 主财报已知零 + 电话会 `unknown`，两个范围分开 |
| 缺限额 | v2 `fetch_if_missing` 不带 `acquisition_limits`：`request_error` + `request_diagnostic`，零子进程 |

需要新增母例时，扩展 `connector.py` 的 `FF_SHORT_SCENARIO` 分支，不要改生产代码来迎合夹具。

## 责任判定

| 现象 | 首先归属 | 处置 |
|---|---|---|
| 请求字段/限额错误、`allow_download` 与 `filing_intent` 矛盾 | 调用方 | 用公开 `request_error` / `request_diagnostic` 说明；FF 不改语义 |
| 复用分支启动 provider、路由到错误的 ensure/query | filing-fetch | 本仓修路由和测试 |
| 下载计数与业务结果不一致、重试放大请求 | filing-fetch | 本仓修共同责任层 |
| `acquisition_failure` / `acquisition_observation` 缺失或自相矛盾 | company-wiki | 交 ROOT 带公开输入输出给 CWP |
| 电话会 `provider_requests` / `provider_usage_complete` 与 provider 实际不符 | ET | 交 ROOT 带 ET 公开结果 |
| 临时目录、权限、部署配置 | 环境 | 记录条件，不改业务合同 |

外仓原因必须连回原始 `evidence_ref`（`ff-short/1/...` 或 `ff-job/1/...`），本仓不复制对方正文、路径或凭据。

## RED → GREEN

1. 在 `tests/test_feedback_observation.py` 或对应定向文件写 RED：走真实 `main(argv)` / `scripts/fetch_filing.py` 边界，或复用现有夹具入口；断言第一次偏离合同的位置。
2. 先确认 RED 是合同问题，不是夹具问题：同一场景在未改代码的基线上也应失败。
3. 修共同责任层（`scripts/fetch_filing.py`、`scripts/ff_short_feedback.py` 或对应 owner 模块），不修测试来消除 RED。
4. 定向 GREEN 后，用原场景（原请求结构、原退出码、原信封）复验，并跑：
   ```powershell
   python -B -m pytest -q -p no:cacheprovider tests/test_feedback_observation.py tests/test_ff1_envelope_candidates.py tests/test_failure_usage_continuity.py tests/test_m3_acquisition_usage_ff.py tests/test_ff_job_facade.py
   ```
5. 记录修复版本（SHA）、回归用例、消费者待验/已验状态。相同版本、相同输入、同一失败不触发循环重跑；有新证据时用新的 `attempt_id` 关联首笔发生。

## 写回

- 具体缺陷：在本计划 `issues/` 留最小脱敏复现、责任仓、实际修复和复验版本。
- 计划状态：更新本卡 `findings.md` / `progress.md`，写清命令、通过/失败/跳过数和清理结果。
- 跨仓组合、真实 provider 复验和公司池调度交 ROOT；本仓只交公开观察、版本和可复验引用。
