# FF T3 验收收据 owner 路径

基线为 FF `711db1c1bd2d1eda56c6de8edbcc692f86ad4680`。RF 的既有周跑直接启动本仓内部 pytest，最近失败记录是 `20261122T083603Z`。调用方需要通过已记录的原运行读回四项结果。此次只交付 FF 端的执行与收据，RF 消费和 Windows 任务仍分别验收。

## 接口与职责

- `python -B scripts/ff_t3_receipt.py --receipts-dir DIR get --run-id ID`。只读一个原运行。也可用 `get --latest` 按原始登记开始时间选最近一次。序号由登记时间及稳定 ID 生成，读取和修改时间都不改变顺序。没有收据返回 `state=missing`、退出码 2，目录也不创建。找到的收据退出 0，包括失败或不明。最新收据损坏时查回 unknown。读取已经失联的运行投影 `unknown`，保留已经完成的部分用例。
- `python -B scripts/ff_t3_receipt.py --receipts-dir DIR run-live --run-id ID`。FF owner 显式执行，封存同一 ID 后在一个进程执行原 `DownloadE2E` 的现有四项，按每项运行和清理结束的标准 unittest 事件登记。真实三市场套件配置、50 MiB、180 秒及 provider 费用上限沿用原用例。给定相同 ID 再请求执行时返回原结果或其运行状态。只有真实四项都通过时执行命令退出 0。有确定失败时退出 1。阻塞、不明、缺项或仅离线实证退出 2。读者不会启动新处理。
- JSON 为 `ff-t3-assurance/1`。包含 `run_id`、`owner_revision`、`mode`、`state`、`completed_at` 和按 `cn_annual`、`hk_annual`、`us_annual`、`corrupt_original` 标识的 `cases`。每项保留 `outcome`、`reason` 和已证明结果的 `evidence_ref`。用例的序号不会入语义。执行不完整或缺少用例保留已收到部分，并给 blocked 和原因，不生成成功结果。
- 声明 `live` 的唯一 CLI 写入口绑定现有的 native 套件。测试注入的执行器登记为 `offline`。受测试主机缺工具时原用例 skip，被写为 blocked。已有的真实收据、使用费用及旧 RF 台账仍按各 owner 规则读取。该申明不替代单个下载作业的实际费用回告。
- 保持收据单一 owner 存储。原子写和文件锁沿用 FF 持久化库。失败的栈与行号沿用 FF 已有脱敏诊断，保存在 owner 收据并绑定用例的稳定引用。公开查询可在原用例返回已有 FF 类型的脱敏 cause，保留错误类型、行号和安全原因。早期任意附加诊断只留 owner，已有多余键不妨碍完整用例。
- CLI 默认写 `.ff_t3_assurance/`。消费端用自己部署所知的明确 owner 目录或默认值。破损/无法读取的旧收据视为 unknown，继续对应原 run ID。

## 验收

在独立临时根用合成执行器验证四项成功、不等价的同数目用例、真实子进程退出后的部分记录、重复读和重复请求不再执行、历史诊断兼容及清理阶段失败。通过独审后再按发布版本为 RF 接收；RF 可用公开 get 读原结果并核对实跑标记和四项结果。此次累计实际 provider 请求、费用和 Windows 任务登记均为零。实跑与上线按原 M3 真实边界另行验收。

作者定向合计 79 项通过，4 项真实用例按配置关闭，8 项子测试通过。冻结指纹为 17731a5923f9b8325ee1ed96ca19d43c391fde4785355e09a31764a4b8973c03。Ruff、mypy、Git diff 校验通过。独立审查重跑 14 项通过并 ACCEPT。公开目录 cold get 核对原部分结果和错误类型/行号，原时间和文件内容未改。各项临时状态已清理。
