# filing-fetch 全面审查与测试加固 — 实施计划

## 目标
修复审查发现的契约漂移（错误分类、文档、失效测试），并建立覆盖
『A股/港股/美股 × 文档已存在/不存在/部分存在』全场景矩阵的三层测试体系：
mock 单元测试（快）+ 隔离实例真实 E2E（真实 company-wiki 代码/临时状态）+
生产 live 一致性测试（少量）。

## 决策记录（用户已确认）
| # | 决策 | 内容 |
|---|------|------|
| D1 | 错误码契约方向 | 实现对齐 SKILL.md：真正产生 config_error / identity_error / not_found / worker_paused |
| D2 | E2E 基础设施 | 全量真实 company-wiki（真实代码 + 隔离临时实例）；下载场景用真实 StockInfoDLSimple / dayu-agent |
| D3 | Git 基线 | 不提交，v1.2.0 未提交改动与本次修改一并进行 |

## 当前基线状态
- 66 tests pass（60 mock + 6 real-tool，其中 2 个 skip），耗时 ~32s；ruff 0.15.18 clean
- 工作区含未提交 v1.2.0（catalog_locked 重试）；根目录有垃圾文件 `nul`
- 无 pyproject.toml / pytest.ini / coverage 配置；测试用 `python -m unittest discover -s tests`

---

## Phase 1 — 代码契约修复 — 状态：completed

### 1.1 scripts/filing_contracts.py
- [x] `validate_request`：在 unknown-field 检查后新增 `_required_text(request.get("company_query"), "company_query")`
- [x] `validate_request`：market hint 非 None 时必须 ∈ {CN, HK, US}，否则 request_error
- [x] `validate_handle`：新增 request_id 非空文本校验（code=upstream_error，与 handle 其他校验一致）
- [x] 删除死常量 `GAP_RECEIPT_SCHEMA_VERSION`、`DOWNLOAD_AUTHORIZATION_SCHEMA_VERSION`
- [x] 保留 `SUPPORTED_COMPANY_WIKI_CONTRACTS` 并改为 dict（原为 frozenset 不可下标），
  在 1.2 resolve/ensure schema 校验中真正使用（resolve/ensure 分别查表）

### 1.2 scripts/fetch_filing.py
- [x] `_validate_company_wiki_root` + `load_company_wiki_root`：全部 FilingFetchError 加 `code="config_error"`（含 token 替换失败）
- [x] `_resolved_company_identity`：全部 raise 加 `code="identity_error"`（字段空值校验内联化以携带正确 code）
- [x] `_run_company_wiki_json` 非零退出分类扩展：CatalogOperationLockedError → catalog_locked（现有）；
  RuntimeError+"paused" → worker_paused（新增）；其他 → fatal（fail-closed）
- [x] `resolve_filing`：
  - [x] 删除死分支 `if "company_query" not in request` 与恒真 `if "company_query" in request`；
        删除 `_identity_arguments` 中不可达的 entity/security_id 冲突检查
  - [x] `timeout_seconds` 增加 `math.isfinite` 校验（消息改为 "positive and finite"）
  - [x] resolve 响应校验 `payload["schema_version"] == SUPPORTED[...]["resolve_schema_version"]`，否则 upstream_error
  - [x] ensure 响应校验 `resolution["schema_version"] == SUPPORTED[...]["ensure_schema_version"]`，否则 upstream_error
  - [x] "source is not reusable: ..." → `code="not_found"`
  - [x] "did not return exactly one source handle" → `code="upstream_error"`
  - [x] "source lacks capture provenance" → `code="not_found"`（消息保留 missing_capture_fields 细节）
- [x] `main()`：stdin / --request-file 的 JSON 解析失败、非 dict、文件不可读 →
  `FilingFetchError(code="request_error")` → exit 2
- [x] 退出码语义保持不变：FilingFetchError（任何 code）→ 2；意外异常 → 1；成功 → 0

### 1.3 验证
- [x] `python -m unittest discover -s tests` 61 个 mock 测试全绿（含 live 1 个：test_cli_stdin_accepts_utf8_chinese_query）
- [x] `ruff check scripts tests` 通过

### 1.4 计划漂移记录
- 实现中途发现 `SUPPORTED_COMPANY_WIKI_CONTRACTS` 为 frozenset（dict 字面量被转键集）不可下标 → 改为 dict（首次运行 19 个测试 TypeError）
- 现有 17 处 mock 响应补 `"schema_version": "1.0"`（16/24 空格两种缩进各命中一次 replace_all）

---

## Phase 2 — mock 层测试扩充与去重 — 状态：completed

