# Progress

2026-10-09: exact worktree baselines verified. RED tests authored; not yet run.

RED actual: FF6FAIL/1PASS; ET8FAIL. Raw failure logs not retained because pytest env repr exposed a suspected host credential; diagnostic_incident.json records field/operation only. Tests now use synthetic launch environment.

Final local GREEN: FF203PASS/1 existing snapshot skip/39subtests22.90s; final wire42PASS2.54s; ET116PASS44.72s. Ruff/mypy/host guard green. ET branch committed1d03de61. No paid/live API, install or main edits. Own fixtures cleanup recorded; FF containing commit closes this lane local delivery. MAIN M2/M3 pending.

2026-10-09 M2 repair: independent review temporarily refused FF f2182732 / ET 1d03de61. Added decoded content/key/array/duplicate-key, decoded reason and valid receipt-contamination cases first: FF 10 FAIL / ET 10 FAIL against original delivery. Old red_summary.json, green_summary.json and diagnostic_incident.json retained unchanged. No raw RED log retained.

Final repair GREEN: FF launch/companion/S0b suites 67 PASS, 0 skips, 7.00s; ET launch/API/cost-capability suites 73 PASS, 0 skips, 11.35s. FF's two actual child runs distinguish clean receipt (fixture request 1/start true/complete) from escaped contaminated receipt (null/null/incomplete). ET's two actual supervisor CLI runs reject escaped content before v1 text or v2 original payload, retain fake HTTP measurement and remove runtime files. Ruff and git diff --check green in both repair writes. ET normal follow-up commit c91f5f54bc2a24e7b5d6e648dba3f9d578f5fa52; FF containing commit closes this local repair delivery. No hook bypass, merge, push, install, external HTTP or production configuration/key change.

Five explicit M2 pytest TEMP roots removed after terminal tests, paths checked under TEMP and reparse handling kept inside owned roots. m2_cleanup.json records 623679 bytes removed; branch worktrees retained for independent re-review. MAIN M2 acceptance remains pending; live M3 authentication and entitlement were not attempted.
