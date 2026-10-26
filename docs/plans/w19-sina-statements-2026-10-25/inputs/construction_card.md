# W19-SINA-STATEMENTS：A股历史三表 API、CWP存储、FF调用

**这是完整独立施工卡，可交给一个新 harness。** A/B/C三大节点即可，不等待ROOT对小步骤签收。交接前必须调用独立审查agent，全面检查完整度、架构、数据与测试质量；所有实质问题修复并复审通过后才交接。仅完成parser、mock、SKILL说明或三表中的一张都不算完成。

## 0. 目标、工作目录、上下文

给公司名/证券代码，经既有识别一次，读取新浪公开接口的历史利润表、资产负债表、现金流量表；CWP保存带来源的规范化数表，FF提供可实际调用的入口并在技能里正确路由，第二次相同请求优先本地复用。

| 项目 | 本卡独占施工目录 | 分支 / 基线 |
|---|---|---|
| CWP：API引擎、存储、公共查询 | `C:/Users/郑曾波/Projects/company-wiki-w19-sina-statements` | `codex/w19-sina-statements-20261025`；源码基线243993d2c9e12c2a9cb6e2b728e547928607abff |
| FF：薄客户端、SKILL、跨仓测试 | `C:/Users/郑曾波/Projects/filing-fetch-w19-sina-statements` | `codex/w19-sina-statements-20261025`；源码基线e0d96426445e4b93bc6cc7a6e6014996ad0a777d |

CWP为主工作目录，选择 `PLAN_ID=w19-sina-statements-2026-10-25`、`PWF_PLAN_ROOT=docs/plans`。本卡随同研究报告和原始响应夹具复制到该计划的`inputs/`，使用工区内独立上下文，不依赖ROOT日后变化。工作区实际初始化记录见同目录`W19-setup.json`；没写ready就不能假设目录已创建。

先读两个仓库适用AGENTS及本卡。适用技能：planning-with-files；FF按其现有SKILL行为。维护本卡自己的task_plan/findings/progress，不写ROOT当前状态/PWF，不启动收费模型。

### 不与已发三卡冲突

- W16只改RF；W17只改Audit；W18只改CWP `tools/holdout_replay/**`、`tests/holdout/w18/**`及自己的计划。本卡不进入这些目录。
- ROOT继续CWP HTML/PDF原生结构、`document_understanding/**`、`source_catalog/narrative_*`和真实摘要/cache链；本卡**不修改这些生产路径**。
- 本卡CWP独占新增 `src/company_wiki/source_catalog/financial_statements/**`、`tests/financial_statements/**`、本卡PWF、`delivery/w19/**`。
- 必需窄接缝限：`source_catalog/store.py`及`models.py`的三表DDL/版本迁移；`canonical_writer.py`的第三方多期间原始字节入口；以及新增类型确需的既有source metadata/registration/reader接缝。ROOT本节点不改这些接缝；作者只做本功能必要增量，在handoff逐项列明。不得借此大改writer、resolver、通用SourceRef或整套metadata策略。
- FF独占新增`scripts/fetch_statements.py`及`ff_financial_statements*.py`、`tests/financial_statements/**`、本卡PWF；允许修改SKILL.md加入真实可执行路由。优先复用现有配置/有界进程；只有证实共用代码不能直接用时，才对`ff_configuration.py`/`ff_process_transport.py`作必要兼容提取并测试旧消费者，不复制第三套实现。
- 不修改RF/Audit/StockWiki/Dayu/IQS/StockInfoDLSimple/ET，不同步用户安装技能副本，不合并主线；ROOT接收后统一集成和定点同步。两个工区不能用同一Git index或在别人的主目录施工。

## 1. 已完成调查，直接沿用

完整报告及真实响应在`inputs/research/`。原总控位置：`docs/plans/du11-source-closure-2026-10-18/review/sina-statements-research-20261025/`，不要把历史HTML壳当有数据的三表。

```text
https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022
?paperCode=sh688012&source=lrb&type=0&page=1&num=10
```

