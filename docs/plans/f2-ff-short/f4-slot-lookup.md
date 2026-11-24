# F4 · 定时 slot 按原批次只读冷查

对应总控 [F4-FF-SLOT-LOOKUP](../../../../company-wiki/docs/plans/feedback-loop-2026-11-17/owner-cards/F4-FF-SLOT-LOOKUP.md)。基线 `main@15c4614`，实现 `4190c03`，独审发现修复 `0ba5aa9`。工作目录为本仓 `main`，没有使用第二套定时账本，没有改定时下载流程、任务配置、原生作业、生产资料、CWP 或 ET。

## 公开入口与语义

`scripts/ff_job_feedback.py reconcile` 接收 `feedback-action/1` / `method=lookup` / `kind=reconcile`。`evidence_ref` 以 `ff-scheduled-refresh/1/sr-<UTC 戳>-<10 位十六进制>` 引用原 run；其余引用仍走原 `ff-job/1` 路径。调用方的 run/attempt/step 必须与原收据的 `feedback_identity` 一致（历史收据没有该字段时绑定 `<run_id>` / `scheduled`）；`step_id=<run_id>` 表示整批，`<run_id>/<原失败键>` 表示单个子项。另一轮执行、另一期、其他尝试或无法绑定的引用返回 `unknown`，仍在运行的当前 run 返回 `pending`。

只从 `--jobs-dir` 指向的原状态根读 `scheduled/runs/<run_id>.json`、`scheduled/state.json` 和 `jobs/<owner_job_id>.json`。不建目录、不加锁、不修复账本、不触发发现、读取、下载或电话会。`--config` 与超时参数沿用原 CLI，但 slot 路径不消费它们。

| 原记录事实 | 跨仓 `job_status` | `status` / `cost_state` |
|---|---|---|
| 运行中且只在 `state.current` | `pending`（不给结果） | 无 |
| 已结束，子项未结算 / 有未决派发 | `unconfirmed` | 视原用量，通常 `cost_unknown` |
| 已结束，有已证实的失败子项、无待续 | `failed` | 每项均证实且无待续时 `known`，否则 `cost_unknown` |
| `completed` 且无失败 | `succeeded` | 同上 |
| `superseded` 且无待续 | `cancelled` | 同上 |
| 某条已登记的单项失败 | `failed`，附 `item.key/reason/stage` | 沿用整批已证实的用量依据 |

原生 `partial` 与聚合原因不塞进跨仓不认识的 `job_status`：结果沿 `native_status`、`reason_codes`、`counts`、`items`、`native_attempt` 和同一个 `evidence_ref` 原样回传，可由本仓 `ff_scheduled_refresh.py runs` 或原记录继续查。只返回合同需要的终态、费用状态和引用；冷查退出 0 永远不等于业务成功。

费用以原 `usage.acquisition_jobs` / `reading_runs` 为依据：逐项核对派发（`original` / `retry` / `reused`）、原作业的 `project_job_cost` 与 `metadata_usage_incomplete`。同一 run 已派发却不在原 usage 中的作业也计为未结算；另一 run 的作业不按同日或同公司补入。任一项未知、未绑定、待续未结或没有快照时保留 `cost_unknown`；原快照写已知而后来的原作业变未知时不采信旧零费用。

## 测试与实测

