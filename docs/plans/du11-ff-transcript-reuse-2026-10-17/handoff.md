# DU11-FF-TRANSCRIPT-REUSE — 交接 (handoff)

状态：见 `handoff.json` 的 `status`。作者分支 `codex/du11-ff-transcript-reuse`，**未合并、未推送、未清理 worktree**，STOP 等待 ROOT 统一并线。

## 1. 目标与结论

未显式限定 provider 时，FF 先做**来源中性**的本地 exact 查询复用已登记电话会（任意真实 provider），
只有真正无候选（且无本地受限证据）才走原 FMP 采集；显式 `provider=fmp` 保持原 provider 约束与
import 去重语义。复用结果的 provider 忠实取自成功 reader receipt 的 `manifest.provider`，缺失即 unknown，
绝不回填 `fmp`。

实测（`receipts/A_RED_baseline.json` / `A_RED_after_fix.json`，同一份已登记 `motley_fool` 电话会、同一请求）：

| 版本 | status | provider | ET 调用 | provider_calls | CWP 子进程 |
|------|--------|----------|---------|----------------|-----------|
| 基线 `f1a939e5` | `downloaded`（重复下载） | `fmp` | 1 | 1 | 3 |
| 本卡 | `reused` | `motley_fool` | 0 | 0 | 2（1 query + 1 reader） |

`receipts/ab_probe.py --ab` 一次即可重跑两侧：它自己从 `f1a939e5` 抽取基线 `scripts`，并记录
`ff_commit.archive_tar_sha256` 与逐文件 `ff_scripts_sha256`，不再依赖临时目录。

## 2. 两个公开 CWP 入口（本卡不合并它们）

1. **来源中性**（provider 省略）：stdin 直接发送普通 `SourceRequest`
   （`schema_version="1.0"`, `provider=null`, `mode="exact"`, `allow_download=false`），
   **不包** `company-wiki-transcript-import-lookup-request/1` envelope →
   `SourceVersionReader.query_local`。unknown / after_as_of / invalid 候选只会出现在 `excluded_candidates`。
2. **显式 provider（fmp）去重**：保留 `company-wiki-transcript-import-lookup-request/1`
   envelope + `lookup_transcript_import`。该入口要求 provider 非 None；本卡从未向它传 null。

未新增任何 CWP 接口，也没有在 FF 内复制 CWP 的 source-query 实现。

## 3. 输入/输出兼容矩阵

输入 `companion_transcript`（schema 与 `filing_contracts._validate_companion_request` 完全未改）：

| 输入 | 本地查询入口 | 结果 |
|------|--------------|------|
| `provider` 省略 | 普通 `SourceRequest`（provider=null） | `reused` / `unknown_publication` / `downloaded`（仅真缺失）/ `not_found`（reuse_only）/ `ambiguous` / `upstream_error`（具名） |
| `provider: "fmp"` | lookup envelope，provider=fmp | `reused`（provider 必须为 fmp）/ `unknown_publication` / `downloaded` / `ambiguous` / `upstream_error`（具名） |
| `provider: 其他` | 0 子进程 | `request_error` / `unsupported_transcript_provider`（companion 原样保留；transport 直接调用时同名 `upstream_error`） |
| 无 `companion_transcript` | 0 子进程 | `not_requested` |
| FY/Q 缺失或非法 | 0 子进程 | `period_unresolved` |
| identity 未 verified/active | 0 子进程 | `not_applicable` |
| `fetch_if_missing` 缺 limits | 0 子进程 | `request_error` / `invalid_acquisition_limits` |

输出：公开 v2 envelope（`ff_v2_envelope._TRANSCRIPT_KEYS`）**未改**，`scripts/ff_v2_envelope.py` 未改动。
内部 child result 新增两个仅供调用方/收据使用、会被公开 serializer 丢弃的诊断键
`qualification` / `excluded_candidates`（gap 情形另带 `excluded_publication_statuses`）；
`provider` 在真实 provider 未知时**不出现**（不再伪造 `fmp`）。所有新增诊断都落在既有字符串字段 `reason`
与既有内部键内，不新增公开 schema 字段：