- `source`: `lrb`利润、`fzb`资产负债、`llb`现金流。
- `type`:0全部、4年报、3三季报、2中报、1一季报。`page`从1开始；已验证num10和num2，不赌大num无限历史。
- `result.status.code=0`不充分，必须检查`result.data`及report_date/report_list。中微无效第5页与无效证券都可能HTTP200/code0/data=null，前者可为分页终点，后者为not_found。
- 本次全历史：中微lrb36期、fzb33期、llb36期，均2016-12-31至2026-06-30；各表分别4页。美的lrb、招行fzb、平安lrb有单页异构样本。BJ及母公司口径尚未验证，不能写全市场覆盖PASS。
- 原始API快照18份gzip共175,785B。研究20次请求共2,634,389B，无生产目录/库写入、无LLM。`gzip`仅夹具压缩；SourceRef仍应验证实际生产存储字节，不能把压缩SHA与解压SHA混用。

## 2. 架构：一份提供者实现，存储只属于CWP

```text
公司历史三表请求
    ↓
filing-fetch fetch_statements.py（配置/请求/有界进程薄客户端）
    ↓ pathless JSON
CWP financial_statements CLI/service
    ├─ 复用既有公司识别owner一次（内部传DTO，不重复证明身份）
    ├─ 本地完整范围命中 → 公共数表查询，0 HTTP
    └─ 缺失/显式刷新 → Sina provider → 原始JSON/SHA/来源版本
                                     ↓ 唯一canonical writer
                             既有目录湖 + source catalog
                                     ↓
                 financial_statement_versions + financial_statement_values
                                     ↓
                 三表只读API/JSON导出 + SourceRef/JSON Pointer
```

不另建身份库、任务库、收费账本、可变共享研究数据库或本地HTTP常驻服务。API先做可导入Python服务与JSON stdin/stdout CLI，供FF调用；“API”不要求HTTP服务/MCP服务器。数据表属于资料存储，不产生估值、评级、目标价或投资accepted/rejected结论。

建议模块：`contracts.py`、`sina_provider.py`、`normalize.py`、`repository.py`、`service.py`、`cli.py`、`schema.py`；按责任组织，避免巨型抓取脚本，也不为每市场另开重复引擎。本卡先支持CN/sina；留标准provider边界即可，禁止无需求引入一堆供应商。

### 2.1 提供者职责

- 只构建固定新浪端点及经过一次既有识别的交易所+代码，禁止用户任意URL；SH/SZ/BJ编码来自已有证券DTO，不靠首位数字猜。已有安全/身份处理复用，不叠加新的人工许可、私有根、授权JSON、canary、逐文档签收。
- 一次采集共享字节/绝对截止时间/费用上限，使用既有AcquisitionBudget或可兼容的同一个对象，不按每页重置预算。每表有有界max_pages（默认64，可收紧），检查重复页、分页不前进、count变化和报告期唯一性，禁止无穷`while True`或按固定12次结束。
- 读取期间落实响应字节上限和截止时间，不能先无限read再检查；无key、无LLM、无购买。403/429及时返回命名结果；有限瞬时重试必须计入同一deadline/HTTP数/字节，不能藏第二套重试。
- 每张表独立结果；一表失败不回滚已保存的其他有效来源。不把partial改成complete；原始页保存后规范化失败可从该SourceRef重放，不再联网。
- 记录真实HTTP请求数、响应字节、费用0、阶段/耗时；遇未知只记unknown，不用“provider_calls=1”冒充12个实际HTTP。

### 2.2 原始来源及空间

- 第三方`provider=sina_finance`、publisher新浪财经，`document_kind=financial_statement_dataset`（名称若与当前受支持类型冲突，在A节点确定唯一同义名并写接口）。不得标official，不伪造一个财政年代表多年度页。
- 现有`DownloadCandidate`强制单年；`import_original_staged`固定official。将“已校验来源元数据+原始字节”的必要能力泛化在**原CanonicalSourceWriter**内，复用唯一`_commit_staged`/去重/SourceRef机制；不要修改原filing的单年语义或创建第二个原件writer。
- 实际响应原字节只在CWP保存一份；初版采用标准可回读的JSON原件。不要为压缩另改全仓SourceRef字节含义。夹具可gzip，生产若以后要压缩必须有独立的公共reader契约，本卡不以此扩范围。
- 相同规范化报告内容再次刷新，不为变动的HTTP时间/外层响应时戳反复保存同内容业务版本；无新数据时复用已有SourceRef并只更新必要last_checked观察。报告内容/期间/口径/修订元数据改变则保留新版本，不能覆盖旧快照。
- 初次只抓请求所需历史范围，明确`all_history`才完整向前翻页；不要批量抓全部A股、不要每个科目一个原文件、不要每个读取生成CSV/MD/缓存副本，也不送叙述切片/摘要worker。
- C节点测量中微全历史原件+SQLite新增占用及重复查询增量；本例初次新增总量目标≤16MiB，重复完全相同请求文件数/业务版本/值行数/字节不增长（必要last_checked和SQLite固定页/WAL变化单独列明）。超标先查重复表示，不能悄悄抬目标。测试交付夹具总≤2MiB，日志/报告≤5MiB，不提交数据库、完整原件目录或依赖环境。

