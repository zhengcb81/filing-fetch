# offline_contract_matrix — FF↔ET↔CWP 离线真三层联调与文档类型覆盖矩阵

显式手动运行、完全独立临时状态的跨仓套件。证明一次真正的
**FF 公开入口 → EarningsTranscriptsTransport → ET transcript_tool.main →
真实 retrieval supervisor/worker/transcript_api → FF 真实 import → CWP 原文注册 →
SourceVersionReader.open_version 实读 → 再次 FF 命中** 链路（链 A），并给出文档类型覆盖图。

产品源码只读；只在 owned scratch 写状态。无真实网络、无真实收费、不翻译。
所有请求都是 fixture 请求，单列不入母账。合成响应不证明外网可达、真实供应商完整或经济质量。

## 运行

```
python -B tools/offline_contract_matrix/run.py \
  --cwp-project <explicit-cwp-code-root> \
  --et-project  <explicit-et-code-root> \
  --owned-root  <new-owned-root> \
  --out-root    <new-attempt-root>
```

每 case 超时 ≤30s；批次绝对截止 ≤180s；失败保留 partial。二次执行用新 attempt，不覆第一次。
单元测试（快速、离线、不跑跨仓）：`python -B -m pytest -q tests/test_w06_contract_matrix.py tests/test_w06_matrix_runtime.py tests/test_w06_case_authority.py`。
本卡新增调度/恢复快测：`python -B -m pytest -q tests/test_du8_matrix_scheduling.py tests/test_du8_matrix_deadline_recovery.py`。

## 调度（DU8-FF-MATRIX-COMPLETION）

41 个固定 case 由 `case_scheduling.assign_groups` 分配到 ≤ `WORKERS`(=2) 个并发组。
分配按**成本均衡**（最重优先贪心，全序 = cost 降序 + id 升序），不再是按位置轮转
（`entries[index::workers]`）。位置轮转不含成本信息，实测把最重的三个 case 放进同一组，
产生 **75.5306s / 59.8019s** 的两组负载（不平衡 15.73s = 26%），使该组成为关键路径。

**诚实的收益规模**（在保留的 W07 **41/41 全覆盖**实测表上评分，完美均衡下界 67.6663s）：

| 分区 | 关键路径 | 相对下界 |
|---|---|---|
| 旧位置轮转 | 75.5306s | 1.1162 |
| 新 `case_scheduling`（shipped 静态模型） | **74.0080s** | 1.0937 |
| 完美均衡下界 | 67.6663s | 1.0000 |

即真实改善约 **1.52s / 2.02%**，且 **79.8% 的随机 20/21 分区也能超过旧轮转**。
所以这是**可复现的小幅改善，不是接近最优的调度**。不要把它宣传成大幅提速。

成本模型只用**运行前可得**的固定信息：`CaseSpec.runs` 的链数。不读历史计时文件——
矩阵必须能从固定输入复现，机器相关的陈旧计时表是隐藏输入。
曾试验过一个按 `declared_layer` 加权的模型：它在 W07 表上看似近乎最优（67.723s），
但仅有 4 个取值、最优权重区间极窄，bootstrap 重采样后 mean ratio 退化为 1.0598 且只有
64.2% 概率胜过旧轮转——**比本 run-count 模型的 1.0498 / 70.2% 更差**，故**判定为过拟合并弃用**。

`case_scheduling.static_cost` 提供 `cost_of` 钩子，持有实测秒数的调用方可据此调度并达到下界；
runner 不隐式使用它，否则批次会依赖上一次运行的计时。

约束保持不变：并发 ≤2（均衡不通过放大并发实现）、30s/case、180s/batch、10s proof reserve、
`remaining` 不续期。同一 case 的 download→reuse 链绝不被拆到两个组。

报告 `scope.case_scheduling` 记 `group_loads_seconds`、`group_case_counts`、
`predicted_makespan_seconds`、`perfect_balance_lower_bound_seconds`、`imbalance_seconds`、
**`cost_source`**（static/measured，防止把预测当实测）。
批次因绝对截止被截断时，`scope.stop_reason` 必须具名（不再静默截断）。

## 架构

- **代码绑定**：runner 将 supplied CWP `src`/ET 码根经 child `PYTHONPATH` 只读绑定；先 child
  import 打印实际 `company_wiki.__file__`/`transcript_tool.__file__` 验证落在 supplied 码根并记 SHA，
  再执行。数据根是 owned fixture root（`company_wiki_root`），绝不把 `--cwp-project` 当生产数据根。
- **链 A（真三层）**：FF v2 请求 = 本地命中 filing + `companion_transcript(fetch_if_missing, exact FY/Q)`。
  FF config `earnings_transcripts_tool` 指向 **test-proxy** `et_transcript_proxy.py`（明确标注 test-proxy，
  非未经代理生产二进制）。proxy 转发真实 `transcript_tool.main` argv，只用既有 private launcher seam
  （`tests.test_retrieval_runtime:build_fake_session`）替换 worker HTTP。真 supervisor/worker/transcript_api
  子进程照常跑。ET 结果经 FF 真实 `transcript_import_cli` 入 CWP，`source_reader_cli` open_version 实读校验。
