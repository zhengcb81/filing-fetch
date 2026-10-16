# DU6-FF-PORTABLE-EVIDENCE

状态：DONE；2026-10-16。工区 `C:/Users/郑曾波/Projects/filing-fetch-du6-portable`。

分支 `codex/du6-ff-portable-20261016`；源码基线 `e2efa81d7995836d457479eb528fa6f8cd5dc3f3`，另外只有启动PWF种子。

先读[施工卡](construction_card.md)和[接口](INTERFACES.md)。本卡可现在独立启动，不等待 ROOT v4 或另外两卡。

## A：接口与行为RED

Status: done

`tests/test_du6_portable_matrix_evidence.py` 先冻结旧行为（旧默认 findings 指纹 417a7891…/65条、旧 audit 不改输入、旧矩阵 argv 分派不变，3条已绿），
再列 2 条接口 RED（`audit` 无 `evidence_root`、CLI 无 `replay` 分支）与行为 RED（搬迁保持字节、旧根不可用不回落、篡改/升级拒绝）。
收据 `receipts/01-red-first.txt`（3 passed / 29 failed，全部归因于缺失接口本身，未把缺API当生产缺陷）。

## B：共同责任实现和集中回归

Status: done

只接两处：`oracle.audit(report, *, evidence_root=None)` → 同一 `_bound_evidence`（仅换相对引用读取根），
`cli_main.main` 显式 `replay` 分派 + `ff-matrix-evidence-replay/1` 小记录。旧默认/旧argv/旧金标未改。
集中命令 245 passed（含新32条），Ruff 只查改动源与新测试通过。收据 `receipts/02-centralized-regression.txt`。

## C：实际CLI、清理与交付

Status: done

真实41链一次（pinned CWP `f08aa101…` / ET `d0ac42c6…`，离线 fixture 边界，0 真实供应商/LLM/翻译）：
38 PASS / 0 FAIL / 1 PARTIAL / 2 NOT_RUN / 174.57s（180s 批预算 + 10s proof reserve 保全，超时属宿主负载差异，未重跑求绿、未改 expected/timeout）。
随后搬迁重放 5 步全通：跨空格+中文目录复制后重放、原根不可用不回落、override 缺失不回落旧根（exit 2）、单字节篡改产原生 SHA Finding、历史失败 fixture findings 逐条保留。
独立手算 21/21 PASS（`receipts/07-independent-quality-check.txt`），隔离/清理 `receipts/06-cleanup-receipt.txt`（保留证据 1,494,302 字节，OWNED_TEMP 只剩 sentinel）。
正常 commit 后 handoff.md/json，STOP，不并主线或安装。

## Next Step

STOP 等 ROOT 验收并线；本线不再施工。真实41链的 PARTIAL/NOT_RUN 三点是批期限证据，已在 handoff `not_run`/`known_limits` 具名交 ROOT。

## 固定只读联调依赖

- `C:/Users/郑曾波/Projects/company-wiki-du6-ff-readonly` @ `f08aa101ab49ca983d3a40356abfb05347f586b3`；只读，禁止改源码/Git。
- `C:/Users/郑曾波/Projects/earnings-transcripts-du6-ff-readonly` @ `d0ac42c60dcca992db78860b8469cfed3dd527e5`；只读，禁止改源码/Git。
