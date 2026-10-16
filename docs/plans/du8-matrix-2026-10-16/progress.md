# DU8 FF 进度（ROOT 接收）

作者 A/B：新 37 测试通过；作者相关回归 344 通过（作者收据，独立不冒称重跑）。
作者 C：21 PASS/1 FAIL/2 PARTIAL/17 NOT_RUN @174.31 秒；26/1/2/12 @174.56 秒；14/0/12/15 @182.49 秒。完整验收仍 OPEN。

作者 v1 夸大 16–21 秒调度改善、v2 泛化优越结论均已撤回。全覆盖历史表真实收益仅 1.5226 秒 / 2.02%，不能用来解决整体两三倍变慢。
主机负载与 deadline 合同问题可同时存在；没有控制实验不能把失败全部归为外部。

ROOT 独审：37 PASS / 0 FAIL / 0 SKIP，3.07 秒；确认原文件真实 UTF-8 字节损坏，非控制台显示。
ROOT 新测试首轮：8 FAIL / 4 PASS，其中两个真实行为缺口、六个新增恢复接口尚不存在。原 RED 保留在 CWP 的 du8-reception/ff-root-red.log。

ROOT 修复与一次完整重测结果由 root-reception.md 和 CWP ff-root-repair.md/json 记录；在真实报告落盘之前不宣告 C 完成。
原文件完整字节在 root-original-corrupt-markdown.json。


## ROOT 最终接收（2026-10-16）

工程修复与最终独立审查完成：251 PASS / 0 FAIL / 0 SKIP，9.19 秒；范围内0 P1/0 P2。
唯一真实完整矩阵20 PASS / 0 FAIL / 4 PARTIAL / 17 NOT_RUN，173.2744 秒，C仍OPEN。
原30/180/10秒与固定CaseSpec不改；完整209文件/1,151,019字节、guard/restore/manifest保留。
后续优先减少重复启动/准备成本，不重调权重、不提高限额、不删除case求绿。
详见本目录 root-reception.md/json，正常hooks提交/并线/推送由ROOT负责。
