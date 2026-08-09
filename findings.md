# 研究发现 — filing-fetch 审查（2026-08-01）

## 架构结论
- filing-fetch 是 company-wiki CLI 的瘦客户端：identify → resolve（复用，默认）/ ensure（下载，需 --allow-download）
- 两模块：scripts/fetch_filing.py（CLI+编排，501 行）+ scripts/filing_contracts.py（校验，154 行）
- 信任边界：身份/目录/路由/下载/落盘归 company-wiki；请求校验/授权/上游兼容/handle 深校验归 filing-fetch
- 调用形状：`python -m company_wiki.source_catalog.cli --config <abs> identify|resolve|ensure`，
  cwd=wiki_root（但绝对 --config 时 cwd 不参与解析）；成功=stdout 单行 JSON+退出 0；
  失败=stderr JSON `{status:"failed",error_type,error}`+退出 1（company-wiki cli.py:803-816）

## 上游契约核实（company-wiki 实测，探索代理验证）
- identify（cli.py:195-203）：--query/--market/--exchange；恒退出 0；输出
  {schema_version:"1.0",status:resolved|ambiguous|conflict|missing,resolved:{…}|null,candidates,reason}
- resolve/ensure --entity 模式（filing-fetch 所用）：
  - resolve 输出扁平 ResolutionResult{schema_version:"1.0",request_id,status,reason,matches[]}（resolver.py:256-265）
  - ensure 输出含 resolution 嵌套键（acquisition_service.py:43-53）→ 与 fetch_filing.py:400 吻合
  - status 枚举：reused_exact|reused_equivalent|ambiguous|missing|identity_conflict
- matches handle 无 request_id（在 ResolutionResult 上）→ filing-fetch 自行注入（fetch_filing.py:416），脆弱但可用
- 锁：CatalogOperationLockedError 有结构化 error_type；锁文件 <catalog_dir>/operation.lock（O_CREAT|O_EXCL）；
  测试可 import company_wiki.source_catalog.lock.CatalogOperationLock 主动持锁
- worker 暂停：状态在 <catalog_dir>/worker_control.json（desired_state:paused）；
  ensure --allow-download 时抛 RuntimeError("source acquisition is paused; ...")（cli.py:655-661），**无专属 error_type**
- 下载路由：CN→StockInfoDLSimple/v2-clean-rewrite（json_command_v1，stdin JSON）；
  HK/US→dayu-agent venv（dayu_cli_v1）；两外部项目本机均存在且入口可 import（已实测）
- 落盘：唯一 company_raw root 下 <Entity>/raw/financial_reports/{annual|semi_annual|quarterly}/ 等映射子目录
  （canonical_writer.py:90-101），**非** SKILL.md 字面的 raw/{kind}/
- 实体目录名：_safe_component 去首尾空格和点（"Apple Inc."→"Apple Inc"）；
  匹配=目录名 casefold 全等 或 sidecar 顶层 ticker/security_id/company_name（resolver.py:513-529）
- capture_ready 四条件（resolver.py:563-578）：https source_url、published_date、snapshot_sha256、
  capture_trace(retrieved_at+collector_name+collector_version)；scan 自动补 hash/capture_trace；
  旧格式 sidecar 唯一可能缺 https_url（source_url 非 https 时 capture_ready=False）
- as_of_date < published_date → future_matches → MISSING（resolver.py:405-411）
- identify 离线可用：security_master 快照在 <catalog_dir>/security_master/{cn,hk,us}.json；
  复制生产快照到临时实例即可；不传 --refresh 无网络
- 隔离实例：config 必须放 <tmp>/config/source_catalog.yaml（project_root=config 上两级）；
  source_catalog.yaml 顶层键必须恰好 {schema_version,catalog_dir,roots}；单 company_raw root 是 writer 硬要求

## 缺陷清单
| # | 严重度 | 位置 | 问题 |
|---|--------|------|------|
| D1 | 高 | filing_contracts.py:43-46 + fetch_filing.py 全局 | 错误分类漂移：SKILL.md 承诺 config_error/identity_error/not_found/worker_paused 从未产生；全部归为 fatal。worker_paused 在 retryable 集合中是死代码 |
| D2 | 高 | filing_contracts.py:75-98 | validate_request 未强制 company_query（SKILL.md 声明必填）；缺失时以 fatal 而非 request_error 报错；fetch_filing.py:345-350 恒真/死分支；_identity_arguments:158-161 冲突检查不可达 |
| D3 | 中 | fetch_filing.py:394-402 | resolve/ensure 响应 schema_version 从未校验；SUPPORTED_COMPANY_WIKI_CONTRACTS 死常量 |
| D4 | 低 | fetch_filing.py:324 | resolve_filing 未查 math.isfinite(timeout_seconds)（CLI 查了，API 层没查） |
| D5 | 高 | fetch_filing.py:198-213 | worker 暂停（上游 RuntimeError+"paused"）被归为 fatal 不可重试；SKILL.md:116 的承诺无法兑现 |
| D6 | 高 | tests/test_real_tool_conformance.py 全文 | 测的是 filing-fetch 从不调用的 --company-query 原子模式；2 个 skip 掩盖过期期望（"download_blocked" 不存在、identity status 无 "failed"、错误路径读 stdout 实为 stderr）；硬编码 wiki 路径 |
| D7 | 低 | SKILL.md:22, 105 | raw/{kind}/ 路径模板与实际映射子目录不符 |
| D8 | 低 | SKILL.md:98-102 | 退出码表未覆盖 upstream_error/catalog_locked 耗尽/worker_paused（实际也走 exit 2） |
| D9 | 低 | filing_contracts.py:19-20 | GAP_RECEIPT_SCHEMA_VERSION / DOWNLOAD_AUTHORIZATION_SCHEMA_VERSION 死常量 |
| D10 | 低 | 仓库根目录 | 垃圾文件 `nul`（Windows 重定向事故产物，0 字节） |
| D11 | 低 | tests/test_fetch_filing.py | 两对重复测试；test_main_fatal_error_exit_code 名不符实（实为成功路径） |
| D12 | 中 | fetch_filing.py:452-457 | --request-file/stdin 解析失败 → exit 1 fatal，应为 request_error/exit 2 |
| D13 | 中 | filing_contracts.py:113-116 | request_id 无非空校验（resolution 缺时注入 None 可通过） |
| D14 | 中 | filing_contracts.py:75-98 | market hint 无白名单校验；非法值漏到上游 argparse 退出 2 → 映射 fatal 且信息混乱 |
| D15 | 观察项 | company-wiki 侧 | canonical_name 与目录名不一致时（如官方名 vs 目录 "AMD"）可能 reuse miss→重复下载；filing-fetch 无法独修，E2E 场景 2 提供观测 |

## 现有测试盘点
- 66 通过（60 mock patch subprocess.run + 6 live，2 skip），~32s；覆盖声称 90%
- mock 层从未真实验证：进程参数序列化、cwd/env、PYTHONUTF8、CREATE_NO_WINDOW、超时传播、重试循环、退出码
- 已有：CN（中微公司）/HK（小米）/US（AMD）mock 身份验证；not_found/ambiguous/hash 损坏/路径逃逸/未来日期等单点
- 缺失：Phase 2 §2.1-2.5 全部边界；真实 E2E（Phase 3/4）从零建设