- **财报 fixture provider**：`fixture_provider_adapter.py`（CWP `json_command_v1`，cn/hk/us）在
  *fixture provider 边界* 合成供应商响应（candidate + 下载原件），真实 CWP ensure/import 照常执行。
  合成原件是**合法小 PDF/HTML/TXT**（PDF 含正确 xref/trailer），元数据 synthetic，绝非 `%PDF` 占位。
- **独立状态**：scratch 内含 fixture wiki root + configs + security master + calls/tmp/receipts。
  子进程最小合成环境（假 FMP_KEY、无生产路径）；`config/FMP_API_KEY.txt` 从不读取/复制/提交。

## 文档类型覆盖图

| 案例 | 文档类型 | 声明层 | 预期观测层 | 预期检查 |
|------|----------|--------|--------|------|
| chainA_download_reuse | investor_call_transcript | real-3layer | ff-cli + et-supervisor/worker + cwp-import | 下载→复用（1→0 请求） |
| fin_cn_annual_hit | annual_report | ff+cwp | ff-cli + cwp-source-query | 本地命中，0 请求 |
| fin_hk_semi_hit | semi_annual_report | ff+cwp | ff-cli + cwp-source-query | 本地命中，0 请求 |
| fin_us_quarterly_hit | quarterly_report | ff+cwp | ff-cli + cwp-source-query | 本地命中，0 请求 |
| fin_hk_annual_fetch | annual_report | ff+cwp | ff-cli + cwp-ensure/import + fixture-adapter | fetch_if_missing 下载→复用 |
| nonperiod_prospectus | prospectus | ff+cwp | ff-cli + cwp-ensure/import + fixture-adapter | 按自身 kind 入库 |
| nonperiod_equity_offering | equity_offering_prospectus | ff+cwp | 同上 | 按自身 kind 入库 |
| nonperiod_convertible_bond | convertible_bond_prospectus | ff+cwp | 同上 | 按自身 kind 入库 |
| nonperiod_investor_relations | investor_relations | ff+cwp | 同上 | 按自身 kind 入库 |
| call_fy_only_no_q | investor_call_transcript | ff-only | ff-cli（period 门） | FY-only 不猜 Q4 → period_unresolved |
| call_past_cutoff | investor_call_transcript | ff+et | ff-cli + et-supervisor/worker | 过 cutoff 给实际诊断，非 eligible |
| call_wrong_quarter | investor_call_transcript | ff+et | ff-cli + et-supervisor/worker | 季度 provenance 拒绝不匹配 |
| err_request_error | — | ff-only | ff-cli（请求校验） | request_error + diagnostic |
| err_402_entitlement | investor_call_transcript | ff+et | ff-cli + et-supervisor/worker | provider_entitlement_required |
| err_missing_creds | investor_call_transcript | ff+et | ff-cli + et-credential-preflight | 凭证缺失诊断，0 请求 |
| err_unknown_usage | investor_call_transcript | ff+et | ff-cli + et-worker-failure | 未知 usage=null（非 0），不吞调用 |

覆盖：CN/HK/US 周期报（annual/semi/quarterly）本地命中；无本地 fetch_if_missing 走 fixture provider，
reuse_only 不获取；非周期 prospectus/equity_offering/convertible_bond/investor_relations 按自身 kind 入库
（未支持者如实具名 gap，不改合同/provider，ROOT 决定）；US call 精确 FY/Q 各分支；请求/凭证/费用/402/重复请求等错误。
生产配置/原件初末无写；HTTP≤0 真实、translation=0；fixture 请求单列。

## oracle 失败向量（Node A RED）

`oracle.py` 审查 report，检测六向量；`tests/test_w06_contract_matrix.py tests/test_w06_matrix_runtime.py tests/test_w06_case_authority.py` 逐一证明检测（RED）：

1. `fake_layer_claimed_real` — 整层 fake 却声明 real-3layer。
2. `second_run_still_downloads` — 复用 case 第二次仍下载。
3. `missing_et_receipt` — 真三层发起了 provider 调用却无 ET usage receipt。
4. `wrong_cutoff` — 过 cutoff case 未给实际 cutoff 诊断。
5. `fake_zero_cost` — 未知 usage/费用被写成 0 或吞调用。
6. `unrestored_scratch` — 生产字节变动或 sentinel 未恢复。

report schema `ff-et-cwp-offline-matrix/1`，逐 case 记 declared/observed layer、实际模块/HEAD/SHA、
request/response/receipt refs、provider counters、下载/翻译、expected/actual/PASS|FAIL|NOT_RUN、scope、恢复。
未知值一律 `null`，不代填 0。

## ROOT reception status (2026-10-11)

The table above describes intended coverage, not observed PASS. The fixed required registry contains 41 cases. Exit 0 requires every case PASS, complete bound request/response/receipt/fresh-byte evidence, measured budgets, and restored owned scratch. FAIL/PARTIAL/NOT_RUN or any oracle finding returns nonzero.

