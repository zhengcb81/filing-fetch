# FF-S3 交接：一请求、实际限额与安装面简化

普通交接，不是授权合同。root 负责核 diff、补 producer、合 main 与统一安装。

## 1. 身份

| 项 | 值 |
|---|---|
| base | `origin/main` @ `c47c397c4d93979d8a7defbe026eff9e9edf0e6d` |
| branch | `codex/ff-s3-single-request-limits` |
| head | 本交付提交（`git rev-parse HEAD`，交付分支上最后一个提交） |
| 工作目录 | `C:\Users\郑曾波\Projects\filing-fetch-s3-limits`（唯一写入处） |
| 局部 PWF | `.planning/s3-ff-single-request-limits-20261003/`（task_plan / findings / progress） |
| 仓内改动 | 8 modified + 5 new（见 §2） |
| 基线漂移 | 无 reset、无 rebase；基线与计划一致 |

## 2. 修改清单

### 行为（`scripts/`）

| 文件 | 改动 |
|---|---|
| `fetch_filing.py` | 新增 `_limit_arguments`：把 `acquisition_limits` 渲染成三个 `--max-download-*`，由 `_command_arguments` 追加，`ensure` 与 `close-gap` 同时携带 |
| `fetch_filing.py` | 新增 `_download_intent(request, explicit)`：**唯一**下载意图推导点。v2 以 `filing_intent` 为准，显式 `allow_download` 只能确认不能反驳（反驳 → `request_error`）；v1 返回调用方 flag。`resolve_filing(allow_download=...)` 默认改为 `None`（原默认 `False` 造成库/CLI 分化）；`main()` 也走同一函数 |
| `fetch_filing.py` | 新增 `_shared_deadline(...)`：一次 `time.monotonic()` 采样取 min(剩余全局 deadline, 配置 `timeout_seconds`, 请求 `acquisition_limits.timeout_seconds`)，结果即本次请求所有子进程共享的 deadline。**单调时钟采样次数与基线完全一致**（既有 `side_effect=[...]` 测试序列未变） |
| `fetch_filing.py` | `_run_company_wiki_json`：超时/启动失败不再回显异常正文（含命令行路径）；非零退出只报 `exited <rc>` + `_classify_wiki_error` 分类码，**不再回显 stderr 正文**；新增 stdout 字节 cap（共享常量） |
| `fetch_filing.py` | `_run_source_query`：同样拆分 timeout/OSError，不再回显 `exc` |
| `fetch_filing.py` | `_resolve_source_ref_v2` 内过期的 “frozen RequestPlan producer” 注释改为当前语义（额度已在 argv；producer 仍报 gap 就如实返回 gap） |
| `transcript_tool_transport.py` | `_MAX_JSON_BYTES` → 公开 `MAX_JSON_OUTPUT_BYTES`，供 fetch_filing 复用（同一字节天花板，不新建第二条后台 pipe 线程） |

### 安装面（`tools/`）

| 文件 | 改动 |
|---|---|
| `sync_installs_b3.py` | manifest 收窄为**允许清单**：`SKILL.md`、`CHANGELOG.md`、`references/`、`scripts/`、`config/company_wiki.json`；移除 `tests/`、`.gitignore`、`config/` 递归。新增名称闸：凭据标记（api_key/secret/token/credential/…）、`.env*`、`.pem/.key/.p12/.pfx/.log`、缓存目录、`.pyc/.pyo` |
| `sync_installs_b3.py` | CLI 变为二选一：`--check`（只读）或 `--install`（唯一写入模式），可 `--dest DIR` 指向仓内临时目标；**无参数 → usage 错误 exit 2**，不再默认写 `~/.agents|~/.claude|~/.codex`；`main(argv)` 支持注入便于测试 |
| `pre_push_gate.py` | `_install_sync`（check→自动 sync→re-check）替换为 `_install_check`：只跑 `--check`、打印漂移、**恒返回 0**——既不写全局技能根，也不因安装漂移拦 push |

### 文档

