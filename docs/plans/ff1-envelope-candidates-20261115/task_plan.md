# FF-1 信封贯通（FF 半边：消费方 + 透传）

## 包ID
FF-1信封贯通（candidates 从引擎贯通到 v2 信封与 job 层）

## 分支 / 基线
- 分支: codex/ff1-envelope-candidates-20261115
- worktree: C:/Users/郑曾波/Projects/filing-fetch-ff1-envelope-20261115
- base commit: 1dfd81836794ec3bf73b41014a98714e97299ae8 (main)

## Goal
把候选明细从引擎贯通到 v2 信封与 job 层：
- C1 operation 契约消费（_SOURCE_OPERATION_FIELDS + candidates/reason 校验 + _pathless_operation_handle 挂载）
- C2 v2 error_envelope 可选 candidates 参数 + filing.candidates/filing.hint + main() identity 接线
- C3 job 层 _ERROR_FIELDS + error_view_from_exception 透传 + pathless 防线覆盖 error 块 + 文档

红线：既有协议零破坏；全部向后兼容；fail-closed upstream_error；不 push 不并 main；conventional commits。

## Phases

### Phase 1: 基线与诊断
- Status: complete
- 基线 commit 1dfd818 确认；全量测试基线 17 failed / 1537 passed / 11 skipped / 3 errors / 44 subtests（失败集全部为真实环境依赖：real CWP e2e / vendored 副本一致性 / real CLI config / live conformance）；ruff 全过；聚焦文件基线 93P/6sub。

### Phase 2: C1 operation 契约消费
- Status: complete
- commit feat(contracts): _SOURCE_OPERATION_FIELDS + "candidates"/"reason"；_validated_operation_candidates 严格校验（状态门控 ambiguous/not_found、13 字段闭集全等、urn/sha/枚举/类型检查、≤5、fail-closed upstream_error 带 invalid_producer_schema cause）；_pathless_operation_handle ambiguous/not_found 分支挂载 FilingFetchError.candidates，reason token 并入错误消息；37 项测试；回归 254P。

### Phase 3: C2 v2 error_envelope
- Status: complete
- commit feat(v2): error_envelope 可选 candidates 参数；filing.candidates+filing.hint 仅 code∈{ambiguous,identity_error,not_found} 且投影存活时写入；identity_error 沿用 v1 hint 文案；ambiguous 闭集 select-and-resubmit hint；not_found 无 hint；projected_error_candidates 安全投影（闭集字段并集=CANDIDATE_DETAIL_FIELDS∪COMPANY_IDENTITY_FIELDS、物理键拒整块、未知键剥离）落在 ff_source_candidate；main() v2 分支传 exc.candidates；17 项新测试。

### Phase 4: C3 job 层
- Status: complete
- commit feat(job): _ERROR_FIELDS + "candidates"（可选）；error_view_from_exception 投影透传且仅消歧 code；build_job_view 子集校验（六键旧形状/七键新形状都接受）+ error 块补 _assert_pathless 防线 + 存储候选形状校验 fatal；docs/ff-job-protocol.md error 行补可选 candidates；15 项新测试含 runner 集成。

### Phase 5: 验收与报告
- Status: complete
- commit test(ff1): 链路验收测试（operation payload→exception→v2 envelope→job view 一条链）。
- 全量套件改后 17 failed / 1604 passed / 11 skipped / 3 errors / 44 subtests：失败集与基线逐名一致（在主工作区 base commit 重跑 6 个失败文件复核：同 17 FAILED + 3 ERROR 名单），passed +67 全部为本 lane 新测试；ruff 全过。
- 六项验收证据见 findings.md「验收证据矩阵」。

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| sed s 命令引号报错（StringIO 替换） | 1 | 改用 python 脚本替换 |
| test_provider_diagnostics_cli 1 例失败（聚焦回归） | 1 | 判定预存（基线失败名单内），非本 lane 引入 |

## Next Step
Lane 完成，等待整合阶段收口（不并 main、不 push）。