Each run creates fresh UUID scratch and output children. Only that scratch child and newly-created empty scratch ancestors are removed. Old files, sentinels, output reports, and initially-existing empty directories are preserved. Retained output is evidence and is not scratch. Process deadlines are absolute across seed/binding/cases/proofs; owned child trees are terminated/reaped when exhausted. Child startup has an explicit platform-variable allowlist, synthetic HOME/config/fake key and socket/translation guards before product imports. No real configuration/key bytes are read or hashed; only stat metadata is observed.

Final engineering checks: 34 PASS and Ruff clean. Integration result: 19 PASS / 21 FAIL / 1 PARTIAL in 132.54 s. Nine real-writer warm2024 sources succeed; 2025/2026 acquisition and primary-filing preconditions remain unresolved. Actual verified source-fact assertions are absent in the minimal repro, so these results alone do not establish the producer root cause. ROOT owns investigation. See docs/handoffs/w06-ff-matrix/root_handoff.md. Do not downgrade expectations, skip cases, hand-create assertions, or call the result COMPLETE.

Fixture responses exercise actual FF/CWP/ET runtime when its prerequisites resolve. They do not prove configured StockInfoDLSimple/Dayu supplier reachability. Configured A-share downloader is StockInfoDLSimple/v2-clean-rewrite; Dayu remains external and receives no code writes. Unknown producer usage remains null; observed fixture calls are separate and never substituted for real-cost data.

## Fixed case authority (ROOT repair, 2026-10-11)

`case_specs.py` is the only executable definition of mandatory cases, full input requests, provider fixture scenarios, expected assertions and declared scope. `cli_main._case_registry()` binds its exact CaseSpec objects; Context verifies each request/fixture vector before starting FF; oracle independently uses the same definitions. `report.required_cases`, expected flags, scenarios and result labels are observations, never authority. Missing/unknown/duplicate cases, changing market/company/period/as-of/intent/mode/companion/limits, clearing an expectation or relabeling an incompatible response PASS cannot certify acceptance.

`oracle.audit_case(spec, case)` is a component check. `oracle.audit(report)` additionally checks the complete fixed coverage and bound request/response/fixture bytes, source proofs and measured isolation. A single case/component positive control never certifies a complete product matrix. Historical reports without newly required fixture receipts remain historical/partial; do not manufacture them. No new human permission, authorization document or identity database is involved.

Focused tool checks: 195 PASS (~5 seconds) and Ruff clean. The original actual product matrix remains 19 PASS / 21 FAIL / 1 PARTIAL. See `docs/handoffs/w06-ff-matrix/case-authority/handoff.md` for independent reception. Construction helper scripts in canonical evidence are historical one-shot edit records, not replay entry points; run the three test files above, then the unchanged real matrix only after ROOT producer fixes.

## 可搬迁保留证据重放（DU6-FF-PORTABLE-EVIDENCE）

接收方拿到的 ZIP/report 里 `evidence_root` 是供应商机器上的绝对路径；搬迁后不必再手工改 review copy，也不必重跑供应商链。

**Python**：`oracle.audit(report, *, evidence_root=None)`。`None` 与旧行为完全一致（取 `report.evidence_root`）；
显式 root 只改现有相对 request/response/fixture/ET receipt 引用的读取根，同一个 `_bound_evidence` 做同样的
SHA/CaseSpec/原 findings 校验。不改写传入 report 或任何输入文件；不搜索磁盘、不回落旧绝对根；override 不是新的身份/授权状态。

**公开 CLI**（`run.py` 直接承载，旧矩阵 argv 不变）：

```
python -B tools/offline_contract_matrix/run.py replay \
  --report ABS_REPORT --evidence-root ABS_ARTIFACTS --output ABS_NEW_REPLAY_JSON
```

- 不要求 `--cwp-project/--et-project/--owned-root/--out-root`；只读保留证据并调用原生 `audit`，
  不启动 Context/seed/provider/CWP/ET/fresh reader/网络。
- 输出是小型 **`ff-matrix-evidence-replay/1`** 记录（不是第二份矩阵报告）：原 report 字节 SHA、原 schema、
  选择的 evidence_root、原 case 结果计数与逐 case 原结果、原 recorded oracle/findings、当前 native replay findings、
  明确历史重放 scope、退出状态。
- 退出码：`0` 仅当原完整矩阵各 case 都 PASS、原 recorded oracle 通过且无历史 findings、且当前 native audit 无 findings；
  重放“只是读得对”是 `1`；输入/输出错误（缺文件、非法 JSON、未知 schema、错误 root、输出同路径/已存在/落在 artifacts 内）是 `2`。
  任何 FAIL/PARTIAL/NOT_RUN、历史 findings、未知 usage=null 都不因路径修好被升级为成功。
- 不覆写原 report、原 artifacts 或已有重放输出；新输出必须是明确独立路径。
- 重放只证明“保留字节 + 当前 oracle”的结果；**不等于**重新读取生产原文、重新下载、重跑 41 链、
  或认证真实供应商/公司数字（与 fresh 真实 41 链 scope 分列声明）。
