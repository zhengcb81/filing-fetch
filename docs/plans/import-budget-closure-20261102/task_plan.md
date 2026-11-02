# FF仓内活动计划：最终入库预算闭合

状态：ROOT_DECOUPLING_SUBTASK / 属于集中解耦，不独立派发。PLAN_ID=import-budget-closure-20261102；PWF_PLAN_ROOT=docs/plans。
仓库C:/Users/郑曾波/Projects/filing-fetch；基线b3f0b9cceb87338c64dc8ddd698707f01ac6691a。
总控C:/Users/郑曾波/Projects/company-wiki/docs/plans/du11-source-closure-2026-10-18/review/architecture-reassessment-20261102/COORDINATION.md。

## Next Step

先按 C:/Users/郑曾波/Projects/company-wiki/docs/plans/du11-source-closure-2026-10-18/review/architecture-reassessment-20261102/DECOUPLING_FIRST.md 的D1固化公共端口/隔离测试；本文件仅细化其中采集预算子项，FF其他连接适配与测试解耦以总计划为准。不先按旧独立分工开工，不重做ET已完成预算修复。

## 已证问题

scripts/transcript_tool_transport.py:1000–1018调用CWP transcript_import_cli；该入库方固定16MiB原文/25MiB结果及base64帽，且请求包未传有效预算。17MiB原文虽在ET/FF显式22MiB额度内仍拒；2B原文配22MiB也拒。上轮只到ET worker的联调覆盖不足。

## 实施

1. 确认现有任务真实预算owner与请求字段，不由provider自报额度。CWP/FF配套让实际原文额度/剩余时间贯穿入库；必要追加预算字段需给旧请求明确默认与新旧fixture，不新增授权flag或签收文件。
2. 原文大小与base64/JSON表示分离，编码传输资源从实际额度推导；不能任意改成更大固定数。费用/下载response_bytes只在实际网络读取记一次，入库本地读取不能冒第二次provider费用。
3. 原文SHA/身份/期次/type/path、真正实际超额、unknown-paid、失败清理仍各归所属owner；导入失败保留真实usage，不自动重复下载。
4. 当前FF已修body/time/stdout门的受影响测试继续，不改ET provider实现/Dayu，不在FF重写CWP存储。

## 测试与交付

单元：实际预算传递、已知大receipt、预算超额和deadline。集成必须到末端：22MiB额度/合法17MiB FMP原始JSON（symbol、period、year、date、content），FF→ET真实CLI/supervisor+fakeHTTP→CWP import/writer→verified-open；原语言TXT为提取结果，保存和读出的原始JSON字节/hash一致，第二次复用0下载。反控超额度、错误identity/SHA、畸形结果、worker回收/失败清理。使用隔离catalog/AUTO/tmp配置，原始目录和生产config不写，清理恢复。
本节点一个集中跨仓独审，发现问题直接根修；不每函数签收。不宣称fakeHTTP是实网采集。正常提交/推送，本仓handoff链接CWP组合证据。ROOT之后做T4/新真实摘要与RF采用。