### 2.1 请求校验边界
- [x] test_missing_company_query_is_request_error（含 code 断言）
- [x] test_blank_company_query_is_request_error（`"  "` / `" AMD "`）
- [x] test_invalid_market_hint_is_request_error（`market: "XX"`）
- [x] test_float_fiscal_year_is_request_error（`2026.0`）
- [x] test_non_padded_as_of_date_is_request_error（`"2026-7-18"`）

### 2.2 错误分类
- [x] test_config_errors_carry_config_error_code（缺文件/坏 JSON/缺 source_catalog.yaml/缺目录，逐一断言 code）
- [x] test_identity_failures_carry_identity_error_code（ambiguous / verified=False / active=False / 坏 schema_version / 不支持 market）
- [x] test_missing_source_carries_not_found_code（missing/ambiguous/identity_conflict）
- [x] test_ensure_missing_carries_not_found_code
- [x] test_capture_not_ready_carries_not_found_code（消息含字段名 https_url/capture_trace）
- [x] test_multi_match_carries_upstream_error_code
- [x] test_worker_paused_maps_to_retryable_worker_paused（code/retryable=True/不自动重试 call_count==2/exit 2）
- [x] test_resolve_schema_version_mismatch_is_upstream_error
- [x] test_ensure_resolution_schema_version_mismatch_is_upstream_error

### 2.3 截止时间与超时传播
- [x] test_timeout_seconds_must_be_finite（inf / nan → ValueError）
- [x] test_subprocess_receives_remaining_deadline（timeout kwarg == 剩余预算 30.0）
- [x] test_deadline_exhausted_before_resolve_is_upstream_error（subprocess 不被调用）
- [x] test_catalog_locked_until_deadline_is_upstream_error（恒 locked → sleep(5)+sleep(3) 后耗尽）
- [x] test_worker_paused_is_not_auto_retried（sleep 不被调用）

### 2.4 handle 边界
- [x] test_published_date_equal_as_of_date_is_accepted
- [x] test_relative_canonical_path_is_resolved_against_wiki_root
- [x] test_bool_byte_size_is_rejected
- [x] test_single_non_dict_match_is_rejected（code=upstream_error）
- [x] test_missing_request_id_in_resolution_is_rejected（配合 1.1 新校验，code=upstream_error）
- [x] test_handle_extra_fields_are_tolerated

### 2.5 CLI main() 边界
- [x] test_main_request_file_happy_path（stdin 被忽略）
- [x] test_main_request_file_invalid_json_is_request_error_exit_2
- [x] test_main_empty_stdin_is_request_error_exit_2
- [x] test_main_allow_download_flag_builds_ensure_command

### 2.6 去重与改名
- [x] 合并 test_identity_response_not_resolved_is_rejected → 删除；保留测试补 code=identity_error 断言
- [x] 合并 test_upstream_unknown_schema_fails_closed → 删除
- [x] 改名 test_main_fatal_error_exit_code → test_main_cli_accepts_fractional_timeout

### 2.7 结果
- 61 → 88 tests 全绿；ruff clean

---

## Phase 3 — 隔离实例真实 E2E — 状态：completed

### 3.1 fixture 构造器 IsolatedWiki
- [x] tests/e2e_support/isolated_wiki.py：布局按计划；**补充 company_wiki.json**（filing-fetch 的
  --config 是 JSON 启动配置，非 source_catalog.yaml——首次运行 13 个 config_error 后修正）
- [x] source_acquisition.yaml 用 **no-op 适配器**（输出 schema_version/status/adapter/candidates 信封；
  第 2 次失败 adpater envelope 缺 schema_version/status，第 3 次缺 adapter 身份——逐层对齐 json_command_v1 契约）
- [x] 种子：CN 宁德时代 / US Apple Inc / HK 腾讯 → **HK 目标目录改为 canonical"騰訊控股"**
  （生产目录"腾讯"简体 vs canonical 繁体不匹配 = D15 观测；旧 sidecar 无 company_name，
  目录名兜底不成立 → 场景 3 改为 canonical 目录下验证旧 sidecar https→capture_ready）

### 3.2 场景矩阵（13/13 通过，两轮稳定）
| # | 结果 | 备注 |
|---|------|------|
| 1 | ✓ | canonical_path 断言用 Path.parts（Windows 反斜杠）|
| 2 | ✓ | sidecar company_name "Apple Inc." 兜底命中（非 security_id——实体匹配只比较 canonical_name）|
| 3 | ✓ | 旧 sidecar https → scan 补 hash/capture_trace → capture_ready reuse |
| 4 | ✓ | not_found；文件集不变 |
| 5 | ✓ | fiscal_year 1999 → not_found |
| 6 | ✓ | as_of 2025-01-01 < published 2025-03-14 → future_matches → not_found |
| 7 | ✓ | **计划漂移**：期望"消息含 missing_capture_fields"不可实现——上游 Phase 16.2 静默丢弃
     非 capture_ready handle，字段细节不传播；钉住 exit 2 not_found，细节由 mock 测试
     test_capture_not_ready_carries_not_found_code 覆盖 |