## 3. 冻结接口（同一个harness负责上下游两侧）

### 3.1 外部请求

FF新增命令：`python scripts/fetch_statements.py --config <既有company_wiki.json> --request-file <JSON>`；支持stdin，成功/partial/gap都输出一份JSON。CLI/library调用走同一请求验证和服务。

```json
{
  "schema_version": "financial-statements-request/1",
  "company_query": "中微公司",
  "market": "CN",
  "statements": ["income_statement", "balance_sheet", "cash_flow"],
  "report_types": ["annual", "semi_annual", "q1", "q3"],
  "period_end_from": "2016-01-01",
  "period_end_to": "2026-06-30",
  "knowledge_mode": "current_snapshot",
  "as_of_date": "2026-10-25",
  "intent": "fetch_if_missing",
  "acquisition_limits": {"max_bytes": 8000000, "timeout_seconds": 120, "max_cost_usd": "0.00"}
}
```

- `intent=reuse_only|fetch_if_missing|refresh`；reuse_only零网络且不需要acquisition_limits；有采集必须带既有三限额，不加allow-download第二重人工开关。refresh为明确刷新意图，沿用任务授权，不是签收文件。
- 可选`all_history=true`与`period_end_from`互斥，仍在同一资源上限内。默认合理范围由显式请求决定，不硬编码最近三年或中微最早日期。输出有范围/分页覆盖，达到限额后诚实partial。
- `knowledge_mode=current_snapshot`是今天取得的历史报告数值，允许查询历史period_end但**不承诺历史时点已知**；`point_in_time`只使用有真实capture时点/版本证据且不晚于as_of的本地版本。今天抓来的历史数据不能因publish_date早就用于过去as-of；不足返回`historical_asof_unverifiable`。不将此诊断升成全局人工门禁。
- 复用已有公司识别一次。建议CWP入口执行，FF不先识别再要求CWP重复识别；请求中公司名与hint冲突才报明确问题。底层接收已解析的DTO，无权限token/签章流程。
- CWP命令：`python -m company_wiki.source_catalog.financial_statements.cli --wiki-root <连接根>`，stdin上述JSON。FF只使用现有配置定位CWP，不走目录扫描、不直接读/写SQLite、不复制provider。
- FF SKILL增加“要历史三表数值→fetch_statements；要原始财报/叙述→fetch_filing”可执行步骤、例子、partial/历史as-of说明。公司任务既要原件又要三表时调用两条已有入口，各自独立结果。不要把普通PDF下载强制附加全历史三表请求，也不要只写文字而没有CLI联调。

### 3.2 返回

使用`financial-statements-response/1`，至少包括：request范围、一次解析的company identity、`status=complete|partial|not_found|unavailable`、逐表同类状态、provider、`knowledge_mode`、`point_in_time_quality`、coverage（advertised/observed/selected报告数、页数、首尾、缺口原因）、真实usage、来源引用、规范化版本和行数据。单表无数据不能输出三表complete。

每个报告有：`statement_version_id,statement_type,period_end,period_kind,period_start(可null),consolidation,currency,provider_rType,provider_publish_date,provider_update_time,retrieved_at,source_ref,source_locator,normalizer_version,quality_flags`。每个值有：`row_ordinal,provider_field,label,raw_value,value_decimal(字符串或null),value_kind,unit,scale,provider_precision,json_pointer`。分组行和未知单位保留kind/标记；null/空/0区分。公共返回和引用不含raw路径、DB路径或配置物理根。

定位示例：`/result/data/report_list/20251231/data/7/item_value`，可从SourceRef原始JSON校验；不得只给一个找不到原值的Excel行号。此示例下标不是固定科目位置，测试从原数据定位。

调用者要少量行可用`fields`和`period_end`过滤；所有字段和分页导出同属一个公共接口，默认响应有行/字节界限，给continuation或partial，不能让FF有界stdout被全市场大表撑爆，也不能把截断结果称complete。

