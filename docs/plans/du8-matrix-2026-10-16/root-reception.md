# DU8 FF：ROOT 接收修复交接

## 状态

**工程修复完成，可正常提交并接收；完整 41 链验收仍 OPEN。** 最终独立审查范围内剩余 0 P1 / 0 P2。未提交、并线或安装；由 ROOT 执行正常 hooks 和 Git 流程。

- 唯一修改工作树：`C:/Users/郑曾波/Projects/filing-fetch-du8-integration`，HEAD `6f381199f146109b4f517537a70da1c20c6e05bd`。
- 作者树、主仓代码、生产原件、密钥、配置、固定 CaseSpec 输入、provider、30/180/10 秒限额均未改。
- 真实供应商、API、LLM、翻译、费用：**0**。

## 已修的三个共因

1. **截止覆盖混用**：`extended_cases.py` 保留固定 1 秒 ET 请求和独立 authority 对完整 PASS 的 GET=1 要求；零 GET 的真实 `provider_deadline` 明确记 `absolute_boundary=PASS / inflight_stall=NOT_RUN`，整体 **PARTIAL**。错误 reason、重复 GET 和其他 negative case 继续 FAIL。不是放宽为 GET<=1。
2. **恢复假通过**：恢复夹具只使用新 Temp 和本次唯一 UUID；当前 request/fixture 字节 SHA、当前 group proxy state 一致、先观察 GET=0/不存在再观察新增 GET，response 未完成才接受；初见正数、日志半写、计数回退、旧/外来 calls、准备阶段 artifacts 不作证。复用已有 OS 进程树 owner、bounded cleanup 和 pipe reader join；清理观测失败 **unknown**。收窄口径为“观察期间当前 case 新进入 GET 后中断 owned tree”，不宣称恰在 kill 瞬间 provider 仍阻塞；真正 stall 子孙终止有独立受控进程测试。fixture 现在只做一次受控中断，clean 41 链另行验收，不再暗中跑两次长矩阵。
3. **交接字节损坏**：三份 Markdown 的真实非法 UTF-8 原字节以 hex+SHA+长度完整归档后，按有效 JSON/findings/独立报告重建。编码控例验证原字节可精确复原、新文档 strict UTF-8 有效。静态 `[52,52]` 与实测均衡区分；收益仅完整历史表 **1.5226 秒 / 2.02%**。修正成本函数命名与错误 LPT 示例。

无新增授权 JSON、人工门禁、身份库、canary 或小节点签收。

## TDD 与独立审查

- 首轮 ROOT 控例：8 FAIL / 4 PASS；其中两个真实行为缺口、六个新恢复接口尚不存在，已如实分类，不把接口缺失当行为缺陷。
- 首次修复：12 PASS；旧新集中 **244 PASS / 17.72 秒**，收据 `ff-root-pre-review-focused.*`。
- 二审发现恢复 observer 仍可能读到旧累计 GET。保存原五 SHA 和原源码快照；追加直接驱动旧 observer 的真实行为 RED：**1 FAIL / 0.53 秒**（不是关键字接口缺失）。更早的 3 项接口缺失 RED 也保留。
- 完成状态观测修复和 7 项边界/编码控例，最终 ROOT **19 项**；与作者 37 项和既有 authority/runtime/边界/owner 相关包合计 **251 PASS / 0 FAIL / 0 SKIP，9.19 秒**。
- 最终独立只读审查：`ff-root-independent-final.md/json`，五源码 SHA 全匹配；已关闭观察器问题，范围内 0 P1 / 0 P2。审查 agent 未重跑测试或进入生产。
- Ruff 指定五文件通过；host assumption guard 新问题为 0（既有 baseline/registered 不变）；`git diff --check` 通过；`core.hooksPath=.githooks` 正常，未使用 `--no-verify`、未改 hook。
- CodeGraph 在用户既有授权下初始化：112 文件可用，6 个 sparse 缺失文件不可读；没有因此补写历史文件或修改生产源码。

最终冻结见 `ff-root-frozen-final.json`。相比首次冻结，只改了恢复夹具与 ROOT 自有测试；三个矩阵 runtime 文件 SHA 与下述真实 41 链执行时完全一致。

## 唯一一次完整 41 链：实测，不重跑到绿

固定只读 CWP `f08aa101ab49ca983d3a40356abfb05347f586b3`、ET `d0ac42c60dcca992db78860b8469cfed3dd527e5`；workers=2、case30、batch180、proof reserve10。外层 205 秒仅约束整个测试进程清理/报告，未延长矩阵内原预算。