| 8 | ✓ | 同长字节篡改 → upstream_error，消息含 snapshot_sha256 |
| 9 | ✓ | 万科 → identity_error（预验证 ambiguous 钉住）|
| 10 | ✓ | 无 master → fatal（钉住映射）；断言在 payload.error（identify 的 stderr 详情被 filing-fetch
     折进错误消息，不在自身 stderr）|
| 11 | ✓ | **锁机制修正**：resolve 不抢锁；ensure 的 acquisition-journal 记录（任何 outcome）抢锁 →
     场景走 ensure+已存在文档 → 一轮 5s 退避后成功；elapsed ≥ 5 断言 |
| 12 | ✓ | **代码修复**：subprocess TimeoutExpired 原映射 fatal → 改 upstream_error（attempt 超预算）
     （fetch_filing.py + mock 测试 test_upstream_subprocess_timeout_is_upstream_error）|
| 13 | ✓ | paused→worker_paused retryable；enabled→no-op 适配器 → not_found（无网络）|

### 3.4 执行细节
- [x] 只读共享实例 / 变异各自实例；总耗时 ~55s
- [x] tearDown 清理加重试（deadline 杀死的 ensure CLI 可能遗留 cwd=<tmp> 的 PowerShell 孙进程
  → WinError 32；_cleanup_temporary 6 次重试，注释说明机制）

---

## Phase 4 — 真实下载 E2E（opt-in）— 状态：completed（HK 环境阻断）

新建 tests/test_e2e_download.py。门控：
`@unittest.skipUnless(os.environ.get("FILING_FETCH_E2E_DOWNLOAD") == "1")` + 工具路径存在检查。
acquisition yaml 用**绝对 USER_PROFILE 路径**指向生产工具（fixture 的 PROJECT_ROOT 是临时目录，
生产的相对 ../ 记号会解析错）。

- [x] test_download_cn_annual_report：**宁德时代** FY2024（茅台 FY2024 在 cninfo 有两个候选——
  中文+英文版 → 协调器合理返回 AMBIGUOUS → not_found，已实测验证并注释）→ exit 0、文件落位、
  sidecar 四条件（https_url/filing_date/content_sha256/retrieved_at——注意 sidecar 无 published_date
  顶层字段，resolver 从 manifest 派生）、二次运行 reuse（mtime 不变 + journal 无第二次 downloaded_new）
- [x] test_download_us_annual_report：AMD 10-K（dayu-sec）→ 全链路 21.7s 通过
- [x] test_download_hk_annual_report：**已跑通（20.3s）**。根因排查：
  1) 首次"0xC0000005 崩溃"是内存压力下的间歇事件（孤儿进程+生产 worker+Playwright 并发；
     机器清理后未再出现）；2) 真正根因：**fiscal_year 不匹配**——dayu CLI 按标题推断财年，
     下载的是最新年报"2025 年報"（FY2025，filed 2026-04-09），请求 2024 被
     `_candidate_from_meta` 年份过滤永远拒绝 → discover 轮询到截止耗尽；
     适配器又强制要求 fiscal_year → 请求改为 **fiscal_year 2025** 后全链路通过
     （下载→落位→sidecar 四条件→幂等 reuse→staging 无残留）
- [x] test_download_rejects_corrupted_local_copy：**计划漂移**——上游无 quarantine-修复闭环
  （quarantine 仅存在于 scan 观察错误路径）；钉住现实：reuse-only 与 --allow-download 均
  upstream_error（永不提供损坏字节），journal 无 downloaded_new（REUSED 记录存在但无下载）
- [x] 每用例后置断言：无 operation.lock；staging 无残留字节（writer 会留下空 request 目录，
  属上游行为，断言放宽为"无文件"）

---

## Phase 5 — live 一致性测试重写 — 状态：completed

