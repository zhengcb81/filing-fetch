# FF-S3 局部 progress

基线 `origin/main@c47c397c4d93979d8a7defbe026eff9e9edf0e6d`，分支
`codex/ff-s3-single-request-limits`，实现主体提交
`8c340f8dcce6f85b0ff106ac56484cde3caab7b5`，唯一写入工作目录
`C:\Users\郑曾波\Projects\filing-fetch-s3-limits`。

## 基线（改动前，2026-10-03）

- `python -m pytest tests -q --ignore=tests/test_real_tool_conformance.py --ignore=tests/test_e2e_download.py`
  → **433 passed, 8 skipped, 1 failed**（186s）；唯一失败
  `tests/test_fc1307a_host_assumption_gate.py::test_fc1307a_the_three_vendored_copies_are_byte_identical`
- `ruff check scripts tests tools e2e` → 通过；`mypy scripts/filing_contracts.py scripts/fetch_filing.py` → 通过
- 覆盖率基线（同 CI 命令）→ **81.66%**（`--cov-fail-under=90` 本地即红，属既有状态）

## RED（先行失败行为测试）

- `tests/test_s3_single_request_limits.py`：**12 failed**（37.9s）
- `tests/test_s3_install_surface.py`：**6 failed**（0.7s）
- 两文件共 18 个新测试在实现前全部为红，覆盖：三额度进 argv、库/CLI 单意图一致、
  冲突具名报错、请求期限压缩 deadline、producer 拒参数只失败一次、输出字节 cap、
  超时回收、stderr 不回显、close-gap 额度、golden、安装面排除、pre-push 只读。

## GREEN（完成后）

- 责任测试包（一次）：
  `python -m pytest tests/test_s3_single_request_limits.py tests/test_s3_install_surface.py
  tests/test_ff_v2_contract.py tests/test_ff_golden.py tests/test_source_ref_v2.py
  tests/test_source_ref_v2_db_query.py tests/test_transcript_companion.py
  tests/test_transcript_companion_transport.py tests/test_fetch_filing.py
  tests/test_fc802_gap_orchestration.py tests/test_fc1204_coverage_gap.py
  tests/test_complexity_ratchet.py tests/test_verify_plan_claims.py -q`
  → **337 passed, 3 skipped, 78 subtests passed**（60.96s），0 failed
- 独立 CLI E2E：`FILING_FETCH_V2_WIKI_SRC=<company-wiki/src> python -m pytest e2e/test_source_ref_v2_cli.py -q`
  → **1 passed**（9.50s）
- 全量 hermetic：
  `python -m pytest tests -q --ignore=tests/test_real_tool_conformance.py --ignore=tests/test_e2e_download.py`
  → **450 passed, 8 skipped, 2 failed**（192.81s）
- `ruff check scripts tests tools e2e` → All checks passed
- `mypy scripts/filing_contracts.py scripts/fetch_filing.py` → no issues
- 复杂度棘轮：`fetch_filing.py` max **32**（冻结 34）、`filing_contracts.py` max 39（冻结 39）
- 覆盖率（同 CI 命令）→ **82.22%**，较基线 81.66% 上升；`--cov-fail-under=90`
  仍红，属既有状态，本卡不新增/不重跑全仓 coverage 门。

## 两个环境红灯（均已在净基线上复现，与 FF-S3 无关）

1. `test_fc1307a_the_three_vendored_copies_are_byte_identical`
   本仓 LF 18794 B `9294dc7c…`；兄弟 `Projects\filing-fetch`、`Projects\company-wiki`
   落盘 CRLF 19190 B `20c9da56…`。归一化后内容完全一致，纯行尾漂移。兄弟仓只读。
2. `test_e2e_isolated_wiki.py::TestWorkerPaused::test_e2e_worker_paused_blocks_download_with_no_pause_worker`
   会话期间兄弟 `Projects\company-wiki` 由 `a104d25` 前进到
   `73de6be refactor: retire legacy source catalog worker routes`（-218 行 cli.py、
   删除 worker/control/startup 路由与 `source_catalog_worker.ps1`）。
   在净基线 `c47c397` checkout（Temp）上同一测试同样失败 → 上游漂移，非本卡改动。

## 临时根与清理

- 所有测试用 pytest `tmp_path` / `TemporaryDirectory`，`finally` 清理。
- 假 `config/FMP_API_KEY.txt` 只在 `try/finally` 内创建与删除，断言退出后不存在；
  未读取任何真实 key。
- 无关哨兵进程在 `finally` 中 kill 并 `wait`。
- `git status` 交付时仅含本卡改动，无 `nul`、无 pycache、无密钥、无下载原件。

## 未做（按卡片）

- 未合 main、未做全局安装、未启动 worker、未写 company-wiki/ET/StockWiki/IQS。
- 未新增签名、人工授权文件、逐候选 receipt、覆盖率门、场景数门。
- 跨仓正式限额接口 E2E 记为 pending（见 handoff）。
