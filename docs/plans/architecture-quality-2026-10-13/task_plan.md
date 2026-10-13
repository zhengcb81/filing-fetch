# filing-fetch 架构质量升级

PLAN_ID: architecture-quality-2026-10-13-ff
Owner: quality_ff；ROOT owns central reception and release.

A [complete] 独立审查公开入口、配置、SourceRef、ET、process lifetime、provider diagnostics、installation、CI；先写 RED 反例。基线31FAIL/3PASS。
B [complete] 共享有界配置/路径解析、runtime/doctor一致；纯SourceRef契约单一实现；query/ensure统一candidate投影；真实calendar校验；便携hook；修正不合法CLI样例、存储路径与退休worker文档噪音。相关与集中快测通过，详checks.json。生产原件/配置/凭证未修改，付费模型与真实下载0。
C [ROOT reception] 原实改5cfad11已由ROOT接收main并推送/同步。ROOT发现.codex旧ff_provider_cause不在本次diff但导致ImportError，已定点补齐；集中跨仓/最终CI记录归ROOT。
D [complete] 针对上述共用部署根因，plan/result新增完整owned runtime只读drift/byte-complete诊断，结果在实际写入后重新观察。只复制所选scope，保持config/unknown/keys和旧状态/退出码语义，fresh运行验收明确NOT_EVALUATED。6RED反例全部失败后，相关安装集中33PASS/8.59s，tmp恢复。正常commit交ROOT接收此engineering-only改进；不需同步runtime技能文件。

Next Step：ROOT接收D的新增commit，正常push并使用plan的完整诊断与fresh普通/lazy入口实际运行验收；不把scope match或byte_complete当执行成功，不自动扩大写scope，不清理unknown/config/key。本lane停写。
