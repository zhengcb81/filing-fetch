# Findings — FF-1 信封贯通

## 代码地图（base 1dfd818）
- scripts/filing_contracts.py:62-133 FilingFetchError 已有 candidates 字段（identity 歧义路径 :449-455 _resolved_company_identity 挂载，任意 list 未校验形状）。
- scripts/fetch_filing.py
  - :803+ _SOURCE_OPERATION_VERSION="1.0"；原白名单无 candidates/reason；_SOURCE_OPERATION_STATUSES={completed,gap,ambiguous,not_found,unavailable,blocked}。
  - _validated_operation：对象→acquisition_failure/observation 诊断→schema/operation/白名单 fail-closed→status 枚举→local_preparation→physical guard（除 acquisition_failure）→request_id→policy_hash。
  - _raise_operation_business_failure：blocked/unavailable/ambiguous/not_found 分支走 _pathless_operation_handle。
  - _pathless_operation_handle：status!=completed 时 errors map raise；completed 分支走 validate_source_candidate。
  - main() v2 错误分支原来不传 candidates；v1 分支 exc.candidates→candidates+hint（identity 文案）。
- scripts/ff_v2_envelope.py error_envelope：filing 块闭集字段，原无 candidates。
- scripts/ff_job_contracts.py：_ERROR_FIELDS 原六字段闭集；error_view_from_exception 不透传；build_job_view error 形状 set(error)!=_ERROR_FIELDS→fatal；error 块不过 pathless 防线；_NEXT_ACTIONS 闭集（ambiguous→resubmit_with_disambiguation；identity_error→resubmit_with_market_or_ticker）。
- scripts/ff_job_runner.py _execute 捕获 FilingFetchError→error_view_from_exception。
- scripts/ff_source_candidate.py：_PHYSICAL_FIELDS 闭集 + contains_physical_field（递归）+ COMPANY_IDENTITY_FIELDS。
- docs/ff-job-protocol.md error 行原为六字段 ApiError 形状。
- 路由：_pathless_operation_handle 仅 source_ref_v2 路由（v2 请求或 --source-ref-v2）；纯 v1 legacy 路径不经此，v1 协议不受新挂载影响。

## 契约要点（与 CWP 生产 lane 共用文本）
- 顶层可选 candidates：list[object]，仅 status∈{ambiguous,not_found} 合法；completed/gap（及其它状态）携带即 invalid（fail-closed upstream_error）。
- 每项字段闭集（pathless）：document_id(str urn)、title(str)、document_kind(str)、provider(str|null)、provider_document_id(str|null)、form_type(str|null)、fiscal_year(int|null)、fiscal_period(str|null)、language(str|null)、content_sha256(64hex str)、byte_size(int)、publication_status(known|unknown|future)、exclusion_reason(published_date_unknown|fiscal_year_mismatch|multiple_candidates|identity_mismatch|capture_not_ready|other_excluded)。实现为全等闭集（多余/缺失字段都 fail-closed）。
- 顶层可选 reason：str（闭集，非 completed 状态的机读原因）。实现：status==completed 携带即 invalid；token 形状 [a-z][a-z0-9_]{0,79}（与 local_preparation reason/causes 同惯例）；透传方式为并入错误消息（"company-wiki ensure ambiguous: multiple_candidates"），v2 filing.reason/job message 自然携带。
- 数量上限：candidates ≤5。

## 设计决定
- D1: 校验器为 fetch_filing 模块级纯函数 _validated_operation_candidates，fail-closed 惯例（upstream_error + invalid_producer_schema source_condition + receipt/observation 附带）与 _validated_operation 一致；候选返回投影副本（防别名）。
- D2: reason 的"闭集"未给枚举值——消费方按 token 形状收口（不越权定义生产方枚举）；completed 携带 reason fail-closed（契约"非 completed 状态的机读原因"）。
- D3: v2 hint 闭集文案：identity_error 逐字沿用 v1；ambiguous="select one candidate from filing.candidates and resubmit with disambiguation fields"；not_found 无 hint（v1 先例）。
- D4: projected_error_candidates（ff_source_candidate）作为 v2/job 两面共用安全投影：仅 dict 项、物理键拒整块、未知键剥离（白名单=CANDIDATE_DETAIL_FIELDS∪COMPANY_IDENTITY_FIELDS——同时容纳 operation 候选明细与 identity 候选两种生产形状）、无可识别字段项拒整块。ERROR_CANDIDATE_CODES={ambiguous,identity_error,not_found} 同处定义，两面共用防漂移。
- D5: job error view 的消歧提示沿用既有闭集 next_actions 词汇（identity_error→resubmit_with_market_or_ticker 等），不加自由文本 hint 字段（Dashboard ApiError 形状闭集）。
- D6: build_job_view error 校验从全等改子集（六键旧形状/七键新形状都合法）；error 块补 _assert_pathless（泄漏→fatal）；存储 candidates 形状非法→fatal。
- D7: 旧记录/旧负载字节形状不变：candidates=None/[] 时字段不出现（golden 与形状断言测试）。

## 基线/改后数字
- 基线（base 1dfd818）：17 failed / 1537 passed / 11 skipped / 3 errors / 44 subtests；ruff 全过。
- 改后（lane HEAD）：17 failed / 1604 passed / 11 skipped / 3 errors / 44 subtests；ruff 全过。失败集逐名一致（主工作区 base commit 重跑 6 个失败文件复核：同 17 FAILED + 3 ERROR 名单，全部真实环境依赖：real CWP e2e / vendored 副本 / real CLI config / live conformance）。passed +67（本 lane 新测试，最终 69 项中 2 项为最后链路测试加入后全量数 1604 未含最后 2 项追加——见 NOT_RUN/说明：全量跑在链路测试加入前；聚焦文件 69P 全绿复核）。
- 本 lane 测试文件 tests/test_ff1_envelope_candidates.py：69 passed。

