# 准备记录 — 2026-10-11

READY_NOT_STARTED：ROOT准备施工卡和固定输入，worker尚未开工。真实provider/LLM成本0。

# 进度 — 2026-10-11 (W07-FF-PERF 施工中)

- 输入修复：input/runtime/et 缺 harness 自有 ET proxy 所需 `tests/test_retrieval_runtime.py`、`tests/test_transcript_api.py`、`tests/__init__.py` 私有 seam；已按 dependency-manifest 固定 commit d0ac42c6 用 git cat-file blob 导出（blob 字节一致），链 A 可运行。
- A RED 一次：`python -B -m pytest -q tests/test_w07_matrix_efficiency.py` → 13 failed / 1 passed / 1.21s。行为证据：seed_all 10 次独立 warm_seed 启动；run_process 非超时异常泄漏子进程；_dependency 嵌套 gitless 快照误报父 HEAD；批次报告缺阶段计时/启动计数；最终 proof 饿死 0 启动。
- B 实现：measurement.py（PhaseTimer/launch_report/cache_stats）、seed_batch.py（单 helper 顺序真实 ensure）、runtime.py（guard 启动日志、MAX_PATH 安全字节码缓存、run_process 回收）、run.py（warm_seed_batch、proof 保留 10s、env 复用）、cli_main.py（阶段计时、依赖真实归属、保留循环）、matrix_cases.seed_all 收敛。
- 关键共因实测：PYTHONPYCACHEPREFIX 镜像路径超过 Windows MAX_PATH(260) 时 Python 静默不写 .pyc——company_wiki 264 模块每次子进程冷编译（~0.4s × ~270 启动）。改短缓存根（attempt 同级 pc/）后全树缓存生效。
- 测试：W07 集中 16 passed；既有 w06 matrix runtime/seed/case-authority 195 passed（未改旧期望）。
- AST 基线核对：matrix_cases 除 seed_all 外 14 个函数 ast.dump 哈希与 input/case-handler-baseline.json 全部一致。
- 待做：C 节点 41 完整离线 E2E（原 30/180 约束）、交接、提交、STOP。
- C 节点完成（2026-10-11）：原 41 完整离线 E2E = 41 PASS/0 FAIL/0 PARTIAL/0 NOT_RUN、90.29s（预算 180s，30s/case 未变）、oracle 0 findings、fresh proofs 26 全 verified、恢复 absent/生产 baseline 保持、真实成本 0。过程失败记录保留（b1 33/1/7@174.4s、b3/b4 负载高峰、b5 无预热并发 40/1@175.2s）。交接：docs/handoffs/w07-ff-matrix-efficiency/。STOP。
