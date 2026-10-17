# 调查 (DU10-FF41-CLOSE)

## A.1 历史基线（已核实，来自保留证据）

- DU8 ROOT 实跑（`company-wiki/.planning/shared-reading-production/du8-reception/ff-root-full41.json`）：
  `20 PASS / 0 FAIL / 4 PARTIAL / 17 NOT_RUN`，173.2744s（170s 处被 proof reserve 截停，具名 stop_reason）。
  - phase：binding 15.5381（1 span）；seed 61.6588（2 spans，两组并行累计）；ff_cli 241.9295（35 spans）；
    fresh_source_proof 2.9883（2 boots）；cleanup 0.1774。
  - boots 197：other_python 92、fixture_adapter 58、ff_cli 34、et_proxy 9、seed_batch 2、source_proofs 2；
    parent calls：binding_probe 1、git 3、fresh_source_proof 2、seed_batch 2、cwp_cli 2、ff_cli 35。
  - bytecode cache 正常（534 pyc，max path 189 < 260）。
- `other_python 92` 的真实身份：FF 生产脚本以 `python -m company_wiki.source_catalog.source_query_cli/cli`
  启动的子进程，在 Windows 下 guard 记录的 `sys.argv[0]` 是反斜杠文件路径，
  `classify_argv` 的 `"company_wiki.source_catalog"`（点分）匹配不上 → 误分类为 other_python。
  这些是 FF→CWP 真实生产链（约 2.6 个/FF 调用），**不可移除**，只能靠热 pycache 降低单个成本（热导入实测 0.75–0.88s）。
- DU8 结论复核成立：调度已成本均衡（实得 1.52s/2.02%），瓶颈是启动路径固定开销 × 机器负载 2–4× 波动。

## A.2 今日机器实测（2026-10-17）

- CPU 负载 38%，11 个 python 进程（其他 lane 仍在跑，但远低于 DU8 时的 82%）。
- binding 型冷导入（写 pycache）14.43s；同进程树热导入 0.75–0.88s —— 与 DU8 的 binding 15.54s 吻合。
  冷编译是每 attempt 一次性成本（owned cache 每次新建是已测边界，不可复用旧 cache）。

## A.3 确证的重复准备（本卡 B 节点目标）

1. **两组各自全量 seed**：`seed_all(ctx)` 每组固定 10 次 ensure 采集（各自真实 adapter/GET）+ 1 次 TXT seed + 1 次 scan。
   10 项 warm seed 的固定消费映射（由冻结 CaseSpec registry 可推导）：
   - 9 个 `fin_{market}_{kind}_hit` → 各自 `(market, kind, 2024, period)`；
   - `chainA_download_reuse` → `(US, annual_report, 2025, FY)`（filing 部分是 reuse_only）；
   - `local_txt_exact_reuse` → TXT transcript seed（组内 in-process seed_original）；
   - 其余 case 不消费 warm ensure 项。
   → 每组只需 seed 其分得 case 消费的子集（≈各 5–6 项），union 仍为全部 10 项 + TXT，覆盖不缩水；
   每个被消费的 seed 仍在消费组内走真实 CWP ensure writer。
2. **两组各自 fresh source proof 子进程**（2 boots，各 import 同一 reader 栈）→ 可单 helper 进程逐组验证，
   per-group part 与 merge 语义不变。
3. 不修调度权重、不提高任何限额（母计划明确）。

## A.4 恢复语义现状

- 单元级恢复行为已由 DU8 测试覆盖（到期 0 新增启动、reserve 边界、非协作子进程回收、
  失败目录不复用、attempt 唯一性、cache 不共享、并发组隔离、预算不续期）。
- OPEN 是**端到端证据**：完整矩阵进程在真实 case 在途（0→新增 GET 观察）被中断 → 树回收 →
  重启为新唯一 attempt → 完整完成 → sentinel/既有目录/生产元数据不变 → 清理。DU8 的中断 E2E
  只做到中断+回收（passed），没有重启恢复腿。

## A.5 RED 计划（fake clock / 离线 fixtures，行为级）

- RED-1：调度分组确定后，各组实际下发的 seed 批次 == 该组 case 固定消费的 warm 子集
  （当前实现对任何分组都下发全量 10 项 → 断言失败）。
- RED-2：union(各组 seed 子集) == 冻结全量消费集（防“以弱样例替代”）；TXT seed 同理按消费组下发。
- RED-3：fresh proof 对 N 组只启动 1 个 helper 进程且逐组 part 完整（当前实现启动 N 个 → 失败）。
- 基线上这 3 个 RED 必须因行为失败（非 import 缺失）；修复后转绿；既有 DU8/W07 测试不回归。

## A.6 依赖快照字节精确性（2026-10-17 追加）

- 首次用 `git archive`（宿主 `core.autocrlf=true`）提取：纯 LF 的文本文件被 CRLF smudge。
  基线#1 / C-1 / C-2 三次实跑消费的是该快照。
- 等价性证明（`receipts/dependency-eol-equivalence.json`，60 样本）：快照文件与 fixed commit 的
  git blob 逐字节相等，或为"blob 纯 LF + LF→CRLF smudge"——即三次实跑消费的**就是 fixed commit 的代码内容**。
- 随后改用 `git -c core.autocrlf=false archive`（字节等于 blob，且 msys tar 可写超深文档路径）
  重建现役快照（53 样本 blob 全匹配 + 全树文件数核对，`receipts/dependency-postcheck.json`），
  供复现使用。逐文件 `cat-file` 原始提取会命中 Windows MAX_PATH（company-wiki 提交树含超深
  docs 证据路径），不可行。
- CWP 主仓 HEAD 已前进到 29cedac（其他 lane 在动），固定快照方法避免了漂移（`dependency-record.json`）。

## A.7 负载波动实录（同日三态）

| 时刻 | CPU | 运行 | 结果 |
|---|---|---|---|
| 上午 | 38% | 基线#1（main 代码，CRLF 快照） | 41/41 PASS，110.85s |
| 午后 | ~0% | C-1（修复后，CRLF 快照） | 41/41 PASS，97.68s |
| 随后 | 96%（多 agent lane 并发） | 基线重做（main 代码，字节精确快照） | 1 PARTIAL / 40 NOT_RUN @183.8s（binding 40.7s、seed 249.8s） |

→ 与 DU8 结论一致：失败主因是外部负载（2–4× 放大启动成本），不是调度或预算设定；
固定 180s 预算下的完整矩阵需要"无其他重测试争抢资源"的窗口。负载失败证据保留
（`receipts/baseline-loaded-machine.json`），未删改。

## A.8 恢复语义补充

- DU8 的中断 E2E 只含"中断+回收"；本卡 C-2 增加重启腿：新唯一 attempt、被杀残留字节不被改写、
  重启独立完成 41/41、sentinel/既有目录不变、临时树移除（`receipts/interruption-restart.json`）。
- 检查未发现需要代码修复的恢复缺陷（DU8 单元级恢复测试覆盖到期 0 新增启动/attempt 唯一性/cache 不共享等）；
  本卡 OPEN 是端到端证据缺口，由 C-2 补齐。
