# Findings — W06-FF-MATRIX

## 任务理解
- 建 `tools/offline_contract_matrix/` 手动离线跨仓套件，证明真三层链 A：FF fetch_filing.py 公开入口 → EarningsTranscriptsTransport → ET transcript_tool.main → 真实 retrieval supervisor/worker/transcript_api（只换 worker HTTP 用既有 private launcher）→ FF 真实 import → CWP 原文注册 → SourceVersionReader.open_version 实读 → 再次 FF 命中。
- 报告 schema `ff-et-cwp-offline-matrix/1`，逐 case 列 declared/observed layer、实际模块/HEAD/SHA、request/response/receipt refs、provider counters、下载与 translation 次数、expected/actual/PASS|FAIL|NOT_RUN、scope、恢复信息。

## 环境事实
- worktree: .../w06/ff-contract-matrix，分支 codex/w06-ff-contract-matrix @ FF 08ec85b。
- 三仓固定 SHA：FF 08ec85b / CWP 01ea86a3 / ET c91f5f54。

## FF 关键接口 (scripts/fetch_filing.py)
- 入口 `filing-fetch`，argv：`--config --request-file --timeout-seconds --allow-download --debug --source-ref-v2`（+惰性 --no-pause-worker 等）。请求 JSON on stdin 或 --request-file。
- config `company_wiki.json`：`{"schema_version":"1.0","company_wiki_root":<abs>,opt "fmp_api_key_file","earnings_transcripts_tool"}`。**禁止 allowed_handle_roots**（fail-closed）。`company_wiki_root` 必含 `config/source_catalog.yaml`（_validate_company_wiki_root）。token 仅 ${SKILL_ROOT}/${USER_PROFILE}。
- 请求 schema 1.1/1.2/2.0。`filing_intent`=reuse_only|fetch_if_missing；`mode`=exact|latest_as_of（exact 要 fiscal_year）。`acquisition_limits`={max_bytes,timeout_seconds,max_cost_usd 十进制串}。`companion_transcript`={intent,fiscal_year,fiscal_quarter,provider,acquisition_limits}。
- 顶层响应 envelope（v2, ff_v2_envelope）：schema_version(2.0), status, request_period{mode,fiscal_year,fiscal_period,as_of_date}, filing, transcript, calls, downloads [,acquisition_observation]。filing: {status, source_ref, byte_verification, document_kind, fiscal_year, fiscal_period, resolution_outcome, download_events}。source_ref={schema_version,document_id,source_id,content_sha256,byte_size,mime_type}。
- CWP 全 subprocess：`python -m company_wiki.source_catalog.cli --config <root>/config/source_catalog.yaml` cwd=root PYTHONUTF8=1。identify/query(source_query_cli)/ensure/resolve/local_prepare(local_prepare_cli)。读回经 `source_reader_cli --purpose preview`。
- 传输 `EarningsTranscriptsTransport`（scripts/transcript_tool_transport.py）：ctor(wiki_root, transcript_tool, config_path, fmp_api_key_file, deadline)。lookup_exact/acquire_exact。ET 子进程 argv：`[sys.executable, str(transcript_tool), "--request-stdin","--include-source-payload","--report-usage"]` stdin=earnings-transcript-request/1。之后 transcript_import_cli 导入 + source_reader_cli verified open + SHA/字节校验。
- 文档种类：FF 侧 free text，映射交给 CWP。transcript 固定 document_kind=investor_call_transcript。

## ET 关键接口 (earnings-transcripts @ c91f5f54)
- 入口 `transcript_tool.py:main(argv, *, _session_factory, _provider_settings, _retrieval_launcher, _retrieval_spec, _retrieval_temp_root)`。
- CLI flags：`--request-stdin --capabilities --report-usage --operation{fetch,discover,fetch-candidate} --allow-download --include-source-payload`。
- **private launcher seam**：`_retrieval_launcher="module:attribute"` 写入 worker 内部 envelope；worker 用 importlib import。factory 契约 `factory(spec:dict, context:dict)->session-like`，context={"workdir"}；返回 duck-type requests.Session（.headers/.get(url,**kw)/.close()），response duck-type requests.Response（.url/.status_code/.headers/.iter_content/.close()）。规范 fake：`tests.test_retrieval_runtime:build_fake_session` + `fake_spec(responses, calls_file=)`；FakeResponse(url,payload,status_code=200,final_url,content_type)。
- **跨仓代理现成样板** `tests/request_budget_cli_proxy.py`：首 argv=fixture JSON，其余转发 transcript_tool.main(_retrieval_launcher=LAUNCHER,...)，用 patch.dict 设 FMP_API_KEY。子进程 PYTHONPATH 传播（env=os.environ.copy()）。
- stderr usage receipt `earnings-retrieval-usage/1`：{schema_version,request_id,usage_complete,usage:{requests_used,response_bytes_used,exhausted}|null}。**未知=null 不为 0**。
- canonicalization：`content=raw.replace("\r\n","\n").replace("\r","\n").strip()`。SHA：provider_payload_sha256(原) + canonical_content_sha256。
- TranslatorFactory.create 不得构造（forbid_translator）；translation 不在 retrieval 路径。
- FMP URL 固定：`https://financialmodelingprep.com/stable/earning-call-transcript`。ET 错误码：provider_credentials_missing|entitlement_required(402)|cost_unknown|http_429|byte_limit|...。