`transcript_lookup_contract`、`transcript_lookup_source_ref`、`transcript_lookup_identity_mismatch`、
`transcript_provider_mismatch`、`unsupported_transcript_provider`、`publication_date_unknown`、
`publication_after_as_of`、`publication_date_invalid`、`transcript_lookup_changed`。

## 4. 结果语义（固定）

- **唯一合格候选**：CWP `query_local` 判定唯一 + FF 用公开 reader 实读验真 SHA/byte_size + manifest 与
  exact 请求（FY/Q、market、security_id）不冲突后才 `reused`；已有合格 match 优先，不因同时存在
  unknown excluded 候选而丢弃。
- **单个 `publication_status="unknown"` excluded**：`unknown_publication`（`as_of_cutoff_verified=false`），
  保留 SourceRef + `source-qualification/1`，**0 读取 / 0 provider**（查询观察，不是 bytes 证明）。
- **多个 unknown、或 unknown 与受限项混存**：`upstream_error` / `publication_date_unknown`，0 下载。
- **仅 after_as_of**：`upstream_error` / `publication_after_as_of`，0 下载。
- **仅 invalid**：`upstream_error` / `publication_date_invalid`，0 下载。
- **结构/bytes/SHA 异常、非法 status、畸形 qualification**：具名 `upstream_error`，0 provider 调用，绝不转 `not_found`。
- **真缺失**：一次原配置 FMP 下载 → CWP 真实 import → 再 reader 验真；重复请求 0 provider 调用（`provider_calls=0`）。

## 5. 测试

| 集合 | 命令 | 结果 |
|------|------|------|
| 本卡 | `python -m pytest tests/test_du11_transcript_reuse_support.py tests/test_du11_transcript_reuse_selection.py tests/test_du11_transcript_reuse_contract.py tests/test_du11_transcript_reuse_e2e.py -q` | 109 passed（47 纯选择 + 45 契约 + 10 冻结 CWP E2E + 7 恢复夹具自检），100.14s |
| 集中回归 | 见 `receipts/c_test_summary.json` 的 `central_regression.modules` | 257 passed / 3 skipped，13.89s |
| lint | `python -m ruff check scripts tests` | clean |
| 全仓 | `python -m pytest tests -q -p no:randomly` | 1320 passed / 9 failed / 16 skipped；9 个失败在基线 `f1a939e5` 同样失败（同文件基线 13 失败），与本卡无关 |
| 变异检测 | `python receipts/mutation_check.py --out receipts/c_mutation_check.json` | 隔离副本基线 92 passed；7/7 变异全部被检出；共享工区未被改写 |

明细：`receipts/c_test_summary.json`、`receipts/c_mutation_check.json`。

## 6. C 节点真实层级与 mock 边界

真实链（`receipts/c_restore_receipt.json` 记录）：

```
resolve_companion_transcript            (真实 FF)
→ EarningsTranscriptsTransport          (真实 FF)
→ python -m company_wiki...source_query_cli  (真实冻结 CWP, plain SourceRequest)
→ python -m company_wiki...source_reader_cli (真实冻结 CWP, verified open)
→ python -m company_wiki...transcript_import_cli (真实冻结 CWP, 仅下载链)
→ 离线 ET fixture 进程                  ← 唯一 mock 边界（记录每次调用）
```

另有一条 E2E 直接跑公开 CLI `scripts/fetch_filing.py`（v2 request + `companion_transcript`），
证明公开入口到 `reused` 的完整链，`downloads=0`、`et_calls=0`。
真实 CWP 源码只从冻结 commit 以 `git archive` 抽取 `src/` + `pyproject.toml` 到本卡 owned 临时根
（tar sha256 `555b11a8…558eac`，356 文件），不整库复制，不复制 companies/transcripts/真实 config。

## 7. 恢复与清理收据

