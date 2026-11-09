# ff-job/1 — filing-fetch durable job façade protocol

Owner: filing-fetch. Protocol: ff-job/1.

`ff-job/1` is the public job surface Dashboard's MODULE-m8-FF-executor binds to.
It wraps the existing short-request engine (`scripts/fetch_filing.py` v2 and
`scripts/fetch_statements.py` semantics) in a durable, cross-process job layer.
The filing job and the short-request CLI use the same public v2 result
completion operation and deadline for the filing and its optional transcript.
Both short-request CLIs retain their request/response contracts, exit codes
and limit validation.

## Execution model (declared)

- `submit` persists a queued job and returns immediately. It never runs the
  engine and never touches the network.
- `run --owner-job-id` executes one queued job through the bounded engine,
  blocking until the job lands a terminal state. The engine call is bounded by
  `--timeout-seconds` and, for fetching intents, by the request's own
  `acquisition_limits`.
- Dashboard's adapter drives `submit` → `run` → `get_status` polling. A run
  that cannot prove its outcome (owning process died) is reported as
  `unknown`, never guessed.

## CLI surface (fixed argv, one JSON answer on stdout)

```
ff_job.py [--jobs-dir DIR] [--pretty] <subcommand> ...
  submit        [--request-file PATH]              # body on stdin or file
  run           --owner-job-id ID [--config PATH] [--timeout-seconds S]
  get_status    --owner-job-id ID
  allowed_actions --owner-job-id ID
  act           --owner-job-id ID --action cancel|retry|reconcile
                --idempotency-key KEY [--config PATH] [--timeout-seconds S]
  list_jobs     [--cursor ID] [--limit N]
```

`--jobs-dir` and `--pretty` are global options and must precede the
subcommand. `list_jobs` returns the frozen Dashboard `JobPage` envelope:
`{"items": [JobView...], "page": {"next_cursor", "snapshot_id", "total",
"total_status"}}` where `total` counts every durable job (`total_status:
"exact"`) and `snapshot_id` identifies the job-id set the page was cut from.
`list_jobs` reports stored state as-is (it does not re-evaluate run
liveness); `get_status` is the authoritative read that may flip a lost run
to `unknown`.

Exit codes follow the house convention: `0` = a valid answer (including a
business-level failed/cancelled job state), `2` = request/config error with a
named envelope, `1` = fatal/unexpected.

No request field may carry a filesystem path, a command string, or a
credential. Engine configuration arrives only through the operator's
`--config` deployment knob (registered by Dashboard as `ff_config`), and the
job store location only through `--jobs-dir`.

## Submit body

```json
{
  "schema_version": "ff-job/1",
  "command_id": "dash-command-id (echoed back in every JobView)",
  "kind": "filing.acquire | statements.acquire",
  "idempotency_key": "[A-Za-z0-9._:~/-]{1,256}",
  "request": { ...native engine request... }
}
```

- `kind=filing.acquire`: `request` is a **v2 filing request**
  (`schema_version: "2.0"`, `filing_intent: reuse_only | fetch_if_missing`,
  validated by the unchanged `filing_contracts.validate_request`). A v2
  request cannot express `refresh`; that statements-only intent is a named
  request error here.
- `kind=statements.acquire`: `request` is an unchanged
  `financial-statements-request/1` body (`intent: reuse_only |
  fetch_if_missing | refresh`, validated by the unchanged
  `ff_financial_statements.validate_request`); the job layer additionally
  enforces the same ≤2-decimal `max_cost_usd` fee string the filing contract
  uses.
- `limits_ref` is materialized as the request's own `acquisition_limits`
  (`max_bytes` positive int / `timeout_seconds` finite positive /
  `max_cost_usd` decimal string ≤2dp) — the same three ceilings the legacy
  CLIs already enforce. `reuse_only` forbids them (except the engine's own
  `latest_as_of` rule, unchanged).

## Idempotency (G-m8-FF-03)

One `idempotency_key` binds to exactly one job:

- same key + same canonical request → the existing `owner_job_id` and its
  current record are returned (`idempotent_replay: true`); nothing is
  re-acquired, the record's `attempts`/`execution_count` are untouched;
- same key + different request → `request_error` (named conflict, never a
  silent second acquisition);
- running an already-terminal job is a no-op (`engine_executed: false`);
- a short owner-local OS lock serializes pointer and job publication. The
  lock releases when a submitter exits. A retry repairs a dangling or
  partial legacy pointer and replays a matching job already on disk.
  Submitters keep one binding even when a live writer is temporarily slow.

Actions carry their own `(action, idempotency_key)` receipts with the same
replay guarantee.

## JobView projection (Dashboard contract fields)

