# W06-FF-MATRIX 交接

**状态：COMPLETE**（离线合成范围内的工程契约与真三层联调通过；非真实供应商/经济质量证明）。
分支 `codex/w06-ff-contract-matrix`，base `08ec85b`，head `8dd00e2`。产品源码零写。

## 交付
- `tools/offline_contract_matrix/`：手动 runner（`run.py`）、fixture builder（合法合成 PDF/HTML/TXT）、
  ET test-proxy（复用既有 private launcher seam）、财报 fixture provider（CWP json_command_v1）、
  失败向量 oracle、report schema、README 覆盖图。
- `tests/test_w06_contract_matrix.py`：oracle RED 六向量 + 合法原件 + report schema 单元测试。
- 报告：`attempts/attempt-5/report.json`（GREEN，16 PASS/0 FAIL，oracle 0 findings）；
  `attempts/attempt-1/report.json`（RED，oracle 当场旗标 3 个真实失败向量，证明检测有效）。
- RED/GREEN 日志分开保留：`logs/unit-tests.log`（RED 检测）+ attempt-1(RED)/attempt-5(GREEN)。

## 真三层（链 A）已证明
FF `fetch_filing.py` 公开 CLI → `EarningsTranscriptsTransport` → ET `transcript_tool.main` →
真实 retrieval supervisor/worker/transcript_api（仅 worker HTTP 经既有 private launcher seam 替换）→
FF 真实 `transcript_import_cli` 导入 → CWP 原文注册 → `SourceVersionReader.open_version` 实读校验 →
再次 FF 同请求命中（1 → 0 fixture 请求）。ET usage receipt 齐备；test-proxy 明确标注。

## 覆盖矩阵
见 `tools/offline_contract_matrix/README.md` 覆盖图。CN/HK/US 周期报（annual/semi/quarterly）本地命中；
无本地 fetch_if_missing 走 fixture provider、reuse_only 不获取；非周期 prospectus/equity_offering/
convertible_bond/investor_relations 按自身 kind 入库（未冒充 annual/FY，无具名 gap）；US call 精确 FY/Q
各分支（本地命中 0 请求/缺失下载/正确季度/FY-only 不猜 Q4/过 cutoff/unknown publication）；
请求/凭证/402/未知费用/重复请求等错误诊断。生产配置/原件初末无写；HTTP≤0 真实、translation=0；
fixture 请求单列（9 次）不入母账；未知 usage=null 不代 0/不吞调用。

## 关键发现（详见 handoff.json findings）
- W06FF-01：CWP `prepare_local_source` 对同 entity+kind 不同期已存在源会返回阻塞 gap，抢先于 fixture
  provider；本线 fetch case 选无同类候选组合以达 fixture 边界，未改产品/合同，ROOT 决定修复。
- W06FF-02：FMP transcript `publication_date=null`，故复用命中显示 `unknown_publication`（正确行为）。
- W06FF-03/04：过 cutoff 给实际诊断非 eligible；worker 失败时 unknown usage=null 非 0、不吞调用。

## 恢复与成本
scratch（owned root）每次 run 后删除；生产 config/原件 metadata 初末一致；sentinel 完好；
baseline `raw_unchanged=true`。真实收费 0、unknown_charge=null；fixture 请求单列。

## ROOT 下一步
用最终 CWP/ET 码根重跑真三层关键路径（`tools/offline_contract_matrix/run.py`）后并线；可将 W06FF-01/02
作为产品跟进候选。worker 未重置其他 worktree、未推主线、未改 API 配置。