## 4. 数字与期间：必须写进代码和测试

1. Decimal解析原十进制字符串，SQLite以TEXT存精确值；不存float/REAL，不round成展示万/亿。`scale=1`只对已经证明原单位的字段；精度f2不是货币/数量单位。EPS需`CNY/share`，比率/数量/未知单位分开，未知不能猜。
2. 保留所有provider field和原标签；金融主体用其自己的科目。美的样本`BIZTOTINCO`与`BIZINCO`不同，不能合并。空field分组行、重复标签、负数、零、null、空字符串、科学计数法/非法数值分别测试，非法数值保留raw并诊断，不能造零。
3. `balance_sheet`用instant；利润/现金的年报/Q1/H1/Q3按原文核实期间。`rType=合并期末`并不能把利润表变时点。初版公开reported累计数，**不要求本卡做单季/TTM派生**；如果自愿增加派生，必须两输入引用/同口径/变更版本可追溯，负例拒绝，不扩大为RF模型。
4. provider发布日期/更新时间/抓取时间分开。2023报告publish_date=2025、2025fzb publish_date=2026-08的真实反例进测试；不改写为预想披露日。修订版与合并/母公司口径不得只按公司+日期覆盖。
5. 一次source SHA验真交给reader责任层，上层校验typed schema/期间/单位，不每格重做整份字节SHA。保存的是来源资料，不是公司投资判断。

## 5. CWP专门数据表与只读查询

同一catalog SQLite中采用**两张通用长表**，以statement_type区分三表，必要时提供三张只读view；不是三套固定数百列的宽表、不是公司wiki Markdown。

- `financial_statement_versions`：主键稳定版本ID；公司/证券、provider、statement_type、报告期、consolidation/currency、源元数据、canonical报告hash/normalizer版本、source_id与document_id、JSON定位、quality/coverage、真实capture时点。内容相同只复用，内容改变保留新版本。provider更新观察与财务版本分开，避免仅HTTP时戳不同就无限增长。
- `financial_statement_values`：FK版本ID + row_ordinal，provider_field、label、原值、Decimal字符串/空值分类、value_kind/unit/scale及JSON Pointer；provider_field允许空/重复，不用它做会丢行的唯一键。索引服务公司/表/期间/字段查询，不重复在每行保存整段原JSON。
- 对source/sourceversion使用真实FK和唯一约束。只有原始source已登记、规范化校验完成，报告版本和值行才在一个事务发布。半页失败不出现“complete但值表一半”的可见版本。
- Catalog schema1.2.0当前初始化会直接return。按唯一owner升级schema（如1.3.0，并把1.2.0纳入可升级版本），fresh/1.0/1.1/1.2的迁移与旧表数据保留、未来未知版本零部分写入、并发双初始化、故障rollback均要测试。使用现有DDL执行方式，不用executescript隐式提交破坏原事务。
- 查询真正read-only：无数据库/无新表时返回named gap，不构造CatalogStore造库/迁移；新schema写操作只在明确采集/重放入口初始化。复用已有reader连接/根配置责任层，根迁移后外部SourceRef/返回不变。
- 结构化数据源不进入LLM叙述worker，不能为每次fetch再做全文切片/MD/摘要；对新document_kind加定向回归证明这一点。

## 6. 实施与验收（A/B/C三大节点）

### A — TDD冻结需求与边界

核对实际基线、现有owner与本卡接缝，写自己的PWF。复制/验证18份真实响应SHA（gzip解压后比原SHA），不重新联网取同样fixture。先写中性RED覆盖normalize、分页、repo幂等/迁移、FF→CWP契约；记录真正RED，fixture坏/路径不存在不能冒充RED。补BJ一个有界真实样本（支持则测试通过，不支持则显式capability gap），禁止因此加新provider或改公司身份库。A文档写好继续B，不等ROOT人工许可。

### B — 按唯一owner实施

顺序：typed contract/纯normalize→provider分页→CWP原件和两表原子持久化→只读查询/重放→FF薄客户端和SKILL。共享实现不复制到FF。实际单公司lookup只做一次，第二请求命中0HTTP；至少一个原件移动到另一配置根再经相同公共引用读取的集成例。

### C — 集中验证、真实小样本、独立终审

**单元：** 精确数字/单位/空值、三表/不同科目、报告期/知识时点、JSONPointer、同key不同值修订、分页count与重复/无进展、HTTP200无数据、403/429、预算读取中停止、response过大与故障清理。

