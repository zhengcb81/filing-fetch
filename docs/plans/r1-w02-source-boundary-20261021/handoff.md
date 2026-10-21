# W02 交接：来源业务失败与独立电话会结果

状态：**ENGINEERING_GREEN_READY_FOR_INDEPENDENT_ROOT_REVIEW**。不是W07来源覆盖/研究质量/整个PWF完成。产品冻结：FF `ed7188616a87369690b6a90ebf40c7b0d829d950`；RF `809a80f2341156421b87b7e0b945badca6c96e27`。两个工区均为 `codex/r1-source-boundary`，未并主线、未推送、未安装。

## 已实现

- FF三个有界适配入口正确消费 `ChildFailed` 的完整业务JSON，不再把 cold catalog / local_candidate_limit 丢为 transport failure；不改通用process层。原exit单列为 `producer_exit_code`。
- 当前operation1.0的 `local_preparation` 与 `blocked` 闭合验形；非JSON、截断、数组、错action/request、unknown字段与物理位置仍拒绝。
- filing先失败时，精确请求的companion是 `not_run`，保留FY/Q/provider/intent/原limits，明确0请求；未请求仍 `not_requested`，未解期仍 `period_unresolved`。不假称ET/FMP不支持。
- RF两次进程传递保留 `companion_observation`、原exit和完整安全FF failure sidecar `filing_fetch_result`；不复制任意stderr。
- 原有source-clock只增加 `current_verified_open` basis。公共2.2reader→RevenueSourceRecord真实走通：publication仍null、今日合格、过去cutoff/未来publication/错SHA/无lineage均拒绝。

## TDD与集中节点

首RED：FF10失败/6通过，RF4失败/6通过。扩展型别反例又捕获3个新validator未处理的JSON field types，修正；其第四个失败是作者测试漏传既有必选参数，按真实API修测试。有效1800秒请求反例捕获意外600秒consumer cap，已去掉，沿用既有FF限额。

最终FF **307PASS/5SKIP +39subtests，47.84s**；RF **142PASS/1SKIP，29.71s**。两仓正常commit hooks的ruff/mypy/host guard全绿，未跳hook/删断言/加豁免。全部跳过node与理由见JSON。真实CWP→FF→RF离线冷catalog CLI链已跑：合成HK快照、空公司目录、实际三个代码入口，`exit2/catalog_unavailable/not_run/Q2/0ET请求`保留。此链不是正式下载、模型或原文内容C验收。

新FF指纹夹具由真实 `SourceRequest` 生产，覆盖HK exact、US latest、CN大小写规范化。指纹只是当前请求的协议绑定，不重新解析公司身份或原文字节。

## 安装与CI接线（ROOT）

只同步JSON中6个FF runtime文件和4个RF runtime文件；新import `ff_source_failure.py` 必须一起装。逐目标旧SHA与专家基线均保留，ROOT实际plan/apply/check，配置/output不覆盖。

两个CI是显式表，ROOT集中加两行：FF `tools/ci_tests.py:CI_TESTS` 加新FF测试文件，RF `tools/pre_push_gate.py:SMOKE_TESTS` 加新RF测试文件。小型本地反例默认约3s/1.5s；真实跨仓大节点需显式两个环境变量，不在日常CI强行运行。

## 保留与清理

0网络、0API、0模型、0下载、0费用/账本改写；生产原件、配置、Dayu、安装、封存initial与四审未改。13个独占pytest临时目录已删除，共2,634,041 bytes，测试夹具恢复初始不存在；留有逐目录清理收据和有界日志/XML。未测scratch峰值，不冒称上限实测通过。

## 剩余与下一步

ROOT独立审两个精确产品版本→修问题→集中CI表接线/合主线/安装→W07真实公司资料链与四路审查。

ROOT新发现的unknown publication叙述口仍有同根因：RF `company_wiki_narrative_contracts._manifest` 与receipt exact需要W03的一致optional availability扩展；本包未抢改该接口，也不声称已覆盖。已知发布日期的原年报路径不受该剩余项影响。

机器交接、文件SHA、安装旧SHA、完整测试命令和收据：[handoff.json](handoff.json)。母包仍为 `revenue-forecast-audit/runs/r1-20261021-cn-wuxi-apptec/remediation`，本目录为本包交付证据，不新增竞争总计划。
