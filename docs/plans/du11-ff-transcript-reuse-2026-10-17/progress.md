# Progress — DU11-FF-TRANSCRIPT-REUSE

## Session 1 — 2026-10-17

### Phase 0 — worktree, PWF, baseline

- `git worktree add -b codex/du11-ff-transcript-reuse … f1a939e5…` created at
  `C:/Users/郑曾波/Projects/filing-fetch-du11-local-transcript-reuse`; HEAD = `f1a939e5`, `git status --porcelain` empty.
- Main repo untouched: only the pre-existing untracked `config/FMP_API_KEY.txt` (stat/path only, never opened).
- PWF created at `docs/plans/du11-ff-transcript-reuse-2026-10-17/`.

### Phase 1 — A: investigation + measured RED

Frozen upstream read at commit `34a7dd71aaa49d18c13fcdd300ce79581114ca5b`
(`git rev-parse 34a7dd71:<path>` == `git hash-object <path>` for `source_reader.py`).
Facts recorded in `findings.md` F1–F8.

Real-behaviour probe (`receipts/ab_probe.py`) — owned temp root, real frozen CWP
`src/` extracted with `git archive` from the pinned commit (`tar sha256
555b11a87ebd67858c08ddbc08971fc97deff3b19079444dc738b6eafa558eac`), one synthetic
`motley_fool` transcript registered through the real `scan` CLI, then the four
public wires plus the real FF companion:

| wire | result |
|------|--------|
| plain `SourceRequest`, `provider=null` | `found` (1 candidate, provider `motley_fool`) |
| `lookup-request/1` envelope, `provider=fmp` | `not_found` / `no_local_match` |
| `lookup-request/1` envelope, `provider=null` | `blocked` / `invalid_request` (exit 2) |
| plain `SourceRequest`, `provider=fmp` | `not_found` (provider filter) |
| `source_reader_cli` receipt manifest | `provider=motley_fool`, `published_date=2026-07-22` |

**RED (baseline `f1a939e5` scripts, receipt `receipts/A_RED_baseline.json`)**:
`ff_companion_provider_omitted` → `status=downloaded`, `provider=fmp`,
`et_calls=1`, `provider_calls=1`, `company_wiki_calls=3` — the exact transcript was
already registered and verified locally, yet FF called ET and imported a duplicate FMP original.

**After the fix (receipt `receipts/A_RED_after_fix.json`)**:
`status=reused`, `provider=motley_fool`, `et_calls=0`, `provider_calls=0`,
`company_wiki_calls=2` (one query + one reader), same `source_ref` SHA as the seeded original.

Both probes removed their owned temp roots (`owned_temp_removed=true`).

### Phase 2 — B: root-cause implementation

- new `scripts/transcript_reuse_selection.py` — pure reader of the public
  `2.0` query result + `source-qualification/1` observations (no I/O, no cache).
- `scripts/transcript_tool_transport.py`:
  - `_source_request` takes the provider instead of hard-coding `fmp`;
  - `_run_source_query` is the single bounded CLI call; `_query` keeps the
    provider-scoped `lookup-request/1` envelope, `_query_local` sends the plain
    `SourceRequest` (no envelope);
  - `_verified_open` now returns the public receipt, `_manifest_provider` reads the
    real provider from `receipt.manifest.provider` (unknown stays unknown);
  - `_verified_lookup` refuses a manifest that contradicts the exact request or an
    explicit provider constraint, then reuses with `provider_calls: 0`;
  - `_read_lookup` implements the documented outcome matrix (match / single unknown
    observation / named gap / missing / named non-reuse status);
  - `acquire_exact` re-queries through the same entry and treats any local evidence
    as "answer changed" instead of a download trigger;
  - `_import_fetched` reports the manifest provider (fallback: the CWP-validated
    tool result declaration), never a request default.
- `scripts/transcript_companion.py`: an omitted provider stays omitted; the child
  result carries the qualification/exclusion diagnostics for duplicate suppression.

Tests added (all offline, call-count based):
`tests/test_du11_transcript_reuse_selection.py` (47), `…_contract.py` (42),
`…_support.py` (frozen-CWP harness), `…_e2e.py` (9), plus
`tests/fixtures/du11_transcript_reuse/fmp_known_publication.fetched.json`.

### Phase 3 — C: real offline E2E

`python -m pytest tests/test_du11_transcript_reuse_e2e.py -q` → **9 passed in 117.85s**.
Real FF CLI (`scripts/fetch_filing.py`) → real `source_query_cli` → real
`source_reader_cli` reuse of a `motley_fool` original, 0 ET calls; unknown-only
exclusion → `unknown_publication` with 1 query and 0 reads; ambiguous two-provider
period → `ambiguous`, 0 ET/0 reads; after-as-of and mixed gaps → named, 0 ET;
missing → one fixture ET → real CWP import → replay reuse with 0 provider calls.

### Central regression

`346 passed, 3 skipped in 22.26s` for this card's tests plus
`test_transcript_companion.py`, `test_transcript_companion_transport.py`,
`test_transcript_launch_contract.py`, `test_transcript_response_budget.py` and the
real `ff_v2_envelope` neighbourhood (`test_ff_v2_contract.py`,
`test_cwp_s0b_source_ref_contract.py`, `test_acquisition_failure_consumer.py`,
`test_failure_usage_continuity.py`, `test_m3_acquisition_usage_ff.py`,
`test_provider_diagnostics_cli.py`).

