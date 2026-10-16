# DU8-FF-MATRIX-COMPLETION — 固定时限内的联调调度与完整覆盖

## 开工信息

- 工作目录：`C:/Users/郑曾波/Projects/filing-fetch-du8-matrix`
- 自有计划：`docs/plans/du8-matrix-2026-10-16/task_plan.md`
- 分支：`codex/du8-ff-matrix-20261016`；源码基线`e8a85585b4c64a9596e576ff3b73e5c2ee29c334`，随后仅启动PWF种子。
- 可以现在启动。CWP/ET仅用launch固定的已提交只读代码依赖，不读ROOT未提交接线。

## 1. 实证与目标

DU6 portable证据搬迁已完成，不重做oracle/pack。最近保留的真实41链为38PASS/1PARTIAL/2NOT_RUN，原5findings仍在；174.565/180秒时批次截止，`request_after_failure_retry` partial，`original_wrong_mime`和`incomplete_sidecar_metadata_gap`未跑。当前cli_main已有WORKERS=2，不能再把“加两个线程”当新方案。ROOT另已将run_process收拢到既有ff_process_transport，修过可选stdin跨平台测试；不要回写重复Popen/taskkill/wait。

本卡测清启动、fixture初始化、单case链、source证明、final proof的重复工作与关键路径，在原case≤30s/batch绝对≤180s、workers≤2下提升稳定性与公平完整覆盖。不得提高限额、换较弱case、裁分母、延后启动batch clock、跳fresh-byte证明或反复重跑直到偶然绿。先独立定位，若某性能/外部依赖原因不在本层可修，给具名证据，不编造41PASS。

## 2. 精确写范围

`tools/offline_contract_matrix/cli_main.py`（调度/初始化/复用相关）、`run.py`（Context只属工程执行）、`runtime.py`（仅向既有transport传递deadline/预算的薄适配）、`measurement.py`（真实计时）、`README.md`；新可选同目录`case_scheduling.py`一个纯调度owner；新`tests/test_du8_matrix_scheduling.py`、`tests/test_du8_matrix_deadline_recovery.py`及专用fixtures、自有PWF。

`oracle.py`、`case_specs.py`、`matrix_outcome.py`、原report schema、生产`scripts/`、ET/CWP/Dayu、现旧tests/gold/CI/config全部只读。本卡不是改download生产链或供应商卡。不得把发生的provider副作用/unknown usage吞掉。

## 3. 固定跨仓接口

仍是现`run.py --cwp-project --et-project --owned-root --out-root`及`ff-et-cwp-offline-matrix/1`，原41 CaseSpec+oracle为唯一判定；保持download→reuse/失败后retry在同一个隔离Context的因果序列，不能并发同一case链。每group wiki/config/counter/cache完全独立，global semaphore≤2；公平调度不能通过放大并发绕限。

ROOT给的只读依赖为CWP`f08aa101ab49ca983d3a40356abfb05347f586b3`和ET`d0ac42c60dcca992db78860b8469cfed3dd527e5`，这两套是历史41链接口已验证的固定工程输入，不是声称当前生产HEAD。禁止更新/改文件/改Git；交付记录实际模块路径/HEAD/SHA。ROOT最终另做最新版本兼容，不让作者追主线漂移。旧保留证据只能replay，不叫新链。

## 4. A/B/C与验收包

A读取历史phase_timing/launch_accounting和当前实现，给成本分解（启动/seed/discovery/acquire/import/fresh-open/final-proof），在fake clock+实际bounded子进程spy下先RED重复初始化、任务尾部饿死、取消后仍开case等实际问题。不要凭机器慢就重新分配虚假时间。

B用测量证明共享只读元数据/模块探测/合法fixture准备是否可一次复用；可变Context/原文入库/调用计数绝不共享。deadline.remaining只来自同一绝对deadline，retry/cleanup/final proof不续期；预留证明时间必须真实可执行。覆盖非协作子进程、失败/丢响应、已退出管道回收、并发group互不污染、反序调度与输入顺序独立、取消后0新增启动。profile仅诊断，不写性能波动型日常CI阈值。

C一次固定全部41链端到端，包含新独立Temp和原sentinel/生产元数据保护。所有PASS才写41PASS；不通过记录真实FAIL/PARTIAL/NOT_RUN并留根因。另做一个受控中断/恢复端到端：证明不把失败目录重用为成功、不重复不可重放副作用，退出回收完整。可用fake clock形成必然超时路径；不能因最终机载波动改case预期。矩阵只需大节点手动运行，不加进每commit日常CI。

集中快测复用已存在W06/W07/DU6/ROOT process-owner/portable范围（A盘点实际路径）与本卡新测试一次；0HTTP真实/0LLM/0翻译，fixture调用单列。历史19/21/1与38/0/1/2证据不覆写。

## 5. 交接

按INTERFACES格式给前后同机同固定依赖的成本分解、调度图/关键路径、真实41分母、失败处理/cleanup和原oracle反篡改保真。本卡只能称工程联调覆盖，不称供应商网络/公司事实质量通过。正常commit并冻结STOP，ROOT合流。