- 红测先写：`tests/test_ff_slot_feedback_lookup.py` 用原结构的脱敏 slot 与作业账本。实现前 7 例中 6 例返回 `unknown` 而失败，`ff-job/1` 对照 1 例通过；两主场景分别为「部分完成、原调用未到供应商、零费用可证」和「部分完成、原费用未知、一个子项待续」。每例都走真实公开 CLI 两次，前后逐文件字节与尝试次数一致，配置 canary 未被执行，未产生 observations 目录。
- 当前 8 例覆盖：上述两场景、缺原 slot / 期次相同但另一轮 / 仍在运行 / 合法跳过 / 另一条损坏收据 / 契约 ID 不是 run id、尝试与子项错绑、历史记录没有单项映射、派发但缺 usage、外部 run 的作业不串账、单项原因绑定、`superseded` 与中途派发、`ff-job/1` 兼容对照（与父提交逐字节同答）。
- `"C:/Miniconda/python.exe" -B -m pytest -q -p no:cacheprovider --basetemp <独立目录> tests/test_ff_slot_feedback_lookup.py tests/test_ff_job_feedback_lookup.py tests/test_feedback_ordinary_failures.py tests/test_feedback_observation.py tests/test_scheduled_refresh.py tests/test_scheduled_refresh_public_e2e.py tests/test_refresh_runner.py tests/test_ff_job_facade.py tests/test_ff_job_cross_process.py tests/test_failure_usage_continuity.py tests/test_ff1_envelope_candidates.py tests/test_ci_tests.py`：修复前 **276 passed、8 subtests passed**；修复后对相邻六文件复跑 **68 passed**。全量聚焦 CI 清单见机器收据。
- 聚焦 CI 清单 `tools/ci_tests.py` 本地执行 1054 项：**1012 passed、2 skipped（平台/快照）、46 subtests passed；40 failed**。失败样本全部是会话沙箱 `safe-delete` 守卫在单轮累计删除达到 50 后拒绝测试夹具清理 `.ready` 的 `SystemExit`，不是产品断言；本机日常门禁 `tools/pre_push_gate.py --push-checks` 为 ruff ok、固定 11 项冒烟通过。远端 GitHub Actions 无此守卫，推送后须继续盯实际结果。
- `ruff check scripts tests tools` 通过；提交的 pre-commit 三项（ruff / 公共契约 mypy / host-assumption guard）通过；新测试已登记 `tools/ci_tests.py:CI_TESTS`。

## 两个历史 slot 的只读实测

用真实公开 CLI 冷读两次，比较结果相同；`.ff_jobs/scheduled/**` 与 `.ff_jobs/jobs/*.json` 共 18 个文件前后 SHA-256 一致，`.ff_jobs/observations` 最新写入时间仍是 21:51:57Z（早于本次读取），没有新发现、下载、供应商请求、作业尝试或费用。

| 原 run | 回告 | 子项派发 |
|---|---|---|
| `sr-20261116T073000Z-34da10ccbe` | `done` / `cost_unknown` / `unconfirmed` / `cost_state=unknown` / `native_status=partial` | `ffjob-0572be84bca9` original known $0；`ffjob-0dd330d80fad` original 未知 |
| `sr-20261123T073000Z-e74674c4b5` | 同上 | `ffjob-0572be84bca9` retry known $0；`ffjob-0dd330d80fad` reused 未知 |

历史收据只有聚合计数、原因与用量快照，没有两条失败各自的单项映射；因此历史 run 的单项引用保持 `unknown`，不伪造子项原因。整批结论按待续子项与未知费用保留未确认。坐标样例与机器结果见 [evidence/f4-slot-lookup.json](evidence/f4-slot-lookup.json)。

## 独审与边界

独立审查 agent（`agent-245281db-fdb2-492b-83a7-539f3c594312`）对 `4190c03` 做了 141 个对抗探针、消费者 trace、父提交与当前入口的逐字节对照及生产账本哈希守卫，结论 PASS。唯一 Medium 发现 F1「同一 run 派发但不在 usage 中的作业未被计入」已在 `0ba5aa9` 修复并加回归；修复后真实两批答案不变，生产账本仍逐字节一致。F2 是审阅草稿统计脚本自身的判定反转，不是产品问题；F3 是 ROOT 消费者 ACK 语义，FF 只回状态和引用。

仍缺证 / 不属于本卡：`ff-job/1` 既有结果和未知费用保持不变；两条旧短请求的 ET 用量绑定由 ROOT 协调；观察包是否 ACK、旧包是否停止重复扫描由 ROOT 对照实际证据单独确认；发现阶段失败的元数据用量沿用原生 `refresh-usage` 规则，仅 `metadata_usage_incomplete` 标未知。生产定时任务没有启动、卸载或修改。

## 清理

所有临时账本、探针与审查产物在 `C:/Users/郑曾波/AppData/Local/Temp/ff-slot-lookup-tests/` 与 `C:/Users/郑曾波/AppData/Local/Temp/ff-slot-review/`；本仓只新增本文件、机器收据、PWF 段落与已提交的源码/测试。未跟踪的 `.ff_jobs/`、`.mimosa/`、`.workbuddy-ai/`、`.worktrees/`、`config/FMP_API_KEY.txt`、`docs/handoffs/dash-ff-20261120/` 原样保留，凭据未读取。
