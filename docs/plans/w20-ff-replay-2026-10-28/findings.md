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
