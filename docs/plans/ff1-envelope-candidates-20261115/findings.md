# Findings — FF-1 信封贯通

## 代码地图（base 1dfd818）
- scripts/filing_contracts.py:62-133 FilingFetchError 已有 candidates 字段（identity 歧义路径 :449-455 _resolved_company_identity 挂载，任意 list 未校验形状）。
- scripts/fetch_filing.py
  - :802-829 _SOURCE_OPERATION_VERSION="1.0"，_SOURCE_OPERATION_FIELDS 白名单（无 candidates/reason），_SOURCE_OPERATION_STATUSES={completed,gap,ambiguous,not_found,unavailable,blocked}。
  - :835-916 _validated_operation：对象检查→acquisition_failure/observation 诊断→schema/operation/字段白名单 fail-closed upstream_error（带 upstream_cause/receipt/observation）→status 枚举→local_preparation 形状→physical guard（除 acquisition_failure）→request_id→policy_hash。
  - :943-959 _raise_operation_business_failure：blocked/unavailable/ambiguous/not_found 分支走 _pathless_operation_handle。
  - :1009-1080 _pathless_operation_handle：status!=completed 时 errors map（ambiguous→ambiguous, not_found→not_found, unavailable→upstream_error, blocked→source_blocked）raise FilingFetchError，无 candidates 挂载；completed 分支走 validate_source_candidate。
  - :1846-1867 main() v2 错误分支：error_envelope(...) 未传 candidates。
  - :1868-1880 v1 错误分支：exc.candidates→error_response["candidates"]+hint（identity 文案 "disambiguate by adding market/exchange or by using a specific ticker"）。
- scripts/ff_v2_envelope.py:138-184 error_envelope：filing 块 = {status,reason,retryable,producer_exit_code?,request_diagnostic?,upstream_cause?,acquisition_failure?,stage?,attempts?}；无 candidates。
- scripts/ff_job_contracts.py
  - :67 _ERROR_FIELDS = {code,message,owner,retryable,next_actions,correlation_id}
  - :85-94 _NEXT_ACTIONS 闭集：ambiguous→["resubmit_with_disambiguation"]，identity_error→["resubmit_with_market_or_ticker"]，not_found→["correct_scope_and_resubmit"]
  - :214-227 _error_view/error_view_from_exception
  - :320-376 build_job_view：result 过 _assert_pathless；cost 形状校验；error 形状校验 set(error) != _ERROR_FIELDS → fatal。**error 块目前不过 pathless 防线**。
  - :379-418 build_result_view 过 _assert_pathless。
- scripts/ff_job_runner.py:162-166 _execute 捕获 FilingFetchError → error_view_from_exception(exc, owner_job_id)。
- scripts/ff_source_candidate.py:65-106 _PHYSICAL_FIELDS 闭集 + contains_physical_field（递归 dict/list，key 小写匹配）。
- docs/ff-job-protocol.md:116 error 行 = Dashboard ApiError shape 六字段。
- 测试: tests/test_ff_job_facade.py（build_job_view/error）、tests/test_ff_v2_contract.py（v2 envelope）、tests/test_ff_golden.py（CLI 序列化 golden，byte-shape 对比）、tests/test_r1_source_business_failure.py（operation 业务失败路径）。
- python: /c/Miniconda/python -m pytest（PATH python 是 shim 无 pytest）。

## 契约要点（与 CWP 生产 lane 共用文本）
- 顶层可选 candidates：list[object]，仅 status∈{ambiguous,not_found} 合法；completed/gap 携带即 invalid（fail-closed upstream_error）。
- 每项字段白名单（pathless）：document_id(str urn)、title(str)、document_kind(str)、provider(str|null)、provider_document_id(str|null)、form_type(str|null)、fiscal_year(int|null)、fiscal_period(str|null)、language(str|null)、content_sha256(64hex str)、byte_size(int)、publication_status(枚举 known|unknown|future)、exclusion_reason(闭集 published_date_unknown|fiscal_year_mismatch|multiple_candidates|identity_mismatch|capture_not_ready|other_excluded)。
- 顶层可选 reason：str（闭集，非 completed 状态的机读原因）。
- 数量上限：candidates ≤5。

## 设计决定
- D1: candidates 校验器做成 fetch_filing.py 模块级纯函数（不进 filing_contracts，避免动公共契约文件；C1 语义属 operation 消费）。校验后返回"投影副本"（只保留白名单键），fail-closed 用 FilingFetchError code="upstream_error" 携带 invalid_producer_schema source_condition，与 _validated_operation 既有惯例一致。
- D2: reason 校验：str + 小写 snake_case token 形状（[a-z][a-z0-9_]{0,79}，同 local_preparation.causes 惯例）+ 长度上限；闭集语义由 CWP 生产方定义，消费方按 token 形状收口（契约说"闭集"但未给枚举值列表，形状校验是本仓可执行的最强 fail-closed；多余语义不在本 lane 越权）。
- D3: v2 hint 文案闭集：identity_error 沿用 v1 语义（market/exchange or specific ticker）；ambiguous="select one candidate and resubmit with disambiguation fields"；not_found 不给 hint（v1 也不给）。
- D4: job error view：error_view_from_exception 透传 candidates（需是 list 且每项 dict，否则丢弃保 None——不 raise，因为 FilingFetchError.candidates 来自 v1 identity 路径是未校验 list）；build_job_view 校验 set(error) <= _ERROR_FIELDS，error 块补 _assert_pathless。
- D5: 旧记录字节形状不变：candidates=None 时字段不出现。

## 基线数字
- （待填：pytest 基线）
- ruff 基线: 通过