## CWP 关键接口 (company-wiki @ 01ea86a3)
- `SourceVersionReader.open_version(ref, *, purpose="filing_reuse", expected_read_policy_sha256=None)->VerifiedContent(.data bytes)`。verify_version 只回 receipt。purpose∈{preview,filing_reuse,source_export,narrative_derivation}。每次调用重验真，不信任旧 buffer。
- SourceRef frozen dataclass：document_id,source_id,content_sha256,byte_size,mime_type,schema_version("2.0")，恰好 6 字段。
- config 是 YAML `source_catalog.yaml`，`load_catalog_config(path, project_root=None)`。必填 schema_version("1.0")/catalog_dir/roots。roots[i]：root_id,path,kind(company_raw|directory|dayu_portfolio),priority,adapter_id,...。project_root=config_path.parents[1]。**没有 load_company_wiki_root/company_wiki.json**（那是 FF 侧）。
- 注册：`SourceCatalog.register_sources(root_id=, relative_paths=)`；CanonicalSourceWriter.import_staged/import_original_staged；transcript 经 `import_transcript_tool_result`。
- transcript_import_cli：`python -m company_wiki.source_catalog.transcript_import_cli --wiki-root <root>` stdin=company-wiki-transcript-import-request/2。
- source_reader_cli：`--config --document-id --source-id --content-sha256 --purpose`→stdout bytes+stderr receipt。
- document_kinds（SIDECAR_KIND_MAP）：annual_report/semi_annual_report/quarterly_report/regulatory_filing/broker_research/investor_relations/investor_call_transcript/prospectus/equity_offering_prospectus/convertible_bond_prospectus/news。PERIODIC=annual/semi/quarterly/regulatory/investor_call_transcript。
- 存储 SQLite catalog_dir/catalog.sqlite3。隔离：scratch source_catalog.yaml catalog_dir 在 scratch、roots.path 在 scratch，--config 指 scratch，cwd=scratch，PYTHONPATH=CWP src。

## CWP 采集适配器契约（财报 fixture provider 注入点）
- `source_acquisition.yaml` schema **1.1**，恰好 4 顶层键 {schema_version,staging_root,timeout_seconds,adapters}；adapters 恰含 {cn,hk,us}。adapter entry：name/version/interface/project_root/config_root/command[/supports_acquisition_budget]。interface∈{json_command_v1,dayu_cli_v1,dayu_sdk_bounded_v1}；json_command_v1 与 dayu_sdk_bounded_v1 都走 JsonCommandAdapter，config_root 必 null。
- command argv：`<cmd...> discover` 或 `<cmd...> fetch --staging-dir <ABS dir>`。stdin=canonical JSON（sort_keys,compact）。stdout 单 JSON 对象。
- discover 响应：`{"schema_version":"1.0","status":"ok","adapter":{name,version 恰等配置},"candidates":[candidate...]}`。candidate 必填 candidate_id/provider/provider_document_id/market/title/source_url(https)/document_kind/filing_date(YYYY-MM-DD)/fiscal_year(1900-2200)；可选 form_type/fiscal_period/language/amended/etag/last_modified/remote_size。entity 忽略（用 request.entity）。
- fetch 响应：同 envelope + `"receipt":{candidate_id,provider,provider_document_id,source_url,staged_path,content_sha256,byte_size,mime_type,retrieved_at(YYYY-MM-DDTHH:MM:SSZ),http_status(2xx),adapter_name,adapter_version(semver),etag,last_modified}`。adapter 自己把字节写进 `--staging-dir`，报绝对 staged_path。
- bounded（CLI --allow-download 恒 bounded）需 `acquisition_usage`=`{"schema_version":"1.0","response_bytes":int,"cost_usd":"str"}`（恰 3 键）；fetch 的 response_bytes≥byte_size。
- import_staged 校验：staged 在 staging_root 下、stat_size==byte_size、sha256==content_sha256、%PDF- 若 mime=pdf、receipt↔candidate 绑定字段相等。目标路径 `<company_raw_root>/<entity>/raw/<kind-subdir>/<sha256><ext>+<.source.json>`。kind-subdir：annual_report→financial_reports/annual，investor_call_transcript→investor_relations/transcripts 等。
- ensure 流程：resolve(REUSED 命中即回，不跑 adapter)→(allow_download? adapter.discover→1 candidate→SELECTED→adapter.fetch→import_staged→IMPORTED/DEDUPLICATED)；reuse_only 不带 --allow-download，adapter 不 spawn（MISSING/REUSED）。CLI --allow-download 必带三 --max-download-*，触发 bounded。
- 现成 fixture 样板：CWP tests/contract/test_source_catalog_cn_stockinfo_e2e.py `_FAKE_BYD_FULL_CLI`（discover+fetch+staged %PDF+receipt）。fake adapter command=["${PYTHON_EXECUTABLE}","-c",<script>] 或指向我写的 adapter 脚本。
- worker config `source_catalog_worker.yaml` ensure **不必需**；source_acquisition.yaml+source_catalog.yaml 必需。staging_root 不得与原始 root 重叠。

