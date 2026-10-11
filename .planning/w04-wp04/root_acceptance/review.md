# W04 WP04 独立只读验收

结论：PASS_WITH_SCOPE_LIMITS_STOP。

- 交接、5 个产品文件、证据 manifest 的 SHA/大小均与实际字节一致。
- 3 个独立微型探针完成；累计 94 条实际断言。未重复 200 项旧测试。
- 默认 serializer 输出与 base 的编码字节一致；非 error serializer 函数 AST 一致。
- FF/RF closed reason/path 全部一致；旧六键 cause 和 unknown 保留。
- 非有限时间、非规范费用、companion 非法限额通过真实 FF CLI → RF 子进程入口验证。缺失隔离配置未被读取，call/download=0，无 provider/LLM/网络。
- 原 4 类 CLI 交接仅 2 类是 sealed 真实拒绝，另 2 类为 HK 请求派生反例；原 request 与 replay JSON 语义相等，但因序列化字节不同，不能称逐字节重放。4 个原 sealed 文件 SHA 保持。
- 新短 TEMP 已恢复不存在，源码原件未改。

## 剩余范围

真实新 HTTP 预算、历史票据与 SEC115B、逐来源 ledger join、新研究质量、发布和安装均未在此验收执行。旧研究失败状态不变。

完整探针、版本和 exact SHA 见 review.json 与 probe.log。

## 报告收尾工具错误

探针、清理与报告已完成后，生成 manifest 的辅助函数重复添加 Windows 长路径前缀，导致首次命令退出 1。仅修正报告元数据收尾；没有重复探针或修改产品。原 probe.log 保持不变，错误细节保存在 report-finalization-error.json。
