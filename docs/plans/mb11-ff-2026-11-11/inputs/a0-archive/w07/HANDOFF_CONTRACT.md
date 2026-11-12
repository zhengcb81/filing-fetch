# W07 共用交接契约（每包内有独立副本）

## 工作方式
在 START_HERE 指定的独立目录工作，只读自己的固定输入，写自己的 allowlist。三个包可同时启动，不相互等待，也不读取彼此未交付代码。ROOT 独占母计划、共享安装与主线并线；不向主仓覆盖文件，不启动真实下载/LLM，不改 Dayu、IQS、原件或生产配置。

PWF 固定为本包 `.planning/<plan-id>/` 的 task_plan/findings/progress；若 harness 支持，设 PLAN_ID 为该 id、PWF_PLAN_ROOT 为当前工作目录。未提交的本包输入是 ROOT 准备的材料，不是无主垃圾；保留它们。别用 git add -A，不启用整库恢复演练。工作目录初始存在与 SHA 见 INPUTS.json；这些是工程可复现记录，不是人工许可。

## 只有三个大节点
**A 定义与 TDD：**核对现有 API，冻结用例预期，先写能暴露行为缺陷的测试；仅 import 缺模块不算有价值的 RED。必要时先最小 stub，再取得行为失败证据。记录实际 RED 命令/退出/原因一次，不逐用例签收。

**B 实现与集中测试：**按卡的唯一写集实现共用方案，运行一个集中快测包，包含成功、反例、未知和错误/恢复路径。不能改原期望迎合实现；若查明旧期望错误，给 ROOT 具体合同/输入/反例，由 ROOT 处理边界外变更。

**C 离线端到端与收尾：**一次有限完整 E2E 验证实际公开入口、报告和临时目录恢复。失败只为具体共因修复重跑；不要每个 commit 跑全矩阵。保留失败证据，不把 PARTIAL/NOT_CHECKED/unknown 改为 PASS。

## 临时目录与空间
临时路径必须是当前工作目录下新建的短路径（如 `.tmp/w07-<uuid8>`）；记录开始前 absent 或 sentinel 内容。成功、异常、timeout 都关闭子进程与 SQLite，删除本次新增文件并恢复原 baseline；只删除自己创建的路径。未存在的测试下载必须回到不存在，不做整份原件备份恢复。保留的小报告放独立 handoff 目录，不能散入生产公司目录。代码快照/固定 inputs 是初始材料，worker 不删。

报告默认总持久体积不超过 8MiB，scratch 目标不超过 64MiB（不含 checkout/已提供 code-only 输入）；这是防膨胀目标，确需超出说明实测原因，不新建审批文件。日志保留摘要、失败片段及指向完整压缩证据的引用，禁止完整环境变量/API key/原文湖复制。真实成本 0；未测峰值/不可知计量填 null，禁止编造。

## 输出接口
在自己的 `docs/handoffs/<plan-id>/` 输出 `handoff.md`、`handoff.json`、测试摘要与必要的小证据。JSON schema 为 `w07-lane-handoff/1`，必含：

```json
{
  "schema": "w07-lane-handoff/1",
  "lane": "W07-...",
  "status": "COMPLETE|PARTIAL|BLOCKED",
  "repository": "absolute path", "workdir": "absolute path",
  "branch": "codex/...", "base_commit": "sha", "implementation_commit": "sha",
  "changed_files": [{"path": "relative", "purpose": "why", "sha256": "bytes sha"}],
  "readonly_inputs": [{"path": "relative", "sha256": "sha"}],
  "interfaces": [{"name": "public entry/schema", "compatibility": "before/after"}],
  "tests": [{"node": "A|B|C", "command": "exact command", "exit_code": 0,
             "counts": {}, "seconds": 0, "evidence": "relative report/log"}],
  "issues": [{"root_cause": "mechanism", "evidence": "input/output refs", "scope": "affected cases", "resolution": "fixed or ROOT request"}],
  "cleanup": {"baseline": "ref", "final": "ref", "restored": true, "nonowned_preserved": true},
  "cost": {"real_provider_calls": 0, "real_llm_calls": 0, "dollars": 0},
  "space": {"persist_bytes": 0, "scratch_peak_bytes": null},
  "source_truth_verified": false, "economic_reasonableness": "not_evaluated",
  "residuals": [], "root_next_action": "receive/integrate or repair"
}
```

模板中的数值是字段说明，必须换实际测量；非零退出和未检查项如实填写。实现先正常 commit，报告后正常 commit，可用 implementation_commit 指向前一提交，避免自引用 hash。只提交自己的确切路径与小输入；不绕 hooks、不 force push、不并 main、不同步用户技能安装目录。RF/FF 若 remote 可用可正常推自己的分支；Audit 当前无 remote，不新建。完成 STOP，给用户卡号、commit、交接报告绝对路径和剩余问题。

ROOT 接收时只做：写集/固定输入边界、一个集中独立反例包、该卡大节点 E2E 留证，随后正常并线/安装及 exact HEAD CI。不新增小节点人工许可；真实公司执行与四路独审仍属母计划。