## root_id
- 用 local_company/external_dayu/external_dropbox（简单标识）。product 侧 root_id 只需非空唯一。path 用含空格/中文目录（斜杠属 path 不属 id）。

## 架构定稿（链 A 真三层 + 矩阵）
- **代码绑定**：runner 收 `--cwp-project`/`--et-project` 显式码根，经 child PYTHONPATH 只读绑定（不 snapshot 除非需）。child 先 import 打印 company_wiki.__file__ 验码根/SHA。数据根=owned fixture root（company_wiki_root），绝不把 --cwp-project 当数据根。
- **链 A（transcript 三层）**：FF v2 请求 = 本地命中 filing（seeded annual）+ companion_transcript(fetch_if_missing, exact FY/Q)。FF config `earnings_transcripts_tool`→我的 `et_transcript_proxy.py`（test-proxy）。proxy 读 stdin 请求→造合成 FMP 响应（原语言 content，CRLF→LF，记 provider_payload/canonical 两 SHA）→调真 `transcript_tool.main(_retrieval_launcher="w06_fake_provider:build_fake_session", _retrieval_spec=..., _retrieval_temp_root=scratch)`。真 supervisor/worker/transcript_api 子进程跑，仅 worker HTTP=fake（经既有 private launcher seam）。FF 真 import(transcript_import_cli)→CWP 注册→source_reader_cli open_version 实读→再次 FF 命中(0 请求)。
- **fake launcher**=`tools/offline_contract_matrix/w06_fake_provider.py`（stdlib-only duck-type Session/Response，读 spec["responses"]，写 spec["calls_file"]），留测试代理层。worker 经 PYTHONPATH import 它。
- **财报 fixture provider**=`tools/offline_contract_matrix/fixture_provider_adapter.py`（json_command_v1），discover 返合成 candidate、fetch 写合成 valid PDF/HTML/TXT 进 staging+receipt。真 CWP ensure/import。cn=json_command_v1；hk/us 用 dayu_sdk_bounded_v1+supports_acquisition_budget（走 JsonCommandAdapter）。
- **合成原件**：真实合法小 PDF（完整 xref/trailer）/HTML/TXT，元数据 synthetic；绝不 `%PDF ...` 假占位。
- **计数**：provider 请求/下载/translation。第一次 fetch_if_missing 1 fixture provider request、第二次 0。translation=0（不构造 TranslatorFactory）。真实收费 0；fixture requests 单列不入母账。
- **report** `ff-et-cwp-offline-matrix/1`：逐 case declared/observed layer、实际模块/HEAD/SHA、request/response/receipt refs、provider counters、下载/translation、expected/actual/PASS|FAIL|NOT_RUN、scope、恢复信息。
- **oracle 失败向量 RED**（Node A）：整层fake却写real、第二次仍下载、少ET receipt、错cutoff、假0cost、未恢复scratch。oracle 检测这些；stub 先存行为 RED。

## 错误/陷阱
- FF config 禁 allowed_handle_roots；company_wiki_root 必含 config/source_catalog.yaml。
- `--allow-download` 仅 v1；v2 用 filing_intent。exact 要 fiscal_year；companion 要 fiscal_year+fiscal_quarter（FY-only 不猜 Q4→period_unresolved/exact_fy_q_required）。
- source_acquisition schema 1.1（非1.0）；adapter.version 必 semver；retrieved_at 必 YYYY-MM-DDTHH:MM:SSZ。
- bounded adapter fetch 必 charge response_bytes≥byte_size。
- usage 未知=null 不为 0。
- source_reader purpose∈{preview,filing_reuse,source_export,narrative_derivation}。
