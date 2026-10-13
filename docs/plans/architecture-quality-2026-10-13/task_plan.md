# filing-fetch 架构质量升级

PLAN_ID: architecture-quality-2026-10-13-ff
Owner: quality_ff；ROOT owns central reception and release.

A [complete] 独立审查公开入口、配置、SourceRef、ET、process lifetime、provider diagnostics、installation、CI；先写 RED 反例。基线31FAIL/3PASS。
B [complete] 共享有界配置/路径解析、runtime/doctor一致；纯SourceRef契约单一实现；query/ensure统一candidate投影；真实calendar校验；便携hook；修正不合法CLI样例、存储路径与退休worker文档噪音。相关与集中快测通过，详checks.json。生产原件/配置/凭证未修改，付费模型与真实下载0。
C [ROOT pending] ROOT 接收本分支，集中跨仓离线契约与最终快CI，按runtime manifest定点同步skills并正常推送，记录精确SHA CI。不加入新的审批或重的CI，不覆盖其他harness工作。

Next Step：由ROOT读取company-wiki中心results/filing-fetch/report.md与handoff.json接收，禁止在canonical checkout直接覆盖/重置未解释的WIP；本lane停止写入等待接收。
