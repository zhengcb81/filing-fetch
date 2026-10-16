# 独立质量审查（final pass）

审查者：独立 agent（非本卡作者上下文），在实现与交接完成后执行；自行从
[construction_card.md](construction_card.md) / [INTERFACES.md](INTERFACES.md) 推导验收要求，
再逐条对交付物核查，并独立重算所有 SHA/计数、独立重跑测试与 Ruff。

**结论：PASS — 可交 ROOT 接收。** 无接口漂移、无输入改动、无回落路径、无历史结论升级、无白名单越界；
交付物中每个实质性数字都与提交字节一致（唯一例外是审查者指出的两处计数口径/语义瑕疵，均已修正）。

## 独立重算核对（不信任文字）

- 基线 `e2efa81` 的 `audit()` 真身在历史 fixture 上产出 65 条 findings、规范指纹 `417a7891…64e30`，
  且基线拒绝 `evidence_root` kwarg（TypeError）——与 RED 收据一致。
- 4 个改动文件 SHA/字节数、chain report `6e2705f3…`/869196、历史 fixture `aa2ab10a…`、
  CWP/ET 固定 commit 与 8 个模块 SHA、38/0/1/2 计数、5 条 findings、174.565s、248 测试 = 旧 213 + 新 35
  （collect-only 核对旧测试集合）、保留证据 1,494,302 字节：全部复算一致。
- 独立走查 chain-report 的 167 个被绑定文件 vs `evidence/artifacts`：0 处 hash 不符。
- 提交到 git 的证据字节与 worktree/SHA 声明一致（271/271）；tampered 样本 = 原文件 + 恰好 1 字节。
- 独立重跑集中命令：245 passed（审查时点）；Ruff 干净——与收据相符。

## 发现项与处置

| # | 严重度 | 发现 | 处置 |
|---|---|---|---|
| 1 | 低-中 | `receipts/08-evidence-byte-fidelity.txt` 未提交、未被交接引用 | **已修**：随本次 commit 提交并在 handoff.json/handoff.md 引用 |
| 2 | 低 | handoff.json 引用的 `handoff-review.md` 当时不存在 | **已修**：本文件即该审查记录，verdict 回填 handoff.json |
| 3 | 低 | “Ruff clean” 声明只引 pytest 收据 | **已修**：Ruff 命令+输出并入 `receipts/02-centralized-regression.txt` |
| 4 | 低 | `receipts/07` 的 165 与审查者的 167 口径不一致 | **已修**：`receipts/07` 追加口径对账（165 = oracle 实际校验的绑定；167 = 全部被 trace 命中的文件，含 2 个 `et_fixture_requests==0` 的 ET receipt；两口径 0 不符） |
| 5 | 低 | handoff.json `tests[2].skipped=3` 把 1 PARTIAL + 2 NOT_RUN 记成 skipped | **已修**：改为 `skipped: 0`，明细写进 note |
| 6 | 低 | replay 认证门缺 duplicate/unknown case 行的显式测试 | **已修**：新增 3 条参数化测试（duplicate/unknown/removed） |
| 7 | nit | replay 输出写入非原子 | **已修**：staging 文件 + rename，输出路径永不留半份记录（并有测试断言） |
| 8 | nit | `PYTHONDONTWRITEBYTECODE` / `REVENUE_PUBLICATION_REGISTRY` 未见于收据 | **已修**：`receipts/06` 追加运行环境记录 |
| 9 | info | 分支比任务多一个 `c35ea52` PWF 种子 commit | 接受：ROOT 启动记录，只动本线文档，白名单合规 |

## 复核后的最终状态

- 集中回归 **248 passed**（旧 213 未动 + 新 35），Ruff 干净；见 `receipts/02-centralized-regression.txt`。
- 实现 commit `2509810…`、审查修复 commit `ee11e07…`；本文件与收据随交接 commit 提交。
- 三个大节点收据齐全：RED（`01`）、集中结果（`02`）、真实CLI/搬迁/清理（`03`–`08`）。
