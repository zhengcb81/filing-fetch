# 初始事实

ROOT已准备独立worktree与固定输入；详见INPUTS.json。未实现、未运行未来测试，不能预填PASS。

# 调查结果 — W07-FF-PERF 施工（2026-10-11）

- 主共因：PYTHONPYCACHEPREFIX 镜像路径超 Windows MAX_PATH（260）时 CPython 静默不写 .pyc——生产者树（company_wiki 264 模块）每次多层子进程冷编译（实测 compile() 122 次/启动、缓存路径 274 字符不落盘）。缓存根放 attempt 同级短目录 + 8.3 短路径装载代码根后，镜像路径 ≤252 落盘，实际导入的 98 个 company_wiki 模块全部缓存，FF 本地命中 2.75s→1.55s。
- 次共因：seed_all 10 次独立 CWP CLI ensure（每次全量 import）→ 收敛为一个有界 helper 顺序调用同一真实 ensure 服务；每请求留 request/response/receipt/source-ref/计数。
- 调度缺陷：case 工作可吃光 180s 批预算使最终 fresh-source-proofs 0 启动（旧 2PASS/31PARTIAL/8NOT_RUN 与 1PASS/27PARTIAL/13NOT_RUN 的机制解释）；case 窗口截止到 batch.end-10s 保留量后最终证明恒可运行。30s/case、180s/batch 值与起点未变。
- run_process 非超时异常泄漏子进程；已任意异常 kill/回收。
- 依赖记录：code-only 快照嵌套 FF worktree 内，git -C 误报 FF HEAD；现仅 toplevel==root 报 HEAD，否则 unknown + manifest 来源 commit 分列。
- 并发：三次顺序完整尝试 159.5/173.6/171.2s（仅一次入预算）证明需要并发；但无预热的并发会冷编译双份（b5 175s/40PASS）。绑定探针一次预热热模块 + 2 隔离 worker 后 90.29s/41PASS。
- 输入缺口：input/runtime/et 缺 tests/test_retrieval_runtime.py 等私有 seam（manifest 只登记 19 个顶层模块）；按卡授权用固定 commit d0ac42c6 blob 导出，链 A 通过。
- 工作站负载波动使单进程成本 2–3×（ff_hit 1.55s↔5.43s）；预热+并发把余量拉到 ~90s。
- 真实 provider/LLM 成本 0；synthetic fixture 请求 42 单列；未测峰值/不可知计量填 null。
