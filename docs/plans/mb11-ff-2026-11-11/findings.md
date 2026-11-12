# MB-FF 调查与发现

基线 `ac798a250b2310e0c2714053b08246ad94fffd0c`。以下均为读码/只读核对结果，不是"已通过"声明。

## F1 实际交付 runtime 清单（活动入口 / 逻辑模块 / 公开面 / 状态 owner / 依赖方向）

canonical 安装器 `tools/sync_installs_b3.py` 只安装 `SKILL.md`、`CHANGELOG.md`、`references/`、`scripts/`、`config/company_wiki.json`（`ROOT_FILES`/`ROOT_DIRS`/`CONFIG_FILES`，:33-35）；`tools/`、`tests/` 不进入安装根。实际安装根入口为 `scripts/*.py` 绝对路径 + 空 cwd。

| 分类 | 路径 | 公开面 / 职责 | 状态 owner | 依赖方向 |
|---|---|---|---|---|
| 活动 CLI | `scripts/fetch_filing.py` | `filing-fetch`：`--config/--request-file/--timeout-seconds/--source-ref-v2/--debug`；请求 `filing-request/…`，v2 结果 `filing-response/2`（`ff_v2_envelope.py`） | 无持久状态；`stats` 每请求内存计数 | → `ff_configuration`/`ff_company_wiki_connection`/`ff_process_transport`（公开 subprocess） |
| 活动 CLI | `scripts/fetch_statements.py` | `fetch-statements`：`--config/--request-file/--timeout-seconds/--pretty`；`financial-statements-request/1` ↔ `financial-statements-response/1` | 无；CWP 三表/快照归 CWP | → `ff_financial_statements` → 同上 |
| 活动 CLI | `scripts/ff_job.py` | `ff-job/1`：`submit\|run\|get_status\|allowed_actions\|act\|list_jobs`，`--jobs-dir`；注释明确"No request carries paths, command strings, or credentials" | `.ff_jobs/`（FF 自有作业账本） | → `ff_job_store`/`ff_job_runner` → `fetch_filing.resolve_filing` |
| 逻辑：连接 | `ff_configuration.py` / `ff_company_wiki_connection.py` | `load_connection_root`；`WikiConnection(cwd, commands, acquisition_config)`；`OPERATIONS` 六全集；`command_for`/`connection_cwd`/`connection_environment`/`acquisition_arguments` | 无；配置只读 | 仅部署适配层知道 legacy `company_wiki.source_catalog.*` 布局 |
| 逻辑：请求契约 | `filing_contracts.py`、`ff_source_ref.py`、`ff_source_candidate.py`、`ff_source_failure.py`、`ff_v2_envelope.py`、`ff_provider_cause.py`、`et_v2_contract.py` | 版本化 request/reference/candidate/error/usage DTO 与校验 | 无 | 不导入 provider/storage，不读盘 |
| 逻辑：进程 | `ff_process_transport.py`、`ff_process_tree.py` | 唯一 `subprocess.Popen(shell=False)` 与 bounded JSON/字节读取、进程树回收 | 无 | 只接受显式 argv/cwd/env |
| 逻辑：复用/本地准备 | `ff_local_source_prepare.py`、`ff_local_preparation_observation.py`、`ff_source_ref.py` | `local-source-prepare-request/1` ↔ `local-source-prepare/1` 收据 | 无 | 只通过 `command_for(root,"local_prepare")` |
| 逻辑：transcript | `transcript_tool_transport.py`、`transcript_companion.py`、`transcript_reuse_selection.py` | ET `earnings-transcript-result/2` + `earnings-retrieval-usage/1`；CWP `company-wiki-transcript-import-request/2` ↔ `…-response/3`；verified open receipt 2.1 | 用量快照在单次 transport 实例内（`_last_provider_usage`） | ET 命令与 CWP 六 operation 分离；CWP 负责入库/验真 |
| 逻辑：三表 | `ff_financial_statements.py` | 请求白名单 13 字段（:51-55，无任何命令/路径字段），只经 `command_for(root,"financial_statements")` | 无 | 不导入 `company_wiki`/`httpx`/`sqlite3`（`test_layer_boundary.py` 有 AST 守卫） |
| 逻辑：job | `ff_job.py`/`ff_job_contracts.py`/`ff_job_runner.py`/`ff_job_store.py` | ff-job/1、幂等、unknown→reconcile、spend evidence | `.ff_jobs/`（9 个业务状态路径） | 不复用 CWP acquisition journal |
| 状态/配置 | `config/company_wiki.json`（生产，本卡不改）、`config/FMP_API_KEY.txt`（凭据，不读不复制）、`.mimosa/`（工具状态）、`.workbuddy-ai/memory/`（笔记） | 部署配置/凭据/工具私有状态 | 各自 owner | 测试必须显式注入临时 config |
| 兼容（保留，不重写） | `fetch_filing.resolve_filing` 的 `pause_worker`/`worker_*` kwargs、`company_wiki_root` legacy `Path`、`ff_configuration` 旧 `company_wiki_root` 配置、v1 `--authorization` binding-file、`transcript_tool` 显式 `Path`/`EARNINGS_TRANSCRIPTS_TOOL`/config `earnings_transcripts_tool` | 旧 CLI/wire 与部署位置表达 | — | 兼容适配集中在 `ff_company_wiki_connection.py`/`ff_configuration.py` |
| 已退休（不默认打包/不调用） | CWP worker pause-around 编排、`codex/transcript-companion` 猜目录原型、`codex/ff-job-facade-01` 旧 7 cherry、旧 B34 分支 `53285c2`、W06/W07 旧完成声明 | 历史出处见 `inputs/a0-archive/` | — | 不因"整理"重新引入第二套实现 |

