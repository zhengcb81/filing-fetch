# 调查发现

ROOT准备事实（2026-10-28）：新独立工区`C:\Users\郑曾波\Projects\filing-fetch-w20-replay`，基线`5396bd688e5b775e746fe3290852f0532d4548f8`，分支`codex/w20-ff-replay-20261028`。主仓tracked WIP未变；原件/模型未复制、无下载或收费。所有任务具体要求、allowlist、接口与独立审查要求见construction_card.md。

作者尚未调查产品/测试；未知项不能预写PASS。跨仓依赖固定已提交版本，不能顺手改原仓。

## A阶段调查（作者，2026-10-28）

### 工区与基线核验
- branch=codex/w20-ff-replay-20261028，HEAD=5396bd688e5b775e746fe3290852f0532d4548f8（与卡一致），status仅本plan目录4个untracked文件（ROOT seed，A首批提交）。

### 跨仓依赖现状（R7）
- CWP仓：C:\Users\郑曾波\Projects\company-wiki，master HEAD已漂移到c6c446d0（2026-10-28 18:58），冻结基线618df929ffa889424b3346d5299d67b9b1c72709在master历史内（2026-10-28 18:16"fix: preserve true prose gaps..."）。DU10快照.du10-deps/cwp绑的是900dbf6489（旧），不能冒用。
- ET仓：C:\Users\郑曾波\Projects\earnings-transcripts\earnings-transcripts（嵌套一层），main HEAD=2584b7eed062a9a30254bc06b4f19ab5471b414e（=DU11冻结ET commit，2026-10-17后未动）。
- DU10固定代码视图配方：git -c core.autocrlf=false archive <commit> | tar -x 到无.git快照；manifest见docs/plans/du10-ff41-close-2026-10-17/receipts/dependency-record.json（schema du10-dependency-record/1）。本卡需在FF自有临时目录从冻结commit重建CWP/ET视图+小manifest，测试后删除。

### 矩阵现状
- 41 required case唯一权威=tools/offline_contract_matrix/case_specs.py（AUTHORITY_VERSION w06-cases/1）；oracle.py独立同registry审计。
- cli_main.py argv仅--cwp-project/--et-project/--owned-root/--out-root/--workers(1..2)+replay子命令；无case过滤→R6/R8需加通用显式过滤，partial标supplemental+selected/completed/skipped，未跑=NOT_RUN，不得缩required_cases冒充full。
- 限额：30s/case、180s/batch、workers≤2、10s proof reserve、remaining不续期。DU10已实现41/41 PASS@97.68s（安静窗口），机器负载敏感。

### FF产品模块结论（scripts/）
- 产品代码无failpoint环境变量后门（符合R1，注入只能在测试边界）。
- FF不落盘任何回执/状态文件；回执都是子进程stdout/stderr JSON DTO，单次读校验即弃；重试都是全新子进程；回执身份绑定=request_id指纹匹配+manifest/canonical_identity对比+五键verified-open。
- 关键既有防护：acquire_exact下载前重查本地（transcript_lookup_changed绝不二次下载）；导入后失败不重试且保留用量（test_transcript_response_budget.py:47-88单元级已有）；transcript_import_hash_mismatch；_verified_open实读sha256。
- ET test-proxy（et_transcript_proxy.py）现有场景：success/worker_loss/entitlement_402/http_429/http_500/wrong_mime/stall/request_failure/wrong_symbol/wrong_quarter/oversize；用ET私有seam tests.test_retrieval_runtime:build_fake_session替换worker HTTP，W06_MATRIX_STATE JSON注入。

### R2故障点vs现状映射（A阶段结论）
| 施工卡故障 | 现有覆盖 | 矩阵级缺口 |
|---|---|---|
| provider返回后导入前失败 | 单元级已有（budget/du11 tests） | ET proxy无"成功后import前失败"场景 |
| 导入已持久但receipt/FF返回中断 | 无 | run_ff杀FF进程+二次同请求→reused 0下载 |
| ET子进程退出/截断JSON | 代码路径完备但无测试喂坏ET stdout | proxy加truncated_json/exit_crash场景+单元喂坏stdout |
| 错误身份/期间/材料hash | 单元最全+矩阵original_wrong_sha等 | verified-open回执身份键被换的矩阵case可补 |
| 旧/部分回执 | 回执身份绑定代码完备；DU67回放.partial治理 | 回执文件篡改后重读的直接case缺 |
| 再次请求/并发同公司期次 | transcript_lookup_changed单元级 | 矩阵级并发同请求case缺 |

## A阶段冻结（作者，2026-10-28）——设计决定

### 代码视图（R7）
- 已按DU10配方在FF工区`.w20-deps/{cwp,et}`重建：CWP `618df929`(src+pyproject,403文件) + ET `2584b7ee`(8文件最小闭包:transcript_tool/transcript_api/retrieval_runtime/transcript_extraction/retrieval_budget+tests seam)。cat-file全量字节核验0不匹配；manifest=receipts/dependency-record.json。拒绝复用.du10-deps（绑旧900dbf64）。ET最小闭包依据：模块仅env驱动配置、无仓内文件读取；ET全树17MB含transcripts/130文件(疑真实资料)故不取全树。测试后删除视图。

