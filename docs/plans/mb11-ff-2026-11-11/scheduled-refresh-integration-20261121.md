# FF 定期更新组合接线

以 `1ab0a94` 的运行状态和作业入口为基线。主线定期更新计划在 company-wiki 的 `docs/plans/scheduled-filing-refresh-2026-11-21`。

## 已完成

- 走 CWP 的公开 discovery、backlog、read 和 status。精确采集核对实际 provider 和 accession。相同键查回原作业，返回不同版本只做对账。
- 已登记电话会以 `investor_call_transcript` 进入阅读积压，外采只接受有证 FY/Q。财报元数据提供方无需支持电话会枚举。
- 正式阅读用量按原 CWP run ID 保存累计快照。重复回读不重复相加，保留未知费用和已知数值。
- 原生安装器按实际 Windows 字节编码读取任务 XML，兼容系统 OEM 和 UTF-16 BOM。创建与删除的诊断留给操作层，公开 stdout 为单一 JSON 收据。

聚焦回归 86 项通过。另有 50 项运行覆盖原生作业与跨进程断点。Ruff、持续集成使用的 mypy 和 Git 差异检查通过。本次代码验收使用隔离目录，未启用正式任务。
