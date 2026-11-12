# W07-FF-PERF：固定 41 场景联调效率根因修复

## 可以现在开工（本批优先）
工作目录：`C:/Users/郑曾波/Projects/_harness_worktrees/w07/ff-matrix-efficiency`
分支：`codex/w07-ff-matrix-efficiency`；基线：`2d380a054c658ce3b5f0763523e49a0ab34acf78`。
独立 PWF：`.planning/w07-ff-matrix-efficiency/`。先读本卡、HANDOFF_CONTRACT.md、INPUTS.json。ET/CWP code-only 已固定在本包 input/runtime，不读取另一 harness 浮动代码。无需等其他包。

## 已发生的问题（不要再盲目重跑）
原来的 CaseSpec/oracle 195测试与非作者28/28已绿。原41是40PASS/1FAIL、164.6232秒；cutoff修复后39PASS/3FAIL独审揭露 malformed stdout 抹掉已测 stderr usage，此共因已修，最终7PASS。

两个最新完整尝试分别：2PASS/31PARTIAL/8NOT_RUN、182.8623秒；1PASS/27PARTIAL/13NOT_RUN、184.54秒。没有把这些当作31个产品错误：180秒到期使尾部未跑、最终 fresh-source-proofs 没时间运行，oracle正确把缺最终证明的条目降为PARTIAL。保持失败记录；本包定位启动/准备/多层进程共因，让同一证据链在原预算内走完。

本基线含尚未并main的cutoff/usage修复；worker只动工具编排，ROOT负责FF/ET生产修复与发布。不能修正旧失败记录或把工程绿描述为全链完成。

## 唯一写集
- `tools/offline_contract_matrix/runtime.py`：实测阶段计时、兼容进程编排。
- `tools/offline_contract_matrix/cli_main.py`：现有单一deadline内编排。
- `tools/offline_contract_matrix/run.py`：仅 Context 执行安排/计时；不改请求/返回/期望语义。
- `tools/offline_contract_matrix/matrix_cases.py`：**只准 seed_all**；其余 case handler不改。
- 新 `tools/offline_contract_matrix/seed_batch.py`/measurement_* helper，如确需。
- 新 `tests/test_w07_matrix_efficiency.py`。
- 自己 `.planning/w07-ff-matrix-efficiency/**`（初始input只读）与 `docs/handoffs/w07-ff-matrix-efficiency/**`。

其余只读：CaseSpec/RunSpec、oracle*.py、matrix_outcome.py、source_proofs.py、fixture内容、所有case handler及现有测试期待、scripts生产逻辑、ET/CWP/config/key/CI/hooks。输入 manifest 对只读文件及除seed_all外的函数单独留证。不可删除原case/降低预期/跳过proof/加审批/第二计时器。

## 已准备的运行依赖（只读）
ET：`.planning/w07-ff-matrix-efficiency/input/runtime/et`，commit d0ac42c60dcca992db78860b8469cfed3dd527e5。
CWP：`.planning/w07-ff-matrix-efficiency/input/runtime/cwp`，commit d75f0d42e0fc11caa50d5030d16fa238c0e02d55，src/pyproject code-only。
依赖 manifest SHA f8e17feda1f540948521f595d7e4fd2697b39b6b3867cdb2bd04107eea27a00f。
两份只含代码共约3.6MB，不含原件/生产config/密钥。输入runtime已忽略，不提交复制代码；需要重建时按 dependency-manifest 的固定commit/path用 git archive导出，而非复制主仓WIP。ROOT已实测：这两个code-only目录位于FF worktree内部，现有git -C会向上找到FF HEAD（2d380a05），不能把它误报为ET/CWP提交。工具依赖记录须区分实际git归属与manifest固定来源commit：只在toplevel等于传入root时用git HEAD，否则git_head为unknown/null，来源commit从本包dependency-manifest读取并与现有实际module绑定分开表示。此处是报告真实性，不增加身份许可或新门禁；集中快测加一个嵌套gitless快照反例。

## A：测量与 TDD
先用已有 deadline/runtime/OwnedAttempt 接口建立阶段计时：binding、seed、FFCLI、ET supervisor/worker、fixture、fresh source proof、cleanup、总时长与实际启动数。计时不改变deadline起点/限额；unknown的阶段不能瞎估。

诊断只需小样本/已有完整日志，不先耗180秒重跑同一个失败。重点检查 seed_all 现有10次独立CWP CLI ensure（CN/HK/US年/半年/季报＋US2025年报）和扫描的重复准备。先用受控时钟/小假进程做调度行为RED，例如准备重复、计时遗漏、最终proof饿死、异常遗留进程；假进程只用于工具unit，最终真链保留。

## B：根因实现，保留真实链
优先把**同样10个真实CWP ensure写入**收敛为一个有界 helper进程顺序调用同一实际服务，每个request/response/receipt/source-ref/计数留下；不能直接造SQLite或假source-record替代原writer，不能预种本该触发新下载的文件。

复用单一 Deadline/OwnedAttempt 和已有synthetic env，减少重复启动/扫描/准备。每个需要检验的真实FF公开CLI、ET supervisor/worker、CWP writer/Reader仍按场景实际执行；不能把264次启动一概删掉。最终实字节/locator proof必须在所有相关变更后运行，早期proof不可替代最终状态，也不能移出预算或使用旧run缓存。

若测量证明需最多2并发worker，先给有向依赖与所有权：每组独立Context/wiki/proxy/counters，首次download→reuse链保持顺序，不能共享catalog并发写或把provider计数混合。不为并发而并发，先消除准备共因。保留CaseSpec/RunSpec权威、当前30s/case及180s/batch原值与起点，禁止重置remaining时间或增加timeout。

集中快测：`python -B -m pytest -q tests/test_w07_matrix_efficiency.py`，另跑与实际修改接口有关的既有matrix runtime/seed测试（具体文件名由当前tests确定），不改旧期望。检查超时仍拒绝、seed每请求真实记录、最终proof顺序、多个owned上下文不混、初始化/异常/timeout恢复。记录改前/改后计时，别据小fake计时宣称41通过。

## C：原41完整离线 E2E（仅大节点）
在当前工作目录运行，ABS_NEW_SCRATCH与ABS_NEW_REPORT是不同的新短路径：

```powershell
python -B tools/offline_contract_matrix/run.py --cwp-project .planning/w07-ff-matrix-efficiency/input/runtime/cwp --et-project .planning/w07-ff-matrix-efficiency/input/runtime/et --owned-root ABS_NEW_SCRATCH --out-root ABS_NEW_REPORT
```

实际预期：原41全部执行且PASS，oracle无冲突；各跨市场/不同文档/首次下载与复用/补TXT/cutoff/identity/失败恢复原期望保持；最终fresh实字节/SourceRef/locator证明完成，恢复absent/sentinel，production只读baseline保持，原30/180约束未变。计时包括原批次已有setup/执行/proof与恢复安排，不移阶段来隐藏时间。

首次完整run失败，只为证实共因修复后再跑；如仍PARTIAL准确交最慢阶段、依赖、剩余方案与失败报告，不声称交付目标达成。不加每commit41CI。每条真provider/LLM成本为0，synthetic请求单列。

交完整41报告、oracle结果、fresh proof、before/after阶段与启动测量、CaseSpec/oracle/case handler不变证据、小快测与恢复证据，正常提交STOP。ROOT独立接收后并线FF/ET；worker不写ROOT生产修复工区。
