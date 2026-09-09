# filing-fetch companies-root reuse-only E2E —— 设计与当前边界

> 2026-09-08：本harness继续仅作synthetic T1回归，不作用户要求的真实数据E2E。真实原文/真实CLI/真实provider设计现见[R4测试矩阵](../../company-wiki/docs/plans/painpoint-outcome-audit-2026-09-05/simplified-test-matrix.md)及同目录R4实施计划：L本地位置等价与四既有根覆盖，P真实生产/provider，VR隔离与AR外部运行分层。旧WP02/03/04/13目标保留，旧G依赖不再执行。样本缺失不得synthetic fallback后仍记通过；golden不得改变原目标或抹失败。本次不执行测试/下载，不修改harness。

原始设计：2026-08-07 ｜ 状态核对：2026-09-04 ｜ harness 已实现；本次仅静态核对，未重新执行 E2E。

当前仅覆盖 synthetic companies-root 复用路径，不覆盖 dayu/Dropbox roots、latest_as_of gap plans、artifact bundles 或 consumer parser/LLM zero-call reuse，不能据此宣称三仓全链路验收完成。当前规划路由见 [PLANNING_STATUS](../PLANNING_STATUS.md)。

## 对抗式审查

### Q1. 以后每次都能用吗？（可重复性）
**拷问**：原 isolated-wiki E2E 的 `seed_market` 从**生产 wiki 的 companies/** 复制 seed 文件——
生产文件一旦变动（如 catalog-space-remediation 退役文档）E2E 全挂。可重复吗？
**当前结论**：文档 seed 已改为 synthetic，不再从生产 companies/ 复制；每次建立新的隔离状态目录。仍读取本地 company-wiki 代码、worker 配置；security-master 存在时优先复制本地快照，缺失时生成 synthetic fallback。不能把全部输入描述为完全独立于本地环境。

### Q2. 每次都能检验每一个步骤吗？（步骤覆盖）
**当前范围**：断言覆盖 companies-root reuse-only 路径：
1. identify（CN/US/HK 三市场解析）
2. resolve reuse（capture_ready + missing_capture_fields=[]）
3. resolve missing（不存在财年 → not_found，exit 2）
4. handle 深度字段（request_id/snapshot_sha256/https_url 结构）
5. 双跑比较 request_id 与 snapshot_sha256
6. 首轮结果与 golden 比较 status、request_id、snapshot_sha256、https_url、canonical_tail、missing 六项投影字段

### Q3. 目录内容变动时测试还有效吗？（抗变动性）
**结论**：✅ golden 键 = `FIXTURE_VERSION + seed 内容指纹`——seed 内容变化 → 新键 → 显式失败；
代码演化 → handle 字段漂移 → golden 不匹配 → 显式失败（回归信号）；fixture 缺失 → 显式报错。
**历史记录（2026-08-07）**：改 US seed 字节使 golden 键变化并显式失败；本次未复跑该变异实验。

### Q4. 需要 expected 结果目录吗？
**结论**：需要。`expected/expected-<key>.json`：三市场的 status/request_id/snapshot/https_url/
canonical_tail/missing + repo HEAD。`--update-golden` 是有意行为。

### Q5. 如何控制变量？
| 变量 | 控制 |
|---|---|
| seed | 自建 synthetic（harness 内联，字节确定）——不依赖生产 companies/ |
| company-wiki 运行时 | 本地 `Projects/company-wiki`；CI 通过 revenue-forecast compatibility manifest 和 `ci_checkout_siblings.py` 准备 sibling runtime |
| 输出 | 每次全新临时 wiki + `.runs/<key>/run-N` |
| 确定性 | 双跑比较 request_id 与 snapshot_sha256；golden 比较六项结果投影 |
| 仓库版本 | golden + 运行输出记录 HEAD |
| 网络与环境 | reuse-only harness 无下载动作；隔离 fixture 仍读取本地 worker 配置及可用 security-master，缺失 master 时使用 synthetic fallback |

### Q6. 如何区分"回归"与"环境问题"？
harness 显式返回：断言/golden 不匹配为 exit 1，缺少 golden 为 exit 2；其他环境异常可能抛出异常退出，不能保证全部输入/环境错误都稳定归类为 exit 2。golden 不匹配时打印字段级 diff。

### Q7. 自证检测能力（变异测试）
- 历史记录（2026-08-07）：改 US seed 字节 → golden 键变化 → 显式失败（EXIT=2）；恢复后通过。本次未重验。

### 现有测试的说明
- `tests/test_e2e_isolated_wiki.py` 继续覆盖隔离实例行为细节；`IsolatedWiki.seed_market` 已改用 `SYNTHETIC_SEEDS` 写文档和 sidecar，旧“迁移 synthetic seed”候选已由代码演化实现。这里不据此声明当前测试已经运行通过。
- `tests/test_real_tool_conformance.py` 为 **live opt-in**（依赖生产 catalog 状态；
  finder 已过滤 active 状态，状态变化时正确 skip）——不属"可重复 E2E"范畴，单独运行。

---

## 运行与自动运行

- `python e2e/run_companies_reuse_only_e2e.py`（exit 0/1/2）
- 当前本地 `.git/hooks/pre-commit` 调用 `.pre-commit-config.yaml`，执行 ruff 与两个公开契约模块的 mypy；完整回归需另行执行。`.githooks/pre-commit` 保留旧 pytest/E2E/install-sync 脚本，但本次查询 `core.hooksPath` 未设置，不能称其每次提交自动执行。
- `.github/workflows/quality.yml` 在 push/PR 配置 manifest-driven sibling runtime、静态检查、类型检查、测试/coverage、config doctor、reuse-only E2E、install-sync 和 plan verifier；本次仅核对配置，未查询远端运行结果。
