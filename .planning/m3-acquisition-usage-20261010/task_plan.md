# FF lane record — M3-USAGE (FF 子仓步骤，唯一总执行 PWF 在 CWP 工作树)

## Scope
FF 保真投影 acquisition-observation/1：source_candidate/缺失/失败沿 v2 envelope 顶层随行；
不重算用量、不推断费用、不重验 MIME/身份。v1 输出冻结。

## Steps
1. ff_provider_cause.validated_acquisition_observation（闭合校验+深拷贝）✓
2. diagnose_stderr_observation 扩 4-tuple（单次解析）✓
3. filing_contracts.FilingFetchError 携带 acquisition_observation（fail-closed）✓
4. ff_v2_envelope 三分支顶层 sibling（filing 闭合形状不动）✓
5. fetch_filing：_SOURCE_OPERATION_FIELDS 白名单、gap/handle/错误路径接线 ✓
6. tests/test_m3_acquisition_usage_ff.py（21）+ 责任回归（167）✓

## Next Step
无（本仓 GREEN；集成与真实大节点由 MAIN 负责）。
