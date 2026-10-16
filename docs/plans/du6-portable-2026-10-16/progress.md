## ROOT主线接收完成 — 2026-10-16

本施工包及ROOT共因修复已正常并入主线 `d11d5f9e3e766521c84787b691f935466bf32f47`，作者完整历史保留。正式工程验收和原失败见root-reception.md/json及zip。

本卡只改工程矩阵工具，生产技能文件未变，无需重装。

ROOT随后正常推送并核对精确远端HEAD/CI；状态归总于CWP母PWF。

**Next Step：** 本包STOP；后续由ROOT接生产共享引擎、正式摘要和母E2E，不重新开启作者施工。

---

## ROOT接收更新 — 2026-10-16

ROOT接收工程验收通过，待正常提交/并线/远端。独立核对271证据SHA，搬迁、篡改、缺件、原根缺失、历史失败真实CLI重放保持38PASS/1PARTIAL/2NOT_RUN与旧19PASS/21FAIL/1PARTIAL，不洗绿。ROOT修复固定.partial/竞争output覆盖，唯一owned暂存+原子不覆盖发布。集中251PASS/1FAIL暴露旧矩阵重复taskkill/communicate/wait生命周期，统一复用既有生产run_bounded，保留CompletedProcess非0原字节/原deadline，不改case30/batch180或<5秒断言；真child+descendant回收、无taskkill。最终305PASS/74.42s（含原生产transport责任测试），Ruff通过。最初180s harness超时原因unknown，后续实际5.247s回收失败有单独证据，不混为一个推断。0供应商，Temp恢复，作者/ET/生产原件及密钥不改。硬链接不支持的文件系统明确失败不覆盖；真实41链partial/NOT_RUN及母计划仍开放。

**Next Step：** 正常提交并主线、可用远端发布和相关技能文件定点同步，由ROOT归总母PWF。

---

# 进度

ROOT仅建立已提交基线的独占工作树/启动计划；尚未实施、未跑业务测试；0API，未复制原件、AUTO、密钥或主仓WIP。

## 2026-10-16 实施完成

- A：新测试 `tests/test_du6_portable_matrix_evidence.py`（32 条）+ RED 收据 `receipts/01-red-first.txt`（3 passed / 29 failed，全部归因缺失接口）。
- B：`oracle.audit(..., evidence_root=None)` 与 `cli_main` `replay` 分派/`ff-matrix-evidence-replay/1` 小记录；
  集中回归 245 passed（旧 213 + 新 32），Ruff 干净（只查改动源与新测试）。
- C：真实41链一次（pinned CWP f08aa101 / ET d0ac42c6）38 PASS / 1 PARTIAL / 2 NOT_RUN / 174.57s；
  搬迁重放 5 步（含空格+中文目录、原根不可用、override 缺失、单字节篡改、历史失败 fixture）全通；
  独立手算 21/21；清理收据 `receipts/06-cleanup-receipt.txt`（保留证据 1,494,302 字节；OWNED_TEMP 只剩 sentinel）。
- 交付：`handoff.md` / `handoff.json`（du6-handoff/1）随第二次 commit 提交；随后 STOP，不并主线、不推安装副本。
