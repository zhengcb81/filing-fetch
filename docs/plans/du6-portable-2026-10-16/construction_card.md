# ROOT启动记录：READY

本工区已创建；下方 PREPARING 为原施工卡起草时状态。以本目录 task_plan 和 ROOT launch 为准。

# DU6-FF-PORTABLE-EVIDENCE：给现有矩阵增加可搬迁的原生oracle重放

## 0．接单状态与工作目录

- **状态：PREPARING；等待 ROOT 创建真实工作树并把总表改为 READY。** 本卡不创建工作树，预定路径不代表可直接开工。
- 项目：`C:/Users/郑曾波/Projects/filing-fetch`。
- 已只读确认当前主线基线：`e2efa81d7995836d457479eb528fa6f8cd5dc3f3`，2026-10-16。
- 预定独占工作目录：`C:/Users/郑曾波/Projects/filing-fetch-du6-portable`。
- 预定分支：`codex/du6-ff-portable-20261016`，ROOT负责建立并登记。
- 本线 PWF：工作树内 `docs/plans/du6-portable-2026-10-16/`。
- ROOT负责整合、发布与跨线协调；本线正常commit后STOP，不改主线/安装副本。

## 1．目标与现存证据

已有W07把真实41场景离线 FF→ET→CWP 联调压至约90秒，CaseSpec、oracle、并发隔离、期限、fresh proof已交付，**不要重做这些功能**。

真正未解决的是接收材料的路径：`tools/offline_contract_matrix/cli_main.py` 把 `evidence_root` 写成绝对路径，`oracle.py::_bound_evidence` 在该根下实读相对request/response/fixture/ET receipt并验SHA。历史 `docs/handoffs/w06-ff-matrix/root_handoff.md` 已写明ZIP保留旧根，接收者要手工修改review copy路径。需要一个明确root override和公开重放入口，避免手改报告或重新执行供应商链。

**最简实现：现有oracle加可选root，现有CLI加replay分支。** 不新增pack格式、manifest、第二oracle、transport库、持久证据库、许可/签收文件或自动修复报告。复制既有artifacts目录用于搬迁试验即可。

## 2．实际布局与严格白名单

已核实当前布局：

- `tools/offline_contract_matrix/run.py` 底部调用 `from cli_main import main as _main`，因此现有公开 `run.py` 可直接承载新replay参数；无需改wrapper。
- `cli_main.py::main(argv: list[str] | None=None)` 当前由argparse要求 `--cwp-project/--et-project/--owned-root/--out-root`，默认正常矩阵最多2 workers。
- `oracle.py::audit(report)` 最后调用 `_bound_evidence(report)`；后者约212行读取report.evidence_root，并已做 `resolve()/is_relative_to(root)` 和实际字节SHA核对。

只允许写：

1. `tools/offline_contract_matrix/oracle.py`
2. `tools/offline_contract_matrix/cli_main.py`
3. `tools/offline_contract_matrix/README.md`（文档，不是新增source实现）
4. 新 `tests/test_du6_portable_matrix_evidence.py`
5. 自己的 `docs/plans/du6-portable-2026-10-16/**`

其余只读：run.py、runtime.py、CaseSpec/RunSpec、case_specs.py、matrix_cases.py、extended_cases.py、fixture/provider、source_proofs.py、report.py、measurement.py、旧tests/expected/fixtures、生产scripts/config、CWP/ET、供应商下载主入口、RF/Audit、CI/hooks、安装。最多两份既有源文件改动；不能以新工具目录规避白名单。

真实41链所需CWP与ET必须使用固定已提交版本的独立只读工作树，不能读ROOT正在改的未提交源码。ROOT在READY时填写/确认这些只读根和40位commit；作者仅将其作为 `--cwp-project/--et-project` 输入，禁止在其中写代码或运行Git更改。

## 3．冻结输入输出接口

### 3.1 Python

```python
audit(report: dict[str, Any], *, evidence_root: str | Path | None = None) -> list[Finding]
```

