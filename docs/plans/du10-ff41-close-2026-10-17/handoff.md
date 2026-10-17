# DU10-FF41-CLOSE 交接 — COMPLETE

固定 41 例端到端矩阵已在本卡关闭：**C-1 完整实跑 41/41 PASS（97.6772s / 180s，oracle 0 findings）**，
**恢复行为（受控中断→重启→继续→清理）E2E 通过（v3，12/12 检查含硬化门槛）**，
独立最终审查两轮后 **VERDICT: APPROVE，零未解决问题**。本文是交接总纲；机器可读版 `handoff.json`。

## 1. 冻结与提交

- 分支：`codex/du10-ff41-close`；基线 `c7c8867da35cd19d4f419fa70947332615e8e9c0`（main）。
- 提交链：`bb60678`（实现：seed 子集化 + 新测试 + PWF/证据）→ `cb7e2fb`/`af3f7a1`（会话中断交接文档）
  → `22ef5a1`（独审 findings 修复：恢复门槛硬化 + SHA 实值 + 计数更正）→ 本 handoff 提交（最终 HEAD，STOP）。
- 独立审查所审 SHA：`af3f7a14486d83ac6c3a3f63cbfad427e200ccd9`（第一轮）与
  `22ef5a14e8b72d840608282e3ed413322cbaa6b2`（第二轮复核）；报告原样存档
  `receipts/independent-review-round1.md`、`receipts/independent-review-round2.md`。

## 2. 精确 41 例结果（C-1，一次完整实跑）

命令（exit 0）：

```
python -B tools/offline_contract_matrix/run.py \
  --cwp-project C:/Users/郑曾波/Projects/.du10-deps/cwp \
  --et-project  C:/Users/郑曾波/Projects/.du10-deps/et \
  --owned-root  C:/Users/郑曾波/Projects/.du10-tmp/final-owned \
  --out-root    C:/Users/郑曾波/Projects/.du10-tmp/final-out --workers 2
```

- **41/41 PASS**（FAIL 0 / PARTIAL 0 / NOT_RUN 0），batch 97.6772s ≤ 180s，最长 case 10.4227s ≤ 30s；
  oracle `pass=true, findings=[]`；`restore.restored=true`；`stop_reason=null`；
  guard：boots>0、denied 0、translation 0（无真实网络/翻译）。
- 逐 case 结果与耗时：`receipts/final-run.json`（41 条明细）；
  报告 SHA `a0dd3c1a7af32f66000b92e074e69520f7aaa64550b98993af0552b4d18d83da`（删除前终验一致，见 `receipts/cleanup.json`）。
- 阶段：binding 3.5084 / seed 14.2489（子集化后；基线 26.9168）/ ff_cli 151.7909（52 spans）/
  fresh_source_proof 1.6241 / cleanup 0.3385。
- 预算未动：case≤30s、batch≤180s、workers≤2、proof reserve 10s；41 CaseSpec 与 oracle 零改动。

## 3. 恢复结果（C-2，v3 权威、v2 保留、v1 历史）

- **v3（`receipts/interruption-restart-v3.json`，du10-interruption-restart/2）passed=True，12/12**：
  中断腿 chainA run1 在途（0→1 GET 观察）→ 进程树回收 → 无 report 伪装；重启腿 144.542s **exit 0、
  41/41 PASS、oracle 0 findings**；新唯一 attempt、被杀残留全量 SHA 前后一致、
  **sentinel/既有条目前后 SHA 实值相等**（`sha_pairs`）、临时树移除。
- v2（`receipts/interruption-restart-v2.json`）passed=False 保留：其重启腿在负载下退化为 40/1，
  硬门槛 `leg2_completed_clean`/`restart_all_41_pass` 如设计 fail-closed——门槛非恒真的反向证据。
- v1（`receipts/interruption-restart.json`，旧门槛）保留为历史；缺口已在 findings A.10-11 记录。

## 4. 测试与清理

- 受影响测试（11 文件）**329 passed**（作者 52.24s / 独审 54.85s 两次独立实测）；
  复核轮 42/42（42 passed 7.07s）。新回归 `tests/test_du10_ff41_rootcause.py` 5 项
  （2 个行为级 RED + 1 API + 2 守卫）。
- 临时目录清理：`C:/Users/郑曾波/Projects/.du10-tmp` 全部移除；`receipts/cleanup.json` 记录
  删除前文件计数、三份报告删除前终验 SHA、FMP key stat 前后（内容从未读取）、主树状态
  （仅 untracked 密钥文件，元数据不变）。sentinel 前后 SHA 见 v3 `sha_pairs`。
- `C:/Users/郑曾波/Projects/.du10-deps` 依赖快照保留（可按 NEXT_HANDOFF.md 的
  `git -c core.autocrlf=false archive` 配方重建）。

## 5. 固定依赖

- CWP `900dbf6489f3b995a0bfb7fcbb8a001a68df241d`、ET `7d06777e250ee3f7ae58f0be2cee62944bd2c104`
  （只读快照，测试前后记录：`receipts/dependency-record.json`；字节核验 `dependency-postcheck.json`
  53 样本全匹配；EOL 等价 `dependency-eol-equivalence.json` 60 样本；独审另抽 8/8 MATCH）。
  CWP 主仓 HEAD 已漂移（29cedac），固定快照是唯一实跑输入。

## 6. Finding 修复映射

| 来源 Finding | 修复 |
|---|---|
| DU8：完整矩阵 20 PASS/4 PARTIAL/17 NOT_RUN（启动路径重复准备 × 机器负载） | 每组 warm-seed 按冻结 CaseSpec 消费推导子集（g1=5、g2=6+TXT，union=全量）；seed 26.92→14.25s；C-1 在安静窗口 41/41（负载敏感性同日三态实证，findings A.7） |
| DU8：中断后重启恢复 NOT_RUN | C-2 v1/v3 E2E：中断→回收→新唯一 attempt 重启完成→清理，全过 |
| DU8：`call_hard_timeout` 具名 OPEN（1s deadline 负载敏感） | C-1 与 v3 重启腿均 PASS；v2 负载窗口出现 1 个未名 PARTIAL（当时脚本未记名，v3 起 `restart_non_pass_cases` 记名） |
| 独审 R1 [P2] sentinel 前后 SHA 实值缺失 | fixture v2+ `sha_pairs` 实值入收据，v2/v3 重跑 |
| 独审 R1 [P2] 恢复门槛可被降级重启通过 | 硬门槛 `leg2_completed_clean`+`restart_all_41_pass`，无排除项；v2 拦截/v3 通过双向验证 |
| 独审 R1 [P3] 测试计数不实 | findings A.9 更正（329；旧 185 系三文件批次计数） |
| 独审 R1 [P3] 收据互覆/残留抽样 | warm-seed-receipts 按组前缀；残留全量 per-file SHA |

## 7. 范围声明（不越权）

本卡证明的是**工程联调覆盖**：固定 41 例在离线 fixture 边界（FF→ET→CWP 真实代码链，
仅供应商响应为 fixture）下的合同矩阵与恢复语义。**不证明**真实供应商可达性/覆盖、
不证明任何公司/财报数字质量、不构成 CI 每 commit 门（矩阵仅大节点手动运行）。
未知用量/费用保持 null，未吞没任何 provider 副作用。
