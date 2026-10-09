# FF local-source prepare：主线薄组合

## Objective / scope

Base 59c4d0d，branch codex/main-local-source-prepare-20261009；owner MAIN。仅 FF scripts/ff_local_source_prepare.py、fetch_filing.py、对应test、SKILL说明和现有CI列表。CWP owner负责 bytes/DEI/根/metadata+restore事务；Dayu代码零改动。消费者不读取原件或数据库物理路径。

## Fixed interface

Explicit v2 reuse_only exact request → DB-only query。hit 原来2次调用，不增加prepare；只有真实not_found才本地prepare，再ready时query同一scope。v1保持旧只读路径；fetch_if_missing/latest由CWP ensure组合一次，不在FF重复。

local_prepare_cli --config ... --request -：stdin local-source-prepare-request/1，source_request现SourceRequest字段/schema1.0/allow_download=false；limits 64 candidates/128MiB/local timeout=min(global remaining,600)。本地原件限额独立于远程下载cap，不能因原件已大于下载cap而重下。返回local-source-prepare/1，零download，pathless SourceRef2.0/null。named blocked/unavailable/ambiguous/not_found直接返回真实error，不provider fallback。

## Steps

- [x] 先写责任用例；纠正非法reuse fixture后实际9FAIL/1PASS，1.29秒。
- [x] 通用transport+一次miss组合；33PASS/1SKIP/.45秒；Ruff+mypy绿。
- [x] 大节点影响回归204PASS/2SKIP+39subtests，32.49秒；isolated root恢复不存在。2SKIP是显式CWP_V2_CODE_ROOT缺失及旧生产security-master条件测试，不能称全无skip。
- [ ] CWP owner真实3个MSFT DEI原件+CN未知pub，经此FF实际CLI、临时catalog、0provider；记录真实statuses，不强求4PASS。
- [ ] 两包主线集中整合/正常commit/push；定点安装fetch/helper/SKILL，旧安装SHA检查，config/output/key不动。
- [ ] 原三家与新三家真实RF/四审由主计划MAIN执行，不以此工程包代替。

工程反例与actual node共一个集中验收，禁止给小节点增加人签。
