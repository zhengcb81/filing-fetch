## ROOT接收更新 — 2026-10-16

ROOT接收工程验收通过，待正常提交/并线/远端。独立核对271证据SHA，搬迁、篡改、缺件、原根缺失、历史失败真实CLI重放保持38PASS/1PARTIAL/2NOT_RUN与旧19PASS/21FAIL/1PARTIAL，不洗绿。ROOT修复固定.partial/竞争output覆盖，唯一owned暂存+原子不覆盖发布。集中251PASS/1FAIL暴露旧矩阵重复taskkill/communicate/wait生命周期，统一复用既有生产run_bounded，保留CompletedProcess非0原字节/原deadline，不改case30/batch180或<5秒断言；真child+descendant回收、无taskkill。最终305PASS/74.42s（含原生产transport责任测试），Ruff通过。最初180s harness超时原因unknown，后续实际5.247s回收失败有单独证据，不混为一个推断。0供应商，Temp恢复，作者/ET/生产原件及密钥不改。硬链接不支持的文件系统明确失败不覆盖；真实41链partial/NOT_RUN及母计划仍开放。

**Next Step：** 正常提交并主线、可用远端发布和相关技能文件定点同步，由ROOT归总母PWF。

---

# 调查

施工卡的静态发现不等于已复现RED；由A节点核实。原失败/未知/分母保留；只更新自己的PWF。

## 已复现事实

1. **接口缺失（RED，非生产缺陷）**：基线 `oracle.audit(report)` 无 `evidence_root` 形参（调用即 TypeError）；
   `cli_main.main` 用 argparse 要求四参数，`replay` 子命令不存在（SystemExit 2）。见 `receipts/01-red-first.txt`。
2. **旧默认 findings 可精确冻结**：`tests/fixtures/w06_contract_matrix/authority` 的真实41报告 + artifacts 在无 override 下
   产生 65 条 findings（missing_case_fixture_evidence 40 / case_not_passed 22 / fake_layer_claimed_real 1 / wrong_cutoff 1 /
   fake_zero_cost 1），规范 JSON 指纹 `417a7891420e02e1bb9fb1641cb95ab5037c5fd754581488cf6dd4f919a64e30`，与路径无关。
   该 fixture 的 runs 是旧 runner 产物（无 `fixture_ref`），因此 40 条 missing_case_fixture_evidence 是**历史部分证据**，
   不是本次回归；它正好充当“可搬迁失败 fixture”。
3. **搬迁根 override 只换读取根**：同一 `_bound_evidence`；报告字典与文件 SHA 不变；相对 refs/SHA/CaseSpec/原 findings 全保留。
4. **无回落证明双向**：(a) 原 artifacts 根移动掉、override 有效 → findings 与原地重放逐条相同（用的是 override）；
   (b) override 根移走、旧根仍在 → exit 2 明确诊断、不写记录、不悄悄用旧根成功。
5. **单字节篡改可检出**：request/response/fixture/ET result/ET usage 各自 SHA 绑定命中；
   inline response 自述不符、文件缺失、ref 指向目录、非法 JSON、路径越界均产生具名 Finding，不 traceback。
6. **真实41链一次的结果**：38 PASS / 0 FAIL / 1 PARTIAL / 2 NOT_RUN，174.57s。
   PARTIAL `request_after_failure_retry` = 子进程绝对期限到期；2 个 NOT_RUN = 10s final-proof reserve 保全（stop_reason 明载）。
   这是 W07 记录的宿主负载差异（90–175s）落在 180s 批预算上的结果，**不是** pinned 版本不匹配；按卡未改 expected/未扩 timeout/未反复重跑。
   证据：`evidence/chain-report.json`（scope.stop_reason、phase_timing、launch_accounting）与 `receipts/04-c-relocation-replay.txt`。
7. **ET 测试 proxy 依赖在 pinned checkout 中齐全**（`tests/__init__.py`、`tests/test_retrieval_runtime.py`、`tests/test_transcript_api.py`），
   稀疏检出只缺 docs/planning，运行时代码完整；`code_binding.verified=true` 且 import 落在 supplied 代码根（8.3 短路径显示）。
8. **隔离**：真实密钥文件只 stat（size=32/mtime 未变），从未读/复制/打印/hash；CWP/ET 只读树 status 全程空；
   生产 config/原件/AUTO/真实 registry 0 写入；0 供应商调用。
