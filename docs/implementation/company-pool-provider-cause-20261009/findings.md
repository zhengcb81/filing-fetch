# FF consumer findings

- CWP 原 generic stderr 分类保留；可选 acquisition-failure/1 用同一 validator 读取 stderr 或返回 body 最外层，不扫描嵌套 gap_plan。
- producer code 公共闭集实际 33 项（最初协调消息称34）；静态 AST 比对双方逐字一致，两边差集为空，不运行邻仓 private import。
- 使用严格七键：schema_version/code/retryable/provider_started/usage_complete/acquisition_usage/usage_scope。usage=精确 schema1.0 三键、bytes非负整数拒bool、cost有限非负decimal string。完整性false允许保留非零下界；null不猜零。
- FF 公开对象仍六键 filing-upstream-cause/1；金额字节仍留 CWP 原 accounting/public DTO。新增 retryable 不是自动重试许可，generic catalog classification 决定原 retry scope。
- 原 FF 任意 OSError 被错误标成未启动，真实子进程执行后 cleanup 的 OSError RED 证明该假设不成立。新增 ChildStartFailed 仅包 outer Popen 的 OSError；该类型继承 OSError，保留 ET 等旧调用方异常行为。
- 返回型 provider failure GAP 沿旧 GAP/status/exit/count 语义发表安全 cause；普通缺来源和坏/缺 diagnostic 无新 cause。
- 旧 ET->CWP 测试在本长工作树 pytest basetemp 触发 CWP import FileNotFoundError；同断言在短自有 TEMP 根通过。第一次人工 runpy 诊断另因相对 __file__ 形成相对 fixture；这不是原 pytest 失败根因。fixture resolve 定点提高直跑可靠性，但不宣称修复 CWP 长路径限制。
- 测试 paid_calls=0，无真实 market/model API，无生产原件、config、owner key、installed skill 写入。

- CWP现有 `_stage_with_retry` 最多3次fetch且仅完整usage/retryable=true才重试；FF自身generic fatal不重试。真实链的4provider starts=1discovery+3fetch，FF calls=2。FF不将adapter内部的有界重试误记为自身重试；操作累计费用责任仍在CWP。

## Complexity policy correction (2026-10-09)

- Root identified CI37861936346 as numeric-only: old ratchet required ff_provider_cause max14<=10. Locally reproduced1 FAIL/1 PASS; no business failing assertion was removed. Search found only tests/test_complexity_ratchet.py enforcing numeric complexity; pre-commit/pre-push have no other complexity threshold. Historical PWF statements are preserved as history.
- The legacy AST estimate is not graph-theoretic McCabe: it counts branch-like nodes in module-level synchronous functions, including nested blocks, excludes test_ functions and does not assess classes/async functions. Tool explicitly reports this scope; no claim that a low score proves code quality.
- Old parser caught SyntaxError and returned0, conflating unreadable code with simple code. New diagnostic propagates the direct parser error and reports CLI syntax/read failures with exit1; score changes do not affect exit0. Historical10/34/39 comparisons are retained only as observable fields.
- quality.yml's curated list now includes existing tests/test_provider_cause_contract.py and tests/test_acquisition_failure_consumer.py, plus seven new diagnostic contracts. No new full-suite invocation or real provider dependency.
- Initial full focused run had5 skips; explicit candidate CWP root d7923191 enabled the2 environment-dependent cases, both passed. Remaining2 production snapshot cases and1 Windows symlink capability case are honest limitations, not green assertions. No paid/model/network provider requests.
