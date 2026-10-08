# R6-FF-CAUSE HANDOFF — ready_for_main

## 1. 修的共用机制、原实测问题 / 最小 RED；与公司特判的区别

共用机制：company-wiki producer 失败 stderr 的**单次安全解析**与可选诊断
传播。原实测问题（基线 `697af96`）：CWP 在 stderr 发布了具名机器码
（error-taxonomy-1.1），FF 分类后只留下 `ensure exited 1` + `fatal`，
机器原因丢失。最小 RED：

- `python -m pytest tests/test_provider_cause_contract.py -q` → 24 failed /
  2 passed（`AttributeError: no upstream_cause`；`ModuleNotFoundError:
  ff_provider_cause`）。
- `python -m pytest tests/test_provider_diagnostics_cli.py -q` → 5 failed /
  5 passed（v1/v2 失败 envelope 缺字段 KeyError；kwarg TypeError）。

与公司特判的区别：code 词表是**经验证的 CWP 公共机器码闭集** +
FF 自身可观测的 producer 状态（启动失败/截止/输出超限/传输失败）+
`unknown`；没有任何按 ticker/sourceSHA/页面/公司白名单推断原因的逻辑，
不复制未验证 message 字符串。

## 2. 公共接口（实际导入路径、签名、字段、版本、最小例）

- `scripts/ff_provider_cause.py`（新）：
  - `UPSTREAM_CAUSE_SCHEMA_VERSION = "filing-upstream-cause/1"`；
    `OPERATIONS = {identify, ensure, resolve, close-gap, query}`；
    `CAUSE_KEYS` = 6 键。
  - `diagnose_stderr(operation: str, stderr_text: str) -> (filing_code, cause_dict)`
    —— 唯一的 stderr 解析入口（≤64 KiB、strip 后计长；畸形/过大/混合 →
    `("fatal", code="unknown")`）。
  - `condition_cause(operation, condition, *, provider_started=None,
    usage_complete=None) -> (filing_code, cause_dict)`；condition ∈
    {producer_start_failed, producer_deadline_exceeded,
    producer_output_exceeded, producer_transport_failure}。
  - `build_cause(operation, code, *, provider_started=None,
    usage_complete=None)`（开放词表 ValueError）；`validated_cause(value)`
    （非合规对象 → None）；`classify_stderr(text) -> str`（旧分类器兼容）。
- `filing_contracts.FilingFetchError(..., upstream_cause: dict | None = None)`
  —— 传入非合规对象抛 `TypeError`；默认 None（既有调用零改动）。
- `ff_v2_envelope.error_envelope(..., upstream_cause: dict | None = None)`
  —— 放入 `filing` 内；v1 CLI 失败时顶层 `upstream_cause`。
- 最小例（见 `tests/test_provider_cause_contract.py::test_diagnose_stderr_direct_contract`）：

```python
import ff_provider_cause
ff_code, cause = ff_provider_cause.diagnose_stderr(
    "ensure", '{"status":"failed","error_type":"legacy_evidence_archived",...}')
# ff_code == "fatal"
# cause == {"schema_version": "filing-upstream-cause/1", "operation": "ensure",
#           "code": "legacy_evidence_archived", "provider_started": None,
#           "usage_complete": None, "retry_scope": "none"}
```

与卡的差异：无。`provider_started/usage_complete` 生产路径只出现
`null` 或 FF 可证明未启动时的 `false/true`——CWP 未发布该字段（见
findings 缺口 G1/G2），这是卡明确要求的诚实 unknown。

## 3. Git 基线 / 分支 / 提交 / HEAD / 未提交文件

- 基线：`697af966475a4aa7bb0687c78bfb81a7edb54f21`（worktrees.json 发布的
  FF main 精确基线；worktree 起始 clean）。
- 分支：`codex/cmrf-provider-diagnostics-20261008`（本 worktree，
  未推远端；未动 canonical 主目录）。
- 交付提交：
  - `5da45dc6c253f7f181569661d430909acdbb3904`（代码 + 测试）
  - `8bb7b85f57ca7effed2a42afe8fbcdbba72c15ff`（docs/E2E/CHANGELOG）
- 当前 HEAD = `8bb7b85f57ca7effed2a42afe8fbcdbba72c15ff`。
- 未提交文件（用途）：`HANDOFF.md`、`handoff.json` —— 本交接记录本身，
  供 MAIN 读取验收；不含 owner WIP。canonical FF 的
  `config/FMP_API_KEY.txt` 属 owner WIP，本 worktree 中不存在，未读入、
  未提交。

## 4. 测试（精确命令、退出码、通过/阻塞数、耗时、真伪原件）

