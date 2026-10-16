# DU8 共同接口、隔离、验收与交接

本轮三条线现在可同时启动，不等ROOT完成CWP/ET接线。它们分别在RF、FF、AUDIT三个Git仓库的独立工作树，不能在主仓或旧工区施工。ROOT仍负责CWP来源层/阅读引擎/正式摘要、ET接收、最终跨仓联调/安装/并线；用户已授权CodeGraph必要初始化，无需再次询问。

## 任务边界

- 只改施工卡精确白名单和自己的PWF；不改兄弟仓、CI/hooks、安装副本、生产配置/原件、默认registry/运行output，不吸收主仓未提交改动。
- 只读依赖固定已提交HEAD，实际路径和SHA见launch.json。ROOT当前WIP不是作者测试输入，不以“缺ROOT尚未接的字段”为理由跨仓修改。
- 不新增private/public、人工签收/授权JSON、canary或许可链。既有任务意图足够；byte/SHA/期间/as-of/预算由其责任层核验。数值、证据和未知状态仍诚实保留，不把诊断改名为新门禁。
- 0真实HTTP/0供应商/0翻译/0付费；网络fixture单列，绝非供应商可达或真实公司质量证据。不要读/复制/打印环境密钥或FMP_API_KEY.txt。
- ROOT已按实际相对core.hooksPath检出已提交hooks（若未设置，保留Git默认），并带已有CI和所需受控资料。正常commit，不SKIP/--no-verify；日常跑相关快测，不每commit全仓测试。

## 三个大节点

A：读施工卡、源代码/AGENTS、已提交PWF与历史交付；用实际入口证明问题或重复责任，保存第一份行为RED；现状不成立就报告事实与更窄方案，不为立项制造错误。

B：实现共同责任/最小必要接线，一次集中相邻回归。原gold/基线断言不为实现洗绿，独立期望从冻结旧行为/手工计算/实读证据建立；新期望若有错误先保留并解释，不能隐藏分母或旧FAIL。

C：真实公开CLI/消费入口的隔离端到端，覆盖成功、拒绝、超时/中断、重复/恢复。仅原A/B/C节点集中审查，不另要求人签小节点。业务/源码/质量未通过的部分具名OPEN，不冒称全系统通过。

## 测试状态与清理

所有运行写自己创建的TemporaryDirectory，开始放预存sentinel并冻结只读输入/配置/生产文件元数据，finally核验；原先不存在的下载、DB、registry、派生测试输出结束删除，原有内容/目录保持。只清理由绝对路径确认处于owned测试根内的文件，不做完整恢复备份演练。跨进程用现有bounded process owner，退出/超时均回收子孙和管道，不另写taskkill/等待链。RF尤其在import/CLI前设置隔离REVENUE_PUBLICATION_REGISTRY，不删除真实registry。

只保留小汇总、首RED、最终大节点日志和必要反例；日志压缩后读回核字节，目标≤5MiB/包，绝不复制原件湖或全篇MD。大真实日志仅一份，报告引用它。失败/unknown/NOT_RUN与实际分母原样保留；报告/目录成功存在不等于语义或覆盖成功。

## 统一交接输出

自有PWF提交handoff.md、handoff.json、receipts/。MD至少：已查明的根因、职责/接口变化、现行为兼容矩阵、实际运行命令、数字/单位手工锚点、测试结果与NOT_RUN、清理、ROOT如何接收。JSON形状：

```json
{"schema_version":"du8-handoff/1","card_id":"DU8-...","base_commit":"40sha","branch":"codex/...","implementation_commits":[],"changed_paths":[],"interfaces":{"entrypoints":[],"inputs":[],"outputs":[],"unchanged":[]},"tests":[{"command":"argv","exit_code":0,"passed":0,"failed":0,"skipped":0,"receipt":"relative/path"}],"red_receipts":[],"independent_expected_basis":[],"fixtures":[{"kind":"synthetic|retained-real","scope":"...","sha256":"...","limits":"..."}],"old_failures_preserved":true,"known_limits":[],"not_run":[],"supplier_calls":0,"production_writes":0,"cleanup_receipt":"relative/path","root_integration_steps":[]}
```

正常commit实现/测试/自有PWF后冻结源码，报告完整SHA和handoff路径，STOP。作者不自行并主线、不安装技能、不推远端主线。ROOT负责独立验收及跨仓接线；任何接口提案须给可复现反例，白名单外不擅改。
