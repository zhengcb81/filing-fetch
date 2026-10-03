# FF-S3 局部 PWF — 一请求、实际限额与安装面简化

来源卡片：`docs/plans/narrative-evidence-pilot-2026-09-26/harness_lanes/s3_filing_fetch_single_request_limits.md`
（company-wiki 仓，只读参考）。

## 所有权边界

- 唯一写入工作目录：`C:\Users\郑曾波\Projects\filing-fetch-s3-limits`
- 分支 `codex/ff-s3-single-request-limits`，基线 `origin/main@c47c397c4d93979d8a7defbe026eff9e9edf0e6d`
- company-wiki / earnings-transcripts / revenue-forecast / StockWiki / 全局 `.agents/.codex` 技能目录：只读
- root 负责：CWP producer 三个限额参数、全局安装、跨仓集成

## 基线观测（2026-10-03）

- `python -m pytest tests -q --ignore=tests/test_real_tool_conformance.py --ignore=tests/test_e2e_download.py`
  → **433 passed, 8 skipped, 1 failed**（186s）
- 既有失败 `tests/test_fc1307a_host_assumption_gate.py::test_fc1307a_the_three_vendored_copies_are_byte_identical`：
  本仓 `tools/host_assumption_guard.py` 为 LF（18794 B），兄弟 checkout
  `Projects\filing-fetch`、`Projects\company-wiki` 落盘为 CRLF（19190 B），字节哈希漂移。
  与 FF-S3 无关，属宿主机行尾状态；兄弟仓只读，不在本卡修复范围。
- `ruff check scripts tests tools e2e` → 通过
- `mypy scripts/filing_contracts.py scripts/fetch_filing.py` → 通过
- 复杂度棘轮：`fetch_filing.py` max 32（冻结 34）、`filing_contracts.py` max 39（冻结 39，不可增长）

## 任务分解

### 1. 行为测试先行（RED）

- [ ] `tests/test_s3_single_request_limits.py`：真 FF CLI → 本地 fake child CLI，捕获实际 argv/stdin
- [ ] 三额度 `--max-download-bytes/--max-download-seconds/--max-download-cost-usd` 进入 ensure/close-gap argv
- [ ] 同一请求库 / CLI 意图一致；冲突具名 `request_error`
- [ ] 请求期限压缩共享 deadline，短 deadline 有界超时
- [ ] producer 拒未知参数 → 具名失败，不剥参数重发、无隐式重试
- [ ] 子进程输出字节 cap；超时回收自己创建的进程且不碰无关进程
- [ ] 静态子进程失败不回显 stderr 正文 / 路径 / key
- [ ] installer manifest 排除假 `FMP_API_KEY`、tests、本地 .env、缓存、运行日志
- [ ] pre-push 不写全局安装

### 2. 实现贯通

- [ ] `_command_arguments` 输出三额度 argv
- [ ] `resolve_filing` 单一下载意图推导（`filing_intent` 为唯一权威）+ 显式冲突报错
- [ ] `resolve_filing` deadline = min(剩余全局 deadline, 配置期限, 请求期限)
- [ ] 有界子进程：deadline + 输出字节 cap + 静态错误不回显
- [ ] installer：显式 `--install`、manifest 收窄；pre-push 只读告警

### 3. 文档与交接

- [ ] `SKILL.md` 更新为 v2 推荐例子 / 一次采集请求 / 限额 / FY-Q / ET 工具配置 / 失败分离
- [ ] 删除失效的 RequestPlan 手工签收与二次下载许可说明
- [ ] `docs/implementation/s3-ff-limits-handoff.md` + `tests/golden/s3_ff_limits_argv.json`
- [ ] 提交并 push `codex/ff-s3-single-request-limits`

## 明确不做

- 不新增签名、人工授权文件、逐候选 review receipt、覆盖率门、场景数门
- 不自行合 main、不安装全局技能、不启动无限 worker
- 不把 producer pending 写成端到端通过
- 不修改 company-wiki / ET / StockWiki / IQS 源码