重写 tests/test_real_tool_conformance.py（7 测试，实测 ~40s ≤ 60s）：
- [x] root 改为 `load_company_wiki_root()` 动态读取
- [x] `identify --query`（CN 贵州茅台 / HK 腾讯 / US AMD）：schema 1.0 / resolved / market / verified / active
- [x] ambiguous：identify --query 万科 → 退出 0、status=ambiguous、resolved=null、candidates 非空
- [x] ensure --entity：顶层 resolution 嵌套键、resolution.status=missing（**计划漂移**：ensure 写一条
  append-only journal 记录（含无下载的 REUSED/MISSING 路径），这是本套件唯一的写操作；
  AMD 可能已在生产存在 → 改用贵州茅台 quarterly（保证 missing））
- [x] 生产 round-trip：DB 动态定位宁德时代 FY2024 annual（capture_ready 校验），filing-fetch 真实子进程
  reuse-only → exit 0（注意：使用 filing-fetch 默认配置，生产 wiki 无 company_wiki.json——首次失败修正）
- [x] 确定性测试（identify 两次全等）
- [x] ensure 测试对生产 catalog 锁竞争做 3×5s 重试，仍锁则 skip（生产 worker 扫描窗口可能 >15s，属设计行为）

---

## Phase 6 — 文档与仓库卫生 — 状态：completed

- [x] SKILL.md：版本号 v1.3.0；状态码表补 `worker_paused` 行；退出码表澄清
  （2 = 所有结构化错误，1 = 仅未预期 fatal）；落盘路径修正为映射子目录；
  exchange hint 注明仅 identity 阶段；frontmatter description 同步路径
- [x] CHANGELOG.md：v1.3.0 条目（错误分类、schema 校验、请求校验收紧、worker_paused、
  超时分类、main 解析、三层测试体系）
- [x] `nul` 已不存在（计划基线过时，标记已无效）；.gitignore 增加 `nul` 防复发
- [x] pyproject.toml：ruff（line-length=100 / target-version=py313）、
  coverage（source=scripts，omit tests，fail_under=90）
- [x] 全量验证：ruff clean；`python -m unittest discover -s tests` → **113 tests OK（5 skip）**；
  coverage **96%**（fetch_filing 95% / filing_contracts 97%，≥ 90% 目标）
- [x] 计划漂移检查：见各阶段 §计划漂移/漂移记录条目（nul 消失、SUPPORTED_CONTRACTS frozenset、
  锁机制 resolve 不锁、场景 7 字段细节、HK 环境阻断、quarantine 无修复闭环、茅台双候选、
  sidecar 无 published_date 顶层字段、生产无 company_wiki.json）

---

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| SUPPORTED_COMPANY_WIKI_CONTRACTS 不可下标（frozenset）| 1 | 改为 dict（Phase 1，19 测试 TypeError）|
| 现有 mock 响应缺 schema_version | 1 | 16/24 空格两种缩进 replace_all 补 "1.0"（Phase 1）|
| 测试文件被误报"modified since read" | 1 | 重新 Read 后编辑（Phase 1）|
| 隔离实例 13 个 config_error | 1 | fixture 缺 company_wiki.json（filing-fetch --config 是 JSON 启动配置）（Phase 3）|
| no-op 适配器 envelope 不符 | 1-3 | 逐层补齐 schema_version/status → adapter 身份 → candidates（Phase 3）|
| HK 旧 sidecar 实体不匹配 → not_found | 1 | 目标目录改为 canonical"騰訊控股"（D15 观测，Phase 3）|
| 场景 12 间歇 fatal（TimeoutExpired）| 1 | 代码修复：subprocess 超时 → upstream_error（Phase 3）|
| tearDown WinError 32 | 1 | 清理加重试（deadline 杀 CLI 遗留 cwd=<tmp> 的 PowerShell 孙进程）（Phase 3）|
| 场景 11 elapsed 断言过紧 | 1 | ≥ 10.0 → ≥ 5.0（实测单轮退避 9.6s 成功）（Phase 3）|
| 茅台 FY2024 双候选 → AMBIGUOUS | 1 | CN 下载改用宁德时代（Phase 4）|
| sidecar 断言 published_date 不存在 | 1 | 改断言 filing_date（manifest 派生 published_date）（Phase 4）|
| staging 断言过严 | 1 | writer 留空 request 目录 → 断言无残留字节（Phase 4）|
| corrupted 断言 journal 非空 | 1 | REUSED 也记录 journal → 断言无 downloaded_new（Phase 4）|
| round-trip --config 指向生产 company_wiki.json | 1 | 用 filing-fetch 默认配置（生产无此文件）（Phase 5）|
| HK 下载失败（0xC0000005 + 900s 超时）| 3 | 诊断链：内存压力间歇崩溃 → 孤儿进程清理 → **根因=fiscal_year 2024 与 dayu 标题推断 2025 不匹配**，适配器年份过滤永远拒绝 → 改 fiscal_year 2025 通过（Phase 4）|
