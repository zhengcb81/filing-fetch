# W06 cutoff result — filing-fetch consumer

## Goal
Preserve ordinary ET not_found separately from provider failures and retain named actual date exclusions. No oracle relaxation or repeated download.

## Owner / baseline / dependencies
- Owner: portability_final_acceptance/cutoff_ff_mapping; ROOT alone publishes.
- FF independent worktree: C:/Users/郑曾波/Projects/_harness_worktrees/w06/ff-contract-matrix-root
- Base: 88997b85ce5be20dc3d563b5c040706590df6dbb (initial Git status clean).
- Selected PLAN_ID: w06-cutoff-result; PWF_PLAN_ROOT: this FF worktree.
- ET producer owned by parent: keep /1 and /2, not_found, fiscal_period, candidate_count=0; optional closed error_code call_after_as_of or publication_after_as_of. Ordinary/old not_found has no error code.
- Canonical evidence: C:/Users/郑曾波/Projects/company-wiki/.planning/w06-cross-period-acquisition/cutoff-implementation/ff/

## Exact write set
scripts/transcript_tool_transport.py; scripts/et_v2_contract.py; tests/test_transcript_launch_contract.py; tests/test_transcript_companion_transport.py; tests/test_et_s0b_contract.py; this selected three-file PWF; docs/handoffs/w06-cutoff-result/. No ET, CWP product, config, tools, frozen fixtures, other plans, CI, key, install, Git writes.

## Current Phase
E complete — v2 malformed-usage common error projection FROZEN STOP; independent concentrated rereview pending.

## Next Step
Independent reviewer concentrates on original cutoff probes using central product-freeze-v2.json; ROOT owns matrix timing and publication. ET/v1 freeze stay unchanged; author STOP.

## Phases
### A — Contract and behavioral RED
- [x] Read current code, matrix PWF and exact final matrix cutoff receipt.
- [x] Confirm FF maps all non-fetched to provider_unavailable; ET omits actual date reason.
- [x] Snapshot five owned files plus frozen tools/fixtures/goldens before edits.
- [x] Assert named cutoff, ordinary/legacy not_found, unknown diagnostics, usage complete/unknown and zero import; run only new behavior tests. Do not count import errors as RED.
### B — Minimal consumer implementation
- [x] Keep existing provider failure mapping; preserve not_found with finite error-code mapping.
- [x] Ordinary/legacy or unknown code becomes exact_transcript_missing, never guessed cutoff.
- [x] Update existing et_v2_contract test-only boundary for the optional not_found diagnostic; do not wire another production validator.
- [x] Focused GREEN and lint; ROOT owns the concentrated ET+FF responsibility node and unchanged original41.
### C — Author freeze / ROOT handoff
- [x] Verify frozen tools/fixtures/goldens unchanged, narrow Git diff and scratch restoration.
- [x] Update own PWF, hash owned five-file product/test delivery, write handoff/report/manifest.
- [x] STOP without commit/merge/push/install.

## Verification boundaries
Only synthetic supplier/process responses in tests. No real credentials, supplier/network/LLM calls. Unique short scratch under canonical evidence is owned and removed after verification; logs/manifests explicitly retained as evidence. New tests cover /1 and /2 producer shapes without changing old success goldens.

## Errors Encountered
| Error | Attempt | Resolution |
|---|---|---|
| Known-path conftest.py read absent | Read-only inspection | pyproject.toml defines scripts/tests pythonpath; no fixture dependency or RED claim. |
### D — ROOT production envelope finding
- [x] New counterexamples belong to the actual transport, not merely the test-only contract.
- [x] Preserve RED for wrong request/schema/provider/period/count and nonzero child exit.
- [x] One lightweight receipt envelope check at the existing transport boundary, retain real usage; no duplicate success/source identity validator.
- [x] Focused affected GREEN, new independent freeze; preserve prior RED/GREEN/concentrated124PASS4SKIP as superseded intermediate receipts.

## Historical v1 reception facts (superseded by E)
- Final concentrated B134 PASS /4 SKIP /1.90s; SKIPs are listed individually in handoff.md and are not counted as PASS.
- Final author freeze SHA a235b0c2c25f6c52a6402dd160737f2ec6ffa10309c368ee6eb06fbdc332cf4f; HEAD unchanged88997b85, protected354/tool205 unchanged, no product edits after this freeze.


## E — 独立验收 malformed stdout 用量保真共因修复

2026-10-11 ROOT重新打开本线；旧134/4与freeze不覆盖。独审三个向量stdout {broken-json/[]/null，stderr当前request完整usage1次987bytes；API成功解析usage后JSONdecode/non-dict再用空receipt覆写，实际用量丢失。
写集仍仅现有FF five-file；实际产品只transport、实际测试只launch contract，ET冻结全部不改。先追加3个正规业务RED，随后_et_result在实际receipt解析后建立一个局部共用unavailable投影；每次只parse usage一次，所有已收到receipt后的失败都消费同一validated snapshot，不能因正文异常重置。pre-receipt transport异常仍unknown，未知/污染usage不得冒complete。无新增身份复验/门禁。
测试节点：3RED→共用实现→一次FF5文件集中责任/lint/diff；不重复41/ET全部/原matrix180s或CaseSpec期待。新central证据ff/malformed-usage-repair/；新product-freeze-v2由总作者封存，旧文件原SHA保留。独立审查agent仅集中复验。Next Step：E业务RED直接实施，不等小节点签收。
