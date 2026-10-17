# ROOT 独立接收审查 — DU10-FF41-CLOSE

结论：**PASS，零未解决问题，可接收本工程施工包**。受审最终作者 HEAD `ff2ba400ad37e1188b88ed61ff7a1814a647b94b`，基线 `c7c8867da35cd19d4f419fa70947332615e8e9c0`。审查员 `/root/du10_ff_reception_review` 全程作者工区只读。

## 实际审查与独审复用

完整 diff 的可执行生产工具变更只有 `cli_main.py` 与 `matrix_cases.py`：按每个独立 worker 组中的固定 CaseSpec/reuse_only 请求推导其所消费的暖种子。所有被消费种子仍走真实 ensure writer，union 仍是固定 10 个 ensure 种子与 TXT；两个组共享 US2025 项，各组实际 5/6 个 ensure。缺失期次/失败向量没有被预先填平，41 case handler、执行请求和断言没有改写。单 worker 或无 seed_cases 的旧调用仍准备全量种子。

独立核对 13 个受保护文件 blob 完全相同，包括 CaseSpec、oracle、Outcome、seed_batch、source_proofs、runtime、调度、fixture 与 ET proxy。CaseSpec 有 41 个唯一 ID，final-run 紧凑结果集合逐个一致；case 30 秒、batch 180 秒、2 workers、proof reserve 10 秒均未上调。

作者已有两轮独审，第一轮确实发现恢复判定缺口与收据缺项，第二轮绑定 `22ef5a14e8b72d840608282e3ed413322cbaa6b2` 审查修复通过。ROOT 对 4 份工具/测试/恢复脚本源文件逐个比较，最终 HEAD 相对该受审版全部字节相同；之后只有交接文档与清理收据。复用其有效审查，避免重复完整大矩阵。

## 证据完整性

C-1 收据 41/41 PASS、97.6772 秒、最长 case 10.4227 秒、oracle 0、restore true。原始 report SHA `a0dd3c1a7af32f66000b92e074e69520f7aaa64550b98993af0552b4d18d83da` 在独审第一轮检查时真实存在，reviewer 实查了 report 与 3 例 request/response 的 6 对 SHA，记录与 final-run/cleanup 一致。原大产物已依卡清理；ROOT 当前无法拿紧凑摘要重放原始 oracle，这一限制明确保留。

C-2 v3 是真实新 UUID 重启，观察本次链路请求从 0 到新增 GET 后杀进程树；杀前/后来源范围绑定同一个 attempt。重启新 attempt 41/41 PASS、exit 0、144.542 秒，12 项条件全真，原 killed attempt 的 40 个文件 SHA 全量不变，sentinel/既有输出前后 SHA 实值相同。v2 的 40/41、exit 1 被两项硬条件拦下，失败收据保留；因此没有用 `passed=True` 吞掉失败。恢复证明是**新 attempt 重启到完成**，不宣称旧 attempt 原地续跑。恢复脚本外层 400 秒是监督进程总回收上限，内层矩阵 180 秒 deadline 与 30 秒 case 上限未变，v3实际144.542秒。

固定依赖 CWP `900dbf64` 与 ET `7d06777e` 的只读快照，ROOT 独立抽查 4+3 个实际入口/核心源文件 SHA 与指定 commit blob，7/7 相同。作者说明历史运行快照存在 LF→CRLF archive smudge，独审曾验证其语义等价；当前快照字节已与 blob 相同，不把当前字节检查冒充历史时刻检查。

## 实际快测

`python -B -m pytest tests/test_du10_ff41_rootcause.py tests/test_w07_matrix_efficiency.py tests/test_root_du8_matrix_acceptance.py -q -p no:cacheprovider --basetemp <ROOT独立TemporaryDirectory>/pytest`

**42 passed in 10.56s**（外层墙钟19.501秒），exit 0；独立临时目录已删除，作者树 `git status --short` 仍为空。未执行完整41矩阵、未读密钥、无网络/模型调用。详细命令、源SHA、收据SHA与固定依赖核对在同目录 JSON。

## 范围与余留风险

这证明固定离线 fixture 供应商边界的 FF→ET→CWP 工程契约，以及隔离中断/重启/清理语义；不认证真实供应商覆盖、真实财报事实或摘要质量。高机器负载仍可能使固定时间预算不足，作者基线高负载失败与 v2 降级重启都保留，不能承诺任意机器负载下41/41。该限制没有被提高上限或删除case掩盖，不构成本卡交接阻断。