### Errors encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| probe ET fixture rejected by the CWP import contract (`transcript_import_failed`) | 1 | read `transcript_fmp_contract.py`: `canonical_content_sha256`/`content_bytes` are the *content field*, not the JSON body; regenerated the fixture accordingly |
| `LocalQueryContractError` for a short `content_sha256` was never raised | 1 | added the lowercase-SHA-256 check to `_observed_ref` |
| E2E teardown saw 78 `__pycache__` files under the frozen `src/` | 1 | set `PYTHONDONTWRITEBYTECODE=1` for the E2E session so the frozen tree stays byte-identical |
| session fixture `frozen_source_tar` not found when defined in the helper module | 1 | fixtures now live in the E2E module; the helper module only exposes `frozen_archive()` |
| session guard "company-wiki repo status unchanged" failed | 1 | removed: ROOT is editing company-wiki concurrently (the frozen commit is immutable; the tar SHA is recorded instead) |

## Session 2 — 2026-10-17 (independent review + fixes)

### Independent review
Independent reviewer subagent audited source `c787757` (report `receipts/reviewer_report.md`):
**VERDICT: PASS**, 0 blocker / 0 major, 3 minor + 7 nit. It independently reproduced the A/B contrast
(baseline `downloaded/fmp/1 ET/3 CWP` vs `reused/motley_fool/0 ET/2 CWP`), the frozen archive SHA, all 13
dependency blob SHAs, the restore receipt, the full-suite failure set, and an M1–M7 mutation run.

### Fixes (all findings closed)
- M1 stale counts → regenerated `receipts/c_test_summary.json` (102 = 47 selection + 45 contract + 10 E2E;
  central 257/3; full suite 1313/9/16) and handoff.md.
- M2 inconsistent mutation receipt → `mutation_check.py` now copies `scripts/`+`tests/`+`pyproject.toml` into
  an owned tree (never mutating the shared worktree), records a clean `92 passed` baseline, the failing test
  names per mutation, and a pristine-restore check. 7/7 mutations detected.
- M3 pre-seed restore baseline → `OwnedWiki.checkpoint()` after seeding+scan; `assert_restored()` now asserts
  every pre-test entry outside the catalogue/runtime area is byte+mtime identical and allows exactly one
  canonical-import pair (`expect_canonical_imports()`).
- N1 task_plan Next Step/errors → updated (this file is the live error table).
- N2 baseline RED unbound → `ab_probe.py --ab` extracts the baseline itself and records the archive tar SHA
  plus per-file script SHAs; both A receipts regenerated.
- N3 second provenance source → comment now names the CWP proof; new test: no manifest provider and no tool
  declaration → provider stays unknown.
- N4 mutation script touched the shared worktree → isolated copy only.
- N5 frozen-tar cache residue → rebuilt per run inside an owned holder, removed in `finally`.
- N6 dropped aggregate diagnostic → `excluded_publication_statuses` forwarded with `excluded_candidates`.
- N7 literal "candidate without provider" → added; plus the A-node explicit-fmp positive control on the real
  catalog (`test_real_cwp_explicit_fmp_lookup_finds_and_reuses_its_own_source`).

### Self-found gap while writing the anti-control (fixed)
Driving the new restore harness by hand showed that a **tampered seed was not detected**: the post-seed
`changed_since_checkpoint` list was computed but never asserted. Fixed in
`tests/test_du11_transcript_reuse_support.py`: `assert_restored()` now requires
`changed_since_checkpoint == []` (legitimate catalogue-runtime file changes are reported separately as
`catalogue_or_runtime_changed`), plus seven harness self-tests on a miniature frozen tar prove the receipt
catches a modified seed, modified sidecar, stray company file, changed frozen source, an exact import pair and
a second import pair.

### Final source head
Source commit `5dee9a20c1c5952688673caf784fdce4e9391a50` (c787757 → d16dce2 → 5dee9a2). Re-verification after
all fixes: `ruff` clean; card 109 passed (100.14 s: 47 selection + 45 contract + 10 E2E + 7 harness
self-tests); central 257 passed/3 skipped (13.89 s); mutation 7/7 detected on an isolated copy;
full suite 1320 passed / 9 failed / 16 skipped with the same 9 pre-existing base-commit failures.
The docs-only handoff commit sits on top of this source head.

### Round-2 independent review
Same reviewer agent re-reviewed `5dee9a2`: **FINAL VERDICT PASS**, 0 blocker / 0 major / 0 source minor,
0 unresolved source findings. It reproduced every number independently (109 / 257+3 / 1320+9+16, mutation
7/7 with a load-bearing check — removing the new assertion makes two self-tests fail — restore 362/366/368,
A/B `downloaded/fmp/1 ET/3 CWP` vs `reused/motley_fool/0 ET/2 CWP`, explicit-fmp positive E2E, ruff clean,
source blobs unchanged). Residual items were delivery bookkeeping only and are closed here:
R2-1 `ab_probe.py --source-commit` + regenerated A receipts (`ff_commit.source_commit` now the frozen source
SHA, per-file SHAs unchanged); R2-2 task_plan/handoff set to `5dee9a2`, round-2 PASS, unresolved 0;
R2-3 recorded as a known observation (no source change, which would invalidate the frozen binding).
