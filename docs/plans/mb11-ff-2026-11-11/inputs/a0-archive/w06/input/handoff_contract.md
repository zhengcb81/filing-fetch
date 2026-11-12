# W06 交接与责任接口

## 施工绑定

唯一施工根、分支和起点见自己的 construction_card.md 与 inputs.json；只能在自己的 worktree 写允许集合。自己的 PWF 为 .planning/w06-<lane>/ 三文件，交接 docs/handoffs/w06-<lane>/。input/ 是 ROOT 固定输入，不能覆写。每卡都可独立读，不依赖其他 worker 的 WIP。

无新许可 JSON、人签收、private/public、canary 或授权链。原件、生产配置、Dayu/IQS、邻仓 WIP 和现存 sealed runs 只读。ROOT 负责公共源码、适配、发布、安装及母账。

## handoff.json（schema w06-lane-handoff/1）

必须有 lane/status(COMPLETE|PARTIAL|BLOCKED 中一个)/repository/workdir/branch/base_commit/head_commit，changed_files[{path,sha256,purpose}]，input_evidence[{path,sha256,bytes}]，interfaces[{name,before,after,compatibility}]，tests[{phase,command,exit_code,counts,elapsed_seconds,log,log_sha256,scope}]，findings[{id,root_cause,disposition,evidence,test_ids}]，cleanup{owned_root,baseline,after,restored,raw_unchanged}，cost{provider_calls,model_calls,paid_usd,unknown_charge}，space{retained_bytes,scratch_peak_bytes,measurement}，remaining 与 root_next_action。

代码测试通过、工程契约通过、真实供应商/公司研究通过是不同结论。NOT_RUN/null 如实保留；synthetic 响应不能称真实下载/原材料。报告工具完整且准确报告产品失败可 PARTIAL；既有产品错误不能以新工具运行 exit=0 冒签修复。

另给 handoff.md、manifest.json，manifest 列交接文件实际相对路径/SHA/字节，自身不递归哈希。保留 RED 和 GREEN 的不同日志，不覆盖；日志不要包含环境密钥或原文大响应。按原 Git hooks 正常 commit，不 force/跳 hooks，不推主线。ROOT 集中接收最终提交并重放关键向量。

## 三个大节点

1. 读固定源码、明确接口及期望，先留真正行为 RED。缺模块/导入/路径错误不是算法已复现；新工具尚不存在时先给可调用 stub，再复现行为缺失。
2. 实现，集中快速单元与接实际责任层的 integration。旧测试断言保持；慢真实跨进程测试只在最终工程节点跑一次，不新加逐小步全套门。
3. 独立 scratch E2E/恢复，交一次最终证据和正常 commit。失败/超时也保留准确收据，未恢复不签 COMPLETE。

## 测试与留存

使用全新明确 owned root；如预置 sentinel，先记录清单/原 SHA，后只清本线生成路径并恢复 baseline。结束前关闭 SQLite/子进程；路径解析后确认边界，不删整块 TEMP 或 protected 测试目录。临时复制只有明确 synthetic 小样本/必要代码快照，不全湖扫/hash/copy、不完整恢复备份。默认每线持久交接 ≤8MiB、scratch 峰值 ≤64MiB，必要的代码快照另计并据实报告。无收费/外部网络。

## ROOT 接线顺序

三包无顺序依赖，可分别接收。Measure 工具由 ROOT 接入 process reviewer 检查点；FF矩阵由 ROOT 在下一并线大节点跑；Portability 工具复核来源存储层。纯快速工具单元可列入受影响 CI，跨仓/多根完整回放保留手动大节点入口，不让 commit 变成几十分钟。W05 交付后由 ROOT 用各最终源码再跑必要兼容，worker 不自行 rebase 未完成主线。