## 验收证据矩阵（全部 mock/单测；tests/test_ff1_envelope_candidates.py）
① 合法 candidates+reason 贯通：TestFF1ChainAcceptance::test_operation_payload_reaches_v2_envelope_and_job_view（一条链：operation payload→_pathless_operation_handle raise→error_envelope filing.candidates+hint→error_view_from_exception candidates→build_job_view error.candidates）；另有 C2 CLI 级 test_main_v2_operation_ambiguous_error_carries_candidates、C3 runner 级 test_runner_lands_failed_job_with_candidates_in_error。
② 非法形状 fail-closed：TestC1OperationContract 17 变体坏形状（坏枚举 published_date_mismatch/pending、坏 sha、坏类型、坏 urn、>5、非 list、多余/缺失字段）+ completed/gap/unavailable/blocked 携带 candidates + completed 携带/坏 token reason → 全部 upstream_error（upstream_cause.code=invalid_producer_schema）。
③ 旧负载行为不变：TestC1::test_legacy_payload_without_new_fields_is_unchanged（消息逐字节 "company-wiki ensure not_found"、candidates None）；TestC2::test_absent_or_empty_candidates_leave_shape_unchanged + test_main_v2_error_without_candidates_keeps_legacy_filing_shape（filing 键集 {status,reason,retryable}）；TestC3::test_error_view_without_candidates_keeps_legacy_six_keys + test_build_job_view_accepts_legacy_six_field_error；golden 套件全绿；全量失败集与基线逐名一致。
④ identity_error 多候选：TestC2::test_identity_error_writes_identity_candidates_and_v1_hint + test_main_v2_identity_error_carries_candidates_and_hint（v2 envelope candidates+hint）；TestC3::test_error_view_passes_identity_candidates_for_identity_error（job error candidates+闭集 next_actions 提示）。
⑤ pathless guard：消费侧 operation 白名单拒 path 键（TestC1 mutation {"path":...}）；envelope 侧 TestC2::test_unsafe_candidates_are_dropped_not_leaked（path/bundle→整块丢弃）；job 侧 TestC3::test_error_view_drops_unsafe_candidates + test_build_job_view_rejects_physical_leak_inside_error（fatal）；未知键剥离 test_unknown_keys_are_projected_out_of_identity_candidates。
⑥ code 门控：TestC2::test_other_codes_never_carry_candidates（upstream_error/request_error/source_blocked/fatal/gap 无 candidates/hint）；TestC3::test_error_view_drops_candidates_for_non_disambiguation_code。

## 偏离与说明
- 契约"每项字段白名单"实现为全等闭集（多余且缺失都 fail-closed）——比"仅多余拒"更严，方向一致。
- reason"闭集"生产方未给值表：消费方按 token 形状校验（见 D2）。
- 验收④ job 面"hint"以既有闭集 next_actions 词汇承载（Dashboard ApiError 无 hint 字段，不能加自由文本字段）。
- 全量套件最终跑点：链路 2 项测试加入前（1604P）；其后聚焦文件 69P 全绿 + ruff 全过复核。差 2 项未计入全量数字，如实登记。

## NOT_RUN
- 真实 CWP 生产方端到端（生产方 lane 并行开发中）：全部证据为 mock/单测，如实标注。
- 未 push 远端、未并 main（按红线）。

## 独立重审修复（Lane C re-review，2026-11-15 第二轮）
重审结论：0 OPEN P1；2 OPEN P2 + 1 P3，均已修复并单独 commit。

- F1 (P2) build_job_view 存储 error 形状校验过宽：子集校验（set(error) <= _ERROR_FIELDS）放行残缺形状（单键/五键缺 correlation_id）。修复=收紧路径：`_ERROR_BASE_FIELDS`（六键 legacy）与 `_ERROR_FIELDS`（七键含 candidates）两个全等合法形状，`set(error) not in (_ERROR_BASE_FIELDS, _ERROR_FIELDS)` → FFJobError fatal。新增测试：六种缺键参数化拒收、七键但缺 base 字段拒收、单键拒收（原测试只测多余键）。
- F2 (P2) 校验对象与输出对象分离：存储 candidates 用投影校验、view 却取 record 原件，篡改存储的未知键（api_key/command）原样透进 JobView（envelope 面剥离、job 面不剥，防线不等强）。修复=重写路径：形状+pathless 校验后把 `view["error"]` 重写为 `{**error, "candidates": 投影副本}`（不改动 stored record 原件）；不可投影列表（非 dict/物理键/全未知键项）仍 fatal。新增对抗测试：七键 error + candidates 项带 api_key/command → 视图只含闭集键且非原对象；全未知键项 → fatal。
- F3 (P3) 类型边界显式固化：参数化坏形状补 uppercase sha（"A"*64）、fiscal_year=2025.0（float）、byte_size=True（bool）三种拒收（代码行为已正确，测试固化）。
- 修复后复跑：tests/test_ff1_envelope_candidates.py 82 passed（69+13 新增）；ruff 全过；job/envelope 聚焦回归 303 passed 1 skipped 44 subtests（1 失败=基线预存 test_real_cli_config_error_has_no_upstream_cause）；全量套件见 progress.md 终数。
