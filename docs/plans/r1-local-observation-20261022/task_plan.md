# FF local preparation observation

Base a1cb84da; branch codex/r1-local-budget-observation. Only this isolated FF checkout is writable. No changes to mother CWP/RF/W06 runs, provider/download/model/keys, production config, installed skills or main.

1. [complete] Freeze actual failure and public producer/consumer boundaries; fail-first real bounded subprocess tests.
2. [complete] Preserve safe published local operations/diagnostics and actual local request limits through the existing exception/envelope chain, without changing error/retry/budget semantics.
3. [in_progress] Focused regression/static checks, cleanup and SHA-bound normal commit handoff; ROOT non-author review/integration.

Next: normal source commit and SHA-bound handoff; ROOT independent review and integrated CWP/FF/RF replay remain pending. ROOT owns the producer budget-observation gap and RF optional-consumer extension; this lane does not invent counters or a second ledger.
