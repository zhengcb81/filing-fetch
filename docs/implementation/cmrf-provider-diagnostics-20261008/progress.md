# R6-FF-CAUSE progress

- 2026-10-08 (1): worktree/baseline/branch verified against worktrees.json
  (697af966475a4aa7bb0687c78bfb81a7edb54f21, clean). Card, harness README,
  handoff_interface, shared root-cause plan, FF SKILL, FF repo layout read.
- 2026-10-08 (2): read-only CWP survey done — error emission is
  `structured_error` {status,error_type,error,retryable} on stderr exit 1
  (error-taxonomy-1.1; 6 machine codes), no provider_started/usage fields;
  adapter-level machine codes/usage dropped at CLI boundary (see findings.md
  observation table + gaps G1–G3 for MAIN).
- 2026-10-08 (3): task_plan.md + findings.md written; design frozen
  (six-key upstream_cause/1; single shared stderr parse; honest-null rule;
  retry semantics untouched).
- 2026-10-08 (4): RED recorded — contract suite 24 failed / 2 passed
  (AttributeError: no upstream_cause; ModuleNotFoundError ff_provider_cause),
  CLI suite 5 failed / 5 passed (KeyError missing field; TypeError kwarg).
- 2026-10-08 (5): GREEN — added scripts/ff_provider_cause.py (closed-vocab
  parser/builder/validator, all functions ≤10 McCabe after splitting
  validated_cause's header check); wired _run_company_wiki_json /
  _retry loop (last-cause survival) / _run_source_query; FilingFetchError
  optional validated upstream_cause kwarg; v1 top-level field; v2 inside
  filing via error_envelope(upstream_cause=...). 36/36 new tests green;
  full offline suite 552 passed / 6 skipped; isolated-wiki + conformance
  21 passed / 1 skipped; ruff + mypy + complexity ratchet clean.
- 2026-10-08 (6): concentrated E2E run_isolated_cause_e2e.py PASS 25/25
  (real CWP CLI via PYTHONPATH read-only, isolated tmp wiki, fake bounded
  CN provider with start/HTTP/usage log; A broken-config 6/6, B typed
  provider failure 7/7 with honest-null cross-check, C1 import 5/5,
  C2 SourceRef byte-verified reuse 7/7). Temp roots cleaned; earlier --keep
  roots removed manually; report JSON kept beside the script.
- Next: HANDOFF.md + handoff.json, final gate re-run, branch commits.
