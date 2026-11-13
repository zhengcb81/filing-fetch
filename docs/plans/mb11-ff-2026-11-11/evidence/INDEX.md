# MB-FF 测试与恢复证据索引

代码/测试 tip：`c870ab78f14c4f7d458de87e907e311e7fc5eb5a`；分支 `codex/mb11-ff`；基线 `ac798a2`。本索引只列最终声明使用的证据；中间轮见文末。

## 最终证据

| 证据 | 内容 | 结果 | 文件 |
|---|---|---|---|
| 基线 | 卡片指定 9 文件，改动前 | 164 passed + 6 subtests，19.79s，exit 0 | `baseline-tests.log` / `baseline-junit.xml` |
| 新 suite | `tests/test_public_operation_isolation.py`（26 用例，含 prepare 后仍 miss 不再 ensure、job engine 单次加载、公开样例字段校验） | 26 passed，42.86s，exit 0 | `a13-tests.log` / `a13-junit.xml` |
| 受影响集 | 基线 9 文件 + 新 suite + `test_fc802_gap_orchestration.py` | 197 passed + 6 subtests，54.55s，exit 0 | `a14-tests.log` / `a14-junit.xml` |
| 安装 runtime | canonical installer + 安装根内复制测试/fixtures + poison `config/company_wiki.json` + 空 cwd | 26 passed，37.56s，exit 0 | `c-runtime6-tests.log` / `c-runtime6-junit.xml` |
| 完整 CI | `python tools/ci_tests.py` | 1012 passed / 2 skipped / 44 subtests，161.96s，exit 0 | `ci-full-r6.log` |
| 安装/检查 | `tools/sync_installs_b3.py --install/--check --dest <scratch>/skills --json` | 30 files，exit 0 / exit 0 | `install6.json` / `install6-check.json` |
| 静态检查 | ruff（scripts/tests/tools）+ mypy（`fetch_filing.py`、`ff_request_context.py`） | All checks passed / Success | 本次交接命令 |

关键日志 SHA256 前 16 位：

- `a13-tests.log` `c75f7de19297cc5b`
- `a14-tests.log` `981ae71c4d26a17f`
- `c-runtime6-tests.log` `13af43192c53ae74`
- `ci-full-r6.log` `aeeadbb453cf221f`
- `install6.json` `9b5cdc4fc73aea7f`
- `install6-check.json` `05b7560ce7081868`

2 个 skip 均为既有条件：production security-master 缺失、Windows symlink 不支持；不是本卡改动引入。

## A0 归档

- `inputs/a0-archive/ARCHIVE_MANIFEST.json`：37 个归档文件逐文件 SHA256/字节数。
- `inputs/a0-archive/RECYCLE_LIST.md`：给 ROOT 的回收候选与禁止项。
- `inputs/a0-archive/w07/main-evidence-index.json`：main 已跟踪的 W07 首失败/最终/时序 6 份收据路径、SHA256、字节数；只索引不复制，避免把旧 16-case 声明覆盖 ROOT 后续 41-case 证据。
- `inputs/a0-archive/w07/attempts/manifest.json`：6 组唯一 attempt 收据（18 个 JSON）的 SHA256。

## 中间轮（仅迭代记录，不作为最终声明）

`a1`（首轮 RED：2 次配置加载）、`a2`/`a3`/`a5`/`a6`/`a7`/`a8`/`a9`/`a10`/`a11`/`a12`、`ci-full`/`r2`/`r3`/`r4`/`r5`、`c-runtime`/`runtime2`/`runtime3`/`runtime4`/`runtime5`、`install*`。其中 `a1` 的失败断言和 `a6` 的断言错误保留原始内容，不裁掉失败段。

## 恢复状态

- 仓内工作树最终 clean；未修改生产 `config/company_wiki.json`、`config/FMP_API_KEY.txt`、`.ff_jobs/**`、`.mimosa/**`、`.workbuddy-ai/**`、CWP/ET/SID/Dayu 源码、全局 skill。
- 测试 scratch：C:/Users/郑曾波/Projects/mb11-ff-scratch/** 已于2026-11-13验收后回收（5,030文件/18,119,347字节）；仓内索引与最终日志保留。
- 真实网络/下载/收费调用：0；FF 产品模型调用：0。独立审查是 harness agent，不是 FF 产品调用。
- A0 归档为只读复制；未删除/重置旧工区、分支或未提交文件。
