# FC-802: filing-fetch latest/gap 编排（GAP 不误映射 not_found；allow_download 两分支）

Plan: FCAP-2026-08-09-r2 task_plan Phase 8 FC-802. Owner: filing-fetch。

## 问题

当前 resolve_filing 把所有非 reused 状态映射为 FilingFetchError(not_found)，GAP 计划被吞掉；
allow_download 两分支不存在；close-gap 事务（FC-801）未被调用。

## 设计（filing-fetch 保持薄：不复制 provider/root/identity 规则）

1. **mode=latest_as_of 时总走 ensure 命令**（无 --allow-download 也返回 GAP plan，metadata only）。
2. **结构化 gap 结果**：ensure status="gap" → resolve_filing 返回
   `{"status": "gap", "gap_plan": {...}, "resolution": {...}}`（不再 raise not_found）。
3. **allow_download 两分支**：
   - allow_download=False → 结构化 gap（fetch/write=0）。
   - allow_download=True + 请求带 authorization 块 → 组装 CloseGapBinding
     （request_id=plan.request_id、gap_plan_hash=plan.gap_hash、policy_hash=resolution envelope 的
     policy_hash、provider/accessions/caps/expiry 来自 authorization 块）→ 调 company-wiki
     `close-gap` CLI（binding 写临时 JSON 文件）→ 返回最终 handle（envelope）。
   - allow_download=True 但无 authorization → 结构化 gap（授权缺失，不下载）。
4. **请求 schema**：`authorization` 可选块加入 1.2 allowed fields
   （{allowed_accessions, max_items, max_bytes, expires_at}；非 dict/缺字段 → request_error）。

## 场景（tests/test_fetch_filing.py 追加）

- FC802-1：latest_as_of + no download → 结构化 gap（status=gap、gap_plan 存在），不 raise。
- FC802-2：latest_as_of + allow_download + 无 authorization → 结构化 gap。
- FC802-3：latest_as_of + allow_download + authorization → close-gap 命令被调用
  （断言命令含 close-gap、--binding-file；binding 内容 request_id/gap_hash/policy_hash/accessions
  正确）→ 返回 handle（reused_exact）。
- FC802-4：exact 模式 reused → handle 不变（回归）。
- FC802-5：exact 模式 missing → 仍 not_found（只有 GAP 结构化）。
- FC802-6：authorization 块非法 → request_error。

## Stage

### Stage 1: request schema authorization 块（filing_contracts.py）
**Status**: Not Started

### Stage 2: resolve_filing GAP 结构化 + close-gap 分支（fetch_filing.py）
**Status**: Not Started

### Stage 3: closure（全量 suite、receipt、review）
**Status**: Not Started