| 文件 | 改动 |
|---|---|
| `SKILL.md` | 重写：schema `2.0` 为推荐入口（`filing_intent` + `acquisition_limits` + pathless `source_ref`），`1.2`/`1.1` 明确标为 legacy 薄兼容；新增 *Acquisition limits*、companion transcript（FY/Q、`EARNINGS_TRANSCRIPTS_TOOL`、失败分离）、*Installing this skill* 章；删除 `v1.4.0` 版本行与“schema 1.1 即全部”的旧双门口径；保留全部如实能力限制（Indexed≠Reusable、exact vs latest、Real-root canary limits 等） |
| `references/contract-ownership.md` | “先取得用户显式授权再转发下载授权”（v1 `authorization` 双门）→ “只转发一个有界采集意图：v2 `filing_intent`+`acquisition_limits`，或仅对存量调用者的 v1 `--allow-download`” |
| `CHANGELOG.md` | 新增 `## Unreleased` 段记录上述契约变化 |
| `docs/implementation/s3-ff-limits-handoff.md` | 本文件 |

### 测试（新增 18 + golden 1）

| 文件 | 内容 |
|---|---|
| `tests/test_s3_single_request_limits.py` | 12 个测试：真 FF CLI（子进程）与真库调用 → 本地 fake producer，捕获**实际 argv** |
| `tests/test_s3_install_surface.py` | 6 个测试：安装面允许清单、假 key 排除、显式安装、pre-push 只读 |
| `tests/fixtures/s3_fake_cwp/fake_source_catalog_cli.py` | fake `company_wiki.source_catalog.cli`，5 种模式（default / reject_limits / slow / flood / noisy_failure） |
| `tests/golden/s3_ff_limits_argv.json` | limits → argv 表 golden（`tests/golden/` 为既有目录，按卡复用） |
| `tests/test_e2e_isolated_wiki.py` | 更新 1 处断言到新契约（stderr 正文不再回显） |

**未改**：`filing_contracts.py`（EXACT 校验原样保留）、`ff_v2_envelope.py`、
`et_v2_contract.py`、`transcript_companion.py`、`transcript_tool_transport.py` 的行为。

## 3. limits → argv 表

`_command_arguments` 的追加段（`_limit_arguments`），`ensure` 与 `close-gap` 共用：

| 请求 `acquisition_limits` | 追加到 argv |
|---|---|
| 缺失（v1 请求 / v2 `reuse_only`） | 无（`reuse_only` 本就禁止携带） |
| `{"max_bytes": 5000000, "timeout_seconds": 3, "max_cost_usd": "1.25"}` | `--max-download-bytes 5000000 --max-download-seconds 3 --max-download-cost-usd 1.25` |
| `{"max_bytes": 1, "timeout_seconds": 12.5, "max_cost_usd": "0.05"}` | `--max-download-bytes 1 --max-download-seconds 12.5 --max-download-cost-usd 0.05` |

规则：整数秒渲染为 `3`（非 `3.0`）；小数秒原样；`max_cost_usd` 是调用方写的
十进制字符串，**原样透传，不改金额格式**。

时间预算：`deadline = min(剩余全局 deadline, now + 配置 timeout_seconds, now + acquisition_limits.timeout_seconds)`。
该 deadline 被 identify / ensure / close-gap / companion 的每个子进程共用；
stdout 超过 `MAX_JSON_OUTPUT_BYTES`（32 MiB，与 ET transport 同一常量）即失败。

## 4. 真实 golden 与版本

| Golden | 请求 schema | 响应 schema | 状态 |
|---|---|---|---|
| `tests/golden/ff_v1_success.json` | `1.2` | `1.1` | 未改，仍绿 |
| `tests/golden/ff_v1_not_found.json` | `1.2` | `1.1` | 未改，仍绿 |
| `tests/golden/ff_v2_source_candidate.json` | `2.0` | `2.0` | 未改，仍绿 |
| `tests/golden/ff_v2_fetch_source_candidate.json` | `2.0` | `2.0` | 未改，仍绿 |
| `tests/golden/ff_v2_gap.json` | `2.0` | `2.0` | 未改，仍绿 |
| `tests/golden/ff_v2_period_unresolved.json` | `2.0` | `2.0` | 未改，仍绿 |
| `tests/golden/ff_v2_transcript_downloaded.json` | `2.0` | `2.0` | 未改，仍绿 |
| `tests/golden/ff_v2_upstream_error.json` | `2.0` | `2.0` | 未改，仍绿 |
| `tests/golden/s3_ff_limits_argv.json` | —（argv 表） | — | **新增** |

`filing_contracts.py` 版本常量未动：`FILING_REQUEST_SCHEMA_VERSION=1.2`、
`FILING_RESPONSE_SCHEMA_VERSION=1.1`、`FILING_V2_REQUEST/RESPONSE_SCHEMA_VERSION=2.0`、
`SKILL_VERSION=1.2.0`。ET 侧 `earnings-transcript-request/1`、
`company-wiki-transcript-import-request/2`、`...-response/3`、SourceRef `2.0` 全部未动。

