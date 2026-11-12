# MB-FF — 独立施工卡

## A0：旧分支/未提交改动的接收状态（2026-11-11新增）

先读总计划 `reconciliation.md` 和 `review/repo_reconciliation_20261111/acquisition_review.md` §3/4/5。ROOT已将B34逻辑候选显式null发布日期修复接收至main `d563b630df887219039b9340703217b68da48c69` 并推送，最终反例保留当前form_type/fiscal_period/source_market/issuer绑定。176项相关回归及最终23项B34通过，独审PASS；CI清单随后在`ac798a2`接入同一回归（38项通过，日常smoke不变）。不要再cherry-pick旧53285c2或整合旧B34树。

旧 `codex/ff-job-facade-01` 的7个cherry+已被57351d0/7d8392e接收，不是7个新需求；旧job工区6个重复源码/测试已精准restore，协议两处语义也已吸收。`codex/transcript-companion` 原型由正式ET transport替代，不得带回猜目录逻辑。FF三处pytest/空placeholder/三个空Temp工区已清理。

A0剩余：将旧job协议差量、W06的两份过期PWF与六份输入、W07唯一首失败/最终/时序收据归档后给ROOT回收清单；不把旧16-case完成声明覆盖ROOT后续41-case证据。`.ff_jobs`是业务作业状态，配置密钥、工具状态和记忆保留，不当垃圾。上述整理不引入第二job库，也不扩成产品许可。随后按原六operation/安装隔离目标执行本卡；允许NO_CHANGE_PROVEN。

## 任务定位与唯一工区

- 原仓：`C:/Users/郑曾波/Projects/filing-fetch`；基线 `ac798a250b2310e0c2714053b08246ad94fffd0c`；目标主线 `main`。
- 新工区：`C:/Users/郑曾波/Projects/mb11-ff`；分支 `codex/mb11-ff`。本卡尚未开工，不把准备好的卡称为已派发。
- 本仓PWF：`docs/plans/mb11-ff-2026-11-11/`。先建立 task_plan.md、findings.md、progress.md，记录真实基线与工作量；本卡及公共接口说明可复制到该目录inputs。
- 总控计划：`C:/Users/郑曾波/Projects/company-wiki/docs/plans/module-boundaries-2026-11-11/`。开工只需读本卡、该目录 interfaces.md、acceptance.md、runtime_verification.md 和本仓AGENTS；无需回放旧聊天/全部历史PWF。

```powershell
git -C 'C:/Users/郑曾波/Projects/filing-fetch' worktree add -b codex/mb11-ff 'C:/Users/郑曾波/Projects/mb11-ff' ac798a250b2310e0c2714053b08246ad94fffd0c
```

若工区/分支已存在，先只读核归属；不能 reset、清别人的目录或接管未知工作区。可以用新的唯一后缀并记录。用仓库实际可用的Python/离线依赖；不要重新抓取原件或部署到全局技能目录。

## 全卡共用完成规则

- 先列本仓实际交付runtime的活动入口、逻辑模块、公开面、状态owner和依赖方向；包含兼容/退休分类。确认缺口只是入口，不是允许忽略其他已登记模块。发现同根绕行在本卡owner内归并修复，新增业务需求交父计划。
- 保留现有公开协议；各模块只写自己代码和状态。公开协议真需要改时先把失败例和最小兼容方案交ROOT协调，继续其余独立工作；不擅自改邻仓。
- A写行为/隔离测试 → B修owner根因 → C模块验收。A/B/C是工程步骤，完成A即可继续B/C，不需ROOT或用户逐步批准。
- 接口负例应体现实际能力/依赖错误；fixture/缺依赖/沙箱权限失败不冒作产品RED。已有边界通过就保留，不为凑改动重写。
- 只在模块最终交付前调用独立审查agent，审完整度、架构归属、回归和所有新增测试。修复所有本卡可行动问题并复核，才交付；非本范围新发现明确列给ROOT。
- 测试用新临时目录，恢复初始状态；生产原件/配置/既有WIP不动。只运行受影响测试与必要最终包级CI，不每小步重跑全量，不删断言换绿。
- 提交并推送自己的交付分支（存在remote时）；不自行合并主线、不修改ROOT总PWF。交付本仓PWF下 handoff.md/json、独审报告、测试/恢复证据索引，格式见总计划handoff_contract.md。