### 关键机制事实（B/C依据）
- ET假会话`get`记录先于stall落盘(tests/test_retrieval_runtime.py:169-180)→kill-before-durable判据=calls_file出现get记录。
- CWP导入时序：transcript_import.py先验证material.text_sha256==声明sha(:131)→staged→canonical→DB；source_query走SQLite。ET谎报sha会在CWP导入处被拒(transcript_import_rejected)，FF侧:1030 hash对比是第二道。→hash_lie场景两个结局都诚实，断言析取+记录分支。
- canonical文件+sidecar出现在import CLI内；FF其后还有verified-open子进程(≥1.5s)→"文件出现即杀"确定性落在FF退出前；是否已DB注册由恢复运行事后判定(reused=已持久/downloaded=未持久)。
- FF子进程树回收复用scripts/ff_process_tree.py(WindowsJob/KILL_ON_JOB_CLOSE,POSIX killpg)。
- 适配器fetch完成日志(adapter_invocations.log action=fetch)即"provider已返回、CWP导入窗口"判据→财报kill case无需改adapter。

### 实施设计（B/C）
新增（均在allowlist内）：
1. tools/offline_contract_matrix/w20_fault_cases.py——补充注册表(schema w20-supplemental/1)+9个case handler：w20_call_kill_before_durable(stall杀)/w20_call_kill_after_import(文件出现杀,分支记录)/w20_call_et_truncated/w20_call_et_exit_nonzero/w20_call_hash_lie/w20_call_stale_receipt(旧/截断回执不误读)/w20_call_concurrent_same(并发同请求)/w20_filing_kill_recovery(CN prospectus)/w20_filing_concurrent_cross_company(CN+HK同年并发)。复用CaseSpec/RunSpec数据类；ctx.active_case_spec机制可绑定补充spec。
2. et_transcript_proxy.py新增场景truncated_json/crash_after_result/hash_lie/stale_usage——全部在test-proxy边界对真实ET输出做后处理，不动产品。
3. cli_main.py加通用`--cases id[,id...]`显式过滤（注册表=41+补充并集）；selection进report.scope.selection{mode:selected,selected,completed,skipped}；未选=NOT_RUN具名reason；required_cases恒为41权威；选择运行exit 0仅当所选全PASS且selection一致；无--cases路径字节级不变。oracle.audit按selection分支（选择运行跳过全量coverage_gap、校验选择一致性；全量运行不变）。
4. seed_plan_for解析spec改为并集注册表（补充case多为全新FY无需warm seed）。
5. tests/test_w20_replay_selection.py（选择/标注/exit语义/RED：缩required_cases冒full、未选非NOT_RUN等）+test_w20_replay_faults.py（代理后处理纯函数+FF侧坏ET stdout/旧回执单元反证，复用DU11 FakeCWP seam）。
6. README补W20节。产品FF零改动预期（行为已正确则交付回归+no-code结论）。

### 明确不做
- 不改case_specs.py的41权威与_METADATA；不跑/不破坏41全量既有通过状态（DU10 41/41@97.68s为保留证据）；C阶段只跑补充选择+代表性base子集，全量41按卡R6/R8不重跑（如时间/负载允许可选一次，失败如实记录负载原因不追绿）。
- 结构化三表（W19 fetch_statements薄客户端）：独立CWP数据服务，无FF侧下载/导入状态，与中断恢复机制无关→不强加case，交接说明。
- 并发case不承诺exactly-once下载：并发窗口双GET是诚实可能；断言=最终恰一持久版本、无跨公司混用、无假成功、后续复用0下载（R3措辞）。

## C阶段真实链发现（作者，2026-10-28）
1. **ET非零退出双路径分类**（产品事实，非缺陷改判）：真实子进程非零退出→ChildFailed(TransportError子类)→FF归为`provider_result_oversized`；离线seam路径（DU11 FakeCWP直接返回code）→`provider_tool_failed`。两者都是具名、保留调用次数的拒绝。未改产品；W20 spec按真实子进程路径冻结，单测钉住双路径。root_followup候选：为非零退出单列reason。
2. **hash谎报实测**：ET谎报payload sha→CWP导入端拒绝→FF报`transcript_import_failed`（具名upstream_error、calls=1、无重试无假成功）。反证成立，预期reason表已收编该码。
3. **并发同请求实测**：两FF进程并发→一方导入成功一方具名`transcript_import_failed`（CWP规范写入唯一性），最终单一持久版本、回放0请求。无假成功、无重复版本。exactly-once下载未承诺（诚实）。
4. **组内durable判定污染**：kill/hash case的"是否持久"检查须按本case文件名差集，不能全wiki判断（先行case的导入会污染）。已修。
5. **cleanup Windows共享锁**：kill case的ET孙进程握句柄至自身deadline；harness清理加有界耐心（20×1s）+如实失败。一次restore=false为手动rm竞态瞬态，复现实验（前后快照0 delta）证明非稳态。
6. **宿主负载**：全天2-4×波动（W07已知）；3-run补充case与base chainA均间歇撞30s/case界→诚实PARTIAL。按R8停止追绿：9 case均至少一次真实链PASS（跨attempt互证，run-receipts.json全录17 attempt）；kill_before_durable第3段复用在所有全批窗口被负载阻断，最佳单attempt PARTIAL具名。
