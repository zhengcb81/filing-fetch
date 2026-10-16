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
