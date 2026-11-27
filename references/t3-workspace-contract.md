# T3 live workspace owner contract

`ff_t3_receipt.py run-live --run-id ID --config FILE` looks for the explicit
`connection.commands.t3_workspace` operation in the existing FF connection
file. Without that binding the new run records all four cases as blocked
with `workspace_not_configured`. Old receipts remain readable through
`get --run-id` and `get --latest`. Install the CWP owner command and bind
it in the actual SYSTEM configuration before running a new live ID.

FF sends one UTF-8 JSON object on stdin and receives one JSON object on
stdout. The request schema is `cwp-t3-workspace-request/1`. The response
schema is `cwp-t3-workspace/1`. Every response echoes `operation`,
`run_id` and `case_id`. Case IDs remain `cn_annual`, `hk_annual`,
`us_annual`, and `corrupt_original`.

| Operation | Extra request fields | Required response fields and ownership |
|---|---|---|
| `open` | | `status=opened`, opaque `workspace_id` and an isolated `connection` with absolute `cwd` and existing FF-compatible `commands`. The workspace uses the configured CWP provider code with independent mutable state. For `corrupt_original`, seed, index and corrupt one disposable source inside that workspace before binding the commands. No provider work on open. |
| `observe` | `workspace_id`, `checkpoint` | `status=observed`, echoed workspace and checkpoint, and `facts`. At `first`, return verified `source_id`, `sha256`, `mtime_ns`, `downloaded_new`, `provenance_complete` and `no_residue`. Provenance covers matching issuer/filing type, source URL, filing date, captured byte hash and retrieval trace. At `reused`, return `source_id`, `sha256`, `mtime_ns`, `downloaded_new`, `reused_before_download` and `no_residue`. At `corrupt`, return `corrupt_original_unchanged`, `downloaded_new` and `no_residue`. CWP owns every fact involving bytes, paths, metadata or its acquisition journal. |
| `close` | `workspace_id` | `status=closed` plus echoed workspace after cleanup. CWP needs a bounded, idempotent cleanup for a lost open response or abruptly terminated FF process, keyed by the original run and case. |

FF uses the same `fetch_filing.py` entrypoint against the returned isolated
connection for the first and second requests. It compares source identity
and reuse against CWP's observations. Existing request budgets remain 50 MiB,
180 seconds and zero provider fees per acquisition request. FF seals the
original ID before dispatch. Reading or repeating that ID uses the original
receipt. Only explicit `run-live` can start a probe.

The FF transport contract has a local subprocess fixture. The deployed CWP
sources currently expose catalog, source query, source open, and ingestion
operations. The isolated workspace owner described here still needs a CWP
implementation and deployed binding to enable live T3.
