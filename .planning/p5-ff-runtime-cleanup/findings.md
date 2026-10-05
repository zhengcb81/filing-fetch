# P5-FF Runtime Cleanup — Findings

Base `d4d2fac`. Key locations mapped below (real-file verified 2026-10-05).

## A. Old worker orchestration in scripts/fetch_filing.py

- Block comment + context: L493-507 (`_PAUSE_REFCOUNT_NAME`,
  `_PAUSE_OWNER_NAME`, `_WORKER_STATUS_TIMEOUT`).
- `_catalog_dir` L510, `_pid_is_alive` L514-535,
  `_read_pause_entries`/`_write_pause_entries`/`_prune_pause_entries`
  L538-558.
- `PausedWorkerScope` class L561-706 (`__enter__` worker-status probe +
  join/respect/first-pause logic; `_register`/`_unregister` refcount+owner
  persistence; `__exit__` worker-resume).
- Scope call sites: `_resolve_source_ref_v2` L1095-1102,
  `_run_legacy_filing_command` L1152-1159, `_close_gap_and_return_handle`
  L1583-1591. Each also appends `--allow-acquisition-while-paused` to the CWP
  argv when pause_worker is set.
- `pause_worker=` kwargs threading: `resolve_filing` L1235-1237 →
  `_resolve_source_ref_v2` L1332-1334, `_run_legacy_filing_command`
  L1341-1343, `_close_gap_and_return_handle` L1375-1377.
- CLI args: `--no-pause-worker` L1707-1714, `--worker-graceful-timeout-seconds`
  L1715-1720, `--worker-resume-wait-seconds` L1721-1726; wired at
  L1776-1778.
- Error taxonomy: `worker_paused` kept in `filing_contracts.py`
  `_ERROR_TAXONOMY` (L63-68) and `_classify_wiki_error` L366-374 — the code
  stays valid as an upstream-reported status; only the caller-side pause/
  resume orchestration is being deleted.

## B. Bounded-process gaps

- `scripts/fetch_filing.py::_run_company_wiki_json` L281-344:
  `subprocess.run(..., capture_output=True)` then
  `len(completed.stdout) > MAX_JSON_OUTPUT_BYTES` (L331) — truncation only
  AFTER full buffering; `len(str)` counts Python chars, not UTF-8 bytes.
- `scripts/transcript_tool_transport.py`:
  - `_run_json` L107-136: same capture-then-truncate at L128; cap constant
    `MAX_JSON_OUTPUT_BYTES` defined L23.
  - `_verified_open` L186-234: stdout hashed after full capture; stderr
    receipt size checked post-hoc at L218.
  - `_et_result` L280-395: post-hoc stdout cap at L350.
- timeout kills direct child only; grandchildren holding pipes can hang
  `communicate()`. None of the current call sites create job objects or
  process groups (only `CREATE_NO_WINDOW` on Windows).

## C. Compat surfaces to keep

- `resolve_filing(...)` signature unchanged (pause kwargs stay as accepted
  no-op compat args; no new dual gate).
- `--source-ref-v2` flag remains accepted (v2 auto-selected for v2 requests).
- Wire schemas: SourceRef `2.0`; FF operation `/1`; ET request `/1` /
  payload `/2`; CWP transcript import request `/2` / response `/3` untouched.
- `MAX_JSON_OUTPUT_BYTES = 32 MiB` stays the shared cap.
- ET `_ET_CLEANUP_GRACE_SECONDS = 3.0` outer cleanup window unchanged.

## Test file reuse plan (card 5)

- Update in place: test_fetch_filing (drop pause-scope assertions),
  test_s3_single_request_limits (bound re-checks).
- New: tests/test_p5_process_transport.py, test_p5_worker_scope_retirement.py,
  e2e/test_p5_ff_process_runtime.py.