**集成：** fresh及原1.2库升级不丢旧数据、并发/故障rollback、两个根的SourceRef复用、原始字节损坏拒绝、数表缺失时查询0写、重放原始JSON零网络、相同内容不重复raw/版本、不同内容保留旧版本、非叙述worker不领这类数据。

**离线端到端：** 真CLI进程`FF fetch_statements → CWP service → fake HTTP/冻结真实响应 → canonical原件 → 专门两表 → 公共query → FF JSON`；不是单纯fake一个最终结果。中微全历史按冻结样本得到36/33/36，和9,729源行（含结构行/null）可对照；具体哪些输出数值行单列，不谎称全部是金融事实。重复同请求0HTTP且无新增版本/原件；一表失败两表可读且整体partial；输入范围/行过滤/continuation不漏行重行；严格过去as_of使用新抓历史快照应拒绝冒充PIT。

**真实有界端到端：** 使用独立测试根和真实FF/CWP CLI，对中微三表 + 一个非工业主体至少各一次（可小范围/num10），证明真实采集与二次复用；选另一个SZ/BJ或不同历史跨度作泛化。最多50公开请求/20MB/300秒，费用0、LLM0，不扫全市场。与已存在本地官方原件通过SourceRef核对至少三表各2项：金额/币种/单位/期间/合并口径；若官方原件缺失，只用已有正确工具在同测试根小范围下载并记录费用/字节，不能写生产。测试必须给出逐值expected/actual/原locator；不可把Sina和自己的解析结果互相比当作独立财务正确性验证。

**测试环境恢复：** 开始记录配置、生产库、原件指纹/存在性；测试创建独占临时根，所有新下载/DB/WAL/输出都只在该根。finally清理且验证恢复不存在；若复用预置fixture，前后SHA一致。不要完整备份/恢复生产库作演练，不删原件或历史作者文件。失败也收清理结果，不能靠吞异常显示通过。

**检查范围：** 只跑相关单元/集成/端到端及窄接缝的旧消费者；Ruff/mypy按仓现有要求，正常hooks。不要反复跑超时全量，不改CI阈值/删断言换绿。真实外部服务阻塞可交明确未完成报告，但不能以“全完成”交接或扩大权限门禁。

**独立agent终审必做：** 冻结两个仓的最后源码SHA和上述证据，独立agent从调用方实际运行入口审完整度、架构/无硬编码、全部三表/财务单位期间、迁移/存储虚拟化/去重、真实测试和清理。审查者必须独立运行至少一条完整FF→CWP→存储→查询/复用链，并加入至少一个作者未给的负例/突变；不能仅阅读作者日志。发现的实质问题全部根修、相关复验、独立复审后才交接。只对实现者自述盖PASS不合格；最后测试/审查必须绑定最终产品版本，文档收尾commit可后置但不得偷偷改已审源码。

## 7. 交接接口与停止位置

在CWP工区`delivery/w19/`交付`handoff.md`和符合旁附模板的`handoff.json`，关联FF工区的commit和具体变更路径；包括：

- 两仓基线、实现/交接commit、分支、remote/push状态、完整变更清单、ROOT需处理的窄接缝、无无关改动说明。
- 可复制的FF请求/响应、CWP调用命令、3类状态/partial范例、实际每表覆盖及数据含义、SourceRef/locator可回读证明。
- A真实RED、B绿、C离线/真实用例、逐值官方对照、请求/字节/费用及空间数据、独占目录恢复收据。
- 独立审查agent标识、范围、所有finding关闭证据、最终产品SHA绑定；保留首轮失败，不把旧版本收据当新代码通过。
- 当前不足（BJ/母公司/历史修订如不可验证）、没有声明实现的能力；0人工授权JSON/新身份库/LLM。
- 正常commit，可push作者分支但不merge master；root不保证FF和CWP同刻上线，能力缺失须named gap。记录FF/CWP新组合互操作与旧filing旧库兼容测试。

ROOT验收后按“CWP原件/表/公共接口先发布→FF调用/技能更新→定点安装同步→一次跨仓真实复用”接入；RF数值/模型采用后续由其责任层接手，**本卡不和W16重复造RF历史基数算法**。完成本卡后STOP等ROOT，不擅自把主线CF1–CF4/公司循环签收完成。