## 目标

FF已有WikiConnection、pathless v2和TranscriptTransport，不重建。完成六类CWP operation与ET的独立启动/请求组合隔离，收敛一次请求的配置和连接组装，证明公开结果不依赖邻仓源码布局。调查报告 `review/acquisition_architecture.md` 的ACQ-S1/S2/T1是结构/证明缺口，尚非真实业务失败。

## 写入范围

- 默认测试：`tests/test_decoupled_connection.py`、新增`tests/test_public_operation_isolation.py`、`tests/fixtures/public_operation_isolation/**`、`tests/financial_statements/test_fetch_statements_subprocess.py`、`test_layer_boundary.py`；必要`tools/ci_tests.py`登记。
- 对应owner改造限 `scripts/ff_company_wiki_connection.py`、`ff_configuration.py`、`fetch_filing.py`、`ff_financial_statements.py`、`transcript_tool_transport.py`、`transcript_companion.py`，以及确需的本仓纯端口/请求context模块。稳定CLI薄包装可调接线，不整体搬scripts。
- 只写本仓PWF；不改job持久化语义、生产`config/company_wiki.json`、密钥、ET/CWP/SID源码和全局skill。

## A/B/C

1. A：六类operation catalog/query/local_prepare/open/transcript_import/financial_statements在tmp中使用显式fixture command。移除邻仓PYTHONPATH和生产配置，cwd为空；真实subprocess调用filing/statements/job，query hit不启动provider、miss→prepare→query/ensure最多一次。
2. A：提供独立ET command/interpreter/cwd测试；请求context不应对同一部署配置重复加载得到不同connection。原`.py`路径+当前解释器的旧配置仍兼容，不能在业务请求里新增任意命令执行字段。
3. B：先看RED指向的真实owner。如果现有实现已能满足，交付证明而无需改代码；否则将连接/启动descriptor统一在FF composition root注入已有transport，业务层只看operation/typed结果，不看provider目录。
4. B：statements只调用CWP公开三表；ET返回usage后即使import失败仍保留已知消耗，unknown不当零；成功/partial/gap/错误版本保持现有语义。可选大诊断不遮业务stdout。
5. C：对真实FF交付runtime运行同样suite，不强制新建wheel或改安装体系。job reuse/reconcile不重做下载；独审并修复。

## 测试入口

```powershell
python -B -m pytest tests/test_decoupled_connection.py tests/test_source_ref_v2_db_query.py tests/test_ff_job_facade.py tests/test_transcript_companion_transport.py tests/test_transcript_owner_budget.py tests/test_failure_usage_continuity.py tests/financial_statements/test_fetch_statements.py tests/financial_statements/test_fetch_statements_subprocess.py tests/financial_statements/test_layer_boundary.py -q -p no:cacheprovider
python -B -m pytest tests/test_public_operation_isolation.py -q -p no:cacheprovider
```

第二个文件为本卡拟新增；若已有等价测试则在handoff指出映射。完整现有CI按模块大节点执行一次。交付source/ref/usage/错误的公开小样例供ROOT组合，不能借fixture重新实现CWP或ET。

## 出口

六operation、ET独立命令及一次请求配置归属均有证明，当前CLI/wire不变；无邻仓代码可见也能工作，真实不支持operation具名失败且不猜目录。没有缺陷的部分允许`NO_CHANGE_PROVEN`，必须附实际测试依据。

## 并线交接步骤（目标分支：FF `main`）

1. 作者提交并推送卡片分支，交付最终tip、精确diff、包级测试、独审绑定tip及测试目录恢复记录；不把未提交工作区当成卡片交付。
2. ROOT在独立集成工区核对最新 `origin/main`、提交祖先关系与本卡写集合，只接收交付提交；保留其他工区未提交文件、provider配置和`.ff_jobs`状态。
3. 在集成后FF树集中运行本卡受影响suite一次。若冲突解决改变源码，测试和独审绑定最终代码tip；不整树覆盖、不删未登记状态。
4. 通过后由ROOT推送 `main`，在本卡handoff与总控reconciliation记录实际SHA、测试和状态`MERGED`；具体失败交回FF作者，不扩成跨仓私有调用。
