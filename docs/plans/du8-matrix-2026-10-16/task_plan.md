# DU8 FF 矩阵接收计划（ROOT 修复）

## 状态

A/B 工程实现完成；C 三次真实运行分别仅 21/26/14 PASS，未达到完整验收，仍 OPEN。
ROOT 优先修复截止覆盖混用、恢复观测假通过与交接字节损坏。既有失败不得消失。

## 顺序

1. 固定 ROOT 行为反例，修同一测试责任层；不修改产品 provider 或固定 CaseSpec 输入。
2. 小型进程/假时钟集中验证；原有 37 新测试一起回归。
3. ROOT 独占一次固定依赖的 41 链公开入口：workers=2，case=30 秒，batch=180 秒，proof reserve=10 秒。
4. 保留全部 report/artifacts/restore/guard，原样报告 PASS/FAIL/PARTIAL/NOT_RUN；独立审查最终 SHA。

## 合同

1 秒限制覆盖冷启动。零 GET 的正确 deadline 是边界通过、在途覆盖未运行，整体 PARTIAL；只有真实 GET=1 的 stall 才可能完整 PASS。
静态 [52,52] 是估算权重相等，不代表实测均衡；完整保留样本仅改善 1.5226 秒 / 2.02%。
无新审批、签收、权限或下载门禁。最终提交和推送由 ROOT 负责。

## 重建依据

原本文件是非法 UTF-8。按有效 handoff.json、findings.md 与独立审查重建；原字节完整保存在 root-original-corrupt-markdown.json，可按 hex 复原，不猜补损坏文本。


## ROOT 最终接收（2026-10-16）

工程修复与最终独立审查完成：251 PASS / 0 FAIL / 0 SKIP，9.19 秒；范围内0 P1/0 P2。
唯一真实完整矩阵20 PASS / 0 FAIL / 4 PARTIAL / 17 NOT_RUN，173.2744 秒，C仍OPEN。
原30/180/10秒与固定CaseSpec不改；完整209文件/1,151,019字节、guard/restore/manifest保留。
后续优先减少重复启动/准备成本，不重调权重、不提高限额、不删除case求绿。
详见本目录 root-reception.md/json，正常hooks提交/并线/推送由ROOT负责。