## 5. ET / CWP 实际调用 0/1 表

| 范围 | 真实 CWP | 真实 ET | 真实 FMP | 费用 |
|---|---|---|---|---|
| `tests/test_s3_single_request_limits.py`（12） | **0**（本地 fake producer） | 0 | 0 | 0 |
| `tests/test_s3_install_surface.py`（6） | 0 | 0 | 0 | 0 |
| 既有 hermetic 套件（隔离 wiki） | 1 | 0 | 0 | 0 |
| `e2e/test_source_ref_v2_cli.py`（独立 CLI E2E） | 1（隔离 wiki，复用路径，downloads=0） | 0 | 0 | 0 |
| 全程真实 API key 读取 | — | — | — | 0 |

`EARNINGS_TRANSCRIPTS_TOOL` 未配置 → companion 走
`provider_unavailable / transcript_tool_not_configured`，**ET 实际调用 0**；
既有 `test_transcript_companion*` 用隔离 fixture 验证时期/语言/hash 与已有复用，未改。

## 6. 错误与退出码（本卡实际改变的项）

| 场景 | 之前 | 现在 | 退出码 |
|---|---|---|---|
| producer 不认识三个 `--max-download-*` | 不发这三个参数（额度丢失） | 发出参数 → argparse 拒绝 → `exited 2` → 分类 `fatal`；**只尝试 1 次，不剥参数重发、不回退 v1、不伪报完成** | 2 |
| 子进程超时 | `company-wiki <action> failed: <TimeoutExpired 含命令行路径>` | `company-wiki <action> exceeded its deadline budget`（`upstream_error`） | 2 |
| 子进程无法启动（OSError） | `company-wiki <action> failed: <异常正文含解释器路径>` | `company-wiki <action> failed to start`（`fatal`） | 2 |
| 子进程非零退出 | `exited N: <stderr 末 2000 字符>` | `exited N` + 分类码，stderr 只用于 `_classify_wiki_error` | 2 |
| 子进程 stdout 超 32 MiB | 视为 “not JSON” | `exceeded the output byte cap`（`upstream_error`） | 2 |
| 库调用 v2 `fetch_if_missing` 且显式 `allow_download=False` | 静默按不下载执行（与 CLI 分化） | `request_error`，消息说明与 `filing_intent` 矛盾 | 2 |
| 库调用 v2 且不传 `allow_download` | 默认 `False`（漏下载） | 按 `filing_intent` 推导，与 CLI 一致 | 0/2 |

未变：`request_error=2`、`config_error=2`、`identity_error=2`、`not_found=2`、
`upstream_error=2`、`catalog_locked=2`、`worker_paused=2`、`fatal=2`、
非 `FilingFetchError` 异常 `1`、成功/gap `0`。

## 7. 测试命令与结果

```
# 红（实现前）
python -m pytest tests/test_s3_single_request_limits.py tests/test_s3_install_surface.py -q
  -> 12 + 6 failed

# 责任测试包（完成后，一次 GREEN）
python -m pytest tests/test_s3_single_request_limits.py tests/test_s3_install_surface.py \
  tests/test_ff_v2_contract.py tests/test_ff_golden.py tests/test_source_ref_v2.py \
  tests/test_source_ref_v2_db_query.py tests/test_transcript_companion.py \
  tests/test_transcript_companion_transport.py tests/test_fetch_filing.py \
  tests/test_fc802_gap_orchestration.py tests/test_fc1204_coverage_gap.py \
  tests/test_complexity_ratchet.py tests/test_verify_plan_claims.py -q
  -> 337 passed, 3 skipped, 78 subtests passed (60.96s), 0 failed

# 独立 CLI E2E
set FILING_FETCH_V2_WIKI_SRC=<company-wiki>\src
python -m pytest e2e/test_source_ref_v2_cli.py -q
  -> 1 passed (9.50s)

# 全量 hermetic（同 CI）
python -m pytest tests -q --ignore=tests/test_real_tool_conformance.py \
  --ignore=tests/test_e2e_download.py
  -> 450 passed, 8 skipped, 2 failed (192.81s)   # 两个失败见 §8

# 静态
python -m ruff check scripts tests tools e2e         -> All checks passed
python -m mypy scripts/filing_contracts.py scripts/fetch_filing.py -> no issues
复杂度棘轮 fetch_filing.py max 32 / 冻结 34；filing_contracts.py max 39 / 冻结 39

# 覆盖率（同 CI 命令）
python -m pytest tests -q --cov=scripts --cov-branch --cov-fail-under=90 ...
  -> 82.22%（净基线同命令 81.66%；两端本地均 <90，属既有状态，本卡不新增覆盖任务）
```

