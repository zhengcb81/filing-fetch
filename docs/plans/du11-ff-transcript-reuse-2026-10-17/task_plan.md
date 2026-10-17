# DU11-FF-TRANSCRIPT-REUSE — 实施计划

Plan-ID: `du11-ff-transcript-reuse-2026-10-17`
Card: `company-wiki/docs/plans/document-understanding-2026-10-13/parallel/du11-2026-10-17/du11_ff_transcript_reuse.md`
Base commit: `f1a939e522c22b23659712a8bd2b344f5eb0a364`
Branch / worktree: `codex/du11-ff-transcript-reuse` @ `C:/Users/郑曾波/Projects/filing-fetch-du11-local-transcript-reuse`
Frozen upstream: CWP `34a7dd71aaa49d18c13fcdd300ce79581114ca5b`, ET `2584b7eed062a9a30254bc06b4f19ab5471b414e`

## Goal

未显式限定 transcript provider 时，先通过公开 CWP local exact query 复用已登记的合格电话会（任意真实 provider），
唯一合格来源由公开 reader 实读验真后复用；只有真正无候选（且无本地受限证据）才走原 FMP 采集。
复用范围与采集 provider 解耦；provider/publication 元数据忠实取自成功 reader receipt manifest。

## Ownership / write scope (exact)

- `scripts/transcript_companion.py`
- `scripts/transcript_tool_transport.py`
- `scripts/ff_v2_envelope.py` (only if real-provider compatibility requires it)
- new `scripts/transcript_reuse_selection.py` (pure helpers, no storage/cache)
- new `tests/test_du11_transcript_reuse*.py`
- new `tests/fixtures/du11_transcript_reuse/`
- `docs/plans/du11-ff-transcript-reuse-2026-10-17/**`

Everything else is read-only. Do not touch `config/FMP_API_KEY.txt` (untracked, user credential; never read/copy/commit).

## Phases

### Phase 0 — Worktree, PWF, baseline verification
**Status:** complete
- [x] dedicated worktree + branch at fixed base
- [x] PWF files created in owned plan dir
- [x] confirm main repo clean-ness statement + record worktree HEAD/status
- [x] freeze CWP dependency source list + SHA (extract only needed source from frozen commit) — `receipts/c_dependencies.json`

### Phase 1 — A: investigation + real-behavior RED
**Status:** complete
- [x] record public CWP wire facts (plain SourceRequest path vs lookup envelope path, qualification fields, reader receipt manifest) — `findings.md` F1–F8
- [x] build synthetic real CWP temp config/db with a motley_fool-registered transcript (real `scan` CLI)
- [x] real RED: FF companion default lookup (provider=fmp) misses the existing motley_fool source → ET/duplicate import (measured) — `receipts/A_RED_baseline.json`
- [x] RED receipts for: plain neutral request found, lookup envelope provider=null blocked, explicit fmp envelope counter-case
- [x] input/output compatibility matrix — `handoff.md` §3

### Phase 2 — B: root-cause implementation + central regression
**Status:** complete
- [x] decouple reuse scope (source-neutral local query) from acquisition provider (FMP only)
- [x] neutral query interpretation: found / single unknown excluded / multiple-or-restricted unknown / after_as_of / invalid / truly missing
- [x] provider truthfully from verified reader receipt manifest (no `fmp` fabrication)
- [x] explicit `provider=fmp` keeps envelope path, unknown_publication dedup, FMP acquisition constraint
- [x] regression matrix per card; 0 ET / 0 provider calls proven by call counters
- [x] existing transcript tests still pass unchanged (346 → now 257 central + 98 card tests)
- [x] mutation check: every core defect is detected by the new tests — `receipts/c_mutation_check.json`

### Phase 3 — C: real offline contract E2E + delivery
**Status:** complete
- [x] real FF CLI (narrowest public companion path) → real `source_query_cli` (plain) → real `source_reader_cli` reuse across providers
- [x] unknown-only excluded: 0 ET / 0 GET; known+unknown → qualified match wins; truly missing → acquisition
- [x] explicit fmp envelope unknown branch + neutral plain request branch measured separately
- [x] explicit fmp positive control on the real catalog (`found` via plain and envelope entries, then replay reuse)
- [x] missing → fixture ET process → real CWP import → reader → repeated reuse (1 download, 0 on replay)
- [x] restore/cleanup receipts (initial inventory + post-seed checkpoint, exact import pair, owned temp removed)
- [x] freeze implementation commit; independent reviewer agent audit twice
- [x] round 1 on `c787757`: PASS (0 blocker / 0 major, 3 minor + 7 nit) → fixed in `d16dce2`
- [x] round 2 on `5dee9a2`: **PASS**, 0 blocker / 0 major / 0 source minor / 0 unresolved source findings

### Phase 4 — Delivery (docs-only handoff commit)
**Status:** complete
- [x] task_plan/findings/progress/handoff.md/handoff.json/receipts
- [x] docs-only handoff commit on top of source head `5dee9a2`
- [x] STOP: no merge, no push, no worktree cleanup

## Decisions made

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | provider omission → plain `SourceRequest` query (provider=null), no envelope | card requires both public entries kept distinct; envelope path requires non-null provider |
| D2 | explicit `provider=fmp` keeps `company-wiki-transcript-import-lookup-request/1` envelope | preserves unknown_publication dedup + FMP acquisition constraint |
| D3 | provider of a reused source = reader receipt `manifest.provider`; missing → unknown (None), never `fmp` | card: no label fabrication; query candidate top level is not the proof |
| D4 | single pure-unknown excluded → `unknown_publication` (SourceRef + qualification, 0 GET); multiple/restricted → `upstream_error` named reason | existing wire cannot express several unknowns honestly |
| D5 | after_as_of/invalid-only excluded → named gap + 0 GET | must not pretend the source does not exist, must not download across as-of |
| D6 | acquisition provider stays FMP regardless of neutral lookup | card: "缺失后仍只用现有FMP", no new provider switch |

## Errors encountered

The live table is `progress.md` → "Errors encountered" (fixture contract mismatch, the missing SHA-256
validation, the `__pycache__` residue, the misplaced session fixture, the invalid repo-status guard, and the
reviewer-round receipt mistakes). All are resolved; none is open.

## Next Step

None for the author: delivery is complete on branch `codex/du11-ff-transcript-reuse`. ROOT owns the merge,
push and worktree cleanup, and should verify the frozen source head `5dee9a2` (the docs-only handoff commit
sits on top of it and changes nothing under `scripts/` or `tests/`).
