# filing-fetch 全链路 E2E —— 对抗式审查与设计

日期：2026-08-07 ｜ 状态：定稿，harness 已实现（`run_companies_reuse_only_e2e.py` + `expected/`）

## 对抗式审查

### Q1. 以后每次都能用吗？（可重复性）
**拷问**：原 isolated-wiki E2E 的 `seed_market` 从**生产 wiki 的 companies/** 复制 seed 文件——
生产文件一旦变动（如 catalog-space-remediation 退役文档）E2E 全挂。可重复吗？
**结论**：❌ 原 seed 依赖生产状态。✅ 新 harness **自建 synthetic seeds**（3 个市场，几 KB 文本文件），
完全 hermetic；每次全新临时 wiki + 单调递增运行号；退出码 0/1/2。

### Q2. 每次都能检验每一个步骤吗？（步骤覆盖）
**结论**：✅ 步骤断言覆盖全链路：
1. identify（CN/US/HK 三市场解析）
2. resolve reuse（capture_ready + missing_capture_fields=[]）
3. resolve missing（不存在财年 → not_found，exit 2）
4. handle 深度字段（request_id/snapshot_sha256/https_url 结构）
5. 双跑确定性（两次运行 handle 逐字段一致）
6. golden 比对（全字段）

### Q3. 目录内容变动时测试还有效吗？（抗变动性）
**结论**：✅ golden 键 = `FIXTURE_VERSION + seed 内容指纹`——seed 内容变化 → 新键 → 显式失败；
代码演化 → handle 字段漂移 → golden 不匹配 → 显式失败（回归信号）；fixture 缺失 → 显式报错。
**实测**：改 US seed 字节 → golden 键变化 → "seed changed" 显式失败 ✓。

### Q4. 需要 expected 结果目录吗？
**结论**：需要。`expected/expected-<key>.json`：三市场的 status/request_id/snapshot/https_url/
canonical_tail/missing + repo HEAD。`--update-golden` 是有意行为。

### Q5. 如何控制变量？
| 变量 | 控制 |
|---|---|
| seed | 自建 synthetic（harness 内联，字节确定）——不依赖生产 companies/ |
| company-wiki 运行时 | 本地 `Projects/company-wiki`；CI clone 到 `$HOME/Projects/company-wiki`（IsolatedWiki 的 PRODUCTION_WIKI 路径约定） |
| 输出 | 每次全新临时 wiki + `.runs/<key>/run-N` |
| 确定性 | 双跑断言 handle 逐字段一致 |
| 仓库版本 | golden + 运行输出记录 HEAD |
| 网络 | 无（hermetic；真实下载/live 一致性测试保持 opt-in，另行运行） |

### Q6. 如何区分"回归"与"环境问题"？
输入/环境失败（exit 2）、步骤断言失败（exit 1）、golden 键缺失（exit 2）分开报错；
golden 不匹配时打印字段级 diff。

### Q7. 自证检测能力（变异测试）
- 改 US seed 字节 → golden 键变化 → 显式失败（EXIT=2）✓；恢复 → 全绿 ✓。

### 现有测试的说明
- `tests/test_e2e_isolated_wiki.py`（pytest 内，15 场景）继续覆盖行为细节；其 `seed_market`
  仍依赖生产 seed 文件——若生产文件被治理删除会挂，**候选改进**：迁移到 synthetic seed。
- `tests/test_real_tool_conformance.py` 为 **live opt-in**（依赖生产 catalog 状态；
  finder 已过滤 active 状态，状态变化时正确 skip）——不属"可重复 E2E"范畴，单独运行。

---

## 运行与自动运行

- `python e2e/run_companies_reuse_only_e2e.py`（exit 0/1/2）
- `.githooks/pre-commit`：pytest 套件 + 本 E2E（每次提交）
- `.github/workflows/quality.yml`：clone company-wiki 到 $HOME/Projects + pytest + E2E（push/PR）
