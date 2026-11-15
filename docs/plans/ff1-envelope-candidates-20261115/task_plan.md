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
- 记录基线 commit；跑全量测试基线数字；ruff 基线。

### Phase 2: C1 operation 契约消费
- Status: in_progress
- _SOURCE_OPERATION_FIELDS 增加 "candidates"/"reason"；_validated_operation 校验（状态门控、每项白名单、枚举闭集、≤5、fail-closed upstream_error）；_pathless_operation_handle 挂载 exc.candidates；测试（合法/非法/旧负载不变）。
- 提交: feat(contracts): ...

### Phase 3: C2 v2 error_envelope
- Status: pending
- error_envelope(candidates=None) 可选参数；仅 code∈{ambiguous, identity_error, not_found} 且非空时写 filing.candidates + filing.hint（闭集文案）；fetch_filing main() v2 分支传 exc.candidates；测试。

### Phase 4: C3 job 层
- Status: pending
- _ERROR_FIELDS 加 "candidates"；error_view_from_exception 透传（形状校验后的列表）；build_job_view stored error 校验 set(error) <= _ERROR_FIELDS（candidates 缺省不出现）；error 块 pathless 防线；docs/ff-job-protocol.md 一行；测试。

### Phase 5: 验收与报告
- Status: pending
- 六项验收（①-⑥）+ 全量测试 + ruff；交报告。

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|

## Next Step
Phase 2：实现 _validated_operation 的 candidates/reason 校验。
