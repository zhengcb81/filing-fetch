# Progress — FF-1 信封贯通

## Session 2026-11-15

- 开工：worktree C:/Users/郑曾波/Projects/filing-fetch-ff1-envelope-20261115 建于 main 1dfd818，分支 codex/ff1-envelope-candidates-20261115。
- 诊断复核：确认 fetch_filing 白名单无 candidates/reason、_pathless_operation_handle 不挂候选、v2 error_envelope 无 candidates 参数、job _ERROR_FIELDS 闭集且 error 块无 pathless 防线、文档 error 行六字段。
- 基线：全量 17F/1537P/11S/3E/44sub；ruff 过；聚焦文件 93P/6sub。
- C1 完成：_SOURCE_OPERATION_FIELDS+2 字段；_validated_operation_candidates 严格校验（状态门控/全等闭集/枚举/≤5）；_pathless_operation_handle 挂载+reason 入消息；37 测试绿；回归 254P 绿；commit feat(contracts)。
- C2 完成：ff_source_candidate 增 projected_error_candidates+CANDIDATE_DETAIL_FIELDS/LIMIT（C1 常量上收共享）；error_envelope 可选 candidates（filing.candidates+闭集 hint，仅三 code）；main() v2 分环传 exc.candidates；17 新测试绿；回归 411P（1 失败=基线预存 provider_diagnostics real CLI）；ruff 过；commit feat(v2)。
- C3 完成：_ERROR_FIELDS+candidates；error_view_from_exception 投影透传（同三 code 门控，ERROR_CANDIDATE_CODES 共享）；build_job_view 子集校验+error 块 _assert_pathless+存储候选形状校验；docs/ff-job-protocol.md error 行更新；15 新测试绿；回归 420P（同 1 预存失败）；ruff 过；commit feat(job)。
- 全量改后：17F/1604P/11S/3E/44sub；失败集与基线逐名一致（主工作区 base commit 重跑 6 个失败文件复核同名单）；passed +67。
- 链路验收：TestFF1ChainAcceptance 2 项（operation payload→exception→v2 envelope→job view 一条链）；文件 69P 全绿；ruff 过。
- 收尾：PWF 三文件终态更新；收尾 commit。
- 红线核对：未 push、未并 main、每 commit 前 git branch --show-current 核对、旧负载/旧记录形状断言全绿、物理防线覆盖 candidates。

## Session 2026-11-15（第二轮：独立重审修复）

- 重审 finding：F1 (P2) build_job_view 存储 error 子集校验过宽（残缺形状放行）；F2 (P2) candidates 校验对象（投影）与输出对象（record 原件）分离，篡改存储未知键可透进 JobView；F3 (P3) 大写 sha/float fiscal_year/bool byte_size 缺显式拒收测试。
- 修复 F1=收紧路径：_ERROR_BASE_FIELDS（六键）/_ERROR_FIELDS（七键）两个全等合法形状，其余 fatal；新增 6 缺键参数化 + 七键缺 base 字段 + 单键拒收测试。
- 修复 F2=重写路径：校验通过后 view["error"] = {**error, "candidates": 投影副本}（不动 record 原件）；不可投影 fatal；新增 api_key/command 未知键剥离测试 + 全未知键项 fatal 测试。
- 修复 F3：坏形状参数化补 uppercase sha / fiscal_year=2025.0 / byte_size=True。
- 复跑：test_ff1_envelope_candidates.py 82 passed（69+13）；ruff 全过；聚焦回归 303P/1S/44sub（1 失败=基线预存 provider real CLI）；全量 17 failed / 1619 passed / 11 skipped / 3 errors / 44 subtests。
- 失败集逐名核verify：17 个失败节点 = base commit 6 文件重跑的 16 个（逐名一致）+ test_config_doctor（在主工作区 base commit 单跑确认 FAILED，预存）。零新增失败；passed 1537→1619（+82 全为本 lane 测试，含链路与重审新增）。
- commit fix(job): 重审修复单独提交。
