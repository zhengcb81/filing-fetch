# F4 · filing-fetch 原作业与用量恢复

## 本仓交付

本仓发布基线为 main c380f996099bb76d072771598fba33ecf0cefb35。实际复验源码为 bf92ec1677f8a7aa316c64c44a927727f778acac，候选分支 codex/f4-ff-native-reconcile。ROOT 接收后沿 main 发布并配置宿主。

分诊先区分两种情况。若业务状态和原用量已落盘，读回原作业及历史费用状态。若作业进程失联，按原选择条件读取 CWP 现有索引，所得结果可以补记到原作业。旧费用证据仍由原作业决定。原费用不明时，禁止自动重做外部调用有防止重复计费的实际目的，本次只保留原地核对这一恢复路径。请求已有的字节、期限和金额限额随原作业保留。

反馈引用使用 ff-job/1/<owner_job_id>，步骤绑定同一 <owner_job_id>/<native_attempt>，调用方的 run_id 和 attempt_id 继续随原观察保留。请求为 feedback-action/1，kind=reconcile，method=lookup。已登记终态时，返回原 job_status、cost_state、cost 和 recorded_usage，另带新请求、下载和费用计数。原证据缺失或原尝试已不可确认时保持 unknown。真正还在运行的同一次作业返回 pending。

仅指定 --jobs-dir 时查询现有收据，连缺失目录也保持只读。指定同一作业的 --config 连接配置后，可用既有 FF 原生对账对中断的同一 attempt 做 catalog-only 文件查询，或按 reuse_only 读取三张表。对账由原生作业写回并去重。latest_as_of 的恢复确认当前本地索引的候选，供应商端最新状态仍不明。反馈动作的公开报告继续按原 action ID 通过 report/get-report 查读。

## 生产配置

核对实际启动 ff_job.py 的作业根和连接配置。当前 canonical FF 的 .ff_jobs 有 7 份实际作业，config/company_wiki.json 存在。总控在 filing-fetch 的 actions.reconcile 配置固定 argv，owner cwd 指向发布检出，timeout_seconds 设为 20。下面的 FF_CHECKOUT 应展开为绝对路径。原生只读查询超时为 10 秒。

```text
["C:/Miniconda/python.exe","-B","-X","utf8",
 "FF_CHECKOUT/scripts/ff_job_feedback.py","reconcile",
 "--jobs-dir","FF_CHECKOUT/.ff_jobs",
 "--config","FF_CHECKOUT/config/company_wiki.json","--timeout-seconds","10"]
```

只查询已落实的历史作业可省去 --config。总控从原 JSONL 通过下面命令恢复，既有短请求引用仍由其原短请求结果支撑。此路由沿用本仓作业锁和固定对账键，重复恢复始终查询同一原作业。

```text
python -B -m tools.feedback_loop.local_host --config SETTINGS recover --hosts HOSTS --sidecar ORIGINAL_JSONL --wait-seconds 5
```

## 验收与 ET 兼容性

- 本仓定向 **115 passed、8 subtests passed**。新增四例覆盖原 ID/attempt、费用已知和未知、缺原作业或错尝试、已登记后重复读取，以及对账请求留存原限额。现有 CI 定向清单收录该文件，CI 清单自身的 15 项测试通过。
- 实际作业库 7 份原作业的状态及计量与 FF JobView 一致，含 1 份原费用未知和 1 份原 attempt=2。26 个原数据文件的 SHA 和修改时间保持一致。探针记录外部事件零。
- 实际 CWP 宿主只启用 owner-json 的 actions.reconcile。从隔离 exact 和 latest_as_of 的本地受控供应商样本分别硬停 FF 进程，再并发恢复。每例保持同一原作业、一次业务启动和一次原地核对。原件 SHA 一致，重启后新增供应商请求、下载、作业和费用都为零；旧费用保持 unknown。现有 report 回执丢回复恢复也通过。组合 **3 passed，1 条其他仓用例 deselected**。
- 直接运行 ET 本仓公开 get-usage，解出 publication.usage_receipt 后交 FF 的既有 earnings-retrieval-usage/1 解析器。真实归档样本得到 0 请求和 0 字节的完整计量，离线历史计量对照得到 1 请求和 812 字节。异 request ID 及传入外层发布包装时保留未知。沿用原 ET 与 FF 的公开计量接口，通话资料新增请求数为零。

[脱敏机器收据](evidence/f4-native-reconcile.json)含实测版本、状态、原件 SHA、旧限额、路由和 ET 计量。7 个隔离测试目录已清理。ROOT 接收候选后按真实部署配置完成最后一次公开入口复验。
