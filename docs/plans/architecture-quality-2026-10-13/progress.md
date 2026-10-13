# progress

2026-10-13：ROOT指定隔离worktree/基线，未写canonical。
- A：CodeGraph context/impact + 已定位文件阅读；无本仓AGENTS；向ROOT报告scope，ROOT确认无DU/跨仓冲突。31FAIL/3PASS反例证实缺陷。
- B：已实改共享配置、SourceRef契约、candidate职责、calendar和portable hook；相关298PASS，集中742PASS/7SKIP/78subtests/66.21s；最终pure SourceRef收口后受影响174PASS/3SKIP/2.39s，新增38项均纳入最终177PASS/3SKIP/2.54s。ruff/mypy/host guard绿。
- ROOT创建稀疏worktree漏e2e导致最初ci_tests零测试（不是代码失败）；仅本worktreegit sparse-checkout add e2e之后真实快套件通过。没有删除测试或放松断言。
- 临时测试目录由pytest/TemporaryDirectory清理；无付费调用/真实下载；安装和推送由ROOT接收处理。保留branch交付；完整commit登记在ROOT中心handoff.json。

2026-10-13 ROOT接收后的部署职责收口：
- ROOT在3副本fresh CLI发现.codex旧非diff依赖缺symbol并已修复，要求在原独占branch做engineering-only只读完整owned诊断，canonical不写。
- 6项新TDD：首次fixture tools导入路径问题先纠正（不是RED业务结果）；真实RED6FAIL/1.20s，全部 owned TemporaryDirectory恢复。
- 实现manifest共享诊断、plan全owned状态、post-apply重新观察、outside读异常纯诊断、NOT_EVALUATED fresh运行语义；selected scope和退出码不变。
- 一次相关安装集中33PASS/8.59s，其中保留配置/unknown/keys、alias、partial retry、target/source race、真实3临时安装CLI的旧测试继续绿；temporary scratch恢复，Ruff/host guard/diff-check绿。没有全套重跑或真实安装/网络/费用。
- 此新增commit由ROOT正常并线推送，工具属于工程层，不扩技能runtime安装scope。
