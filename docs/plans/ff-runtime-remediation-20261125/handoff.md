# filing-fetch 候选交接

## 冻结

源仓 `main` 的精确基线为 `7651f70d06b5ee411b4e9221751f5db3f7fd7526`。本机隔离归档为 `company-wiki/.planning/r25/ff`。同级 `ff-runtime-remediation.patch` 和 `ff-runtime-remediation.manifest.json` 绑定 15 项源码与测试变化的前后 SHA。源仓执行 `git apply --check --whitespace=error-all` 通过。分仓 PWF 在此目录独立交接。

## 重跑

从隔离候选根运行。设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`、`PYTHONUTF8=1`，使用系统独占测试临时根，各测试以合成子进程和独立状态运行。

```powershell
python -B -m pytest -q -p no:cacheprovider tests/test_ff_runtime_lifecycle.py tests/test_ff_job_cross_process.py tests/test_ff_job_feedback_lookup.py tests/test_ff_slot_feedback_lookup.py tests/financial_statements/test_fetch_statements_subprocess.py tests/financial_statements/test_layer_boundary.py
ruff check --no-cache scripts tests tools e2e
python -B -m mypy scripts/filing_contracts.py scripts/fetch_filing.py
```

从发布基线已复现 6 个 RED 和正常对照。最终定向 47 项通过。观察确认故障、过早退出、异常费用、各类冷读和专属运行标识均在前述入口核验。旧跨进程锁测试仍要求同一真实业务状态和退出值，挂起点改到主收据写入之前。新增实际强停用例验证在业务已可能发出后必须冷查原尝试，后台读取是一次 reuse-only 调用，原始付费事实保持未知。

## 范围

真供应商、真实下载、计费和发布均为零。源仓在途工作区、生产作业和全局技能没有被写入。独审需重点判断持久化和观察层分工、启动与收到内容判断的证明边界、诊断副本与可读性、业务 stdout 兼容，以及重复查询是否产生额外请求。

真实 Windows 定时运行和当前全局技能副本待总控发布核对。

## 第二次候选

以同一精确基线重发 `ff-runtime-remediation-r2.patch` 和同名 `.manifest.json`，覆盖 30 个路径。补丁 SHA-256 为 `10c0e6c1f58f4936246894793f57e8a42b7daf671349f32cd952d33f8a9b154a`，候选清单绑定 `1881f0d4f6151e491b309a40140a0560272a5d60616c2514eb21bd3261086c91`，在实际归档基线的源仓通过 `git apply --check --whitespace=error-all`。上面的 15 项和首轮证据保留历史，当前审查只用 r2 清单与在途完整 CI。

冻结后通过 23 项定向复验。运行命令如下，关闭宿主 pytest 插件和观察目录覆盖值即可从候选根使用。

```powershell
python -B -m pytest -q -p no:cacheprovider tests/test_ff_runtime_lifecycle.py tests/test_ff_slot_feedback_lookup.py tests/test_root_w07_matrix_boundaries.py::test_matrix_assembly_loads_context_without_reimporting_its_launcher
```

普通主机完整 CI 正常异步运行，exec session 为 `79868`，落盘结果为 `t/ff-final-ci.txt` 和 `t/ff-final-ci.exit`。此轮交付时完整结果未出。

四条独评 RED 及设计分别记录在 [进度](progress.md) 与 [发现](findings.md)。短财报与三表的回读共用同一原生收据；合同保持业务 stdout 兼容。既有明细只随原始运行恢复。只读作业状态查询不会补投，`reoffer-job` 是明确维护入口。独立审查另需运行 Windows 下原 `ff-direct-detail` 探针和 `test_public_run_and_attempt_find_redacted_replay_scope`，验证原 ID、用量不明时的含义、零重发及包写入范围。

短财报可用有效公司、市场、期间、限额和模式的安全字段再现。登录凭据、opaque continuation、非白名单内容保留省略说明及原字节摘要。短财报伴随电话会使用同一父运行绑定，用量事实由 ET/CWP 发布，各仓原计费保持所属层责任。此轮拆开了电话会运行入口与域解析，以及矩阵启动器与 context 的已证循环依赖。真实 ET、CWP 端到端矩阵未扩大此轮隔离用例。

## r3 自动补投候选

当前审查使用 `ff-runtime-remediation-r3.patch` 和同名清单，仍相对源仓 `7651f70d06b5ee411b4e9221751f5db3f7fd7526`。33 路径补丁 SHA-256 `382793dd33c99688997b54260321025a5fdeec7f31e5af72ec6738715a5a5eac`，候选清单 SHA `cefddfbb7d93622e77389687bc6db23d8b3cde003b232965f83480eb8a54765e`。源仓应用空白检查通过。

CWP 的 `filing-fetch.actions.flush-observations` 指向本仓公开命令。每个受管原生 outbox 配对一个已有 owner state root，按实际配置列表重复参数。

```text
C:/Miniconda/python.exe -B -X utf8 <FF>/scripts/ff_job_feedback.py flush-observations --jobs-dir <FF>/.ff_jobs --jobs-dir <user>/.agents/skills/filing-fetch/.ff_jobs --jobs-dir <user>/.codex/skills/filing-fetch/.ff_jobs
```

查询动作 `reconcile` 可沿用同样三项 `--jobs-dir`。历史单路径参数仍可用。新动作只需要现有 state roots，按上述 argv 配置即可。有单独配置的非默认出箱时，两条动作可加 `--observations-dir <actual-dir>`。没有为本轮复验更改现场 F4 配置或作业。

```powershell
python -B 'docs/plans/ff-runtime-remediation-20261125/host-flush-probe.py' --cwp-root '<company-wiki>'
```

主机探针使用实宿主、显式配置 argv、合成三表和独占状态目录。实际根不可用时无 marker，目录修复后仅自动维护即可恢复。真实结果为 5 个已持久观察，重复 0，原业务调用 1。公开 lookup 同样保持纯读。

故障定向 4 项、查询/计划定向 8 项均通过。Ruff 与 mypy 通过。同版完整 CI 未运行，上一轮异步宽批没有可复用状态文件。实际安装、调度、远端和现场配置在本轮只读。

## 已发布版本的矩阵 CI 增量

公开发布后，普通 Ubuntu 日常 CI 定位到一个测试替身绑定缺口。基线、三条真 RED、邻居场景和独立的增量交接见 [CI 复验](ci-45734325155.md)。
