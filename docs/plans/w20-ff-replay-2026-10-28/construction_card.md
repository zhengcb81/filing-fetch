# W20-FF-REPLAY：下载、入库与回执中断的离线恢复反证

状态：READY，可立即开工。2026-10-28由ROOT分发；这是一张新的完整施工卡，不是已完成的W17/W19或ROOT物理阅读修复卡。

- 工作目录：`C:\Users\郑曾波\Projects\filing-fetch-w20-replay`
- 分支：`codex/w20-ff-replay-20261028`
- 冻结基线：`5396bd688e5b775e746fe3290852f0532d4548f8`
- PLAN_ID：`w20-ff-replay-2026-10-28`；PWF_PLAN_ROOT：`docs/plans`
- 交接目录：`delivery/w20-ff-replay/`
- 主仓仅只读：`C:\Users\郑曾波\Projects\filing-fetch`

## 目标与调查起点

在**现有**FF↔ET↔CWP离线联调矩阵中加入系统故障/重启/复用的行为反证，确认“成功拿到文件、原文真实入库、回执返回、第二次复用”几个阶段中断时不会重复下载、跨公司误复用或假报成功。是现有矩阵的可靠性扩展，不新加provider、不创建第二矩阵或运行生产迁移。

先读当前SKILL、`tools/offline_contract_matrix/README.md`及其41case/调度/180秒批次限制、相关DU8/DU10 PWF交接和现有`ff_local_source_prepare.py`、`ff_process_transport.py`、`transcript_companion.py`等owner。已有41例通过的状态保持；不要重新打包W19新浪API或重做文种路由。CWP原件/SHA/并发锁/ensure仍归CWP，ET下载/原语言TXT仍归ET。

## allowlist与责任边界

可扩展`tools/offline_contract_matrix/`及`tests/test_w20_replay*.py`/必要既有矩阵测试；只有真实反证证明FF缺陷时才改对应FF既有薄adapter（`ff_local_source_prepare.py`、`ff_process_transport.py`、`ff_source_failure.py`、`transcript_tool_transport.py`、`fetch_filing.py`薄入口）。新payload/故障fixture置tests或matrix owned fixture目录。不得改CWP/ET/StockInfoDLSimple/Dayu源码，不能复制原文SHA验证、存储路径/数据库写入到FF；不改安装器/模型/生产config/预算门、Dashboard接口或全局技能。

## 实施要求

R1. A先列既有矩阵已经证明的路径，冻结新增故障点和负责层，优先使用现有failpoint/private test seam，仅在测试边界注入，不在产品留测试环境变量后门。失败结果须携带实际阶段/调用次数和已入库Ref，不能用模拟PASS代替真实子进程/入库行为。

R2. 至少覆盖HTTP/provider返回后但导入前失败、导入已经持久成功但receipt/FF返回中断、ET子进程退出或截断JSON、错误身份/期间/材料hash、读到旧/部分回执、再次请求与并发同一公司期次。上游应由唯一owner负责的事务/锁只核其效果，不在FF造第二状态库/锁/授权文件。

R3. 对durable成功后的重试，要求通过CWP公开source/query/ensure复用真实已入库原件，观测额外下载0；如协议确实无法证明该状态，不假承诺exactly-once，给明确不足与ROOT跟进。对未durable成功的失败，资源限额/安全清理与可重试状态不能混为成功；真正的provider下载不可盲重放。

R4. 不只测年报：用代表性CN/HK/US财报、IR或发行材料及原语言电话会TXT覆盖同一恢复机制；不是追求组合数量。电话会走现有ET adapter，不翻译；缺本地文件时工具正确、已有则不重复下载。结构化三表走现有专门数据服务，不拿PDF解析替代；如本机制与其无关可说明而不强加case。

R5. 复用原runner的显式源码根、独立资料根、合成环境、provider边界替身和真实CWP/ET调用链；固化原件前后SHA与source versions、实际HTTP替身次数、子进程回收和scratch恢复。不要把fixture provider描述成真实外网成功；不读取FMP密钥或运行真实SDK/LLM/下载。