| field | projection |
|---|---|
| `command_id` | echoed from the submit body |
| `owner` | `"filing-fetch"` |
| `owner_job_id` | `ffjob-<12 hex>` |
| `status` | `queued → running → succeeded | failed | cancelled`; `unknown` when a run cannot prove its outcome |
| `status_known` | `false` only for `unknown` |
| `allowed_actions` | declared vocabulary, see below |
| `started_at` / `updated_at` | UTC ISO-8601 |
| `cost` | Dashboard DecimalValue shape, all 12 contract fields (`value`/`currency`/`unit`/`scale`/`period_*`/`fiscal_year`/`basis`/`scenario`/`actual_or_forecast`=`"actual"`/`analysis_subject_id`) |
| `cost_state` | `known | unknown | not_applicable` |
| `error` | Dashboard ApiError shape (`code`/`message`/`owner`/`retryable`/`next_actions`/`correlation_id`) or null |
| `recovery_capability` | `durable_owner_job` for both acquire kinds |
| `kind` / `intent` / `idempotency_key` / `attempts` / `execution_count` | owner-native extensions |
| `result` | pathless return context (closed whitelist; physical-location guard enforced) |

Owner-native `result` shapes:

- filing.acquire: `status`, `resolution_outcome`, `download_events`,
  `source_ref`, `gap_hash`, `reason`, `calls`, `downloads`, plus
  `derived_by: "reconcile_read_only"` when a reconcile landed the state.
- statements.acquire: `status`, `statement_count`, `usage`
  (`http_requests`/`response_bytes`/`cost_usd`), `calls`, `downloads`.

## Allowed actions (declared vocabulary)

- `queued` → `["cancel"]`
- `running` → `[]` — the engine is one bounded subprocess call with no
  interruption point; a running job is never advertised a cancel it could not
  honour.
- `succeeded` → `[]`
- `failed` / `cancelled` → `["retry"]` only when the recorded spend evidence
  proves a re-run cannot double-spend. A queued cancellation has no
  prior attempt. A finished attempt needs complete no-start and zero-download
  evidence. Otherwise `[]` and a retry attempt is a named refusal.
- `unknown` → `["reconcile"]` — exactly one action, per COMMON-02.

`resume` is not offered: a single bounded short request has no pause point.

## Cost projection (G-m8-FF-03 / COMMON-03)

A budget ceiling is never reported as a cost.

| evidence | cost | cost_state |
|---|---|---|
| all stages `reuse_only` (any state) | null | `not_applicable` |
| queued fetch job | null | `not_applicable` (not spent, may still spend) |
| running fetch job | null | `unknown` |
| complete no-start evidence and no committed download | `0.00` USD | `known` (`engine_zero_evidence`) |
| complete reported cost (filing `acquisition_observation.cost_usd`, statements `usage.cost_usd`) | that value | `known` (`provider_reported`) |
| missing fee evidence, incomplete usage, or lost run | null | `unknown` |

A companion with its own acquisition intent can spend even when the filing
is reuse-only. The job keeps the submitted filing intent in its view. A
companion that might have spent without a complete fee account keeps total
cost unknown, even when the filing's cost is known. Both stages share the
earliest effective filing deadline. The companion can impose a shorter cap.

## Unknown → reconcile (G-m8-FF-04)

A run writes its owner pid and its own deadline before the engine call. Any
reader that finds a running job whose pid is dead, or whose deadline plus a
120 s grace has passed, flips it to `status: "unknown"`,
`status_known: false`. A failed acquiring call with an incomplete
usage receipt also lands unknown, since the process may already have
committed data or incurred a fee.

`reconcile` re-checks the owner's actual state through the **read-only reuse
path** of the same engine: the stored request is stripped of its download
intent and its `acquisition_limits`, so the query can never acquire anything.
The answer lands as `succeeded` (data present) or `failed` (data absent) with
`derived_by: "reconcile_read_only"`; the interrupted run's spend stays
`unknown` because a read-only query cannot certify it. Reconcile never
re-sends a download. An absent result does not authorize retry.

## Durable store layout (`--jobs-dir`, default `<skill_root>/.ff_jobs`)

```
jobs/<owner_job_id>.json        full record, atomic replace + fsync
index/idem/<sha256(key)>.json   idempotency pointer
index/idem/.submit.lock        owner-local submission lock
locks/<owner_job_id>.lock       per-job OS lock on a stable file
logs/<owner_job_id>.log         append-only engine audit trail (JSON lines)
```

Every state a Dashboard can observe lives in these files; the CLI keeps no
in-memory ledger, so any process (or a restarted machine) sees the same job.
When upgrading an existing jobs directory, let prior-version writers exit
before starting writers with this lock protocol. Existing job IDs and index
files are retained.

## Recovery capability declaration (COMMON-02)

- `filing.acquire` / `statements.acquire` jobs: `durable_owner_job` — the
  durable record survives restarts, a lost run is detected and reconcilable,
  and retry is guarded against double spend.
- The legacy single-shot CLIs (`fetch_filing.py`, `fetch_statements.py`)
  remain `short_request_only` and are untouched by this layer.

## What this layer deliberately does NOT do

- It does not background executions inside `submit` (no orphan processes on
  the host); Dashboard drives `run` explicitly.
- It does not cancel a running engine call (no interruption point exists);
  cancel is queued-only by declaration.
- It does not express `refresh` for filings (the v2 filing contract has no
  such intent); statements jobs support all three statements intents.
- It does not certify the spend of a lost run; reconcile lands state, cost
  stays `unknown`.