依赖方向结论：业务层 → 公开 `WikiConnection`/typed DTO → bounded subprocess；CWP/ET/SID 的源码目录、DB、provider SDK 都只在子进程侧，不在 FF import 图内。缺口是"证明"与"一次请求的连接注入"，不是已发现跨仓私有调用。

## F2 与 ACQ-S1/S2/T1 的对应

- ACQ-S1（编排大文件混合 CLI/部署/进程）：结构缺口，本卡不整体搬迁；用隔离测试证明现有接缝足够，避免为框架整齐改写。
- ACQ-S2：ET launch 仍是 `.py` 路径 + FF `sys.executable`（`transcript_tool_transport.py:717-740`，cwd = tool.parent）；`resolve_filing` 与 `complete_filing_v2._resolve_v2_companion` **各自**调用 `load_company_wiki_root`（:1324、:1647），一次 v2 带 companion 的请求会解析两次连接、得到两个 `WikiConnection` 对象。这是"一次请求配置归属"的真实可测风险（结构缺口，尚非业务失败）。`ff_financial_statements.fetch_statements:161-163` 在 `--config` 缺省时读生产 `config/company_wiki.json`。
- ACQ-T1：`test_decoupled_connection.py` 只在映射/缺项层枚举六 operation，且第 3 例 monkeypatch 当前进程私有方法；没有"真实 CLI 子进程 + 六 operation 各自命令 + 无邻仓环境"的证明。

## F3 A/B 阶段 RED / GREEN 记录

测试夹具：`tests/fixtures/public_operation_isolation/{independent_service.py,transcript_tool.py}`。它们是公开 wire 的替身，不是 CWP/ET 实现；测试从空 cwd 启动真实 `fetch_filing.py` / `fetch_statements.py` / `ff_job.py`，配置只给显式 fixture command，环境移除 `PYTHONPATH`/`EARNINGS_TRANSCRIPTS_TOOL`/`FMP_API_KEY*`。

| 行为 | 初始结果 | 根因 / 处理 | 证据 |
|---|---|---|---|
| 六 operation 各自只走自己的 command；query hit 不启动 provider/ensure；miss→prepare→query 最多一次；单次 ensure；job reuse 不重下 | GREEN（无需改） | 现有 `WikiConnection.command_for` + `_run_bounded_json` 已满足；`NO_CHANGE_PROVEN` | `a1-tests.log` 18 passed；`a2/a3-tests.log` |
| statements 只走 `financial_statements`；complete/partial/not_found/unavailable/request_error/bad-version 语义；16KB 诊断不遮 stdout | GREEN（无需改） | `ff_financial_statements` 只调公开 command；`_valid_error_envelope` 透传；`ff_process_transport` 有界 stderr | `a3-tests.log` |
| ET 独立 command/interpreter/cwd；legacy `.py` 路径兼容；import 失败保留已知 usage；unknown 不当零；坏 stdout 不触发 import | GREEN（无需改） | `transcript_tool_transport` 用 `sys.executable + tool path`，cwd=tool.parent；`_last_provider_usage` 在失败投影中保留 | `a3-tests.log` |
| 业务请求不能携带任意命令字段 | GREEN（无需改） | `filing_contracts.validate_request` / `ff_financial_statements.validate_request` / `ff_job_contracts.validate_submit_body` 白名单拒绝 | `a3-tests.log` |
| 一次请求只解析一次 deployment config | **RED**：CLI 带 companion 时 `load_connection_root` 被调用 2 次（filing 一次、companion 一次） | 新增纯值 `RequestContext`；`fetch_filing.main` 在 composition root 解析一次并注入 `resolve_filing`/`complete_filing_v2`；`ff_job_runner._run_filing_engine` 同步接线。默认参数保留旧 library 行为 | `a1-tests.log` 失败断言 `config loaded 2 times`；`a2-tests.log` 20 passed |

代码改动（最终）：

- `scripts/ff_request_context.py`（新增）：`RequestContext(config_path, connection)` 纯值。
- `scripts/fetch_filing.py`：`resolve_filing` 增加可选 `request_context` / `context_out`；解析连接时生成一个 `RequestContext` 并通过 `context_out` 交给 composition root；`complete_filing_v2` / `_resolve_v2_companion` 增加可选 `request_context`，有则复用同一 connection，无则保持旧加载路径。`main` 用 `context_out` 把同一 context 传给 companion，不提前读配置（保留 FC-802 patched-resolve 行为）。
- `tools/ci_tests.py`：登记新增隔离测试与 statements 三个测试。

`scripts/ff_job_runner.py` 未改（不在本卡写集合）。其 `_run_filing_engine` 对不带 companion 的作业只解析一次；若作业携带 companion，仍走 library fallback 再解析一次同一 config，得到相等的 `WikiConnection`（不是不同连接）。列为 ROOT 后续可选接线项，不作为本卡 RED。

公开 CLI/wire 未变：未新增/删除参数，未改 request/response schema，未改六 operation 名称，未新增业务请求字段。

## F4 公开协议

当前 CLI 参数、request/response schema、六 operation 名称、旧配置字段一律不改。若确需新增部署配置字段，须把失败例与最小兼容方案写入本 PWF 并交 ROOT 协调；业务请求中**不新增任意命令执行字段**。

## F5 范围外发现

（实施时补；交 ROOT，不冒称全局通过。）
