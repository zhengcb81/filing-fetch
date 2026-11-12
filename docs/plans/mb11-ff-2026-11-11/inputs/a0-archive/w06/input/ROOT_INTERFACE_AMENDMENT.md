# W06 ROOT 接口补充（施工时同时读取）

只澄清已定责任层，不增实施节点、审批或权限。此前固定 input/card 原字节保留，本补充单独加入各 input；自己的 contract 阶段把这些规则写进实现和测试。

## Audit

- reported_fact/management_guidance 的数字带 source_id+locator；analyst_assumption/scenario_stress 可以 source_ref=null，但必须有显式 rationale/依据引用和角色，不伪造未来原件。来源实读仍由独立 process reviewer 承担。
- CLI overall 优先序 INVALID > FAIL > UNRESOLVED > PASS，对应退出码 2/1/3/0；NOT_CHECKED 的必要关系使 overall=UNRESOLVED，不因 observation 格式正确就宣称关系已验。任何整体结论都不证明 source truth/经济合理性。
- 合法未来假设不会仅因在 as-of 后而失败；来源发表/available_by 与预测目标期间分别表达，未知资格作诊断，不能变成人工批准。

## FF

- 已确认真实路径为 fetch_filing.py、EarningsTranscriptsTransport、ET 根目录 transcript_tool.py、CWP SourceVersionReader.open_version。
- scratch FF config 实际 schema_version=1.0、company_wiki_root=owned fixture root，optional earnings_transcripts_tool=owned 测试代理入口、fmp_api_key_file=假值文件。schema不接受新allowed_handle_roots；不要复制默认生产配置/密钥。CWP code通过显式 PYTHONPATH绑定、数据配置只在 scratch，不能使用 editable fallback误跑生产。
- 测试依赖快照可从固定 Git commit只展开代码到 owned scratch；在需要之时记录 actual module/SHA/层级，不能修改 producer 或把整层 fake response称真链。

## CWP

- 模拟 root_id 使用 local_company/external_dayu/external_dropbox 等有效简单标识；斜杠只属于目录路径，不把说明中的 local/company 字样抄成未验schema的ID。
- 真实公开方法是 open_version(ref, purpose=...)；verify_version只给receipt，不持有原bytes。query_ref/open_version 新进程回开属于验真，不以旧buffer替代。
- register仅针对≤6 fixture，不扫生产；rename/root move的identity承诺按现有contract分清，不为保住伪same-ID放宽字节/身份检查。
