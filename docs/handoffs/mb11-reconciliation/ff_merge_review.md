# FF 明确未知发布日期候选：独立静态接收复核

日期：2026-11-11。审查者：acquisition 子代理，未参与候选移植。结论：**可并线；未发现阻断代码问题。** 结论仅适用于下列三个文件的最终工作树内容与已记录的集中验证，不代表真实供应商采集、字节验证或 as-of availability 已通过。

## 审查对象与绑定

- 候选：`C:/Users/郑曾波/Projects/mb11-ff-null-reconcile`。
- 基线：`f65e6ca75fbce0616e65870f0aea78b793ef883c`。
- 来源：B34 `53285c259b0f0c9ede3f74783f45b6f3a38287b9` 的两处生产逻辑小改动、原19例，以及ROOT追加的4个当前期间/主体反例。
- 最终 diff：3文件、117 additions / 1 deletion。没有其他生产文件、配置、协议版本或依赖变化。

| 文件 | 本次读取的规范化 Git blob |
|---|---|
| `scripts/ff_source_candidate.py` | `13ce660d3ad67ed6558a4a4f2ee4bf3068ea6fb6` |
| `scripts/filing_contracts.py` | `90e94c1582409f5a9615831b1af2476123eeee98` |
| `tests/b34/test_unknown_publication_candidate.py` | `22b830f2b7b9bfb141d54af4e245bd91ffcbb9db` |

审查时第三个文件的状态是 `AM`：原文件已stage，最后4例仍在worktree。ROOT正常提交前应stage最终107行文件，确保提交包含上述测试blob；这是已授权接收的提交完整性要求，无须新增审批。

## 逐项核对

1. **只接受明确的未知值。** `validate_handle_metadata` 的新参数默认 `False`；仅逻辑候选调用处显式传 `True`。分支判定使用 `published is None`，不把空串、字符串`null`、数字或布尔值当未知。`published_date`仍在required集合中，缺字段检查先于`handle.get`执行，因此缺失字段不会被误当null。
2. **不伪造日期或来源可用性。** 代码没有用retrieved_at、当前日期或其他字段补发布日期。已有非null日期继续走相同的ISO校验与as_of上界检查。候选保留null，表示“不能从该字段证明披露时间”，不是“已满足as-of可用性”。
3. **early return没有绕过调用者的绑定。** 新return只结束基础metadata函数，位置在required/type、capture_ready类型、digest/content digest一致、byte_size检查之后。调用者随后仍逐项核对document/source ID、snapshot hash、size、MIME、document kind、FY、form_type与fiscal_period。
4. **当前跨市场来源逻辑完整保留。** metadata返回后仍执行`source_identity`选择、request.source_market与source身份market一致、候选market/security_id匹配、issuer_link_id匹配；研究/展示主体与来源主体不同的情况下，原有source_identity投影未被移除或改写。B34旧文件没有覆盖基线的新逻辑。
5. **候选没有被升级成读件凭证。** 最终仍设置`byte_verified=False`；没有新增文件读取、hash观察、availability或source_read_receipt。原路径泄漏检查在metadata调用之前。合法未知日期只让诚实的逻辑候选到达后续consumer。
6. **默认/legacy行为保持。** 未opt-in的metadata调用继续拒绝null；legacy verified-handle路径仍要求明确日期。该补丁没有改变原件owner、预算、下载策略或provider错误分类。

## 测试审阅与已读收据

本代理没有执行测试、安装、网络、provider或模型调用。已只读核对ROOT保存的文件：

- [ff_red.json](C:/Users/郑曾波/Projects/company-wiki/docs/plans/module-boundaries-2026-11-11/review/repo_reconciliation_20261111/ff_red.json)：绑定上述基线，明确null候选被拒，错误`upstream_error / handle published_date must use YYYY-MM-DD format`。
- [ff_verified_tests.log](C:/Users/郑曾波/Projects/company-wiki/docs/plans/module-boundaries-2026-11-11/review/repo_reconciliation_20261111/ff_verified_tests.log)：ROOT集中组 `176 passed, 2 skipped, 38 subtests passed in 15.24s`。
- [ff_b34_final.log](C:/Users/郑曾波/Projects/company-wiki/docs/plans/module-boundaries-2026-11-11/review/repo_reconciliation_20261111/ff_b34_final.log)：最终B34组 `23 passed in 0.50s`。

这些是ROOT的执行证据，不是本审查者独立重跑的结果。测试源检查确认：query/ensure两个公开路径在禁止`Path.read_bytes`的控制下接受null，保留retrieved_at、不增加downloads、不产生availability/receipt；缺失、错误/未来日期及默认/legacy严格行为有反例；原7个ref/scope/path反例保留。新4例分别改变form_type、fiscal_period、market、issuer_link_id；其其他fixture字段匹配当前绑定，未见由无关fixture错误产生假阳性的路径。

## 接收边界

允许将上述三文件作为一个小型FF修复接收；无需整支合入旧B34 handoff或覆盖当前源码，也不需要追加真实采集来证明这个纯候选合同变化。最终提交应包含已审的4个新增反例。

该修复不保证未知发布日期来源可用于特定as-of研究；consumer仍按自己的availability合同处理未知。它也没有证明原始字节存在、可信、通过解析或可用于投资结论。CWP的verified-open/来源owner职责、FF候选投影和下游研究职责保持原边界。未发现需另开模块卡的问题；并线后原MB-FF A0的B34项可标为已吸收，其余隔离合同工作仍按原卡执行。
