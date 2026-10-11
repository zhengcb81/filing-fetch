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

每 case 超时 ≤30s；批次目标 ≤180s；失败保留 partial。二次执行用新 attempt，不覆第一次。
单元测试（快速、离线、不跑跨仓）：`python -B -m pytest -q tests/test_w06_contract_matrix.py`。

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

| 案例 | 文档类型 | 声明层 | 观测层 | 结果 |
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

`oracle.py` 审查 report，检测六向量；`tests/test_w06_contract_matrix.py` 逐一证明检测（RED）：

1. `fake_layer_claimed_real` — 整层 fake 却声明 real-3layer。
2. `second_run_still_downloads` — 复用 case 第二次仍下载。
3. `missing_et_receipt` — 真三层发起了 provider 调用却无 ET usage receipt。
4. `wrong_cutoff` — 过 cutoff case 未给实际 cutoff 诊断。
5. `fake_zero_cost` — 未知 usage/费用被写成 0 或吞调用。
6. `unrestored_scratch` — 生产字节变动或 sentinel 未恢复。

report schema `ff-et-cwp-offline-matrix/1`，逐 case 记 declared/observed layer、实际模块/HEAD/SHA、
request/response/receipt refs、provider counters、下载/翻译、expected/actual/PASS|FAIL|NOT_RUN、scope、恢复。
未知值一律 `null`，不代填 0。