`receipts/c_restore_receipt.json` 记录**两段**基线：

1. `initial_entries=362`（build 后、测试做任何事之前）：含固定 sentinel `restore/sentinel.txt` 与既存输出
   `restore/existing.out`；执行后除 `.source_catalog/`、`runtime/`、`companies/` 活动区外，所有初始条目
   必须 bytes+sha+mtime 完全一致（`frozen_source_changed=[]`，覆盖 `src/`、`config/`、`restore/`、`pyproject.toml`）。
2. `checkpoint_entries=366`（测试自己的 seed 与真实 `scan` 之后、FF 动作之前）：执行后
   `changed_since_checkpoint=[]`、`removed_since_checkpoint=[]`（目录库/运行文件的合法变化单列为
   `catalogue_or_runtime_changed`）；新增只允许 `.source_catalog/` 与 `runtime/`
   （`catalogue_or_runtime_added`）以及**恰好一对** canonical import 原件+sidecar（`canonical_import_added`，
   且必须位于 `companies/…/investor_relations/transcripts/` 下）；`unexpected_added=[]`。
3. owned 根随后被删除（`cleanup_receipt.removed=true`）。

`tests/test_du11_transcript_reuse_support.py` 里另有 7 个**夹具自检**（用微型冻结 tar，不跑 CWP 代码）：
洁净运行通过；被改写的 seed、被改写的 sidecar、公司目录里的外来文件、被改写的冻结源码、恰好一对
canonical import、以及第二对 import 分别被断言捕获。这样“恢复收据本身有牙齿”不会再悄悄退化。

每个 E2E 测试都执行同样的比对与删除（`tests/test_du11_transcript_reuse_e2e.py` 的 `owned_wiki` fixture：
先 `assert_restored()`，再在 `finally` 中 `cleanup()`，即使断言失败也保证删除）。

## 8. 资源与计数

- 真实网络 0、付费 API 0、LLM 0、翻译 0、密钥值读取 0（主仓未跟踪的 `config/FMP_API_KEY.txt` 只按
  stat/path 记录，从未打开、复制或提交）。
- 测试内 ET 边界为本地 fixture 进程，调用被记录；「0 调用」由调用计数断言，不由标签推导。
- 未知费用/计数保持 `null`（`provider_requests`/`provider_response_bytes`/`provider_usage_complete`）。

## 9. 独立最终审查

审查由**另一位独立 subagent** 完成（作者不能兼任），报告：`receipts/reviewer_report.md`。
首轮受审源码 `c787757a9f0409777fd6d469a90d2371bce706d5`：**VERDICT: PASS**，0 blocker / 0 major，
3 minor + 7 nit（全部为交付收据与证据卫生，无源码缺陷）。已逐项修复：

| 项 | 根因 | 修复 |
|----|------|------|
| M1 收据里的用例数过期 | 收据在最后一个契约用例加入前生成 | 重新生成 `c_test_summary.json`（102 = 47+45+10；全仓 1313/9/16）并同步本文件 |
| M2 `c_mutation_check.json` 自相矛盾 | 生成器把最后一次变异的摘要写进 baseline 字段，且 `-x` 半程运行 | 重写为隔离副本、洁净基线 92 passed、记录每个变异失败的用例名、pristine 复原校验 |
| M3 恢复基线在 seed 之前且按前缀放行 | `build()` 就取基线 + `companies/` 前缀全放行 | 改为“初始清单 + seed/scan 后 checkpoint”双基线，新增只允许目录/运行区与**恰好一对** canonical import |
| N1 `task_plan` 的 Next Step/错误表过期 | 阶段状态更新后未同步 | 已更新 Next Step 与错误表（指向 `progress.md`） |
| N2 RED 收据未绑定基线脚本 | 基线来自临时目录且未记 SHA | `ab_probe.py --ab` 现在自己 `git archive f1a939e5` 并记录 tar SHA 与逐文件 SHA |
| N3 下载 provider 的第二来源 | 注释未点明 CWP 证明 | 明写 `tool_result.provider == candidate.provider` 证明；两者都缺时保持 unknown 并新增用例 |
| N4 变异脚本改写共享工区 | 直接改 tracked 文件后 `git checkout` | 改为在 owned 临时副本内变异并复原，共享工区不动 |
| N5 冻结 tar 缓存残留 | 固定 `%TEMP%` 路径只建不删 | 每次在自己 holder 里重建并在 `finally` 删除 |
| N6 `excluded_publication_statuses` 被丢弃 | companion 只转发部分诊断 | 与 `excluded_candidates` 一起转发 |
| N7 未单列“candidate 无 provider”用例 | 只覆盖了 candidate provider 错误的情形 | 新增字面用例（candidate 无 provider、manifest 有真实 provider） |

