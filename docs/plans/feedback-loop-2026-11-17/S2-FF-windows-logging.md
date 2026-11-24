# FF S2 Windows 启动器失败日志

## 第一个可复现缺口

基线 main f43a875。计划任务调用真实 Windows 启动器时，启动器将非零退出子进程的 stdout 和 stderr 文本尾部写入既有轮转日志。旧正则只能遮蔽键后的第一个词，带认证方案的报文会漏掉随后的凭据，任意 stdout 正文也会落盘。F4 的冷读拿到的是启动器合成的 RuntimeError，不能区分实际子进程的 stderr 形状。

## 执行边界

沿用 scheduled_refresh_failures.log、已有轮转和 ff-cli/1 观察身份。启动器保存实际退出码、stderr 形状及能识别的 Python 内建异常类型。自定义或无法识别的 stderr 仅保留类别。原始 stdout 不再采集，stderr 原文不写日志或 F4。用发生引用连接两处既有证据入口。子进程原生 F4 明细、定时 slot 账本和供应商用量原样保留。

## 验收与交接

- 真实 Windows 启动器通过真实 Python 跑离线子进程。基线的失败场景在有数据安全断言时失败，独立正常路径通过。
- 正常路径仍退出 0 且没有新增故障记录。故障路径含合成业务内容和合成认证值，原退出码保留。两次新进程 get-diagnostic 冷读都对应同一原发生，子进程只执行一次。
- 显式启动第二次生成不同引用并保留首个记录及观察文件原字节。不可写收件箱时原退出码与本地轮转日志仍保留。
- 既有 F4 slot 的冷查、正常失败回执和调度组合回归附在最终发布核对。临时状态均隔离，未启动正式 Windows 定时任务或供应商，未接触生产日志和密钥。
- 变更文件限定为 scripts/ff_scheduled_windows.py、scripts/ff_runtime_feedback.py、tests/test_s1_windows_tick_logging.py 和本页。真实调度器登记和历史日志的处置独立。

最终候选正常故障启动、冷读、坏出箱和原 slot 查验组合共 11 项通过，Ruff 与 Git diff 检查通过。较早候选的正常失败与调度组合共 38 项通过。ROOT 对最终三个源码及测试文件核验 SHA 一致，独立重跑三个真实 Windows 入口用例均通过，同意发布。
