# W06 FF cutoff v2 — malformed stdout 与实际用量共用修复

状态：AUTHOR_COMPLETE_PENDING_INDEPENDENT_REREVIEW；作者STOP。旧handoff/v1 freeze不覆盖。
独审3FAIL是完整stderr usage1次987bytes被JSONdecode/non-dict错误分支清空。已先正规3RED（0.37s），再共用实现，集中137PASS4SKIP（2.46s），Ruff/diff绿。SKIP仍旧四项显式跨仓tool/checkout未给，非PASS；ET不重复跑且3产品SHA不变。
产品只transport，测试只launch contract；仍位于原five-file写集。所有post-receipt失败共用一次已验snapshot，真实unknown不伪造complete，无新身份复验/门禁/重试/import。生产配置/key/raw/Git发布零写。
统一中央product-freeze-v2.json SHA 87495b11e3c41986c3a10374bae0c603af6db4d61d7b8ed8c6a01771b7ed3381，8 files +两roots/head，ET3不变，FF5新版本。205工具/354保护文件/ET12+FF18旧goldens全未变；旧v1 e13ee23..及独审失败证据保留，三个mu scratch恢复。
证据：company-wiki/.planning/w06-cross-period-acquisition/cutoff-implementation/ff/malformed-usage-repair/。
Next Step：ROOT将v2 freeze交非作者，仅集中复验原cutoff probes；ROOT调查当前主机41矩阵182.86s的问题，不改CaseSpec/timeout/期待洗绿。本作者不commit/merge/push/install，STOP。