另按 A 节点“显式 fmp 专用 lookup 正例”补了真实 CWP 正向用例
（`test_real_cwp_explicit_fmp_lookup_finds_and_reuses_its_own_source`：先真实 import，再在 catalog 上用
plain 与 envelope 两种入口实测 `found`，最后显式 fmp replay → `reused`、`provider_calls=0`）。

审查后自查又发现并修复一处：post-seed checkpoint 的 `changed_since_checkpoint` 只被计算、未被断言
（被篡改的 seed 当时不会被发现）。现已断言，并新增 7 个夹具自检用例固定该性质。

最终源码提交（frozen source head）`5dee9a20c1c5952688673caf784fdce4e9391a50`（c787757 → d16dce2 → 5dee9a2）。
**第二轮复核（同一独立审查 agent）**：`FINAL VERDICT: PASS for 5dee9a2`，0 blocker / 0 major /
**0 source minor**；逐项独立复跑（109 用例、中央 257/3、全仓 1320/9/16、隔离变异 7/7、恢复收据
362/366/368、A/B 与显式 fmp 正例）后确认。剩余仅为交付记账项，已在本文档与 `handoff.json` 中关闭：

- R2-1 A_RED_after_fix.json 的 `ff_commit` 标签曾指向 `c787757`（逐文件 SHA 一直正确）：`ab_probe.py` 新增
  显式 `--source-commit`，收据现在记录 `source_commit=5dee9a2…` 与逐文件 SHA，不再随 worktree HEAD 漂移。
- R2-2 记账：本文件与 `task_plan.md`、`handoff.json` 的轮次/结论/最终交付提交已改为 `5dee9a2` + round-2 PASS。
- R2-3 观察（不需改源码）：N6 的 `excluded_publication_statuses` 转发没有专门断言，代码正确且纯选择用例
  已覆盖聚合计数；记录为已知观察，不引入源码变更以免破坏冻结绑定。

## 10. 局限与 ROOT 接线

- 本卡**未**上线任何新 provider、**未**评估真实供应商数据质量；`motley_fool` 只是「另一真实 provider」的
  合成登记样本，用作复用证明。
- 未启用 ET 的其它在线 provider；缺失时采集仍只用既有 FMP 配置。
- 复用的「issuer」一致性依赖 CWP `query_local` 的 entity gate；FF 侧另加 manifest 的
  FY/Q、market、security_id 一致性检查（manifest 不含 issuer 字段，故不在 FF 重复做 issuer 认证）。
- 公开 envelope 无法忠实表达多个/受限 unknown 候选项，故收窄为具名 gap（reason 内表达），
  未新增 wire 字段；若 ROOT 后续给 wire 加结构，可按本卡 `Selection.exclusions()` 直接透传。
- ROOT 后续改动若触碰 `source_query_cli` / `source_reader` / `qualification`，需按
  `receipts/c_dependencies.json` 的 blob SHA 对照复核。
- `receipts/` 下的 `ab_probe.py`、`restore_probe.py`、`mutation_check.py`、`make_fixture.py`、
  `make_handoff.py` 是证据生成器（非产品代码）；变异检测只在 owned 临时副本内进行。