| 项目 | 实际 |
|---|---|
| 结果 | **20 PASS / 0 FAIL / 4 PARTIAL / 17 NOT_RUN** |
| 退出码 | 1 |
| 矩阵时长 | **173.2744 秒**（外层 174.1162 秒） |
| native oracle | false，43 findings，原样保留 |
| provider/翻译/费用 | 真实 provider0、translation0、paid0，未知 charge 保持 null |
| 初末恢复 | restore=true，原件/config 元数据未变，owned 只剩原 sentinel，Temp 删除 |
| 完整证据 | **209 文件 / 1,151,019 字节** |

完整目录：`C:/Users/郑曾波/Projects/company-wiki/.planning/du8-ff41-root-20261016/attempt-97cfcba487c84de39bcb2d6475db140a`。包含 report、全部保留 request/response/fixture/result/usage/source proof、guard-events、restore；逐文件 SHA 清单 `ff-root-full41.manifest.json`。未删失败证据，未只拣通过样本。

四个 PARTIAL：

- `chainA_download_reuse`：30.0437 秒触发 case deadline。第一轮真实下载已返回，第二轮未完成，不能算下载→复用闭环。
- `fin_us_annual_hit`、`call_wrong_symbol`：已临近 170 秒保留尾部，剩余 window 过短，被绝对截止中止；分别 0.3745 / 4.9279 秒，不是这两项单独耗时超过 30 秒。
- `call_hard_timeout`：ET 真实 `deadline_exceeded/provider_deadline`、cleanup=true、GET=0，边界通过、在途 NOT_RUN，整体 PARTIAL。完整 FF 调用耗时 9.0785 秒包含其他层准备，不等于把 1 秒 ET 预算扩大。

17 项 NOT_RUN 的具体公司/文档/错误向量均在完整 report 中；非周期招股/增发/可转债/IR、当地 TXT 复用等未运行项目仍然是必需覆盖，未从分母删除。

### 性能根因：已测到哪里，仍不知道什么

本次数据证实耗时超出静态模型，而非证实“调度已经均衡”或“纯外部负载”：

- binding 15.5381 秒；seed 两 worker 累计 61.6588 秒（**并发跨度求和，不能当墙钟**）；35 次 FF 调用累计 241.9295 秒（同样不是墙钟）。
- 首个 CN annual fetch 22.7894 秒、failure→retry 22.6456 秒、chain-A 达到 30 秒。单纯重新排列只能在历史完整表改善 1.52 秒，不能消除这些真实成本。
- 缓存确实生成 534 pyc，最长路径 189（CWP101、ET7）；不能再笼统归因所有缓存都因 Windows MAX_PATH 不工作。
- fresh proof 2.9883 秒、cleanup 0.1774 秒，15 份 fresh source proof 留存。此次主要耗时不在最终清理。
- 本次没有隔离测量 CPU 竞争、各子进程 import 与重复 CWP CLI 开销，**具体比例仍 unknown**。不能仅凭 hostload 解释所有失败，也没有证据认定产品业务逻辑重大错误。

43 个 oracle 标签包括 21 case_not_passed、19 missing_bound_evidence，以及 chain-A incomplete 后派生的 fake_layer/missing_receipt/second_run 标签。它们表示未闭环的断言，不等于已经证明实际重复下载或整层被 fake；第一轮真实下载与第二轮未观察必须分别看原 trace。

## 留给 ROOT 的明确 OPEN 与下一步

1. **C 性能/覆盖**：固定预算无法完成所有必需 case。先用同一受控执行层的少量观测区分 import/进程启动、重复 CWP 查询/能力探测、seed 和 provider 路径成本，找到可复用准备/批处理边界。不得通过调大30/180、裁 case 或不运行向量获得绿。没有新实施前不再重复整批。
2. **在途超时覆盖**：该真实 1 秒窗口仅证明 pre-GET deadline。已有本地受控 stall/tree 测试证明工程清理；真实 ET 在途向量仍 NOT_RUN，不偷换为完整覆盖。
3. **恢复公开入口**：重写后的 fixture 有集中 fake/本地受控进程测试，但本轮没有另跑一次真实 interrupted matrix，明确 NOT_RUN；避免为完成收尾偷偷增加另一套 180 秒长跑。ROOT 可以在需要专门恢复验收的大节点执行其新显式 CLI。
4. 作者历史 C 三次 21/26/14 PASS 和丢失部分 restore/guard 的限制仍保留；本次新证据完整，不追认历史丢件已修复。

工程修复可先并线，不把这四项 OPEN 伪装为供应商、公司事实或完整文档覆盖验收通过。
