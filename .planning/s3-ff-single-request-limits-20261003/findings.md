# FF-S3 局部 findings

## 现状核对（基线 c47c397）

1. `scripts/filing_contracts.py::_validate_acquisition_limits` 只做 EXACT 校验
   （`max_bytes` 正 int 非 bool、`timeout_seconds` 正有限数非 bool、
   `max_cost_usd` 非负最多两位小数字符串、`reuse_only` 不得带额度）。
   校验后的额度没有任何出口。
2. `scripts/fetch_filing.py::_command_arguments`（L208-241）只输出业务字段，
   不输出限额；`_resolve_source_ref_v2`（L1018-1081）与 `_close_gap_and_return_handle`
   （L1433-1538）都经由它构造 `ensure` / `close-gap` argv，因此限额整体缺失。
3. CLI `main()`（L1671-1674）按 `filing_intent` 推导一次 `allow_download`；
   `resolve_filing(allow_download: bool = False)`（L1145）是第二个默认 False 布尔。
   同一 v2 `fetch_if_missing` 请求：CLI 会下载，直接调库默认不下载 → 分化。
4. `resolve_filing` 的 deadline 只来自 `timeout_seconds` 或外部 `deadline`，
   不吸收 `acquisition_limits.timeout_seconds`，因此请求写的 60s 不生效。
5. `_run_company_wiki_json`（L256-305）用 `capture_output=True` 无输出字节上限，
   且失败时把 `stderr[-2000:]` 原样放进异常消息（可能含路径 / key），
   超时异常消息也带 `exc`（含命令行路径）。
6. `SKILL.md` 顶部写 `v1.4.0`，正文只讲 schema 1.1 与 `--allow-download`，
   完全没有 v2 / `filing_intent` / `acquisition_limits` / SourceRef / ET 工具配置。
   `references/contract-ownership.md` 仍写“先取得用户显式授权再转发下载授权”，
   对应已退役的 v1 `authorization` 双门。
7. `tools/sync_installs_b3.py` 的 `ROOT_DIRS` 含 `tests`，`config/` 递归纳入
   （有机会带入本地 key）；无参数即写入 `~/.agents|~/.claude|~/.codex`；
   `tools/pre_push_gate.py::_install_sync` 在 pre-push 里自动执行该写入。

## 关键约束（实现时必须守住）

- **不增加 `time.monotonic()` 调用次数**：`tests/test_fetch_filing.py`
  用 `side_effect=[...]` 固定单调时钟序列（3/2/4/5 个采样），
  额外采样会 StopIteration。deadline 收敛必须在现有那一次采样内完成。
- **不替换 `subprocess.run`**：约 50 处测试 `patch("fetch_filing.subprocess.run")`。
- **`filing_contracts.py` 复杂度已顶到冻结值 39**，不得新增分支。
- **`fetch_filing.py` 冻结 34，当前 32**；`resolve_filing` 当前 32，余量 2。
- CI 有 `--cov-fail-under=90`（`scripts/` 分支覆盖），新增分支需要测试覆盖。
- `tools/verify_plan_claims.py --plan-dir .` 会递归发现本仓 `task_plan.md`：
  局部 PWF 不得使用 `## Phase N（...）— 状态：completed` 标题。

## CWP 侧（只读核对，不改）

- `company_wiki.source_catalog.cli` 的 `ensure` / `close-gap` 目前**不接受**
  `--max-download-bytes/--max-download-seconds/--max-download-cost-usd`。
  argparse 会以 unrecognized arguments 退出 → FF 按非零退出具名失败。
  这正是“producer 不认识三参数时具名不支持/失败”的现状；root 补齐前，
  跨仓正式接口 E2E 记为 pending，不得剥参数重发或回退 v1 绕过额度。
- CWP `config/source_acquisition.yaml` 的 `timeout_seconds`（当前 1800）
  是适配器配置期限，由 CWP 自己消费；FF 侧“配置期限”取
  `--timeout-seconds` / `resolve_filing(timeout_seconds=)` 的配置值。

## 会话内出现的环境红灯（均已在净基线 `c47c397` 复现，非 FF-S3 引入）

### 1. vendored guard 行尾漂移 — 已按 root 决策处理

