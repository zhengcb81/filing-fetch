# P5-FF Handoff：旧Worker编排退出与真正有界的JSON进程

Lane: `P5-FF` · state `complete` · branch `codex/p5-ff-runtime-cleanup`
base `d4d2fac4…`（源仓published main，tracked干净）→ delivery `b5c1c824…`
worktree `C:/Users/郑曾波/Projects/cwp-lanes-20261005/ff-runtime-cleanup`
machine win32 / Python 3.13.9 / date 2026-10-05

## 1. 交付内容（commit `7c6cf48`）

1. **旧Worker编排退出**（`scripts/fetch_filing.py`，-782行 diff）：
   - 删除：`PausedWorkerScope`类（L561-706）、`_PAUSE_REFCOUNT_NAME`/`_PAUSE_OWNER_NAME`/`_WORKER_STATUS_TIMEOUT`、`_pid_is_alive`、`_read_pause_entries`/`_write_pause_entries`/`_prune_pause_entries`、三处scope调用点（`_resolve_source_ref_v2`/`_run_legacy_filing_command`/`_close_gap_and_return_handle`）及其为ensure/close-gap追加的`--allow-acquisition-while-paused`。
   - 兼容：`resolve_filing(pause_worker=…, worker_graceful_timeout_seconds=…, worker_resume_wait_seconds=…)`与CLI `--no-pause-worker`/`--worker-graceful-timeout-seconds`/`--worker-resume-wait-seconds`保持接受、updated help标inert；未新增第二开关。
   - 计数：`stats["calls"]`只计真实上游调用——每次授权下载少~2次worker-status调用，不补虚拟调用。
   - `worker_paused`仍是合法的上游taxonomy code，具名透传、不自动重试。
2. **一处集中的有界进程层**（新`scripts/ff_process_transport.py`，两runner共用）：
   - stdout/stderr在**读取期间**按实际字节计数；`MAX_JSON_OUTPUT_BYTES=32MiB`处即停（不是读完才检查）；非ASCII按UTF-8字节计（1000个汉字=3000字节即可触发2500字节的cap，已测）。
   - stderr并发读取、自有64KiB cap；原始stderr/凭证不回显（错误只出exit码+分类码，经典测试`FAKE_SECRET_KEY_DO_NOT_LEAK`继续通过）。
   - 所有child共享请求剩余deadline，不分段续期；ET 3秒外层清理宽限保持。
   - Windows：`job object`（KILL_ON_JOB_CLOSE，`PROCESS_ALL_ACCESS`权限申请——0x201等窄权限会EPERM），child退出而孙进程持pipe时`TerminateJobObject`后读取者~0.3s回归（真实Popen孙持pipe场景验证）；pywin32缺失时降级`taskkill /T /F /PID`。POSIX：child进程组（setsid）+killpg。只杀本调用创建的树，不扫描他人。
   - 无后台读取线程遗留（非daemon + 双EOF join(timeout=5)）。
   - 复杂度ratchet：新文件max per-function 8（上限10）。
   - 具名失败：`OutputLimitExceeded`/`ChildTimeout`/`ChildFailed(携带stdio chunks)`，调用方映射为`upstream_error`（cap/timeout）或按stderr分类码（exit≠0）。
3. **runner接线**：filing `_run_company_wiki_json`/`_run_source_query`与transcript `_run_json`/`_verified_open`/`_et_result`全部走该层；provider/hash/period/as-of/golden与复用计数语义未变。
4. 测试面迁移：旧`patch("fetch_filing.subprocess.run")`（74+处）改到新接缝`_run_bounded_json`，`tests/support/__init__.py`负责`CompletedProcess → (stdout_bytes, stderr_bytes, rc)`适配。runner专属worker断言迁为“无旧调用/写盘”（`test_p5_worker_scope_retirement.py`：任何resolve/reuse/download路径都不触碰`worker-*`/`filing_fetch_pause.*`）。
5. 文档：SKILL.md工作流第5步与Notes改"retired"；CHANGELOG Unreleased记两条。

## 2. 可运行验收命令

```bash
# 责任测试（18绿）
python -m pytest tests/test_p5_process_transport.py tests/test_p5_worker_scope_retirement.py -q

# 迁移后全绿责任集（194绿）
python -m pytest tests/test_fetch_filing.py tests/test_fc802_gap_orchestration.py \
  tests/test_s3_single_request_limits.py tests/test_source_ref_v2_db_query.py \
  tests/test_transcript_companion_transport.py tests/test_transcript_companion.py \
  tests/test_source_ref_v2.py tests/test_ff_v2_contract.py \
  tests/test_zr405_policy_roots.py tests/test_ff_golden.py tests/test_complexity_ratchet.py -q

# 快速发布门（ruff/mypy/smoke/plan-claims/BOM 全绿）
python tools/pre_push_gate.py
```

## 3. 测试账目（简实读）

全仓`pytest tests/`：**463过 / 10失败 / 14跳过（163s）**。10个失败**开卡前在干净`d4d2fac`基线上即失败**（变更前已复跑核对，集不变）：

- `tests/test_fc803_minimal_download.py` LT-01/02/05/07/09 与 `tests/test_e2e_isolated_wiki.py` 的TestCatalogLockContention(2)+TestWorkerPaused(3)。
- 根因（上游，非本卡引入）：CWP `288b028 feat: enforce source acquisition budgets` 起，`ensure --allow-download` 无`--max-download-*`限额即fatal；这些fixture的request不带`acquisition_limits`。MAIN修法二选一：fixture加limits，或放宽CWP门。属MAIN §6所有，不在本卡写集。

## 4. 事实（本卡）

- 0外网/0真实下载/0 LLM；`handoff.calls`全0。生产config/raw/owner文件未触碰（tracked tree干净）。
- 正文SHA引用（card §5，`d64c4108…`中微2025年报）只读引用，未复制到本卡fixture（对应E2E是baseline-red集合的fc803，不可执行）。
- 临时根：全部pytest TemporaryDirectory + S3 fake CLI isolated包；结束即恢复，无生产残留；诊断脚本已删（diag helper文件未进提交）。
- producer HEAD：company-wiki published `f775406`（只读）; ET HEAD `63c4090`（只读，unused by这组测试）。

## 5. 交接契约注意

- `handoff.json` ⊂ `cwp-parallel-handoff/2`（commit列表、changed_paths、upstream接口、entrypoints、tests真实计数、real_samples标注fixture、cleanup、protection、calls全0、metrics含限额/进程回收指标、remaining含 baseline-red 与 POSIX未在真CI覆盖两项）。
- SourceRef 2.0 / FF operation /1（ensure/close-gap）/ CWP transcript import /2,/3 / ET /1,/2 schema不变；本卡无wire变更，MAIN合入不要求补跨仓E2E新golden。
- 剩余责任：MAIN收到后按总包流程审diff/合入；REAL跨仓离线链（FF→ET→CWP companion与受限download）在本包隔离根的既有责任测试全部绿，真实原文E2E上限述baseline-red。
