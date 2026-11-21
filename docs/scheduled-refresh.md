# Scheduled company document refresh

`scripts/ff_scheduled_refresh.py` coordinates a named roster, bounded source discovery,
existing FF jobs, and incremental reading through company-wiki. The control API is
available without the timer. The profile is disabled until configured explicitly.

## Deployment

Keep the existing `--config` for the company-wiki connection and ET settings. Place the
schedule deployment next to it as `scheduled_refresh.json`, or pass `--refresh-config`.
The deployment file stays local. Dashboard uses the exact same FF config and jobs directory.

```json
{
  "schema_version": "ff-scheduled-refresh-deployment/1",
  "universe_origin": "http://127.0.0.1:8766",
  "stockwiki_identity": {"root": "<StockWiki code root>", "workspace": "<IQS identity workspace>"},
  "pinned_rosters": "scheduled-rosters.json",
  "lookback_days": 30,
  "overlap_days": 7,
  "limits": {
    "tick_seconds": 240, "metadata_pages": 64, "acquisitions": 8, "reading_documents": 6,
    "discovery": {"max_bytes": 8388608, "timeout_seconds": 45, "max_cost_usd": "0.00", "max_requests": 6},
    "acquisition": {"max_bytes": 67108864, "timeout_seconds": 120, "max_cost_usd": "0.00"},
    "reading": {"timeout_seconds": 120}
  }
}
```

- Dynamic roster reads use the existing IQS loopback Universe and the StockWiki public
  identity bridge. Set the workspace that actually owns those IQS entities. A member
  lacking an unambiguous active listing contributes a coverage reason. Resolve it
  explicitly in the owner system or select that listing in a pinned roster.
- A pinned export uses `{"rosters":{"<ref>":{"snapshot_id":"<owner snapshot>","items":[...]}}}`.
  Every row contains `entity_id`, `listing_id`, `market` and `ticker`, with optional `exchange`.
  The source and listing are verified by the owner before candidate acquisition.
- Configure deployment commands for `incremental_discover`, `incremental_backlog`,
  `incremental_read`, and `incremental_read_status` when the installed CWP does
  not publish them under its catalog CLI. Commands are configured locally in the
  existing connection. The status command is lookup-only by `run_id`.
- Windows Python needs the configured IANA time zone database. System zoneinfo or
  the `tzdata` distribution supplies it. Controlled startup uses the configured
  interpreter's normal subprocess path.

## Public control

`status` reads current settings and the latest run. `configure --request-stdin` accepts
`ff-scheduled-refresh-config/1` and returns the updated status. `runs --cursor …` pages
compact receipts. The Dashboard owner can use these calls without launching a scan.

```json
{
  "schema_version": "ff-scheduled-refresh-config/1",
  "settings": {
    "enabled": false,
    "cadence": {"frequency": "weekly", "weekday": 1, "local_time": "07:30", "time_zone": "Europe/London"},
    "roster": {"mode": "pinned", "roster_ref": "three-company-pilot"},
    "document_kinds": ["annual_report", "semi_annual_report", "quarterly_report"],
    "transcripts_enabled": true,
    "reading_level": "local",
    "backlog_enabled": true
  }
}
```

Once the bounded pilot has passed, `tick` checks for work under the selected settings.
The same due slot is reused across repeated launches. A coverage gap cannot advance
the discovery watermark past missing data. Candidate and reading work retain their
owner IDs, including unresolved cost. The independent `transcript.acquire` job uses
the original exact-period ET transport and the CWP transcript import. It needs a
proven FY/Q and can run when the matching filing is absent.

## Windows task

Use the same explicit `--config`, `--refresh-config`, and `--jobs-dir` for the installer,
the Dashboard owner and manual checks.

```
python -B scripts/ff_scheduled_windows.py preview --config CONFIG --jobs-dir JOBS
python -B scripts/ff_scheduled_windows.py install --config CONFIG --jobs-dir JOBS
python -B scripts/ff_scheduled_windows.py remove --config CONFIG --jobs-dir JOBS
```

`preview` prints the definition without installing a task. After the real pilot,
`install` registers the current user's logon and periodic triggers. Its `pythonw.exe`
launcher starts the normal interpreter without a console. The task may remain
registered when the FF profile is off. A disable orders against the next action's
admission, so an already admitted action can still land its result. Changing
the allowed work scope resumes eligible jobs and reconciles old reads through
their original IDs. If task ownership or state cannot be verified, the installer
leaves the existing registration receipt alone.

The FF run log and existing FF job receipts hold the operational history. If the
native feedback host supplies `RESEARCH_FEEDBACK_OUT`, the schedule's terminal
observation joins the usual FF job observations. It is safe to start with recording
only local reading before enabling the configured summary mode.