`tests/test_fc1307a_host_assumption_gate.py::test_fc1307a_the_three_vendored_copies_are_byte_identical`
（处理后更名 `..._are_content_identical`）
- 本仓 LF 18794 B `9294dc7c…`；`Projects\filing-fetch`（fcap@d35b6f5）
  与 `Projects\company-wiki` 均为 CRLF 19190 B `20c9da56…`
- `.gitattributes` 双方都有 `*.py text eol=lf`，但兄弟工作树落盘为 CRLF
  （git clean filter 归一化后 `status` 仍显示干净）
- 归一化 `\r\n -> \n` 后三份内容完全一致：纯行尾差异，无代码差异
- **处置**：比较前先把 `\r\n` 折成 `\n`。量的是代码而不是 checkout；
  真实内容差异仍然全红。`tools/host_assumption_guard.py` 本体与两个兄弟仓均未改动

### 2. 上游 CWP 在本会话中退役了 worker 路由

`tests/test_e2e_isolated_wiki.py::TestWorkerPaused::test_e2e_worker_paused_blocks_download_with_no_pause_worker`
- 会话开始时 `Projects\company-wiki` HEAD = `a104d25`；结束时 = `73de6be`
  `refactor: retire legacy source catalog worker routes`
  （cli.py -218、control.py -236、startup.py -134，删除
  `source_catalog_worker*.ps1/.vbs`、`test_source_catalog_worker*.py`，
  重写 `test_source_catalog_ensure_paused_guard.py`）
- 结果：`--no-pause-worker` 下 CWP 不再返回 `worker_paused`，而是 `not_found`
- 在净基线 `c47c397` checkout（Temp）上复现同一失败 → 上游漂移
- CWP 自己的契约（只读核对，`tests/contract/test_source_catalog_ensure_paused_guard.py`）：
  `ensure --allow-download` 与 `close-gap` 都**不**查询 worker 状态 ——
  以 `()` 与 `("--allow-acquisition-while-paused",)` 两种入参参数化，断言
  `WorkerController` 从不被调用、`"source acquisition is paused" not in err`；
  `worker-status`/`worker-stop` 仅剩“检查/收尾遗留 worker”，`worker-pause`、
  `worker-resume` 已不存在；`--allow-acquisition-while-paused` 仍被接受（no-op）。
- **处置**（root 选定“按 CWP 新契约更新 worker 用例”）：
  - 测试重写为 `test_e2e_no_pause_worker_is_retired_upstream`，断言 `not_found`/不可重试；
  - `SKILL.md` 工作流第 5 步、`--no-pause-worker`/`--worker-*` 说明、
    `worker_paused` 错误行、两条 Notes 改为“pause-around 已被上游退役”；
  - `PausedWorkerScope` 代码保留（薄兼容：`worker-status` 失败即告警并继续，
    不存在的 `worker-pause`/`worker-resume` 不会被调用），未做超出本卡的编排重写

## 覆盖率门

同 CI 命令 `pytest tests --cov=scripts --cov-branch --cov-fail-under=90`
- 基线（净 `c47c397`）：**81.66%**
- 本卡交付：**82.22%**
- 本地两端均红；卡片明确要求“不要全仓 coverage 重验”，故不新增覆盖任务。

## Root acceptance findings — 2026-10-03

- The observed CWP budget failure is caused by the current producer worktree, not by the committed base alone: CWP CLI now requires all three `--max-download-*` values for download/latest-as-of routes, while FF legacy v1 requests cannot carry them. FF v2 `fetch_if_missing` has the limits and passed its argv/intent tests.
- The FF pre-push hook used to execute the full hermetic suite; a real push attempt waited **166.60s** and failed 10/452 tests. The owner has repeatedly asked for faster normal gates. The hook is now fast-only, CI runs one selected suite once, and full tests remain opt-in/manual.
- Verified post-simplification: selected regression **358 passed, 4 skipped, 78 subtests**; SourceRef CLI E2E **1 passed**; fast pre-push gate green. No real provider or credential was used.
- Still unresolved: CWP has no production `discover_bounded` / `fetch_bounded`; its budget contract currently only has fake bounded adapters in tests. Dayu code is prohibited from changing. The CWP/FF integration must fail closed until an approved provider capability exists; don't label argv passthrough as provider enforcement.
- Request contract questions for root: v1 download without encoded limits should be rejected or receive a documented bounded default; `reuse_only + latest_as_of` must be clarified because FF forbids limits there while CWP currently demands them and its Dayu discovery can fetch document bodies.
