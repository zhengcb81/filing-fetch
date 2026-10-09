# FF operation-cause consumer handoff

## Ownership and installation

Worktree: `C:/Users/郑曾波/Projects/_harness_worktrees/cmrf-20261008/ff-diagnostics`
Branch: `codex/company-pool-failure-consumer-20261009`; base `a1f3e4f`。不在初始真实公司执行封存/四review前发布，root统一commit/并线/安装。

## Public interfaces

- CWP任意失败stderr/返回body仅读最外层 acquisition_failure；精确七字段 acquisition-failure/1，operation累计usage。
- FF同一 validator投影固定六字段 filing-upstream-cause/1，新增闭集33 code与CWP一致；无message/path/query/token或金额第二账。
- stderr generic分类和原 catalog bounded retry不变，producer retryable不能升级；返回型GAP保持原状态和次数，公开 cause在filing.upstream_cause。正常GAP没有新cause。
- typed ChildStartFailed只证明outer Popen未启动；普通/post-start OSError provider_started/usage_complete=null。type仍OSError兼容ET旧分支。

## Changed responsibility files

Runtime: scripts/ff_provider_cause.py, fetch_filing.py, ff_process_transport.py, ff_v2_envelope.py。
Tests: tests/test_acquisition_failure_consumer.py（77 cases）, test_provider_cause_contract.py（误断言改typed proof）, test_transcript_companion_transport.py（fixture绝对路径）。
This docs folder contains independent PWF, repeatable actual CLI driver and final proof. No other repository writes.

## Concentrated test commands

Use Python UTF8/-B and PYTHONDONTWRITEBYTECODE=1. Execute pytest in a newly created short owned TEMP root, --basetemp <root>/p; delete that exact root on completion (not global pytest dirs).

`python -X utf8 -B -m pytest -q tests/test_acquisition_failure_consumer.py tests/test_provider_cause_contract.py tests/test_p5_process_transport.py tests/test_fetch_filing.py tests/test_transcript_companion_transport.py --basetemp <short-owned>/p -p no:cacheprovider --tb=short`

`python -X utf8 -B docs/implementation/company-pool-provider-cause-20261009/run_consumer_e2e.py --cwp-src C:/Users/郑曾波/.codex/worktrees/audit-provider-cause/company-wiki/src`

`python -X utf8 -B -m ruff check scripts/ff_provider_cause.py scripts/ff_process_transport.py scripts/fetch_filing.py scripts/ff_v2_envelope.py tests/test_acquisition_failure_consumer.py tests/test_provider_cause_contract.py tests/test_transcript_companion_transport.py docs/implementation/company-pool-provider-cause-20261009/run_consumer_e2e.py`

`python -X utf8 -B -m mypy scripts/ff_provider_cause.py scripts/ff_process_transport.py scripts/ff_v2_envelope.py scripts/fetch_filing.py --cache-dir=<owned-temp>`

No provider/model calls in these tests. The parent milestone also must run RF→FF→CWP integration before publication. Windows long source filename paths remain a separate observable limitation; do not weaken any source assertions to hide it.

## Final result

239 PASS /1 production snapshot SKIP /39 subtests（22.22s）。Actual CLI driver25/25 PASS，`consumer_e2e_report.json`10,983 bytes，临时根恢复true。Ruff/mypy4 runtime/diff--check PASS。No paid calls/Dayu writes/production raw/config/owner key/installation changes. No commit/merge/push. Worktree test/caches removed. Root cross-repository RF→FF→CWP gate remains the milestone publication responsibility.

## CI numeric-gate follow-up delivered (2026-10-09)

Additional card removes all numeric complexity permit checks, preserves a runnable legacy-score diagnostic and invalid-syntax failure, and closes the curated-test omission for provider-cause/operation-consumer responsibility tests. No business function split or threshold increase. Proof: complexity_ci_proof.json plus original RED/GREEN command records.

Actual results: diagnostic7 PASS; focused527 PASS/5 SKIP/78 subtests; explicit2 previously skipped CWP cases2 PASS; Ruff/mypy/compile/import/unique names PASS. Remaining3 capability/sample skips detailed in proof. All owned TEMP restored; supplier calls/fees0. Local commit may be read from git log after normal hook acceptance. Root must push and confirm exact-SHA remote CI; this lane does not publish/merge/install or claim full product completion.
