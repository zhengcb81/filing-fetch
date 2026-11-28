# S6 P2-02 · 入口与证据职责

| 正式入口 | 正常操作 | 既有事实来源与边界 |
|---|---|---|
| `fetch_filing.py` | 原件解析、只读复用、请求授权的采集、按请求伴随电话会 | DirectRun 保留原调用和派发轨迹，CWP 和 ET 分别报告实际结果。 |
| `fetch_statements.py` | 历史三表复用或经 CWP 获取 | DirectRun 和原生返回保留只读回看，费用不能从状态码推断。 |
| `ff_job.py` | submit/run/status/list/actions | JobStore 原记录和锁决定作业、费用与退避，作业日志和 F4 投递提供诊断。 |
| `ff_scheduled_refresh.py` | status/configure/runs/tick | RefreshStore 管单时段与逐文件进度，实际来源仍交对应 owner。 |
| `ff_scheduled_windows.py` | preview/install/remove/运行同一 tick | 现有 pythonw 动作和进程树 watchdog；启动、终止与未知恢复分开。 |
| `ff_job_feedback.py` | get-diagnostic/get-{statement,direct}-run/reconcile/reoffer/flush/report/triage | 冷读原件和已有作业，不重发；无效的控制面请求仅记本仓原生日志。 |
| `ff_t3_receipt.py` | get/run-live | T3 实际回执为事实；既有公开 CWP 临时工作区接口负责环境。本卡仅走离线或冷读。 |

`ff_t3_workspace.py` 是 T3 使用的公开客户端，直接下载 provider、CWP 与 ET 的内部状态以及 Windows 跟踪方式不属于 filing-fetch 日志层。部署脚本转发到上表入口。打包和层目录迁移按父计划后续阶段实施。

基线重现：11 个失败、1 个已正确用例。普通启动有的把含合成凭据的参数反射到 stderr，有的没有日志版本和输入标识。三类 F4 后置参数校验没有诊断。两个目标都不可写时无告警。JobStore 在真实并发写入中没有轮转，日志直接保留合成凭据。之后补充真实本机 HTTP 已接收后截断，基线边界只留 `ChildFailed`，丢失子进程自定义异常的类型和尾帧。