# DU6-FF-PORTABLE-EVIDENCE 交接

- schema `du6-handoff/1`，card `DU6-FF-PORTABLE-EVIDENCE`，2026-10-16。
- base `e2efa81d7995836d457479eb528fa6f8cd5dc3f3`，分支 `codex/du6-ff-portable-20261016`。
- 实现 commit `250981038dc8879003b2d670329278d236706dc4`；详细字段见 [handoff.json](handoff.json)。
- 本线 STOP：不并主线、不推安装副本、不发布。

## 交付了什么

给现有离线矩阵增加**可搬迁的保留证据重放**，只接两处、其余零改动：

1. `oracle.audit(report, *, evidence_root=None)` — 显式 root 只改现有相对 request/response/fixture/ET
   receipt 引用的读取根，仍走同一个 `_bound_evidence`（同样 SHA/CaseSpec/原 findings/未知 usage 校验）。
   `None` 与旧行为完全一致（旧默认 findings 规范指纹 `417a7891…`，65 条，测试冻结）。不改传入 report、
   不搜索磁盘、不回落旧绝对根、不制造授权状态。
2. `python -B tools/offline_contract_matrix/run.py replay --report ABS --evidence-root ABS --output ABS`
   — 公开入口直接由未改动的 `run.py` 承载。只读保留证据并调用原生 audit，不启动 Context/seed/provider/
   CWP/ET/fresh reader/网络（负控禁用 Popen/socket/import 绑定仍能跑通）。输出是小型
   `ff-matrix-evidence-replay/1` 记录，不是第二份矩阵报告。

退出码：`0` 仅当原完整矩阵全 PASS **且**原 recorded oracle 通过无历史 findings **且**当前 native audit 干净；
`1` = 重放读对了但不被认证；`2` = 明确输入/输出诊断（缺文件/非法 JSON/未知 schema/错误 root/输出同路径、
已存在或落在 artifacts 内），永不 traceback 冒充业务失败。历史 FAIL/PARTIAL/NOT_RUN、原 findings、
未知 usage=null、缺 fresh proof 一律不因路径修好被升级。

## 验证收据

| 收据 | 内容 |
|---|---|
| `receipts/01-red-first.txt` | 首个行为 RED + 单列接口 RED（3 passed / 29 failed，全部归因缺失 API） |
| `receipts/02-centralized-regression.txt` | 卡内集中命令 245 passed（旧 213 + 新 32）+ Ruff 只查改动源 |
| `receipts/03-c-pinned-dependencies.txt` | pinned CWP/ET commit、模块 SHA、ET 测试 proxy seam、密钥 stat-only |
| `receipts/04-c-relocation-replay.txt` | 真实41链产物 SHA + 空格/中文目录搬迁重放 |
| `receipts/05-c-no-fallback-tamper-history.txt` | 旧根不可用/override 缺失/单字节篡改/历史失败 fixture |
| `receipts/06-cleanup-receipt.txt` | 分类字节数、OWNED_TEMP 清理、前后隔离比对 |
| `receipts/07-independent-quality-check.txt` | 独立手算 21/21（不 import 新代码，纯字节复算） |

## 真实41链（fresh scope，只跑一次）

固定只读依赖：CWP `f08aa101ab49ca983d3a40356abfb05347f586b3`、ET `d0ac42c60dcca992db78860b8469cfed3dd527e5`
（均 git toplevel 一致，status 空；ET 测试 proxy seam 齐全）。0 真实供应商/LLM/翻译，fixture 边界。

**结果：38 PASS / 0 FAIL / 1 PARTIAL / 2 NOT_RUN，174.565s，5 条 recorded findings，exit 1。**

- PARTIAL `request_after_failure_retry`：子进程绝对期限到期。
- NOT_RUN `original_wrong_mime`、`incomplete_sidecar_metadata_gap`：10s final-proof reserve 保全（`scope.stop_reason` 明载）。
- 这是 W07 记录的宿主负载差异落在 180s 批预算上的期限证据，**不是** pinned 版本不匹配；按卡未改
  expected、未扩 timeout、未反复重跑求绿。具名证据：`evidence/chain-report.json`
  （`scope.stop_reason`/`phase_timing`/`launch_accounting`）。

## 搬迁重放（retained-evidence replay scope）

| 步骤 | 结果 |
|---|---|
| 完整复制 271 文件到含空格+中文的深目录后 replay | exit 1；报告 SHA `6e2705f3…` 不变；findings/case 状态与原地重放逐条相同 |
| 原 artifacts 根移动掉再 replay（report 未改） | findings 与上一步逐条相同 → 读的是 override，不回落旧根 |
| override 根移走、旧根仍在 | exit 2 具名诊断、不写记录、不产生半份“成功”报告、不悄悄用旧根 |
| 独立复制篡改 1 字节 response | exit 1；**新增** `invalid_bound_evidence / err_request_error / receipt bytes changed`，无 findings 丢失；成功样本未动，失败样本留存 `evidence/tampered-sample/` |
| 既有可移植失败 fixture（19/21/1） | exit 1；recorded findings 逐条保留；可读/可搬迁 ≠ 业务通过 |

## 两个 scope 的分界（必须声明）

- **retained-evidence replay**：只证明“保留字节 + 当前 oracle”。不重新读取生产原文、不重新下载、
  不重跑 41 链、不认证真实供应商/公司数字。
- **fresh 真实 41 链**：只有上文那一次运行是新链证据；replay 记录永不替代它。

## 已知限制 / 未做

- 真实链 3 个非 PASS 是批期限证据（见上），follow-up 由 ROOT 决定。
- 测试内的合成 41-case 语料只证明工具行为，不是真实链证据。
- 未新增 pack 格式/manifest 机制/第二 oracle/transport 库/持久证据库/人工授权或签收文件。
- 未跑 fresh SourceVersionReader 原文实读（replay 设计如此）、未做真实供应商可达性、未调 RF、
  未触主线/安装/其他线目录。生产原件/配置/AUTO/真实 registry 0 写入；`config/FMP_API_KEY.txt`
  只 stat（size=32、mtime 未变），内容从未读/复制/打印/hash。

## ROOT 接收步骤

1. 核对手算收据 `receipts/07-independent-quality-check.txt` 与 `handoff.json` 字段。
2. 需要时用 `evidence/chain-report.json` + `evidence/artifacts/` 重跑任一 replay 命令（命令见
   `handoff.json.replay_results`），注意输出路径必须是不存在的独立路径。
3. 合并 `codex/du6-ff-portable-20261016`（实现 commit `2509810…`），在主线跑精确 CI。
4. 决定真实链期限三例的后续（具名证据已留存）。
