# 短请求反馈样本

这些 JSONL 由真实 `scripts/fetch_filing.py` CLI 产出，不是手写样例。每个文件是一次独立执行；`run_id`/`attempt_id` 固定为 `sample-run`/`a1`，`evidence_ref` 每次执行新生成。

## 生成步骤

1. 使用本仓 `tests/test_feedback_observation.py` 的 `Harness`（受控 mock connector + 独占临时目录）逐场景运行 CLI。
2. 每个场景把 `RESEARCH_FEEDBACK_OUT` 指向一个新的 `*.jsonl`，读取退出码和业务信封。
3. 原样复制侧车文件；再读一次确认零新增（`manifest.json` 的 `reimport_zero_new=true`）。

复现片段（在仓根用同一解释器运行）：

```python
import sys
from pathlib import Path
sys.path.insert(0, "tests")
import test_feedback_observation as t

base = Path("<short-temp-root>") / "replay"
harness = t.Harness(base / "reuse", scenario="reuse_hit")
completed = harness.run(
    t._v2_request(), out=base / "reuse.jsonl",
    run_id="sample-run", attempt_id="a1",
)
print(completed.returncode)
```

`manifest.json` 记录每个样本的 scenario、请求、退出码、业务状态、stub 操作序列、ensure/ET 调用次数、行数、检查名、证据引用和子进程环境是否已清除。

## 样本

| 文件 | 场景 | 退出码 | 关键观察 |
|---|---|---:|---|
| `sample-1-reuse-hit.jsonl` | 精确本地命中 | 0 | 只跑 `identify` + DB-only `query`；`provider-start=not_started`；`provider-usage=not_applicable`；`download-receipt=0` |
| `sample-2-missing-limits.jsonl` | v2 `fetch_if_missing` 缺限额 | 2 | 零子进程；`request_error/acquisition_limits_invalid`；`provider-start=not_started`；`provider-usage=known`；`download-receipt=0` |
| `sample-3-latest-unknown-usage.jsonl` | `latest_as_of` 元数据发现后复用 | 0 | `source_candidate/reused_after_discovery`；无原生计量时 `provider-usage=unknown`；`download-receipt=0` |
| `sample-4-download.jsonl` | 受控首取 | 0 | `source_candidate/downloaded_new`；`provider-usage=known`；`download-receipt=1`；ensure 恰好一次 |
| `sample-5-corrupt-rejection.jsonl` | 损坏件预期拒绝 | 2 | `upstream_error/canonical_import_failed`；provider 未启动；`provider-usage=known`；`download-receipt=0` |
| `sample-6-companion-scopes.jsonl` | 主财报已知零 + 电话会费用未知 | 0 | `provider-usage=known` 与 `transcript-provider-usage=unknown` 分属两个 `step_id`；ET 调用一次 |

所有样本只含闭集状态词、业务 token 和 `urn:`/`ff-short:` 引用；不含本机路径、凭据或财报正文。
