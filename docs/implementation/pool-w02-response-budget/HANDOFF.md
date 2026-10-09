# W02 FF单点接线

TDD已完成：两个真实传参反例RED，29现有及新责任测试GREEN，短owned TEMP恢复。operation原始响应额度原值传ET；正文使用现公开10MiB上限，不因合法128MiB总额度报bad_request。仍同一供应商回执，不把actual消费clamp，unknown不写0。两新责任测试加入原精简CI集合。

需要ET交付后用真实FF→ET supervisor/worker（仅HTTP模拟）→CWP入库/读取/复用做一次集中契约联调，当前不是全流程已验。该节点前不发布FF安装，避免旧ET拒绝新字段。base和精确文件SHA见handoff.json。

## MAIN集中联调完成

实际FF→ET supervisor/worker（仅HTTP模拟）→CWP原字节入库/verified open→重复0下载，及20386B响应/1024B额度超限terminal无入库，18检查点通过。发现CWP冗余exactset已责任TDD修复。新增4项post-fetch拒绝/坏ref/open失败RED→GREEN，保留ET已知receipt、不抛失给泛化错误、不建议重下载；33项集中绿，TEMP恢复。原FMP publication unknown保留，没有伪造as-of验证。