R6. 180秒总界限、30秒/case、并发≤2及proof reserve沿当前配置，不增额不塞每次commit。新增case应支持小范围选择/按既有恢复入口补未跑部分；失败时保partial/已完成case，不为补一次状态整批重跑41。若当前CLI已有case选择就复用；缺失时增加通用显式过滤，不写本卡专属硬编码分支。

R7. **冻结跨仓代码依赖，不绑定ROOT的可变工区。** CWP已发布基线为`618df929ffa889424b3346d5299d67b9b1c72709`；ET在A阶段只读解析其已提交HEAD，记录完整commit，不假设路径或隐式跟随HEAD。复用DU10固定代码视图的构建方式；只有manifest绑定的commit与本卡冻结commit完全一致时才能复用现成视图，不能直接用DU10旧`900dbf648...`视图冒当前基线。否则从冻结commit用只读`git archive`/`git show`在FF自有临时目录准备仅必要源码/测试seam的代码视图，不能执行别仓checkout或改其git索引。每批只准备一次、共用只读，记录来源blob/实际module路径SHA；不复制整个仓、历史.planning、SDK或公司原件。测试后删除仅本卡新增视图并保小manifest。所有CWP/ET源码仍只读，产品数据另在owned fixture root；源码视图不成为新provider或生产路径分支。

R8. **部分运行不能冒充41例完整通过。** 当前矩阵CLI尚无case过滤，既有oracle的41个required case是权威全集。若增加通用显式case选择，输出须注明supplemental/partial及实际selected/completed/skipped集合；不能把required_cases改小来得到full PASS。新增故障包可有自己的补充检查结果，但不得取代原41例报告。原完整命令与authority保持兼容，未跑范围明示NOT_RUN；不能为追全绿擅自再跑超时整批。

## 必要测试包与端到端

单元先验故障调度/回执分类/剩余deadline不续期、部分矩阵恢复、同ID跨公司期次不混。集成实际运行若干代表case：FF公开CLI→既有ET真实supervisor/worker（在HTTP边界fixture）→CWP真实import→SourceVersionReader实读→新进程同请求复用，覆盖至少一个durable后中断与一个durable前失败。必要的非ET财报恢复走现有fixture adapter→真实CWP ensure。正常路径、错误路径、恢复路径不能全靠同一个mock。

产物附逐case expected/observed、code root实际module路径/SHA、合成数据声明、请求/下载/入库/复用计数和范围。若产品既有行为已正确，交付上述证据和新增回归，不强改产品。确需CWP/ET owner修复时保counterexample，不跨仓patch；本卡本范围内可修问题全部修并独审后交接，不把跨仓阻塞伪报为全链通过。

## 总控、隔离与开始方式

ROOT（company-wiki当前主线harness）负责跨仓集成、真实收费摘要、最终公司循环及主线合并。本卡现在即可独立开工，不等待其他两卡完成。你是本卡实施owner，不是新的总控。

工作只在上面的**独立工区**及它的分支。主项目目录、company-wiki、其他两卡工区、Dayu、IQS、Dashboard全部只读；不改它们的索引、配置、原件、安装技能或分支。不要切主项目的main/master，不清理它人的未提交文件，不自动合入主线。读取接口可以，禁止跨仓底层文件/数据库写操作。跨仓源码路径仅用于显式只读导入；测试资料根必须是独立fixture root，不能拿源码根当生产数据根。

先检查工区HEAD/branch/status与本卡基线一致，阅读所在仓/上级AGENTS、本卡及已有对应PWF/工具说明；允许在本工区初始化CodeGraph索引。发现基线之后已有别人改动则保留，并明确其owner，不reset。不要复制整个源仓、.planning历史运行环境、生产资料库或SDK；不要恢复全量备份作演练。

在本仓建立`docs/plans/w20-ff-replay-2026-10-28/{task_plan.md,findings.md,progress.md}`（PLAN_ID见下），复制本卡为`construction_card.md`，设置PLAN_ID和PWF_PLAN_ROOT=docs/plans。它是你唯一执行队列，不改ROOT总PWF。所有测试命令显式使用宿主实际可用Python，不能把机器绝对路径写进产品。

## 三个大节点；不增加小节点审批

