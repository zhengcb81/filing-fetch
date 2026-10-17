# Independent final quality review — DU11-FF-TRANSCRIPT-REUSE

- **Reviewer:** an independent reviewer subagent, **distinct from the author** of `c787757`. The author did not participate in this review and could not edit it.
- **Date:** 2026-10-18 (local, Asia/Shanghai); review window 2026-10-17 23:53 → 2026-10-18 00:15.
- **Worktree reviewed:** `C:\Users\郑曾波\Projects\filing-fetch-du11-local-transcript-reuse`, branch `codex/du11-ff-transcript-reuse`.
- **Base commit:** `f1a939e522c22b23659712a8bd2b344f5eb0a364`.
- **Implementation commit reviewed (source freeze):** `c787757a9f0409777fd6d469a90d2371bce706d5` (parent = base).
- **Frozen upstream:** company-wiki `34a7dd71aaa49d18c13fcdd300ce79581114ca5b`; earnings-transcripts `2584b7eed062a9a30254bc06b4f19ab5471b414e` (commit present, **never executed**; ET boundary is a fixture process).
- **Reviewed source blobs (working tree = commit):**
  - `scripts/transcript_tool_transport.py` `77becf9261b8f12b570bc930502daf4bdeb6fd47` (raw SHA-256 `d8aea60a1c78fe884f3aedc70ad2a66ba2cb78a4aa49e0a6ac47be1881036164`)
  - `scripts/transcript_companion.py` `e55156866b8eb232cc107a7d5490ab687e599835` (raw `59b3ae1cbafa830fc5f4b3cf7087009491b70173686fa3870d006baf68088ccb`)
  - `scripts/transcript_reuse_selection.py` `b6449812704bb95a0df396cdcc204a4def4a1007` (raw `8591e9968d5d23c4e056a32062ea4b4fdbac63c3421523d921f3176d93823231`)
  - The other five test/fixture files match the raw SHA-256 values in `handoff.json.source_freeze_sha256` (see M1 note for the fixture's LF/CRLF detail).
- **Write discipline:** I modified no source, test, or planning file. The only file I wrote is this report. I did not run `git checkout/reset/clean/commit`, did not run `mutation_check.py` in the worktree (it mutates tracked files), and did not read `config/FMP_API_KEY.txt` (stat only).

### Review-process notes (important)

1. The worktree was **still being finalized by the author while I reviewed**. `c_mutation_check.json`, `task_plan.md`, `findings.md` and `handoff.json` have mtimes 23:54:34–23:55:23; my review used the frozen source commit and the PWF snapshot after 23:55:23.
2. During my **first** run of the selection+contract suite (≈23:54:2x) the worktree source files were mid-mutation: `transcript_tool_transport.py` / `transcript_companion.py` mtimes are 23:54:25 / 23:54:34, and three tests failed with `sent["provider"] == "fmp"`, exactly the M1/M5 mutation. A clean re-run after the restore gave **90 passed** and the blob hashes above. I disclose this rather than silently keeping the failed run; see N4.
3. The PWF test-count receipts were generated *before* the last contract test (see M1), so the numbers in `c_test_summary.json` / `handoff.json` are stale; I verified the actual counts myself.

## Commands run and results

| # | Command | Result |
|---|---------|--------|
| 1 | `git -C <worktree> status --porcelain=v1`; `git rev-parse HEAD`; `git rev-parse HEAD^` | only `?? docs/plans/du11-ff-transcript-reuse-2026-10-17/`; HEAD `c787757a9f0409777fd6d469a90d2371bce706d5`; parent `f1a939e5…` |
| 2 | `git diff --stat f1a939e5..c787757` / `--shortstat` | 8 files, +2722 / −49; exactly the card whitelist paths (2 scripts + 1 new script + 4 new test files + 1 new fixture) |
| 3 | `git hash-object scripts/…` (3 scripts) | 77becf92…, e5515686…, b6449812… (match `c787757` and the diff index lines) |
| 4 | `python -m ruff check scripts tests` | `All checks passed!` exit 0 |
| 5a | `python -m pytest tests/test_du11_transcript_reuse_selection.py tests/test_du11_transcript_reuse_contract.py -q` (first attempt) | **3 failed, 87 passed** — contaminated by the concurrent mutation described above; not accepted |
| 5b | same, after clean-tree verification | **90 passed** in 1.18 s, exit 0 |
| 6 | `python -m pytest tests/test_du11_transcript_reuse_e2e.py -q` | **9 passed in 119.64 s**, exit 0 (real frozen-CWP CLIs; ET fixture never called on zero-call paths) |
| 7 | `python -m pytest tests/test_transcript_companion.py tests/test_transcript_companion_transport.py tests/test_transcript_launch_contract.py tests/test_transcript_response_budget.py tests/test_ff_v2_contract.py -q` | **126 passed, 3 skipped** in 14.09 s, exit 0 |
| 8 | 10-module central regression from `handoff.json` | **257 passed, 3 skipped** in 29.46 s, exit 0 (matches `c_test_summary.json`) |
| 9 | `python -m pytest tests -q` | **9 failed, 1310 passed, 16 skipped** in 400.15 s, exit 1; failure names in "Full-suite note" below |
| 10 | base-commit run of the failing test files (`git archive f1a939e5` extracted to `%TEMP%`, read-only) | **8 failed, 14 passed**; the 9th (`test_fc1307a…`) passes at base because ROOT has concurrently changed the company-wiki sibling (cross-repo gate), not because of this diff |
| 11 | `python receipts/ab_probe.py --scripts <f1a939e5:scripts> --out …` (baseline A) | `status=downloaded`, `provider=fmp`, `et_calls=1`, `provider_calls=1`, `company_wiki_calls=3`, source SHA `c6a6b3e9…`; tar SHA `555b11a8…`; `owned_temp_removed=true` |
| 12 | `python receipts/ab_probe.py --scripts scripts --out …` (after fix) | `status=reused`, `provider=motley_fool`, `et_calls=0`, `provider_calls=0`, `company_wiki_calls=2`, source SHA `7589339e…`; all six cases byte-identical to `A_RED_after_fix.json`; tar SHA matches |
| 13 | `python receipts/restore_probe.py --out %TEMP%\…` | `reused`/`motley_fool`/`provider_calls=0`, `et_calls=0`, `company_wiki_child_calls=2`; restore receipt identical to `c_restore_receipt.json` (baseline 362, sentinel + existing.out true, changed/removed/unexpected/frozen empty); `cleanup_removed=true` |
| 14 | `git -C company-wiki rev-parse 34a7dd71:<13 paths>` vs `c_dependencies.json` | **13/13 blob SHAs match** |
| 15 | my own `git archive 34a7dd71 src pyproject.toml` → SHA-256 | `555b11a87ebd67858c08ddbc08971fc97deff3b19079444dc738b6eafa558eac` (identical to the receipt); 5,406,720 bytes |
| 16 | verify `handoff.json.source_freeze_sha256` vs commit content | 7/7 Python/test files match the working tree; the fixture's recorded SHA is the **committed LF content** (`62e87b4e…`), while the working tree is CRLF (`ecf2bcda…`); `git show c787757:<fixture>` hashes to `62e87b4e…`, so the binding is correct |
| 17 | mutation sensitivity in an **isolated %TEMP% copy** (never the worktree): M1 request relabel, M2 envelope for omitted, M3 provider fallback, M4 gap→miss, M5 companion→fmp, M6 single unknown→miss, M7 hardcoded fmp | baseline **90 passed**; M1 3 failed, M2 3 failed, M3 1 failed, M4 6 failed, M5 6 failed, M6 3 failed, M7 4 failed — **every mutation detected** |
| 18 | frozen-src import check with `PYTHONPATH=<extracted committed src>` | `company_wiki` and `source_reader` resolve inside the extracted frozen tree, **not** the live `.pth` company-wiki path |
| 19 | temp-root audit after my E2E/restore runs | no `du11-owned-*`, `du11-cwp-frozen-*`, `du11-ab-probe-*`, `du11-restore-receipt-*` left; my own temp artifacts removed |
| 20 | main repo `git status`; `Get-Item config/FMP_API_KEY.txt` (stat only) | only `?? config/FMP_API_KEY.txt`; 32 bytes, LastWriteTime 2026-09-27, LastAccessTime 2026-10-17 23:05:55; content never read by me |

Non-result-changing inspection: I read the task card, all PWF files, the full diff of the three source files and all four test files, the frozen `source_query_cli.py`, `source_reader.py`, `source_reader_cli.py`, `qualification.py`, `resolver.py`, `transcript_tool_contract.py`, `canonical_writer.py`, the base-commit transport/companion, `ff_v2_envelope.py`, `filing_contracts.py`, and the surrounding existing tests (read/grep only).

## Requirement-by-requirement verification

Legend: **Yes** = independently verified from code/tests/receipts; **Yes (note)** = verified with an evidence/delivery caveat; **N/A** = not applicable.

| Card requirement | Verified? | Evidence |
|---|---|---|
| A — fixed HEAD / dedicated worktree / no main-tree changes | Yes | command 1; main repo only the pre-existing untracked key |
| A — real synthetic `motley_fool` registration through the real `scan` CLI | Yes | E2E `OwnedWiki.seed_transcript` + `run_scan`; A probe; source fixture sidecar |
| A — measured RED: default FF lookup misses the `motley_fool` source and creates a duplicate FMP original | Yes | command 11 reproduced from `f1a939e5:scripts`; `A_RED_baseline.json`; no source-string-only assertion |
| A — two public CWP entries are different; plain `SourceRequest` → `query_local`; envelope → `lookup_transcript_import` | Yes | frozen `source_query_cli.py` read independently; plain = `SourceRequest(**data)`/`query_local`, envelope = exact keys/`lookup_transcript_import` |
| A — envelope with `provider=null` is rejected `blocked/invalid_request` exit 2 | Yes | frozen `lookup_transcript_import` raises on `provider is None`; A probe `envelope_provider_null`; E2E |
| A — explicit `provider=fmp` keeps the envelope and its semantics; positive case measured | Yes (note) | A probe measures the negative provider filter; the real positive (fmp source found by the envelope) is measured in E2E `test_real_cwp_explicit_fmp_does_not_reuse_another_providers_source` replay into `unknown_publication`; `findings.md` F10 records this division |
| A — plain `query_local` never returns an unknown-publication success match; unknown only in `excluded_candidates` | Yes | frozen `_query_local` eligibility/exclusion logic read; E2E `probe` asserts `not_found` + excluded `unknown` |
| A — real provider comes from the verified `source_reader_cli` stderr `manifest.provider` | Yes | frozen `source_reader_cli.py`; transport `_manifest_provider`; E2E reader receipt; mutation M3/M7 catch fabrication |
| B — reuse scope decoupled from acquisition provider; omitted → provider-null plain request, no envelope | Yes | transport `_source_request(provider)`, `lookup_exact` branch; contract test asserts `sent["provider"] is None` and no `source_request` key; mutation M1/M2 detected |
| B — explicit fmp keeps the old envelope + unknown-publication dedup + FMP-only acquisition | Yes | `_query` envelope path; E2E explicit-fmp replay unknown branch; ET request provider `fmp` unchanged |
| B — single `unknown` exclusion → `unknown_publication` with SourceRef + `source-qualification/1`, 0 reads / 0 provider | Yes | `_read_lookup` branch; E2E `company_wiki_calls == 1`; contract `kinds == ["query"]`; mutation M6 detected |
| B — several unknown / mixed restricted exclusions → named `upstream_error` gaps (`publication_date_unknown`, `publication_after_as_of`, `publication_date_invalid`), 0 downloads | Yes | `select_local_outcome`/`_gap_reason`; contract parametrization; E2E mixed + after-as-of; M4 detected |
| B — ambiguous/blocked/unavailable/illegal status → named errors, never “missing” | Yes | contract parametrization incl. `not_indexed`; E2E two-provider ambiguous; illegal status test |
| B — only a truly empty local answer falls through to the one FMP acquisition | Yes | E2E missing→1 download; contract replay; `_pending` path unchanged |
| B — verified bytes before reuse (SHA/byte_size/receipt) and manifest identity consistency | Yes | `_verified_open` length+SHA+receipt; `_manifest_conflicts` FY/Q/market/security; damaged-byte tests; E2E real reader |
| B — coverage list (motley/fmp unique, provider metadata, explicit fmp with/without match, ambiguity, blocked/unavailable, unknown-only, multiple unknown, known+unknown, after_as_of/invalid, explicit-fmp unknown, candidate provider vs manifest, missing manifest provider, wrong issuer/period, bad ref/SHA/size, malformed qualification, illegal status) | Yes (note) | all cases above are covered; the literal “candidate has **no** `provider` key” shape is not separately constructed, but the stronger “candidate provider ≠ manifest provider” divergence is covered by `test_omitted_provider_truly_missing_then_replay_reuses_the_imported_source` (candidate `motley_fool`, manifest `fmp`) and the selector never reads `candidate["provider"]` (see N7) |
| B — every non-missing path asserts 0 ET / 0 provider calls by measured child counts | Yes | `FakeCWP.kinds()`/ET call log in contract/E2E; `company_wiki_calls` counts query+reader only |
| B — existing test files pass unchanged; no weak old assertions changed | Yes | commands 7/8; diff contains no existing test edits; 9 failures are outside the card (below) |
| B — request limits/deadline/output cap/failure recovery unchanged; no unbounded retry | Yes | diff leaves the bounded transport and ET request fields untouched; `provider_calls`/usage unchanged |
| C — fixed CWP snapshot only; synthetic config/SQLite/originals; no whole-repo copy | Yes | `git archive <commit> src pyproject.toml`; tar SHA; no `companies/`/real config in the archive |
| C — real FF CLI and/or narrowest public companion → real `source_query_cli` → real `source_reader_cli` | Yes | E2E layering docstring; `test_real_ff_cli_…` runs `scripts/fetch_filing.py`; other E2E run the real companion+transport+CLIs |
| C — unknown-only excluded: 0 ET / 0 read; known+unknown: qualified match wins; truly missing: acquisition | Yes | E2E three dedicated tests with call counts |
| C — explicit-fmp original lookup unknown branch and the neutral branch measured separately | Yes | E2E `test_real_cwp_explicit_fmp_…` + neutral tests; distinct fixtures `fmp_v2` / `fmp_known_publication` |
| C — ET boundary is a call-recording fixture process; a call on a zero-call path fails the test | Yes | `ET_TOOL_SCRIPT` logs every invocation; assertions `et_calls == []`; no network/client import in the changed code or tests |
| C — missing → one fixture ET → real CWP import → reader → replay reuse (1 download, 0 on replay) | Yes | E2E `test_real_cwp_missing_then_one_download_then_replay_is_pure_reuse`; ET log length 1; original count 1; replay 0 ET + 2 CWP calls |
| C — bad-SHA response, ambiguous, timeout counter-controls with no extra download | Yes | contract tests: bad SHA (`transcript_import_hash_mismatch`, 1 ET/1 import/0 reader), ambiguous (0 ET), timeouts (1 ET/0 import) |
| C — no real network / LLM / key read; no company originals copied | Yes (note) | no HTTP client imports in changed code/tests; local CLIs + local fixture; synthetic key file; no test references `config/FMP_API_KEY.txt`; static key access time 23:05:55 predates the author's 23:16+ work and I never opened it — “never opened” is not provable from the repository alone |
| C — restore requirement: initial listing + sentinel + pre-existing entry, bytes/SHA/mtime, no residue, owned temp root deleted | Yes (note) | `OwnedWiki` baseline 362, `restore/sentinel.txt` + `restore/existing.out`; receipt reproduced; `cleanup_removed=true`; no `du11-owned-*` left. Harness strictness caveat = M3 |
| Delivery — local PWF `task_plan/findings/progress`, `handoff.md/json`, `receipts/` | Yes | all present at the reviewed snapshot; `handoff.json` status `IMPLEMENTED_REVIEW_PENDING` and reviewer pending (correct: this review is the input) |
| Delivery — JSON contains card id/status/base/branch/commits/changed paths/scope, schema compatibility, test commands/counts/durations, A-RED↔B fix mapping, C layering/mock boundary, frozen commits/dependency SHAs, restore/sentinel/cleanup, network/provider/LLM counts, reviewer/report/reviewed SHA/0-unresolved | Yes (note) | all sections present and factually correct except the stale test counts (M1); the reviewer section is intentionally pending this report |
| Delivery — source SHA binding, docs-only handoff commit, STOP/no merge/push/cleanup | Yes | `source_freeze_sha256` commit-bound (7/7 Python/test + fixture commit content); `final_delivery_commit` pending; branch not merged/pushed; `git worktree list` shows the branch only |
| Write scope / no forbidden edits | Yes | diff = 3 scripts + 4 new tests + 1 new fixture; `ff_v2_envelope.py`, `fetch_filing.py`, `filing_contracts.py`, `config/`, `tools/offline_contract_matrix/`, CWP/ET untouched; PWF is the card's own dir |
| Compatibility — request schema unchanged; `motley_fool` still rejected; response envelope keys unchanged; unknown `provider_calls`/`provider_requests` stay null | Yes | `filing_contracts.py` untouched; `_option_error` still rejects non-fmp; `ff_v2_envelope._TRANSCRIPT_KEYS` untouched and new diagnostics dropped; `test_absent_usage_keeps_unknown_counts_as_null` |
| No redundant gates / second cache / duplicated CWP query implementation | Yes | `transcript_reuse_selection.py` is pure (no I/O); no new approval/cache/store; transport only spawns the public CLIs |

## Full-suite note (9 failures)

`python -m pytest tests -q` at `c787757` → **9 failed, 1310 passed, 16 skipped** (author receipt says 1309/9/16; the one-test difference is the extra contract test, M1).

- `test_complexity_diagnostics.py` (4): subprocess stdout `None` after a Windows `UnicodeDecodeError` — environment, reproduced at base.
- `test_fc803_minimal_download.py` (3): “company-wiki ensure exited 1” — reproduced at base.
- `test_policy_containment_fc501.py` (1): message mismatch — reproduced at base.
- `test_fc1307a_host_assumption_gate.py` (1): third vendored copy differs; the company-wiki working tree is being edited by ROOT concurrently, so it **passes at base now** and fails at HEAD for a cross-repo reason. The filing-fetch copy is unchanged by this diff.

None of the 9 failures is in a file changed by `c787757`, and none exercises `transcript_companion`/`transcript_tool_transport`/`transcript_reuse_selection`. The author's “9 pre-existing” statement is substantively right for the card (8 reproduce at base; the 9th is the known concurrent company-wiki drift), though the literal “9 also fail at base” is not reproducible at this moment.

## Findings

### M1 — Minor — stale test counts in the delivery receipts

- **Files:** `docs/plans/du11-ff-transcript-reuse-2026-10-17/receipts/c_test_summary.json:2-18` (`collected: 98`, `contract: 42`, `seconds: 108.51`), `docs/plans/du11-ff-transcript-reuse-2026-10-17/handoff.json:106-117` (same values), `docs/plans/du11-ff-transcript-reuse-2026-10-17/handoff.md:72` (“98 passed，108.51s”), `:75` (“1309 passed”).
- **Actual:** selection **47**, contract **43**, E2E **9** = **99** collected; my run of the three modules was 90 passed (selection+contract) + 9 passed (E2E); full suite **1310 passed / 9 failed / 16 skipped**.
- **Root cause:** `c_test_summary.json` was generated at 23:48 before the last contract test was added to the frozen source (the frozen file has 43); `make_handoff.py` copies the stale receipt verbatim.
- **Minimal fix:** re-run the exact card/central/full commands on `c787757`, regenerate `c_test_summary.json` (99 / 43 / 9, 1310 / 9 / 16), re-run `make_handoff.py`, and update `handoff.md:72,75`. No source change.

### M2 — Minor — `c_mutation_check.json` is internally inconsistent

- **File:** `docs/plans/du11-ff-transcript-reuse-2026-10-17/receipts/c_mutation_check.json:2-5` (`"exit": 0`, `"summary": "1 failed, 47 passed"`), `:10-40` (mutation summaries `47/50/57 passed` for a two-file suite now containing 90 tests).
- **Root cause:** the receipt came from a `-x` run whose captured tail/exit code did not belong to a clean baseline (the source was also being mutated at 23:54, which contaminated one of my own runs); the baseline is self-contradictory and the pass counts are not reproducible.
- **Minimal fix:** rerun `mutation_check.py` on a clean/isolated tree, record the exact command, a clean baseline (`90 passed`), the failing test names per mutation, and `source_restored: true`; or remove the receipt. My independent M1–M7 run already confirms every mutation is detected, so the conclusion stands — the receipt just cannot be trusted as written.

### M3 — Minor — restore harness snapshots before seeding and over-allows additions

- **File:** `tests/test_du11_transcript_reuse_support.py:193` (`_mutable_prefixes = ("companies/", ".source_catalog/", "runtime/")`), `:217` (`self._baseline = self.manifest()` in `build()` before any `seed_*`), `:337-382` (`restore_receipt`/`assert_restored`).
- **Issue:** a mutated/overwritten seeded original or sidecar is not a “changed” entry (it was never in the baseline), and any extra file under `companies/`, `.source_catalog/`, or `runtime/` is accepted as an “allowed addition”. The card requires “初始清单/bytes/mtime” and “无意外残留”; the current receipt is true for the run (the 6 added entries are exactly the seed + DB), and specific E2E tests separately assert the originals count, but the harness itself would not catch a modified seed or an unexpected extra company file.
- **Minimal fix:** take the manifest snapshot **after** seeding (or add the seeded paths to the baseline), and assert the post-run manifest equals the post-seed manifest plus exactly the expected new paths (DB/WAL/lock and the imported original/sidecar), not merely “outside three prefixes”.

### N1 — Nit — stale "Next Step" / errors table in `task_plan.md`

- **File:** `docs/plans/du11-ff-transcript-reuse-2026-10-17/task_plan.md:83` (`(none yet)`), `:87` (“Freeze CWP dependency source list + build the synthetic real CWP fixture for Phase 1 RED”).
- **Issue:** the phase statuses were updated (Phase 0–2 complete, Phase 3 in progress), but the Next Step and the errors table still describe the pre-implementation state; `progress.md` has the real errors.
- **Fix:** update the Next Step to “independent review / fix findings / docs commit” and point the errors table at `progress.md` (or repeat the five errors).

### N2 — Nit — the baseline RED receipt does not bind its FF scripts to `f1a939e5`

- **File:** `docs/plans/du11-ff-transcript-reuse-2026-10-17/receipts/A_RED_baseline.json:66` (`"ff_scripts": "…\\Temp\\du11-baseline-scripts\\scripts"`, now nonexistent) and no per-file SHA.
- **Issue:** the after-fix side is bound by `handoff.json.source_freeze_sha256`, but the baseline side relies on an ephemeral temp path. I independently extracted `f1a939e5:scripts` and reproduced the exact receipt, so the evidence is real; a future reader cannot repeat that from the receipt alone.
- **Fix:** record the `git archive f1a939e5 scripts` SHA-256 (or the three script blob SHAs) in the receipt/probe.

### N3 — Nit — downloaded-provider fallback is a second provenance source

- **File:** `scripts/transcript_tool_transport.py:1012-1015`.
- **Issue:** if the verified reader receipt has no `manifest.provider`, `_import_fetched` falls back to `fetched.get("provider")`. The CWP import contract proves `tool_result.provider == candidate.provider` and FF builds the candidate as `fmp`, so this is a CWP-validated declaration rather than a request default — but it is not “unknown stays unknown”.
- **Fix:** either omit `provider` when the manifest lacks it (and document the acquisition name separately) or state the CWP proof in the comment/receipt so the fallback cannot be mistaken for a default.

### N4 — Nit — `mutation_check.py` mutates tracked source files in the shared worktree

- **File:** `docs/plans/du11-ff-transcript-reuse-2026-10-17/receipts/mutation_check.py:76-85` (`git checkout -- scripts/...` restore), plus the `path.write_text` mutations.
- **Issue:** it writes tracked files and restores via `git checkout`. A concurrent test run (mine at ≈23:54:2x, or the author's own) can read a mutated tree; I saw exactly the M1/M5 failure signature before the restore.
- **Fix:** run the mutations in a copied tree / temporary worktree, never in the review or shared worktree; do not use `git checkout` in a tree another agent may be testing.

### N5 — Nit — `ab_probe.py` caches the frozen tar at a fixed `%TEMP%` path and leaves it

- **File:** `docs/plans/du11-ff-transcript-reuse-2026-10-17/receipts/ab_probe.py:38` (`TAR = $TEMP/cwp34a7dd71-src.tar`), `:139-144` (only creates if absent), `:317-319` (removes only the owned root).
- **Issue:** a stale/wrong tar at that path would be consumed silently (the summary records its SHA, and I verified `555b11a8…` against my own `git archive`; the tar is a residue outside the owned root).
- **Fix:** always recreate (or verify the SHA against the commit) and remove the tar in the `finally`; the evidence itself is honest — I reproduced both A receipts.

### N6 — Nit — `excluded_publication_statuses` is computed but dropped

- **Files:** `scripts/transcript_reuse_selection.py:144-154` (`exclusions()` returns `excluded_publication_statuses`), `scripts/transcript_companion.py:115-120` (`_lookup_unavailable` forwards only `excluded_candidates`/`provider_calls`).
- **Issue:** the aggregate counts are diagnostic only and are lost at the child-result-to-public boundary; not a correctness problem (the named reason and the full list survive).
- **Fix:** forward it alongside `excluded_candidates` or delete the unused aggregate.

### N7 — Nit — literal “candidate without provider” case not separately constructed

- **File:** `tests/test_du11_transcript_reuse_contract.py:55-76` (`query_found` always sets candidate `provider: motley_fool`), `:673-702` (replay).
- **Issue:** the card lists “candidate has no provider but the reader manifest does”; the suite covers the stronger case where the candidate's provider is *wrong* (`motley_fool`) and the manifest is `fmp` (replay test), and the selector never reads `candidate["provider"]`, so a literal absent-provider fixture would add little. This is coverage completeness, not a behavioral gap.
- **Fix:** add one `query_found`-with-no-provider case for literal card coverage (or note in `findings.md` why the wrong-provider case is strictly stronger).

## Verdict

The frozen source commit `c787757` meets the card's A/B/C functional requirements: the reuse scope is source-neutral, the acquisition provider remains the existing FMP configuration, the reused provider comes from the verified reader receipt, the outcome matrix is conservative and call-count-proven, the public request/response schemas are unchanged, and the real offline E2E exercises the frozen company-wiki CLIs with the ET supplier as the only synthetic boundary. I found **0 blockers and 0 majors**. The 3 minor findings (stale test counts, inconsistent mutation receipt, pre-seed restore baseline) and the 7 nits are delivery/evidence-hygiene issues, not product defects; they must be corrected (and the final docs-only handoff commit regenerated) before the author writes `COMPLETE`, and the same reviewer should re-check the final source SHA per the card's process.

**VERDICT: PASS** (reviewed source `c787757a9f0409777fd6d469a90d2371bce706d5`; 0 blockers, 0 majors; 3 minor + 7 nit findings pending in the delivery receipts, none in the frozen source).

---

# Round 2 — re-review of the fixed source

- **Reviewer:** same independent reviewer subagent (distinct from the author), re-reviewing after the author's fixes.
- **Date:** 2026-10-18 (local, Asia/Shanghai).
- **Source head reviewed:** `5dee9a20c1c5952688673caf784fdce4e9391a50` (parent `d16dce21c88459c12ea88b14f36af44617bd8c1b`; base `f1a939e522c22b23659712a8bd2b344f5eb0a364`). `d16dce2` = review fixes; `5dee9a2` = restore-checkpoint assertion + harness self-tests.
- **Docs-only HEAD:** `6cb8bf76db4196c42406ac1727e5b83608cf0fa2` (parent `5dee9a2`). I verified `git show --name-only 6cb8bf7` contains **no** path outside `docs/` (nothing under `scripts/` or `tests/`).
- **Tree state:** `git status --porcelain` clean before and after every command. My only tree change is this report section.
- **Source blobs / raw SHA-256 of the frozen head:** transport `02eb471b2e715634420191ab770e9aa24e5177c6` / `20f8903df96af64de94d3ce6959ecdb0a36555589f6c410a8e83e9f9a6276999`; companion `83086a90e90ddca0ae8663578a477b7f119d2ea6` / `7e3f28a5928270850af308b9d20f4187cbaa985f1e0a5b4dffb83c3a1c0084be`; selection `b6449812704bb95a0df396cdcc204a4def4a1007` / `8591e9968d5d23c4e056a32062ea4b4fdbac63c3421523d921f3176d93823231`; contract `9ee5241ba6ae97bd3d987925eb283ca50db8edf0` / `df85a5a871ecd88bc5a111d618110ecdb4768b8ef92859605f13fef9ae000555`; E2E `386db8f16464e75d341fa6d4470bd896498225d6` / `eecd5edb16abf4be818fcec84f7a65675076d0cf7afcfb5cf34d54e6ffd97b09`; support `8b24cbac26aa99254fa518b49bf676252f6fdd0a` / `1adedc50acb402a098754ab1f853e89b430299093421ca93a008e29180dbdd2a`.

## Round 2 commands and results

| # | Command | Result |
|---|---------|--------|
| 1 | `git log --oneline -6`; `git rev-parse HEAD HEAD^ '5dee9a2^' '6cb8bf7^'`; `git status --porcelain` | history exactly `f1a939e → c787757 → d16dce2 → 5dee9a2 → 6cb8bf7`; parents verified; clean tree |
| 2 | `git show --name-only --pretty=format: 6cb8bf7` filtered to non-`docs/` paths | empty — docs-only handoff commit confirmed |
| 3 | `git diff --stat d16dce2..5dee9a2`; `git diff --name-status f1a939e5..5dee9a2` | `5dee9a2` changes only `tests/test_du11_transcript_reuse_support.py` (+122/−1); the full card diff is exactly the 8 whitelisted paths (3 scripts incl. the new selection module, 4 test files, 1 fixture) |
| 4 | `python -m ruff check scripts tests` | `All checks passed!`, exit 0 |
| 5 | `python -m pytest tests/test_du11_transcript_reuse_support.py -q` | **7 passed in 3.70 s**, exit 0 |
| 6 | `python -m pytest tests/test_du11_transcript_reuse_selection.py tests/test_du11_transcript_reuse_contract.py -q` | **92 passed in 0.56 s**, exit 0 (47 selection + 45 contract) |
| 7 | `python -m pytest tests/test_du11_transcript_reuse_e2e.py -q` | **10 passed in 107.13 s**, exit 0 (real frozen-CWP CLIs; new explicit-fmp positive control included) |
| 8 | 10-module central regression | **257 passed, 3 skipped in 13.23 s**, exit 0 |
| 9 | `python -m pytest tests -q -p no:randomly` | **9 failed, 1320 passed, 16 skipped in 297.79 s** — exactly the author's receipt; the same 9 failures as round 1's HEAD run (8 reproduce at base; the `test_fc1307a` cross-repo guard reflects ROOT's concurrent company-wiki edit), no new failure |
| 10 | `python receipts/mutation_check.py --out %TEMP%\…` (isolated copy; worktree hashes captured before/after) | baseline **92 passed**; M1 3 failed/89, M2 3/89, M3 1/91, M4 6/86, M5 7/85, M6 1/91, M7 3/89; `undetected: []`; `pristine_restored`, `shared_worktree_untouched`, `isolated_tree_removed` all true; worktree source hashes unchanged; no `du11-mutation-*` left |
| 11 | M3 sensitivity: isolated copy of `scripts/`+`tests/` with the new `assert receipt["changed_since_checkpoint"] == []` line removed, then `pytest tests/test_du11_transcript_reuse_support.py` | **2 failed, 5 passed** — `test_restore_harness_detects_a_modified_seed` and `…_modified_sidecar` fail without the assertion, proving it is load-bearing |
| 12 | `python receipts/ab_probe.py --ab --out-dir %TEMP%\…` | baseline `downloaded/fmp/1 ET/3 CWP`, `ff_commit.archive_tar_sha256 = 97081d83…` (matches my independent `git archive f1a939e5 scripts pyproject.toml`), per-file hashes match the committed baseline receipt; after-fix `reused/motley_fool/0 ET/2 CWP`, per-file hashes `7e3f28a5/20f8903d/8591e996` match the current frozen source; both `owned_temp_removed`; no `du11-ab-*`/tar left |
| 13 | `python receipts/restore_probe.py --out %TEMP%\…` | `reused/motley_fool/0 ET/2 CWP`; initial 362 / checkpoint 366 / current 368; `changed_since_checkpoint=[]`, `catalogue_or_runtime_changed=[]`, `removed_since_checkpoint=[]`, `canonical_import_added=[]`, `unexpected_added=[]`, `frozen_source_changed=[]`, `restore_entry_changed=[]`; sentinel + existing.out present; cleanup removed; matches the regenerated `c_restore_receipt.json` |
| 14 | final `git status` / source blob hashes | clean; hashes unchanged from the frozen head |

## Round-2 finding-by-finding verification

| Round-1 finding | Fixed? | Independent evidence |
|---|---|---|
| **M1** stale test counts | **Yes** | card tests **109** = 47 selection + 45 contract + 10 E2E + 7 harness self-tests (all four runs above sum to 109); central **257/3**; full **1320/9/16**; `c_test_summary.json` and `handoff.md` §5 match; `-p no:randomly` used for the full run |
| **M2 + N4** inconsistent mutation receipt / shared-worktree mutation | **Yes** | `mutation_check.py` rewrites nothing in the worktree: it copies `scripts/`+`tests/`+`pyproject.toml` into `tempfile.mkdtemp(prefix="du11-mutation-")`, runs a clean baseline **92 passed**, applies 7 mutations there, records the failing test names, restores from the pristine text, verifies `pristine_restored`, and removes the tree. My independent rerun gives the same 7/7 detections and leaves the worktree hashes unchanged |
| **M3** pre-seed baseline / modified seed not detected | **Yes** | `checkpoint()` after seed+scan; `assert_restored()` now asserts `changed_since_checkpoint == []`; `catalogue_or_runtime_changed` separates the DB/log changes. 7 harness self-tests pass; removing the assertion in an isolated copy makes the modified-seed and modified-sidecar tests fail (2 failed/5 passed); the regenerated `c_restore_receipt.json` has the new shape and my `restore_probe` run reproduces it |
| **N1** stale task_plan Next Step/errors | **Yes (residual bookkeeping)** | task_plan statuses are complete/in-progress and the errors table now points at `progress.md`; the Next Step however still names `d16dce2` (see R2-2) |
| **N2** baseline A receipt not SHA-bound | **Yes (residual label)** | `ab_probe.py --ab` extracts `f1a939e5:scripts` itself and records `ff_commit.archive_tar_sha256 = 97081d83…` plus per-file `ff_scripts_sha256`; baseline behavior unchanged; see R2-1 for the after-fix commit label |
| **N3** downloaded-provider fallback comment/test | **Yes** | comment now names the CWP `tool_result.provider == candidate.provider` proof and the "neither exists ⇒ omit" rule; `test_a_download_without_manifest_or_declared_provider_keeps_provider_unknown` passes |
| **N5** frozen tar outside owned holder | **Yes** | `ab_probe.py` rebuilds the CWP tar at `holder/cwp.tar`, hashes it, and removes the holder in `finally`; my run left no `du11-ab-*` directory or tar |
| **N6** `excluded_publication_statuses` dropped | **Yes** | forwarded by `transcript_companion._lookup_unavailable`; verified by code reading. No dedicated assertion exists (the aggregate is covered by the selection test) — see R2-3 |
| **N7** literal candidate-without-provider case | **Yes** | `test_a_candidate_without_any_provider_is_reused_with_the_manifest_provider` exists and passes |
| **Extra** explicit-fmp positive control | **Yes** | `test_real_cwp_explicit_fmp_lookup_finds_and_reuses_its_own_source` passes inside the 10 E2E cases: real import → plain `found` → envelope `found` → explicit-fmp replay `reused` with `provider_calls=0`, one ET call total |

## Residual findings (round 2)

### R2-1 — Nit — `A_RED_after_fix.json` names the wrong commit for its script hashes

- **File:** `docs/plans/du11-ff-transcript-reuse-2026-10-17/receipts/A_RED_after_fix.json:66-69`.
- **Evidence:** `ff_commit.commit = c787757…`, but `ff_scripts_sha256` are `7e3f28a5…` (companion), `20f8903d…` (transport), `8591e996…` (selection), which are the **`d16dce2`/`5dee9a2`** scripts, not `c787757` (`c787757` companion = `59b3ae1c…`, transport = `d8aea60a…`). The receipt was measured from the fixed worktree while HEAD was still `c787757` (`worktree: true`); a re-run today records the docs HEAD `6cb8bf7`, so `git rev-parse HEAD` is not a stable source binding.
- **Impact:** the per-file hashes are correct and authoritative, so the A evidence itself is valid; the `commit` label can mislead a reader who checks the commit rather than the hashes.
- **Minimal fix:** record the source head explicitly (`"source_commit": "5dee9a2…"` / `"source_commit": "d16dce2…"`) or add a `--source-commit` argument to `ab_probe.py`; leave the per-file hashes as the binding.

### R2-2 — Nit (bookkeeping) — task_plan/handoff still reference `d16dce2` / round-1

- **Files:** `docs/plans/du11-ff-transcript-reuse-2026-10-17/task_plan.md:63,68,90` (“fix all findings → source commit `d16dce2`”, “final re-review of `d16dce2`”) and `docs/plans/du11-ff-transcript-reuse-2026-10-17/handoff.json` `independent_review` (`reviewed_source_sha: c787757…`, `status: PASS_REVIEW_1_FIXED_AWAITING_FINAL`, `rounds: … round2 re-review pending`).
- **Issue:** the final source head is `5dee9a2`, and this round-2 review is now complete; the PWF must be updated before `COMPLETE` (the docs commit `6cb8bf7` predates this section).
- **Minimal fix:** in the follow-up docs-only commit, point task_plan at `5dee9a2`, add this round-2 result to `handoff.json.independent_review` (`reviewed_source_sha: 5dee9a2…`, `status: PASS`, `unresolved_findings: 0` after R2-1 is fixed, report `receipts/reviewer_report.md`), and set `final_delivery_commit` to that docs commit.

### R2-3 — Observation — N6 forwarding has no dedicated assertion

- The companion now forwards `excluded_publication_statuses`, and the selection test covers `Selection.exclusions()`; no contract test asserts the forwarded key in the child result. This is diagnostic-only and not a defect; a one-line assertion in the existing gap test would close it.

## Round-2 compatibility / scope

- Source diff `c787757..5dee9a2` = the same 8 whitelisted paths as round 1; no new file outside the card whitelist; `scripts/ff_v2_envelope.py`, `fetch_filing.py`, `filing_contracts.py`, `config/`, `tools/offline_contract_matrix/`, CWP/ET and skill installs untouched.
- Public request schema and v2 response keys unchanged; `motley_fool` still rejected as a request option; unknown provider still omitted rather than relabelled `fmp` (N3 test).
- New tests are all under `tests/test_du11_transcript_reuse*.py`; the support self-tests use only a miniature frozen-source tar and a `TemporaryDirectory`, no CWP/ET execution and no network.

## Round-2 verdict

The fixed source head `5dee9a2` resolves all three round-1 minors and all seven nits. I independently reproduced the claimed counts (109 card tests, 257/3 central, 1320/9/16 full suite), the isolated mutation receipt (92 baseline, 7/7 detected, worktree untouched), the strengthened restore checkpoint (assertion load-bearing; 7 self-tests; regenerated restore receipt), the A/B behavior (baseline downloaded/fmp/1 ET/3 CWP vs after-fix reused/motley_fool/0 ET/2 CWP) and the new explicit-fmp positive E2E. The only remaining items are two non-source nit/bookkeeping items (R2-1, R2-2) and one observation (R2-3); they require no source change, and the source SHA remains `5dee9a2`.

**FINAL VERDICT: PASS** for source head `5dee9a20c1c5952688673caf784fdce4e9391a50` — **0 blockers, 0 majors, 0 source minors; unresolved = 2 non-source nits (R2-1 A-receipt commit label, R2-2 pending post-review handoff update) + 1 observation**. Fix R2-1/R2-2 in the follow-up docs-only commit (R2-1 is a one-line/source-commit-field fix; R2-2 is the handoff/task_plan bookkeeping for `5dee9a2`); no source re-review is needed for these docs-only fixes.
