# Findings — W06 cutoff result

- Real ROOT matrix final attempt: 40 PASS / 1 FAIL; only call_past_cutoff. Its unique legal AAPL 2025-Q2 candidate has call_date 2027-06-01 versus request as_of_date 2026-12-31. Actual ET /2 result has not_found and candidate_count=0, no cause; FF reports provider_unavailable. Neither rejection nor zero body is proof of a cutoff reason.
- scripts/transcript_tool_transport.py:605-621 is the flattening point. Closed provider code vocabulary at 51-64 lacks cutoff. scripts/transcript_companion.py:178-183 and ff_v2_envelope.py already preserve not_found/reason/usage, so they remain untouched.
- ET additive field will be error_code only, call_after_as_of / publication_after_as_of. These names are already accepted by immutable original matrix_outcome.py:44-47. No synonymous reason field, no request/response schema bump.
- et_v2_contract.py is only consumed by tests, not production transport. Extend its existing test boundary rather than installing a duplicate production validator. Original success goldens and strict 26-key payload remain unchanged.
- Unknown child diagnostic strings must not leak or invent cutoff. Existing credentials/HTTP/timeout/usage behavior remains verified by ROOT responsibility tests.
## Final bounded implementation
- One finite ET_NOT_FOUND_DIAGNOSTICS vocabulary contains two actual date exclusions. Transport imports only the constant; no call to test-only normalize_et_v2_result.
- Production not_found preserves state, maps only those two codes, and never forwards child text. Ordinary/legacy/unknown diagnostic returns exact_transcript_missing. Existing provider failures, retryability, bounded process and measured usage unchanged.
- Test-only /2 boundary accepts old six-field not_found plus one optional finite error_code; preserves existing strict success/failure goldens. Header, period and zero-count checks remain in their existing responsibility layer.
- Protected file SHA comparison: 354 unchanged. All original contents of the three tests remain byte-for-byte prefix; only new tests appended. No CWP/ET product/tools/fixtures/config writes.

## ROOT receipt boundary gap and common repair
- Test-only binding negatives did not protect the actual production receiver. Production binding checks now occur once at the existing transport boundary, retaining measured usage while rejecting unrelated/failed receipts. No extra security master or raw verification.
- Set membership over a decoded schema field could raise for JSON array/object. Two formal negatives proved the exception; finite tuple comparison safely rejects both types. Other binding fields use direct equality and count uses strict int.
- Final ROOT concentrated134 PASS /4 SKIP. Three explicit W07 real-ET integration negatives lack test tool path; real-CWP import/replay lacks source checkout. These optional scope tests remain SKIP, actual three-layer original41 is owned by ROOT.

E根因：用量来自stderr、stdout文档合法性独立。_et_result582已解析合格usage，590/598错误分支再_parse空receipt覆盖，606又重复parse同receipt。失败信息和用量应共享一份已验snapshot；错误内容不意味着未知网络用量。独审probe-result/trace保留且只读。

E修复不是给三种坏payload单独补usage字段：_et_result共享局部unavailable(reason,calls,retryable)，仅一次解析合格stderr。泄密/JSON解码/非dict/receipt绑定/具名provider失败/nonzeroexit均同一投影，未知或污染receipt仍未知；未触达receipt的transport异常不伪造用量。不因正常失败重设消耗，不追加身份或许可。
