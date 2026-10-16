# DU8-FF-MATRIX-COMPLETION：ROOT 重建交接

作者 HEAD：6f381199f146109b4f517537a70da1c20c6e05bd；基线 e8a85585b4c64a9596e576ff3b73e5c2ee29c334。
A/B 工程可接收，C 完整 41 PASS 未完成；作者交付原始机器接口仍见 handoff.json。

## 可接收内容

纯 LPT case 分组、固定 run-count 成本估算、CLI 委派、具名绝对截止原因及 37 个小测试。
不改 workers<=2 / case30 / batch180 / reserve10，不改固定 case 输入、provider、生产代码或权限。
全覆盖历史表：旧 75.5306/59.8019，新 74.0080/61.3245 秒；关键路径仅改善 1.5226 秒 / 2.02%。静态 52/52 不是实测均衡。

## ROOT 修复边界

零 GET 的 provider_deadline 不当成业务坏掉，也不算在途覆盖通过；整体 PARTIAL。CaseSpec 对完整 PASS 的一 GET 要求不变。
恢复夹具只绑定当前新 UUID 和该 case request/fixture/GET；复用已有 OS 进程树 owner，观测失败 unknown；独立 Temp 与 sentinel，清理后恢复，不覆盖旧证据。
恢复夹具现在只做一次受控中断，完整 clean 41 链另行验收，不再暗中串行重跑两次矩阵。

## 仍须真实验收

ROOT 只运行一次固定 CWP f08aa101 / ET d0ac42c6 的完整离线链，记录全部结果及保留证据。旧三次 21/26/14 PASS 均为历史失败，不因改文案消失。无真实供应商、API、翻译或 LLM 使用。
最终源码 SHA、窄测试、完整链和独立审查见 root-reception.md 与 CWP ff-root-repair.md/json。

本文件原始非法 UTF-8 字节完整归档 root-original-corrupt-markdown.json；按有效 JSON、独立报告及原始收据重建，未猜补丢失数据。


## ROOT 最终接收（2026-10-16）

工程修复与最终独立审查完成：251 PASS / 0 FAIL / 0 SKIP，9.19 秒；范围内0 P1/0 P2。
唯一真实完整矩阵20 PASS / 0 FAIL / 4 PARTIAL / 17 NOT_RUN，173.2744 秒，C仍OPEN。
原30/180/10秒与固定CaseSpec不改；完整209文件/1,151,019字节、guard/restore/manifest保留。
后续优先减少重复启动/准备成本，不重调权重、不提高限额、不删除case求绿。
详见本目录 root-reception.md/json，正常hooks提交/并线/推送由ROOT负责。
