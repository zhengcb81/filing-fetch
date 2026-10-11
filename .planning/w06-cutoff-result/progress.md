# Progress — W06 cutoff result

## 2026-10-11 — Author starts
- Read existing matrix plan/findings and exact four cutoff artifacts. Read CodeGraph before targeted source inspection; assigned worktree has no index and root FF index misses new modules, so known file reads used.
- Baseline Git HEAD 88997b85ce5be20dc3d563b5c040706590df6dbb; status clean. User permanent FF upgrade authorization and ROOT narrow write-set apply. No keys/network/model access.
- Selected independent PWF created before tests or product edits. Next: freeze hashes and execute business RED.
## Behavioral RED and implementation
- Baseline froze 5 owned files and 354 protected tools/fixtures/goldens/old PWF/handoff files.
- Executed new business tests: 23 FAIL / 8 PASS / 77 deselected, pytest 1.09s, unique scratch restored. All failures are behavior/contract failures, no imports/setup failures.
- Two-file repair implemented after RED; transport reuses only a finite constant from existing et_v2_contract, never calls its validator. Provider failures unchanged; no import/retry/receipt schema changes.

## Author focused GREEN / freeze
- Unchanged new tests: 31 PASS / 77 deselected, pytest0.54s; runner3.19s. Both unique short scratch directories fully restored.
- Ruff --no-cache on the five assigned files and git diff --check passed. 354 frozen protected files unchanged; RED/GREEN test SHA identical.
- Product freeze SHA: 0574664a9634d6ea11a9fa93949c8ea8469a60d013671e97c2015e8e093fa03c. Author stopped without commit/merge/push/install.
- GREEN is limited author responsibility evidence. ROOT concentrated old/new responsibility tests and actual ET/CWP original41 are still required; no claim of end-to-end COMPLETE.

## ROOT concrete envelope finding
- ROOT concentrated A:124 PASS / 4 SKIP /5.00s (6.617s outer). Three W07 real-ET cases lacked explicit test tool path; one real-CWP import/replay case lacked source checkout. These are SKIP, not PASS; parent owns original41 real integration.
- ROOT found production not_found branch lacked response-envelope/child-exit binding; previous negative binding tests covered only the test boundary. Added 8 actual transport counterexamples from valid receipts, one-field corruptions/nonzero exit. Prior freeze is historical intermediate, not final accepted publication.

- Production binding RED:8 FAIL /108 deselected /pytest1.03s, all actual transport returned not_found for wrong envelope/failed child; scratch restored.
- Added one constant-time receipt check in _et_result for schema /1 or /2, current request ID/provider/period and integer zero candidate count; nonzero child exit is provider_tool_failed. Actual usage retained. No success validator/source/identity lookup called.

## Final author STOP
- ROOT binding RED8 FAIL, GREEN39 PASS. Nonhashable schema array/object RED2 FAIL /1 PASS, final affected GREEN41 PASS /77 deselected /0.55s. All intermediate evidence preserved.
- ROOT concentrated-final2:134 PASS /4 SKIP /1.90s; no optional author suite rerun. Individual SKIP reasons recorded in final handoff.
- Final freeze a235b0c2c25f6c52a6402dd160737f2ec6ffa10309c368ee6eb06fbdc332cf4f; HEAD before/after88997b85ce5be20dc3d563b5c040706590df6dbb; protected354/tool205 unchanged; final lint/diff green and all scratch restored.
- Author product/tests frozen STOP. ROOT owns unchanged real41, acceptance and publication.

E启动：ROOT独审3FAIL（malformed stdout+complete bound stderr）；先检查旧8产品SHA一致，ET3不改，旧freeze e13ee23..留证。无网络/keys/config/raw/Git写。

E正规RED：3FAIL/75deselected/0.37s，三个实际_et_result错误输出把requests1清成None，非import异常。已实施局部共享unavailable投影：一次已验stderr usage快照；JSON/非dict/泄key/错误notfound/已调用失败/非零exit均共享，正文不合法不覆写用量，未知/污染receipt仍未知。待一次集中责任节点。

E最终集中节点：**137PASS4SKIP/2.46s**，3RED同一断言转绿；Ruff/diff绿，三个mu owned scratch恢复。旧freeze/独审失败/134PASS等历史记录不覆盖。FF本轮仅transport+launch测试变化；ET3 SHA完全不变。205tools/354protected/30oldgoldens不变；0网络/keys/config/raw/LLM，未commit/install。新中央product-freeze-v2.json SHA 87495b11e3c41986c3a10374bae0c603af6db4d61d7b8ed8c6a01771b7ed3381。
Next Step：非作者用v2 freeze仅集中复验原cutoff probes；ROOT负责182.86s矩阵host时间调查，原CaseSpec/180s预算与期待不改，本作者STOP。