- RED（基线上）：
  - `python -m pytest tests/test_provider_cause_contract.py -q` exit 1，
    24 failed / 2 passed（机制：见上）。
  - `python -m pytest tests/test_provider_diagnostics_cli.py -q` exit 1，
    5 failed / 5 passed。
- GREEN：
  - `python -m pytest tests/test_provider_cause_contract.py tests/test_provider_diagnostics_cli.py -q`
    exit 0，36 passed，~2.5 s。fake `_run_bounded_json` mock + 真子进程
    CLI（临时 fake company_wiki 包，离线）。
  - `python -m pytest tests/ -q --ignore=tests/test_e2e_download.py --ignore=tests/test_e2e_isolated_wiki.py --ignore=tests/test_fc805_real_download_t3.py --ignore=tests/test_real_tool_conformance.py`
    exit 0，552 passed / 6 skipped / 78 subtests，~91 s。
  - `python -m pytest tests/test_e2e_isolated_wiki.py tests/test_real_tool_conformance.py -q`
    exit 0，21 passed / 1 skipped，~56 s（skip = 生产目录可用性门，原有）。
  - 静态：`ruff check scripts tests` exit 0；`python -m mypy
    scripts/filing_contracts.py scripts/fetch_filing.py` exit 0；
    `python -m pytest tests/test_complexity_ratchet.py -q` exit 0（新模块
    初测 12>10，拆分 `validated_cause` 头校验后 ≤10，未放宽阈值）；
    `python tools/host_assumption_guard.py --roots tests tools scripts e2e`
    exit 0（new=0）。
- NOT_RUN：`FILING_FETCH_E2E_DOWNLOAD=1` 真实下载套件（离线线节点不调
  真实市场，未运行）。
- 集中 E2E（手动大节点，离线）：
  `python docs/implementation/cmrf-provider-diagnostics-20261008/run_isolated_cause_e2e.py`
  exit 0，25/25 checks PASS（A 6/6、B 7/7、C1 5/5、C2 7/7），报告
  `isolated_cause_e2e_report.json`。真件：真实 CWP CLI（canonical 只读
  import，PYTHONPATH）+ 真实 FF 公开 CLI；fake：CN json_command_v1 假
  provider（记录 start/HTTP/usage）；无任何真实市场/模型/网络调用。

## 5. 测试根初始/结束状态、清理、峰值、生产配置/原件

- E2E 全部状态在独立 `tempfile.mkdtemp` 根；默认退出即删（复跑验证
  `tmp exists after run: False`）；`--keep` 保留，三次 --keep 产生的根已
  手工删除（`ls cmrf-ff-cause-e2e-*` → 0）。保留字节 0。
- 未写生产 `source_catalog.yaml`/`company_wiki.json`/任何 canonical 仓文件
  （CWP 只读 import；catalog/staging/security_master 均在 tmp）。
- 无收费调用（model_calls=0；E2E provider cost_usd="0.00" 为 fake 记录）。
- 单测均用 TemporaryDirectory 自动清理。

## 6. 需要 MAIN 接线的事项与仍存在的外部限制

- M1（接口差异清单，交 MAIN 跨仓补，本线未改 CWP）：
  - G1：error-taxonomy stderr 无 `provider_started`/`usage_complete`。
    建议 error-taxonomy-1.2 增加两个 bool（畸形 → fail-closed unknown），
    FF 解析器/词表是唯一扩展点（`_CWP_STDERR_CODES` /
    `_PRODUCER_CONDITIONS`）。
  - G2：adapter 层机器码（`AdapterProcessError.error_code`，如
    `upstream_unavailable`）与 `acquisition_usage`/`acquisition_usage_complete`
    在 CLI 边界被丢弃（重序列化进 6 码 taxonomy）。CWP 若透传安全子集，
    FF 可映射具名账户/HTTP 拒绝与预算类。
  - G3：账户/entitlement 拒绝、预算上限、下载后验真失败目前不可机器区分
    （均为 fatal + 原文）；需要 CWP 命名码后 FF 才能区分——当前诚实
    unknown/fatal + 不自动重试。
- M2：MAIN 合并后在 RF 报告/测试套件接入 `upstream_cause`（本线不改
  RF/CWP 消费端）。
- 外部限制：FMP 账户真实 entitlement 拒绝仍属账户侧外部限制，与本线
  代码功能无关（卡已声明）。
- 已知行为决策（非缺陷，见 findings "Documented behavior decisions"）：
  contention 截止耗尽保留最后 catalog cause + `retry_scope=
  catalog_contention`；query 启动失败保留历史 retryable 语义（唯一
  retryable+scope=none 旧例）。

## handoff.json

见同目录 `handoff.json`（其 `files` 为功能交付文件；HANDOFF.md /
handoff.json 本身为未提交记录，见第 3 节）。