**A 调查/冻结预期。** 先读本仓已有实现、相应PWF与commit，逐项列本卡需求是已有覆盖、真实缺陷、还是缺可观察性；已有的复用，不为了有diff再造模块。冻结接口、数据来源、正反例和有限测试命令。记录已通过基线。A不需要等ROOT签收才继续B/C。

**B TDD实施。** 有真实缺陷先保存行为RED，再改所属共同责任层。测试覆盖跨公司/市场/文种的同一规则，禁止公司、页码、某段金标整句特判；不抬token、费用、时间、空间或并发额度，不增加人工权限、canary、授权JSON和签收链。没有缺陷可以交付有效的回归套件及明确no-code结论，不强行重构。只改本卡allowlist；遇到需要改别仓或ROOT保留模块，交付具体counterexample与期望，由ROOT处理，不能私自扩大。

**C 集成/CLI/独审/交接。** 先跑必要单元，再跑一个或少量代表性真实CLI端到端，检查真实入口和实际调用链，不能以mock函数调用次数冒充跨仓端到端。默认离线、不使用任何真实LLM或下载API、不读取密钥；历史真实资料仅只读或使用已有小范围脱敏fixture，不能假称新下载/新预测。每case有界，失败停在命名原因，修根因后只重跑相关部分，禁止反复跑超时全域。若全量本仓既有套件能够稳定短时完成，可在C一次执行；慢套件不加到每次commit。

测试都放在独立test/temporary目录，先记录初态和sentinel；完毕恢复初态，原本不存在的临时下载/数据库/请求文件/子进程须清除，已有fixture不得删改。保留小收据/压缩日志；报告前后字节/文件清单差异、owned child回收和峰值空间，不留逐页副本或大响应。未知费用、时长、外部完整性就写unknown/NOT_RUN，不能编0或PASS。

**交接前必须调用真正独立的审查agent。** 把本卡全部要求、实际diff、测试包、接口、已知局限交给它，全面审查完成度、架构/模块化、硬编码、数据/角色/期间/数字、错误路径、测试真实性和清理。作者不能换个名字自签。独审发现的本范围问题全部修复，保留初审与修复证据，再由独立agent复审最终实现；最终本范围OPEN必须为空才可交接。跨仓阻塞如实单列，不能靠把本范围缺陷移入“范围外”伪完成。

## 固定交接接口

交付目录为本仓`delivery/w20-ff-replay/`。提交`handoff.md`和`handoff.json`，以及`review/initial.md/json`、`review/final.md/json`（确实无问题可只有final，但仍须独立agent实际审查）。JSON至少包含：

```json
{
  "card_id":"见卡号", "status":"READY_FOR_ROOT_REVIEW",
  "workdir":"实际绝对目录", "branch":"实际分支", "base_commit":"原始基线",
  "implementation_commits":[], "tested_code_commit":"实际受测代码commit",
  "reviewed_code_commit":"独审绑定的最终实现commit",
  "files":[{"path":"相对路径","sha256":"最终实际字节SHA"}],
  "requirements":[{"id":"本卡要求","evidence":"报告/测试节点","status":"PASS或明确未执行"}],
  "tests":[{"command":"完整命令","exit_code":0,"passed":0,"failed":0,"seconds":0,"scope":"真实范围"}],
  "review":{"agent_id":"实际独立agent","report":"相对路径","open_findings":[]},
  "cleanup":{"before":"初态收据","after":"恢复收据","restored":true,"bytes_added":0},
  "compatibility":[], "limitations":[], "root_followups":[], "remote_status":"实际状态"
}
```

上面0/true只是结构示例，必须填实测值；未测为null并解释。`tested_code_commit`/`reviewed_code_commit`应指同一最终实现；后续只加handoff文档的commit可以不同，说明两者之间源码无变化。不能拿旧版本签名覆盖新源码。以实现commit和有关文件SHA界定，不做整仓签收/许可文件。

完成进展及时commit；存在已配置远端就推本卡分支，未配置则记录，不创建公开remote。正常hooks不绕过。不要全局同步技能/安装，不提交真实公司原件、密钥、model reasoning、runs大响应和临时环境。向用户回报三个路径：工区、handoff.md、handoff.json；然后STOP等ROOT接收。ROOT会统一复验和并主线，作者不用等待其他卡签收。
