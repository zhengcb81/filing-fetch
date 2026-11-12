# A0 归档后交 ROOT 的回收清单（建议，不由作者执行）

作者只做了只读复制归档，未修改、未 reset、未删除下列任何旧工区文件/分支。ROOT 核对本目录归档与 manifest 后，可按既有流程决定是否回收：

| 来源 | 原路径 | 归档位置 | 说明 |
|---|---|---|---|
| 旧 job 协议差量 | `C:/Users/郑曾波/Projects/_harness_worktrees/dashboard-ff-job-20261109/docs/ff-job-protocol.md`（1 项 M） | `job-protocol/ff-job-protocol.md` + `.dirty.diff` | 两处语义已被 `57351d0` 吸收；其余 6 个重复源码/测试已 restore。归档后该 dirty 可精准回收，旧 ref 不在本卡范围。 |
| W06 过期 PWF | `…/_harness_worktrees/w06/ff-contract-matrix/.planning/w06-ff-matrix/{task_plan,progress}.md`（2 项 M） | `w06/task_plan.md`、`progress.md`、`pwf.dirty.diff` | 旧"complete/16PASS"声明不得覆盖 ROOT 后续 41-case 证据；只留出处。 |
| W06 六份输入 | `…/w06/ff-contract-matrix/docs/handoffs/w06-ff-matrix/input/**`（6 untracked） | `w06/input/` | ROOT 下发的 input/amendment/manifest，原路径不在 main；归档后可回收。 |
| W07 六份基线输入 | `…/w07/ff-matrix-efficiency/.planning/w07-ff-matrix-efficiency/{.gitignore,START_HERE.md,HANDOFF_CONTRACT.md,INPUTS.json,input/case-handler-baseline.json,input/dependency-manifest.json}` | `w07/` | 未跟踪历史输入，不当代码合并。 |
| W07 唯一收据 | `…/w07/ff-matrix-efficiency/.tmp/w07-b1…b6/attempt-*/{report,restore,guard-events}.json`（18 个 JSON） | `w07/attempts/`（含 `manifest.json` 逐文件 SHA256） | 首失败 / 最终 / 时序 / 恢复收据。`.tmp` 其余 1000+ 生成物未证明逐字节重复，本卡不代 ROOT 处置，建议 ROOT 保留或单独核对后再决定。 |
| main 已跟踪证据 | `docs/handoffs/w07-ff-matrix-efficiency/evidence/{first-run-failure-report,final-41-report,final-41-restore,final-41-proofs-g1,final-41-proofs-g2,timing-before-after}.json` | 不复制（已在 main） | ROOT 后续 41-case 证据的唯一权威来源，不用旧 16-case 完成声明覆盖。 |

禁止项（本卡未做，也建议 ROOT 不做）：整仓 reset/clean、删除 `.ff_jobs`、读取或复制 `config/FMP_API_KEY.txt`、把旧 `codex/ff-job-facade-01` 或 `codex/transcript-companion` 重新合回 main、重跑旧收费/下载链、把 W06/W07 旧完成声明写成当前状态。
