# M3 正式下载 T3 收尾

FF 工区从 `dd7162172718e8276a809e9c205e3c80da06141a` 独立检出。本节点只处理本仓正式下载回归及验收记录。

1. 给 CN、HK、US 实际下载和损坏件的下载请求传完整限额。重复请求走相同入口，保留旧请求版本的兼容覆盖。
2. T3 的隔离 fixture 使用 CWP 当前配置。原 fixture 固定了已退休的 Dayu CLI 和旧版 CN 适配器。测试保留 provider 代码入口，把 catalog、暂存及 provider 状态迁到一次性目录。
3. 运行四个 opt-in T3 和有限请求相关的短回归，记录真实结果、版本、计量与清理，复核后接入本仓规划状态。

## 接口与运行环境

- 固定既有用例的公司、市场及期次。每次有下载意图的 1.1 请求携带 50 MiB、180 秒、零 provider 费用。CWP 当前适配器亦限时 180 秒。重复调用沿用相同请求；损坏件的只读调用单独保留无下载形态。
- 调用仍经 FF 与 CWP 公开 CLI。正式测试的 fixture 读取 CWP 当前配置，保持配置的 provider 命令、版本、接口和期限，临时库拥有 staging、provider-state、catalog 与新原文。断言首次下载的原文字节 SHA 同 sidecar 和 handle 一致，重复调用零下载且原文位置、mtime 不变。
- Windows 本机配置的 Dayu Python 是 Low integrity。宿主 Medium TEMP 创建的目录由同一个 Dayu 进程访问时报告 WinError 5，HTTP 交换数为零；CWP 实际部署的 staging 和 provider-state 均继承 Low。复验沿用已配置 Dayu Python，在 Windows 已有的 Low TEMP 内创建只属于本次测试的子目录，并设置当前进程的 `TMP`、`TEMP`、`TMPDIR`。该进程已经实际成功创建及清理子目录。系统 ACL、标签及 provider 配置保持原样。

## 失败归因与定向回归

| 现象 | 证据及处置 |
|---|---|
| 周跑四项 `ensure exited 1` | FF 下载请求遗漏三项限额。加入限额后已实际进入 provider 与原文校验分支。 |
| 正式夹具的旧配置不适用有界下载 | 旧配置固定了 SID 1.1.0 与 Dayu CLI。夹具跟随 CWP 正式版本和原文 SDK，独立配置状态路径。 |
| CN 有界发现拒绝 | 旧 SID `26704a037f67bf3370fe3be6e77d13529916d543` 的 1.3.0 真报文返回 CN、FY2024、内容 ID `1222806982`，缺证券 ID，严格请求为 `300750`。CWP 公开 ensure 报 `adapter candidate security_id does not match request`，发现 2672 B，费用 0。交由 SID owner 修正候选归属。 |
| HK、US 初轮失败 | `provider_failed / PermissionError`，provider 子进程已经启动，尚未发生 HTTP，响应 0 B，费用 0。复验使用与部署等同的 Low 临时路径。 |
| 损坏件返回信封演进 | 下载模式的 ensure 诊断是 `no_verified_location (content_sha256_mismatch)`，provider 未启动。改验可观察安全行为，保留只读错误、有限 ensure 无 handle、零下载、未覆盖原件和无暂存残留。损坏件单测通过，8.18 秒。 |

相关请求、用量和错误信封回归 102 项通过，2.29 秒，Ruff 通过。首次正式测试及定向诊断的测试目录均验证无残留。

在部署等同的 Low 临时目录中，腾讯 FY2025 与 AMD FY2025 的定向复验均通过，单项耗时 36.112 秒、33.575 秒。两项均包含首轮下载一次、按原件及 sidecar 核验 SHA-256、第二轮零下载、无残留检查。

## 最终正式验收

2026-11-16 23:20:55 UTC 开始。**4 项通过，0 跳过，72.57 秒**。同一次运行的 pytest 报告如下。

| 用例 | 期次 | 结果 | 秒 |
|---|---|---|---:|
| `test_download_cn_annual_report` | CATL FY2024 | 一次 CNINFO 导入及零下载复用通过 | 11.121 |
| `test_download_hk_annual_report` | 腾讯 FY2025 | 一次 HKEX 导入及零下载复用通过 | 37.112 |
| `test_download_rejects_corrupted_local_copy` | 合成 CN FY2024 | 两种模式均拒绝损坏件，provider 未启动且原件未覆盖 | 7.590 |
| `test_download_us_annual_report` | AMD FY2025 | 一次 SEC 导入及零下载复用通过 | 16.526 |

成功用例确认初次下载计数、同一原文位置、mtime、两次响应中的 snapshot SHA-256 和复用后真实原文字节一致，同时核对目录锁和暂存清理。四个用例目录和外层运行目录均已清理，残留数 0。正式验收及定向诊断均使用三家配置的公共原文 provider，未使用收费服务。

| 运行输入 | 验收绑定 |
|---|---|
| FF 基线 | `dd7162172718e8276a809e9c205e3c80da06141a` |
| `tests/test_e2e_download.py` 工作树 SHA-256 | `80b8d9e3b578f496f1c3eaea96360deff5ee11fc230951751efd14cf18003435` |
| `tests/e2e_support/isolated_wiki.py` 工作树 SHA-256 | `a406e184a37ebfff13e4c9f25a55057979e8da4dc7c568d84db3dd951e48037a` |
| CWP | `f5d41d9f471a5ea9ed8dd6dc72abf477da743f7a`，宿主 Python 3.13.9 实际导入该 checkout 的 `src/company_wiki` |
| SID | `fb8c8ba5cf60480b97d6d597e93b37f7c14da9ac`，CNINFO 1.3.0 |
| Dayu | `76037b242d0b14a77281d7bc610429296123c5cb`，配置的 Python 3.14.2，HK/US SDK bridge 1.0.0 |

正式验收的临时 acquisition config 将 CN 的 `project_root` 指向已提交的 SID 候选。其他适配器入口和版本保持实际部署配置。运行前后核对三仓源码引用及已审查 FF 测试文件的实际字节，结果一致。验收未改 CWP 原件、配置或 provider 仓库。

## 复现

从 FF 仓根执行，使用能导入待复验 CWP 版本的宿主 Python。Windows 如采用上述 Low Dayu 解释器，先将当前 shell 的 `TMP`、`TEMP`、`TMPDIR` 指向自己在系统现有 Low TEMP 下新建的空子目录。随后从该 FF checkout 调用真实 opt-in 入口。

```powershell
$env:FILING_FETCH_E2E_DOWNLOAD = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
python -B -m pytest -v -p no:cacheprovider --tb=short tests/test_e2e_download.py
```

用例退出会清理其完整工作目录。外层临时目录应为空，核对后移除。