- evidence_root为None时与旧默认完全一致，继续取report.evidence_root。
- 显式override只改变现有相对artifact引用的读取根。传递到同一个 `_bound_evidence`，不能重写CaseSpec判断、SHA或业务oracle。
- 不修改传入report或任何输入文件；不能用全局变量/当前目录临时切换根，避免同进程调用相互污染。
- 复用原有包含性校验。相对refs、请求/响应原始SHA、inline response比较、fixture与ET收据核对、fresh source proof历史字段检查均保留。
- override不是新的身份许可；错误路径/文件/JSON/字节按既有Finding或明确CLI输入诊断返回，不制造授权状态。

### 3.2 公开CLI（冻结为本卡目标）

```powershell
python -B tools/offline_contract_matrix/run.py replay --report ABS_REPORT --evidence-root ABS_ARTIFACTS --output ABS_NEW_REPLAY_JSON
```

- `main(argv)`先区分显式`replay`分支；其余旧argv原样走现有矩阵。旧正常运行参数、WORKERS、30s/case、180s/batch和proof reserve不得改变。
- replay不要求CWP/ET/owned-root参数，不调用Context/seed/provider/runtime import绑定/fresh reader，只读保留证据并调用原生audit。
- 不覆写原report、原artifacts或已有replay输出；新输出用明确独立路径。
- 新输出是小型 **`ff-matrix-evidence-replay/1`**，不是第二份矩阵报告：至少记录原report字节SHA、原schema、选择的evidence_root、原case结果计数、原recorded oracle/findings、当前native replay findings、明确历史重放scope、退出状态。原case行不重标PASS，未知usage不改0。
- 退出0仅在原完整矩阵各case都PASS、原oracle确实通过且无历史findings、当前native audit亦无findings时；原FAIL/PARTIAL/NOT_RUN、原recorded findings不能因路径修好被升级为成功。输入/输出错误返回明确非0，不能traceback冒充业务失败。
- replay只能证明现有保留字节与当前oracle的结果；不能称重新读取生产原文、重新下载、重新跑41链或认证真实供应商/公司数字。
- 原始report对象、cases、cost、unknown、elapsed、source_proofs和recorded findings保持不变；绝不靠篡改report.evidence_root让原文件“适配”。

## 4．A：TDD与旧默认冻结

先读本卡、现有README、W07交接、旧CaseSpec/oracle测试；记录HEAD/白名单，不能读取`config/FMP_API_KEY.txt`内容。

在新测试中冻结：

- 未传override时原 `audit(report)` findings精确保持。
- 同一份原report在另一目录完整复制artifacts后，显式override能调用同一native audit；原report字典/文件SHA不变。
- CLI replay分支不要求生产code-root，不启动Context、seed、provider、CWP、ET或网络。可用禁止启动的负控验证，不只断言一个布尔“offline”。
- 正确受控报告/refs应通过；一个case的组件正控不能冒充完整41矩阵通过。

先写目标行为RED：旧oracle拒绝override/旧CLI无replay要单列接口RED；搬迁后原始bytes保持而旧根找不到的行为另列，不把缺API本身称为生产缺陷。

## 5．B：两处接线与一次集中快测

只在现有oracle参数链和CLI dispatch实现，不增加新pack/unpack框架。沿用相对refs与SHA，不复制业务验证。

必须负控：

1. 单字节篡改request/response/fixture/ET usage/result receipt；已有inline response与文件不符。
2. 文件缺失、错误root、指向目录的ref、非法JSON、未知report schema、路径越界；不能自动搜索别的磁盘目录或回落旧绝对root。
3. 原FAIL/PARTIAL/NOT_RUN、原recorded oracle finding、未知费用/null、缺fresh proof，均不能升级；移除/重复/未知case仍由原CaseSpec覆盖oracle拒绝。
4. report/case/expected/hash字段不能被CLI重写；新输出若和输入同路径或已存在则拒绝，不留下半份“成功”报告。
5. 旧无override的oracle及正常matrix CLI参数仍兼容；参数顺序和`main(argv)`可测试，不改case上限或deadline求绿。

集中命令：

```powershell
python -B -m pytest -q -p no:cacheprovider tests/test_du6_portable_matrix_evidence.py tests/test_w06_contract_matrix.py tests/test_w06_matrix_runtime.py tests/test_w06_case_authority.py tests/test_w07_matrix_efficiency.py --basetemp <OWNED_TEMP>/pytest
```

