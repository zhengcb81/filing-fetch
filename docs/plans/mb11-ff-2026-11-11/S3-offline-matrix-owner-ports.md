# S3/S4 filing-fetch 公开边界整改

基线为远端 `main` 的 `1adea7427675aa64640b6ff7b156d3ff5bc6973a`。总控审计日期为 2026-11-24。运行产物在本次测试自有临时目录，正式工作区的三份既有未提交 PWF 保持原样。

## 问题和实现

- 旧矩阵直接导入 CWP 配置、数据库和 reader 实现，并用 SQL 观察版本和物理原件数量。现在 CWP 批量 SourceExport v2 验证归档原件，二进制 source-reader 精确读回电话会原语言。FF 断言重复调用得到同一 SourceRef、真实发现和下载计数不增加。CWP 本仓 `tests/contract/test_source_catalog_canonical_writer.py::test_writer_deduplicates_downloaded_bytes_without_second_canonical_file` 和 `tests/contract/test_source_catalog_acquisition.py` 验证落盘与去重的内部不变量。老收据继续按它们原先的计数约定复核，本批新结果用 `w06-fresh-source-proofs/2` 标注公开证明。
- W20 已得到 SourceRef 时直接按该引用实读，遗失引用时走公开 source-query 再实读。同一绝对截止内区分已确认、明确未找到和观测失败。导入中断的证据来自合成 ET 回执中的真实供应商原件字节，使用它的 SHA，不误用转录正文 SHA，也不把未完成回执当作明确未落盘。
- ET worker 照常在真实 supervisor 下运行。HTTP fixture 由 FF 持有，支持合成成功、授权失败、限流、公开格式错误、强停和不完整结果。供应商 API、原件目录、真实密钥没有参与。财报 fixture 按公开合同返回 CN/HK/US 的请求证券身份，恢复真实 CWP 发行人校验。已有批量播种仍调用同一已安装入口公开的 command main，通过合成 provider 走真实交易。
- `FilingFetchError` 和路径识别成为可独立装载的接口。原有 import 路径仍识别同一个异常类。跨模块使用校验函数经明确公开命名。没有改变正常输出、下载限额或失败策略。快 CI 执行精确边界测试和冷启动测试，真实多仓矩阵仍显式运行。

## 测试记录

从指定 Git 对象导出 CWP `e3b4a1aff2cceb431abef2fb85faa039ca42bc93` 和 ET `d69448614aa0e02b5059d232b9d981bcee6fc89a` 的源码到隔离目录，ET 导出不含任何 `tests`。ID 固定，只执行公开测试路径。清理收据均表明临时数据和字节缓存恢复，生产元数据无变化，真实网络和翻译尝试均为零。

| 试验 | 结果 | 报告 SHA-256 |
|---|---|---|
| 六个定点组合 | CN/HK 年报下载及归档复用、FMP 402 三项通过。其余三项在两 worker 争用时到 30 秒，保留为 PARTIAL | `4ff4acf832ac0f01c57dc0137886f44186b835c8e0910b6eb50f1edfbebfd9fa` |
| 单 worker 电话会下载和复用 | 业务阶段 18.79 秒，全程 41.34 秒，GET 为 1、0，公开原件证明完整，oracle 零项 | `c2e3be01244f9f7defc3a9395a2e6c497a471900f46c5e9e9cb0758a22b68a67` |
| 单 worker 丢失成功答复后恢复 | 业务阶段 23.12 秒，全程 33.27 秒，原件已确认，GET 为 1、0、0，oracle 零项 | `9171e0df5503db641e160b6c66cecccd9339e803641d71f5902f9f2045409a68` |
| 单 worker 导入阶段中断后恢复 | 业务阶段 22.98 秒，全程 34.65 秒，公开查询确认未落盘，随后重新取得一次并复用，GET 为 1、1、0，oracle 零项 | `a0dea7737510a46d5bb8714c2749a9d7f39e731b83635628b2b55dfcf68f094b` |

三项单 worker 的业务阶段距离 30 秒分别余 11.21、6.88 和 7.02 秒。两 worker 的三项超时仍有价值，说明当前主机并行负载会压缩余量。没有调高窗口。普通发布前 `python -B tools/ci_tests.py` 1067 项通过、46 个子检查通过。两个原有 skip 对应无生产身份快照和 Windows symlink。Ruff、两个公开契约的 mypy 检查和 `git diff --check` 也通过。独立复核重跑 27 项通过。CWP 上游 `476963a4e` 关闭负责测试的只读连接，38 项储存合同和独立真实锁重试复验通过。

### 全 41 例复现

在本仓执行，指定可用的 CWP 和 ET 代码根、两个独立的新临时根。ET 的项目测试文件可以不安装。

```powershell
python -B tools/offline_contract_matrix/run.py `
  --cwp-project <CWP源码目录> `
  --et-project <ET源码目录> `
  --owned-root <新测试数据目录> `
  --out-root <新报告目录>
```

完整报告应为 41 个 PASS，oracle 无发现，`restore.restored=true`。单个用例超过 30 秒或整体达到 180 秒应如实保留 PARTIAL。先单独诊断慢例和宿主争用；选择性报告不构成全量验收。


目前不签收全 41 例矩阵。S3 后续生产拆分还包括 identity client 的传输分离、job feedback 与 runner 的反向调用、顶层 CLI 渐进拆分。后续变更沿各自原始请求和复用行为测试进行。