### 临时根恢复

- 全部使用 pytest `tmp_path` / `TemporaryDirectory`，`finally` 清理；退出后临时根不存在。
- 假 `config/FMP_API_KEY.txt` 只在 `try/finally` 内创建与删除，退出断言
  `not key.exists()`；**未读取任何真实 key**。
- 无关哨兵进程 `finally` 中 `kill()` + `wait()`。
- 未写 `~/.agents`、`~/.claude`、`~/.codex`（测试只用 `--dest` 指向 tmp 目标）。
- 交付时 `git status` 仅含本卡文件：无 `nul`、无 pycache、无密钥、无下载原件、
  无逐执行全文日志。

## 8. root 需要知道的两件事

### 8.1 producer pending（**不是**端到端通过）

company-wiki 的 `ensure` / `close-gap` **尚未**接受
`--max-download-bytes` / `--max-download-seconds` / `--max-download-cost-usd`。
本卡只保证：

- FF 把三个参数真实写进 argv（离线参数捕获测试通过，未 skip）；
- 参数被拒时 FF 具名失败、只试一次、不剥参数、不回退 v1、不伪报完成。

**pending（等 root）**：CWP 实现三参数 → 跑一次限额跨仓 E2E（FF 真 CLI → 真 CWP →
真 adapter），确认 byte/time/cost 在 CWP 侧被真正执行。
在此之前不得把该接口描述为已通过。

### 8.2 两个环境红灯（净基线可复现，非本卡引入）

| 测试 | 原因 | 处置建议 |
|---|---|---|
| `test_fc1307a_the_three_vendored_copies_are_byte_identical` | 兄弟 `Projects\filing-fetch`、`Projects\company-wiki` 的 `host_assumption_guard.py` 落盘 CRLF 19190 B，本仓 LF 18794 B；归一化后内容完全一致 | 由 root 决定：重检出兄弟工作树，或让该守卫比较归一化行尾。兄弟仓对本卡只读 |
| `test_e2e_isolated_wiki.py::TestWorkerPaused::test_e2e_worker_paused_blocks_download_with_no_pause_worker` | 会话期间 `Projects\company-wiki` 由 `a104d25` → `73de6be refactor: retire legacy source catalog worker routes`，`--no-pause-worker` 不再返回 `worker_paused` | 由 root 确认 CWP 新契约后更新 FF 侧 worker pause 用例与 SKILL 描述；本卡不猜别仓实现 |

两者均在净基线 `c47c397` checkout 上复现，因此 pre-push gate 在本机当前是红的。
本卡**未**绕过任何钩子（未用 `--no-verify`、未改守卫）。

## 9. 显式安装命令与 manifest

```bash
python tools/sync_installs_b3.py --install              # 三个全局技能根
python tools/sync_installs_b3.py --install --dest DIR   # 任意父目录（DIR/filing-fetch/）
python tools/sync_installs_b3.py --check                # 只读漂移报告，exit 1 on drift
python tools/sync_installs_b3.py                        # exit 2：必须显式选择
```

manifest（允许清单，`tools/sync_installs_b3.py::manifest`）：

```
SKILL.md
CHANGELOG.md
config/company_wiki.json
references/contract-ownership.md
references/identity.md
scripts/et_v2_contract.py
scripts/ff_v2_envelope.py
scripts/fetch_filing.py
scripts/filing_contracts.py
scripts/transcript_companion.py
scripts/transcript_tool_transport.py
```

排除：`tests/`、`.gitignore`、任何 `config/` 非白名单文件、
`api_key/secret/token/credential/private_key/passphrase/password` 命名文件、
`.env*`、`.pem/.key/.p12/.pfx/.log`、`__pycache__` 等缓存、`.pyc/.pyo`、`.runs`。

**全局安装交 root**：本卡未执行 `--install`（不带 `--dest` 的形式）。

## 10. root 后续动作（本卡未做）

1. 核 `git diff c47c397..codex/ff-s3-single-request-limits` 与 §7 责任测试。
2. CWP 补三个限额参数 → 跑一次限额跨仓 E2E（§8.1）。
3. 判定 §8.2 两个环境红灯的处置。
4. 合 main、跑 `python tools/sync_installs_b3.py --install` 统一安装。
5. 未合入前本分支保持交付状态。
