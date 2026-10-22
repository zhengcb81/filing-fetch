# FF本地准备诊断：交接

工程候选，待ROOT非作者验收。产品commit`6dbb9e84d8389f4d4f2d8305c788b59e4f91d2bd`，分支`codex/r1-local-budget-observation`，基线`a1cb84da`。唯一公共接口说明[INTERFACE.md](INTERFACE.md)，完整逐文件物理/Git LF SHA、测试与安装清单见[handoff.json](handoff.json)。

## 做了什么

旧FF收到了CWP operations/diagnostics，却只留下六字段cause。现在按可选顶层`local_preparation_observation`保留有界纯机器诊断和**本次实际local读取请求限额**，不改变旧status/exit/retry/calls/downloads/cause。缺实测聚合时local_io_usage仍null；producer_started=false不代表本地读取0。ROOT的local-read-budget/1 operation原样传递，charged与观测到的被拒tail不混为费用或网络下载。没有加身份校验/许可/新账/重试/放大预算。

有效RED3F→GREEN3P；最终127P/15.77s/0SKIP。含真实FF CLI及有界子进程、600条大诊断、原样保真和深复制、危险/错型/超限诊断拒绝且safe cause保留、既有W02/原因/安装/CI回归。Ruff/mypy及普通commit三hook全PASS。只向原CI_TESTS表增加本快速回归；没有新门禁。

## 跨层仍需ROOT处理

1. CWP旧错误分支会丢弃部分进度、计数和trigger；这不是FF可还原的事实。ROOT的独立producer lane负责现有8-key local-source-prepare/1中的budget operation。这里的测试budget计数是合成producer DTO，用于传递保真，不冒称对真实资料库测得。
2. RF旧optional键闭合和16KiB/64KiB窗口仍会吞大诊断；已给RF独立线规范和正反例。大fixture optional108288B/full compact108904B/既有FF pretty135853B。必须实际跑FF→RFclient→source_preparation再签跨层通过，不能只加键。
3. 安装时5个runtime必须一起同步，包括**新ff_local_preparation_observation.py**；本线没有写安装副本/配置。producer/cause旧schema保持兼容，RF additive支持需随本功能协调发布。

## 证据和清理

全部日志/XML与原失败只读引用在evidence/；原W06历史未改。独占fixture/测试/类型缓存清理约15.1MB，结束恢复不存在，未删除原件/做完整恢复备份。0真实provider/下载/LLM/key/资料重扫。本工区没有push、并主线或跨仓修改。

复核：

```text
python -m pytest tests/test_local_preparation_observation.py tests/test_local_source_prepare.py tests/test_r1_source_business_failure.py tests/test_provider_cause_contract.py tests/test_ff_v2_contract.py tests/test_ci_tests.py tests/test_selective_installation.py tests/test_install_runtime_diagnostics.py -q --tb=short --basetemp <owned-short-temp> --junitxml <owned-result.xml>
```

下一步：ROOT非作者同SHA审查→producer/FF/RF离线契约联调→ROOT整合/定点安装/提交推送，再决定真实H1重试。本线不自行重扫。


## Independent-review address leak repair (2026-10-22)

W02 found two genuine nested schema_version address leaks (old source 6dbb9e84: independent15P/2RED). Product a30024e57fd22b68662fbdfb1c344b8709391556 rejects only explicit drive:/ and scheme:// address prefixes. The original machine/schema namespace grammar remains: urn:owner:budget/2, owner/schema/1 and reason=file:missing are positive controls. No owner business map, permission, identity or accounting rule was added.

Final same-group139P/24.29s (no skip), Ruff and existing two-entrypoint mypy pass. Final12-case test against the old Git helper loaded in memory is5F/7P (0.78s), retaining safe cause when the optional observation is rejected. evidence/schema-hygiene-fix/final-source.json binds actual and Git LF bytes. Earlier red.xml contains one overly narrow slash test later converted to a positive; use old-source-red.xml and final-green.xml as the final RED/GREEN pair. Initial green.xml137P was intermediate and is not final acceptance. Normal commit hook originally flagged two malicious test inputs as absolute host assumptions; exact original baseline entries now document that the strings never reach filesystem/Path operations and rejection must hold on every OS. No skip, computed-path concealment, gate removal or blanket exemption was used.

W02 re-review on the new frozen source is pending; this repair does not claim cross-layer acceptance. All prior runtime installation requirements and ROOT responsibilities remain.


### Final same-class file URI supplement

W02 a300 recheck17P exposed one additional standard file:/ absolute URI form (18-case recheck17P/1RED). Source136ab5a627083f173c60fc88b7b3f74879a4bf99 adds only case-insensitive file:/ prefix refusal. file:missing remains positive and owner schema namespaces remain unconstrained by business enums. New3 URI variants: RED3F/5P0.35s → entire observation test file32P/2.83s; normal Ruff/mypy/host guard PASS. The earlier139P/24.29s binds a300, not falsely relabelled136. Final W02 18-case frozen recheck pending. file-uri-final-source.json is the latest source binding.
