# MB-FF 进度

## 2026-11-12

- 读取总控 `reconciliation.md`、`acquisition_review.md` §3/4/5、本卡、interfaces/acceptance/runtime_verification/handoff_contract。
- 核对原仓：`main@ac798a250b2310e0c2714053b08246ad94fffd0c`，tracked clean；4 个未跟踪目录/文件（`.ff_jobs/`、`.mimosa/`、`.workbuddy-ai/`、`config/FMP_API_KEY.txt`）均为受保护状态，未读写内容。
- 建立唯一工区 `C:/Users/郑曾波/Projects/mb11-ff` @ `codex/mb11-ff`，HEAD 与基线一致；未接管任何已有 worktree。
- A0 归档完成：旧 job 协议差量、W06 两份过期 PWF + 六份 input、W07 六份基线输入 + 6 组 18 份唯一首失败/最终/时序收据；均在 `inputs/a0-archive/`，逐文件 SHA 见 `attempts/manifest.json`。`RECYCLE_LIST.md` 给 ROOT 的回收候选；**作者未删除/重置任何旧工区文件或分支**。
- 建立 PWF 三文件与实际 runtime 清单（findings.md F1）。确认可用 Python 为 `C:/Miniconda/python.exe`（3.13.9 + pytest 9.1.1），默认 `python` 无 pytest。
- 基线：卡片指定 9 个测试文件 **164 passed + 6 subtests**（19.79s，`evidence/baseline-tests.log`）。宿主 safe-delete 对默认 pytest garbage 目录误报，改用仓外新 `--basetemp`；不改测试/不断言。
- A：新增 `tests/test_public_operation_isolation.py` 与 `tests/fixtures/public_operation_isolation/**`，20 个用例覆盖六 operation、query hit/miss/ensure、statements 四状态+错误版本+大诊断、ET 独立命令/usage 连续/unknown/坏 stdout、业务请求禁命令字段、未配置 operation 具名失败、全 scripts 无邻仓 import。首轮 **18 passed / 2 failed**：job 断言字段名写错（已修）；一次请求 config 被加载 2 次（真实 RED，`evidence/a1-tests.log`）。
- B：新增 `scripts/ff_request_context.py`；`fetch_filing.resolve_filing` 生成并回传同一 `RequestContext`，`complete_filing_v2`/`_resolve_v2_companion` 复用；`main` 用 `context_out` 注入。保留 FC-802 `test_main_passes_gap_through_unwrapped` 的 patched-resolve 行为。复跑 **20 passed**（`evidence/a2-tests.log`）。
- 受影响集（基线 9 文件 + 新测试 + fc802）：**184 passed + 6 subtests**（`evidence/a5-tests.log`）。
- C：canonical installer 安装到 `mb11-ff-scratch/runtime/skills/filing-fetch`（30 文件，install/check 退出 0，`evidence/install*.json`）；把安装根的 `config/company_wiki.json` 故意换成无 commands 的 poison 文件，从空 cwd 以显式 config 运行同一 suite：**20 passed**（`evidence/c-runtime-tests.log`）。证明无生产配置/邻仓源码也可工作。
- 完整 CI 首轮 1005 passed / 1 failed：`test_fc802_gap_orchestration.py::test_main_passes_gap_through_unwrapped` 因提前读 `--config x` 失败；改为 `resolve_filing` 内延迟生成 context 后该用例 2 passed，正在重跑完整 CI。
- 状态：A/B 完成，C 待完整 CI 与独立审查。
