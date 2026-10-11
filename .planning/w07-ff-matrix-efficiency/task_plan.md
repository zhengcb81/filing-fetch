# W07-FF-PERF 独立计划

## 目标
实施 START_HERE.md 指定的任务，保持唯一写集与离线成本0。

## 大节点
- A 完成：RED 一次留证（13 failed/1 passed/1.21s）；measurement.py 阶段计时/启动计时契约；受控时钟/小假进程覆盖准备重复、计时遗漏、proof 饿死、异常遗留进程、嵌套 gitless 依赖反例。
- B 完成：seed_batch 单 helper 真实 ensure 收敛；MAX_PATH 安全字节码缓存 + 8.3 短路径代码根 + 预热绑定探针；run_process 任意异常回收；proof 10s 保留；依赖真实归属；最多 2 个隔离 worker（每组独立 Context/wiki/proxy/counters）。集中快测 18 passed + 既有 195 passed。
- C 完成：原 41 完整离线 E2E = 41 PASS/0 FAIL/0 PARTIAL/0 NOT_RUN、90.29s（预算180s）、oracle 0 findings、fresh proofs 26 全 verified、恢复/生产 baseline 保持。交接报告见 docs/handoffs/w07-ff-matrix-efficiency/。

## Next Step
无（STOP）。ROOT 接收后并线 FF/ET。

## 责任边界
本包只写本卡 allowlist。母 PWF/主线/安装由 ROOT 负责，不等其他包、不读取其 WIP、不改生产配置/原件/Dayu/IQS。
