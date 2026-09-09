# 进度日志

## 2026-08-01 — Session 2：全部六个阶段实施完成
- **Phase 1（代码契约修复）**：validate_request 补 company_query 必填 + market 白名单；
  validate_handle 补 request_id 非空；删死常量；SUPPORTED_COMPANY_WIKI_CONTRACTS frozenset→dict 并
  实际用于 resolve/ensure schema 校验；config_error/identity_error/worker_paused 分类；
  resolve_filing 删死分支、isfinite、schema 校验、not_found/upstream_error 代码；
  main() 请求解析失败 → request_error/exit 2；subprocess 超时 → upstream_error
- **Phase 2（mock 测试扩充）**：61 → 89 测试；§2.1-2.5 全部新增（请求边界/错误分类/截止时间/
  handle 边界/CLI main）；去重 2 对、改名 1 个
- **Phase 3（隔离实例真实 E2E）**：tests/e2e_support/isolated_wiki.py + 13 场景全绿（~55s）；
  锁机制发现：resolve 不抢锁、ensure 的 acquisition-journal 记录抢锁；tearDown 清理重试
- **Phase 4（真实下载 E2E，opt-in）**：CN（宁德时代）✓、US（AMD/10-K）✓ 全链路含幂等；
  HK（腾讯）环境阻断——dayu-hkex 在 RapidOCR 初始化原生崩溃（0xC0000005，dayu-agent 项目问题）；
  修复测试钉住现实（上游无 quarantine 修复闭环，损坏字节永不外泄）
- **Phase 5（live 一致性）**：7 测试重写完成（~40s）；identify/ambiguous/ensure--entity/
  生产 round-trip/确定性；ensure 测试在锁竞争时按设计 skip
- **Phase 6（文档卫生）**：SKILL.md v1.3.0（worker_paused、退出码、路径、exchange）；
  CHANGELOG v1.3.0；.gitignore +nul；pyproject.toml（ruff/coverage）；
  全量验证：`python -m pytest tests` 113 tests OK（5 skip）、ruff clean、coverage 96%（2026-08-08）
- 未提交（用户决策 D3 不提交基线）；工作区：3 个脚本/测试文件 + 3 个新测试文件 + 计划文档
- **HK 真实下载已跑通**（2026-08-01 补做）：根因=dayu CLI 按标题推断财年（"2025 年報"→FY2025），
  请求 fiscal_year 2024 被适配器年份过滤拒绝 → discover 轮询到截止；改 fiscal_year 2025 后
  20.3s 全链路通过。**4/4 真实下载测试全绿**（CN 宁德时代 / US AMD / HK 腾讯 / 损坏拒绝），
  全程无残留进程
- 遗留：live ensure 测试在生产空闲时才执行（worker 持续占用 catalog 锁，按设计 skip）

## 2026-09-09 深夜 — 状态核对（只读，不新增待办）

- 本仓 HEAD `bb8d485`，工作树干净；无未提交改动。
- E2E 范围已在 `bb8d485` 明确：`e2e/E2E_DESIGN.md` 记录 harness 为 **synthetic T1 only**，不代表真实数据 E2E；真实原文/CLI/provider 层由 R4 测试矩阵（L/P/VR/AR）承接。
- CI：`quality.yml`（`config_doctor --require-revenue-config` + `$GITHUB_WORKSPACE` 符号链接）最近推送全绿；本仓不再单独维护 legacy closure 调用。
- 上游观测（只读）：revenue daily `20260909T210001Z` ok=true，triplet 记录 filing `bb8d485`；FC-705 门仍 false（预计 2026-09-10 22:00 后转 true），与 filing 本仓无直接动作。
- 本轮未改代码/配置/任务，未下载、未跑真实 E2E、未恢复 worker。当前权威编排在 company-wiki R4 目录（见 `docs/plans/painpoint-outcome-audit-2026-09-05/current-delta-2026-09-09.md`）。
