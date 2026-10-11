# W07-FF-PERF 交接 — 固定 41 场景联调效率根因修复

状态：**COMPLETE**。原 41 场景完整离线 E2E：**41 PASS / 0 FAIL / 0 PARTIAL / 0 NOT_RUN，90.29 秒（预算 180s）**，oracle 0 findings，fresh 实字节/SourceRef/locator 证明 26 条全部 verified，恢复与生产只读 baseline 全部保持。真实 provider/LLM 成本 0；synthetic fixture 请求 42 条单列。

工作目录：`C:\Users\郑曾波\Projects\_harness_worktrees\w07\ff-matrix-efficiency`，分支 `codex/w07-ff-matrix-efficiency`，基线 `2d380a054c658ce3b5f0763523e49a0ab34acf78`。

## 共因（实测定位，不再盲目重跑）

1. **字节码缓存被 Windows MAX_PATH 静默丢弃（主共因）**：`PYTHONPYCACHEPREFIX` 把源码绝对路径镜像到缓存前缀下，生产者树（company_wiki 264 模块）镜像路径达 262+ 字符，超过 260 限额（原子写临时名再加 ~10 字符），CPython 静默不写 `.pyc`——每次多层子进程冷编译整棵生产树（实测 `compile()` 122 次/启动、`security_identity` 缓存路径 274 字符不落盘）。约 270 次启动 × ~0.4s ≈ 100s+ 纯重复编译。修复：缓存根放 attempt 同级短目录（`pc/`），并用 8.3 短路径装载代码根，镜像路径全部 ≤252 落盘；编排预热（binding 探针一次 import 全部热模块）避免并发组冷编译双份。
2. **seed_all 10 次独立 CWP CLI ensure 启动**：收敛为**一个**有界 helper 进程顺序调用同一真实 `company_wiki.source_catalog.cli.main` 服务（10 个 request/response/receipt/source-ref/计数记录各留一份，未造 SQLite、未预种应下载文件）。
3. **计时遗漏**：原报告无阶段计时/启动数。新增实测阶段计时（binding、seed、ff_cli、et_supervisor_worker、fixture、fresh_source_proof、cleanup、total）与启动计数（父级 + guard 全量含嵌套）；未观测阶段记 `unknown`+原因，不瞎估。
4. **最终 proof 饿死**：case 工作可吃光 180s 批预算使 fresh-source-proofs 0 启动（旧失败记录 2PASS/31PARTIAL/8NOT_RUN、1PASS/27PARTIAL/13NOT_RUN 的正确解释）。修复：case 窗口截止到 `batch.end - 10s` 保留量（30s/case、180s/batch 的值与起点未变，未重置 remaining、未加 timeout），最终证明恒在全部变更后运行。
5. **异常遗留进程**：`run_process` 在非超时异常下不回收子进程。修复：任何异常都 kill/回收进程树。
6. **依赖记录失真**：code-only 快照嵌套在 FF worktree 内，`git -C` 会向上误报 FF HEAD。修复：仅 toplevel==root 才报 git HEAD，否则 `head=unknown`/`head_origin=unknown_nested_snapshot`，来源 commit 从本包 dependency-manifest 单列（见 final-41-report.json dependencies）。

测量证明需要并发后才启用最多 2 个并发 worker（三次顺序完整尝试 159.5/173.6/171.2s 仅一次入预算）；每组独立 Context/wiki/proxy/counters，download→reuse 链整体留在一组，不共享 catalog 并发写、不混 provider 计数。

## 输入修复（按卡授权的重建方式）

input/runtime/et 缺 harness 自有 ET proxy 依赖的 `tests/test_retrieval_runtime.py`、`tests/test_transcript_api.py`、`tests/__init__.py` 私有 seam（dependency-manifest 只登记了 19 个顶层模块），链 A 无法运行。按卡内“需要重建时按 dependency-manifest 的固定 commit/path 用 git archive 导出”授权，用 `git cat-file blob` 在固定 commit d0ac42c6 导出三个文件（blob 字节一致；SHA 见 handoff.json readonly_inputs 的 input-repair 条目）。已验证链 A 真实三层（FF CLI + ET supervisor/worker + CWP import）通过。另：diagnostic 过程中曾在 input 快照内产生 `__pycache__`，已全部删除并复核 manifest 268+19 文件 SHA 全部匹配。

## 证据

- 最终完整 41 报告：`evidence/final-41-report.json`（41/41 PASS、oracle 0、阶段计时、启动计数、缓存统计、依赖真实归属）；`evidence/final-41-restore.json`、`evidence/final-41-proofs-g1.json`、`evidence/final-41-proofs-g2.json`。
- 保留的失败记录（未修正）：`evidence/first-run-failure-report.json`（33 PASS/1 PARTIAL/7 NOT_RUN、174.40s、reserve 触发）；中间尝试 b2–b5 保留在 `.tmp/w07-b2…b5`（b2 为近终码顺序完整 41/41@159.48s；b3/b4 为负载高峰顺序尝试；b5 为无预热并发尝试 40/1）。
- before/after 计时与启动数：`evidence/timing-before-after.json`。
- 只读不变证据：INPUTS.json `readonly_code` 205 文件 SHA 全部匹配（`report.py` 曾被误改已恢复原字节并复核）；matrix_cases 除 seed_all 外 14 个函数 AST 哈希与 case-handler-baseline.json 全部一致（`changed_files.json` 附核对脚本输出）。

## 测试

- A RED 一次留证：`python -B -m pytest -q tests/test_w07_matrix_efficiency.py` → 13 failed / 1 passed / 1.21s（行为证据：10 次 seed 启动、异常泄漏子进程、嵌套 git 误报、proof 饿死 0 启动、缺阶段计时）。
- B 集中快测：同命令 → **18 passed**；既有矩阵接口测试 `tests/test_w06_contract_matrix.py tests/test_w06_matrix_runtime.py tests/test_w06_case_authority.py` → **195 passed**（旧期望未改）。
- C 原 41 完整离线 E2E（卡内命令，ABS_NEW_SCRATCH=.tmp/w07-a6，ABS_NEW_REPORT=.tmp/w07-b6）→ exit 0，41 PASS、90.29s、oracle 0 findings。

## 残余与 ROOT 下一步

- 工作站负载会使单进程成本 2–3× 波动（实测 ff_hit 1.55s↔5.43s）；本包用预热+2 隔离 worker 把余量拉到 ~90s。若在持续高负载主机复跑仍超时，报告内的阶段计时/启动计数可直接定位最慢阶段。
- 缓存镜像路径最长 252（`bytecode_cache.max_pyc_path_len`）接近 260 边界；更深层模块仍可能不缓存（`company_wiki_pyc=98` 为实际导入集合）。
- worker 只动工具编排；ROOT 负责 FF/ET 生产修复与并线发布。本包未改 CaseSpec/RunSpec/oracle/matrix_outcome/source_proofs/case handler/scripts 生产逻辑/ET/CWP/config/key/CI/hooks，未加审批、未加每 commit 41 CI。