Ruff只检查实际改动源与新测试；不对旧源码/旧测试做无关格式化。没有必要时不增加更多小节点复核或每次commit跑41链。

## 6．C：一次真实41链，然后搬迁重放

READY后ROOT给出的已提交CWP/ET只读代码根必须记入本线receipts，连同本FF分支HEAD/关键模块SHA；先验证真实import位置，不能假报父仓HEAD。使用普通新完整checkout，不能遗漏ET已有测试proxy依赖。

```powershell
python -B tools/offline_contract_matrix/run.py --cwp-project ABS_PINNED_CWP --et-project ABS_PINNED_ET --owned-root ABS_NEW_SCRATCH --out-root ABS_NEW_RUN_OUTPUT
```

这是现有矩阵参数，实际输出是runner新建的attempt子目录；以真实stdout定位report/artifacts，不猜目录名。原41场景及oracle不改，0真实provider/LLM/翻译。保留完整真实结果；若因固定版本不匹配失败，交具名证据给ROOT，不换expected或扩大timeout。

真实41链在此大节点运行一次即可；随后：

1. 对该次实际report/artifacts记录SHA，完整复制到另一深度且含空格/中文的本线owned目录。这里只是测试复制，不添加持久pack/manifest机制。
2. 在另一目录，用CLI replay显式指定搬迁后的artifacts，记录原报告SHA不变及findings/原case状态一致。
3. 原数据scratch已由矩阵自身清理。使原artifacts根不可用（仅移动/删除本次自有复制/新产物，绝不动历史证据），再重放同一份**未修改**report，证明没有偷偷回落旧根。
4. 在独立复制中只篡改一处response字节再replay，必须非0且原生SHA Finding成立；失败证据保留，不能改原成功样本。
5. 原FAIL/PARTIAL或既有可移植失败fixtures也走replay，保留原findings，不把可读/可搬迁等同业务通过。

接收侧只保留小型report/stdout/stderr/重放JSON与必要相对artifact证据。不要复制原文湖、依赖工作树、环境或字节码cache到交接。若持久结果较大，明确每类字节数并删本次可重建scratch；不能损毁原历史报告以节省空间。

## 7．隔离、清理与边界

- 原FF配置/key、CWP原件与catalog、ET生产transcripts保持只读；真实密钥文件只允许stat存在性/大小/mtime，不读/复制/打印/hash内容。
- 测试所有输出在独立OWNED_TEMP，保留sentinel。设置`PYTHONDONTWRITEBYTECODE=1`，使用矩阵现有合成环境/网络与翻译guard；不要添加新权限门。
- 若测试环境带RF runtime，任何import/formal调用前把`REVENUE_PUBLICATION_REGISTRY`指向本次TEMP；本卡不需要RF调用，最优是完全不import。
- 运行前后比较原report/artifact字节SHA、依赖关键源码SHA、生产metadata和sentinel；已有输入/目录恢复原样，起初不存在的测试下载/输出/Temp须删。只删除已确认属于本次、解析后位于OWNED_TEMP的路径。
- 正常/异常均回收本次子进程，沿用现有runtime，不添加第二进程管理器。保留失败与未知记录，不盲目反复重跑41链。
- 未stage/commit/发布之前的中间工作写自己PWF；作者不写总README/总PWF，不动其他线目录。

## 8．交接合同

`handoff.json` 使用 `schema_version="du6-handoff/1"`、`card_id="DU6-FF-PORTABLE-EVIDENCE"`，沿DU5字段：base_commit、branch、implementation_commits、changed_paths与最终SHA/必要性、entrypoints、interfaces_reused/可选root兼容、red_receipts、tests实际argv/exit/count/time、真实41链固定依赖commit/模块SHA、fixtures/输入report SHA、原结果和replay结果、old_failures_preserved、supplier_calls、production_writes、cleanup_receipt、known_limits/not_run、root_integration_steps。

必须声明“retained-evidence replay”与“fresh真实41链”各自scope，不能把重放认证成新下载或新SourceVersionReader实读。不引入人工授权JSON/签收/新manifest；ROOT正常验收并线。作者正常commit分支后STOP。
