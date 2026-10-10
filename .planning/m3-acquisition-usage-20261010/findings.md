# FF findings
- _validated_operation 是子集校验（set(payload) <= FIELDS）：新增键对旧 FF 天然向后兼容。
- source_candidate 严格 8 键闭集合同在 RF company_wiki_source_v2（非本线写集）：观察必须走
  envelope 顶层 sibling，不得进 filing，否则 RF 闭集校验拒绝（E2E 实测教训）。
- golden 测试（test_ff_golden）以夹具驱动：夹具无观察键 → 输出无键 → golden 不变。
- CI_TESTS（tools/ci_tests.py）不在本线写集：新套件加入 CI 列表属 MAIN 接线（见 MAIN 清单）。
