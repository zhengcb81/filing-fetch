# W06-FF-MATRIX：真实三层代码的离线联调和文档矩阵

**可独立开工，不等 ROOT/W05。** 工作目录 C:/Users/郑曾波/Projects/_harness_worktrees/w06/ff-contract-matrix；分支 codex/w06-ff-contract-matrix；FF基线 08ec85b27133cdf8a8d3b38fdba15255fc1ebac2。本线 PWF .planning/w06-ff-matrix/，输入 docs/handoffs/w06-ff-matrix/input/。读 FF SKILL.md/真实 argv、既有 isolated_wiki/ET与CWP金样测试，以及输入记录的精确 ET/CWP 源代码。

## 目标和已有能力

已有 tests/test_et_s0b_contract.py、test_cwp_s0b_source_ref_contract.py 证明 frozen producer fixture 消费，并未单凭它们证明一次真正 FF 调 ET、ET raw 入 CWP、随后复用。isolated_wiki 已有三市场财报复用/缺口能力，不重写。建设一个显式手动运行、完全独立临时状态的跨仓套件，加文档类型覆盖图。产品源码只读，发现共因交 ROOT，不抢公共适配器。

固定依赖：CWP 01ea86a37edb5506d6269b6e10d9cb56a1270efd；ET c91f5f54bc2a24e7b5d6e648dba3f9d578f5fa52。后续 ROOT 修复后 runner 可显式传新路径，报告同时记录实际 HEAD/模块 __file__/SHA，不能凭装有包就认定跑了指定版本。

## 排他写集

- 新 tools/offline_contract_matrix/（runner、README、fixture builder、测试代理）。
- 新 tests/test_w06_contract_matrix.py、tests/fixtures/w06_contract_matrix/。
- 本线 PWF 与 docs/handoffs/w06-ff-matrix/。

FF scripts/、旧 tests/e2e_support、既有金样、CI/gate/config 全只读；ET/CWP/StockWiki/RF/Dayu/IQS 零写。用户 config/FMP_API_KEY.txt 不读/复制/提交。输入固定的代码可在 owned scratch 建必要只读快照（使用 git show/archive 的已提交内容，不复制 ignored 原件/环境配置），不修改 producer。没有新provider，不开真实 HTTP。

## 输入输出和调用层级

runner 命令 `python -B tools/offline_contract_matrix/run.py --cwp-project <explicit-code-root> --et-project <explicit-code-root> --owned-root <new-root> --out-root <new-attempt-root>`。顶层 report schema ff-et-cwp-offline-matrix/1，逐 case 列 declared/observed layer、实际模块/HEAD/SHA、request/response/receipt refs、provider call counters、下载与 translation 次数、expected/actual/PASS|FAIL|NOT_RUN、scope 和恢复信息。

**链 A 必须真三层：** FF scripts/fetch_filing.py 公开入口 → scripts/transcript_tool_transport.py:EarningsTranscriptsTransport → ET transcript_tool.main → 真实 retrieval supervisor/worker/transcript_api（只替换 worker HTTP 的既有 private launcher）→ FF 真实 import → CWP 原文注册 → SourceVersionReader.open_version 实读 → 再次 FF 同请求命中。不能 mock整个 ET stdout、import 成功 response 或 CWP SourceRef 后称三层通过。

不要直接使用 existing IsolatedWiki 的 editable/prod fallback：runner 显式将 supplied CWP src 加入 child PYTHONPATH，工作 cwd 和所有 CLI config 都指向 scratch；先 child import 打印实际 company_wiki.__file__ 并验代码范围/SHA，再执行。FF 使用 --config 指向 owned 临时 company_wiki.json，其中 company_wiki_root=fixture root，schema/paths/ET入口等按真实 load_company_wiki_root/help 字段构造；不能把 --cwp-project 当作生产数据根。ET 代码快照也只在 scratch 执行，fake launcher 保持测试代理层，source 配置入口拒绝落在生产根。

ET 已有 tests/test_retrieval_cli_e2e.py/private retrieval launcher；允许新增 FF owned 测试代理调用该 seam，不加生产 CLI flag、不修改 site-packages。需要代码快照则记录 exact SHA；测试 proxy 输出才标 test-proxy，不能称未经代理生产二进制。所有网络出口拒绝，子进程只给最小合成环境，FMP_KEY 是固定假值，TranslatorFactory 构造 spy=0。工作 cwd/config/raw/AUTO/catalog 全在 scratch。

提供 valid 小 PDF/HTML/TXT synthetic 原件而非伪造 `%PDF ...` 占位，元数据明确 synthetic。ET 响应 content 是原语言，CRLF→LF 等既有 canonicalization允许但记 provider_payload/canonical 两 SHA；不翻译。第一次 1 fixture provider request、第二次0，CWP只一个对应来源版本、不重下载/重复持久正文。真实收费0；fixture requests单列不能进入母账。

## 必须覆盖的矩阵

1. CN/HK/US 周期财报：annual/semi_annual/quarterly local hit；无本地 fetch_if_missing 用配置的 fixture provider 边界，reuse_only不获取。只模拟供应商响应，执行真实 CWP ensure/import，不替换整服务。
2. 非周期 prospectus/equity_offering_prospectus/convertible_bond_prospectus/investor_relations：按当前真实 request 能力列支持/不支持；支持者从正确工具/类入库，不能冒 annual/FY。一项不支持就如实具名 gap，**不能为凑矩阵自己加 provider 或改合同**，ROOT决定修复。
3. US call exact FY/Q：local TXT命中0请求；local miss ET fixture下载原语言；正确季度；FY-only不猜Q4；过 cutoff/unknown publication 分别给实际诊断，不能假 historical eligible。电话会和财报分别计结果，财报成功不代表电话会成功。
4. 请求错误、错symbol/quarter、坏SHA、错误mime/超字节、ET 402 entitlement、凭证缺失、未知费用、有调用后失败与重复请求。旧完整 receipts保留；unknown cost为null，不能错误归0/吞调用。
5. 生产配置/原始 ignored 文件初末无写；文件下载到配置的公司根，不写ET生产 transcripts/ 或把path塞进消费者SourceRef；所有HTTP≤0，translation=0。

离线合成未证明外网可达、真实供应商完整、实际经济质量。格式/payload schema用实际producer代码和现有已验golden，不照抄旧26字段宣称新版本也同样；contract changes具名写diagnostic。

## 三个大节点

A：记录旧覆盖矩阵/固定入口。先写 runner oracle 的失败向量：整层fake却写real、第二次仍下载、少ET receipt、错cutoff、假0cost、未恢复scratch。给可调用 stub 保存行为RED，不能把初次缺文件当生产故障。

B：实现小fixture/计数器和 runner，复用旧 helper；单元 `python -B -m pytest -q tests/test_w06_contract_matrix.py`。至少一次 FF真实公开CLI请求和一次ET真实supervisor子进程；其它 helper级case逐条准确标层级。不重复抄全部645旧测试或把慢包自动接CI。

C：新 scratch（≤64MiB必要代码snapshot另计）跑手动 runner 一次；每case超时（建议≤30s）、批次整体≤180s，失败保留partial；无固定sleep几十秒。保存小型报告/精确日志，关闭worker/SQLite，恢复预置sentinel及baseline，第二次执行使用新attempt不覆第一次。工具正确但产品失败为 PARTIAL，保留固定 assertions与raw回放，给 ROOT 最小根因/接缝。

最终按 input/handoff_contract.md 普通commit交报告与manifest。ROOT并线前用其最终代码重跑真三层关键路径，再接新版本；worker不重置其他worktree、不push主线/安装、不修改API配置。
