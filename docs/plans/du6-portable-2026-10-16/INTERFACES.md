# DU6 接口、隔离和交接

这是工程分工说明，不是许可链。用户既有处理授权继续有效；本轮三卡离线，0供应商调用，不创建 authorization/canary/人工签收。

## 启动与文件所有权

1. 只在总表指定的独立工作目录启动，读本卡副本、task_plan 和本文件。核对实际 branch、base 和状态。不要在主仓或旧 DU5 工作树施工，不重置解释不清的修改。
2. 每条线只能改自己的卡列出的精确白名单及自己的 PWF；不改兄弟仓、CWP、共享总计划、配置/凭证、生产原件、AUTO、registry、CI 或安装目录。需要白名单外接口时提交具体反例和建议给 ROOT，继续能独立做的部分。
3. ROOT 接收前冻结 RF 目标计量清单、AUDIT 新 importer 范围、FF 两个矩阵工具源文件。任何外部改动先核对，不自动覆盖。
4. 自己源码的 import 必须指向本工作树，禁止全局 editable install。测试使用当前仓 runner，不另造测试平台。日常快测，B/C 集中回归和真实 CLI；不每 commit 全仓跑。
5. CodeGraph 用于结构调查；无索引按 AGENTS 处理。已点名文件可以直接读，不能因索引缺失宣称代码不存在。

## 冻结边界

- RF：原 normalize_target_bounds、compare_target_measurement 结果形状、builder 缺省语义及历史 typed 合同。新 signed 目标必须由明确 typed 输入进入，原文不改；同币缩放和跨币 FX 分开。无证据的 CC/净额/季度桥不猜。
- AUDIT：已发布 NarrativeBundle /2、/3 和 EvidenceSpan，转换到现 summary-review-map/1；每条 claim、support/context 和原语言不改。只给 bundle 时不得冒认全文召回；完整性不足给范围和 unknown。原 reader/packet/attach/compare 复用，不新语义评分器。
- FF：audit(report, *, evidence_root=None) 默认兼容，replay 只重定位既有相对 artifact，实际 SHA/CaseSpec/原 findings 和未知 usage 保留。不得因搬迁成功升级历史 FAIL；不新 pack 格式、第二 oracle 或持久证据库。

## 测试与空间

- 测试输入只读；输出放自己创建的 TemporaryDirectory/tmp_path。进入前记录 sentinel/已存在文件，所有成功/错误/超时路径恢复原样；新输出原先没有则删除。只删除已核绝对路径位于自己的测试根内的目录，不做全备份恢复。
- 所有 formal forecast 的进程内调用和子进程都必须在 import/执行前指向隔离 registry；前后核对默认 registry 是否存在及 SHA，不能删除真实已有 registry。RF alerts/output 不属于本卡。
- 真实/合成样本分列；只读已有公开小样本，不复制 PDF/AUTO。旧失败、原分母、旧 receipt 和原始 SHA 保留。缺少样本写 NOT_RUN，不造 placeholder 通过。
- 只保留首个行为 RED、最终集中结果和 C 节点 CLI/清理收据。优先小 JSON 汇总及压缩原日志，交接材料目标≤10MiB；不因压缩删失败、裁正文或改原日志。不要打印环境变量和 key。
- FF 真实41链只能用 launch 中固定 CWP/ET 已提交源码依赖。它是离线 fixture 联调，不是实际供应商触达/新鲜原件质量验证。

## 三个大节点与交付

A：读真实代码与 PWF，冻结接口和独立手算/字段期望，先用实际入口复现行为错误。import error 不能作为唯一 RED；区分静态假说和已复现问题。

B：在所属责任层消除共因，集中跑自己的测试和卡列旧回归；不得通过删旧断言、公司特判、扩大预算或复制第二实现洗绿。

C：跑卡内实际公开 CLI、错误路径与恢复；独立质量试读/手算，正常 commit 后写 handoff.md/json，STOP 等 ROOT。作者不并主线、不推安装副本；ROOT 负责合流、精确 CI 与最终跨仓质量。

handoff.json 最少字段：

```json
{"schema_version":"du6-handoff/1","card_id":"DU6-...","base_commit":"full40sha","branch":"codex/...","implementation_commits":[],"changed_paths":[],"interfaces_reused":[],"entrypoints":[],"red_receipts":[],"tests":[{"command":"...","exit_code":0,"passed":0,"failed":0,"skipped":0,"receipt":"relative/path"}],"fixtures":[],"independent_review":[],"old_failures_preserved":true,"known_limits":[],"not_run":[],"root_integration_steps":[],"production_writes":0,"supplier_calls":0,"cleanup_receipt":"relative/path"}
```

production_writes 指生产原件/配置/AUTO/真实 registry；不禁止卡内源码修改。交付 SHA 可由单独 handoff commit 记录前一实现，不自引用。所有真实/合成、缺失/未测和剩余问题照实列出；ROOT 签收是原大节点质量核验，不再添加许可手续。
