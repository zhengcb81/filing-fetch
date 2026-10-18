# Findings

The original reader substituted non-null manifest dates but never validated them against as-of; explicit null fell back to a stale qualified query date. Manifest security comparison stripped zeroes in every market. Explicit provider constraints also accepted unknown current providers. Existing strict date responsibility is `filing_contracts._validate_date`.

There is no existing market-aware security canonicalizer in FF's14 scripts. ROOT identified CWP's sole `security_code.canonical_security_code` owner, so FF must not implement HK padding itself. New optional verified-reader `canonical_identity={schema_version:'source-canonical-identity/1',market,security_id}` is strictly compared to CWP identify's verified company identity. Normal FF workflow copies that identify result unchanged; direct library fixtures with verified=True but noncanonical HK9896 do not become09896 implicitly. Legacy receipts lacking projection retain strict manifest comparison.

The producer flag `--include-canonical-identity` is an integration dependency: ROOT owns the additive CWP port. Old CLI rejecting that flag fails honestly; FF does not retry dropping it or download in response. Current pure stand-ins cover the exact request and receipt shape; they do not constitute a live/frozen-CWP E2E with the new flag. The previous author support suite pins old CWP34a7dd71 and must be consciously aligned by ROOT for cross-repo producer-port acceptance, not called green against unsupported bytes.

Manifest dictionary present with explicit null or absent date key now means unknown; valid/invalid/future current dates are re-evaluated with the established strict date primitive. Entirely absent legacy manifest may use the query's observed date value, but that value is still independently validated against the current as-of. No query-provided eligibility boolean is inherited. Unknown current provider cannot satisfy explicit fmp; unconstrained unknown remains unknown.

Project and parent AGENTS.md files were absent at the inspected FF paths. Project and installed filing-fetch SKILL.md were read: reuse first, existing task authorization, current provider and hard resource limits, no duplicate storage. The main FF checkout has unrelated untracked files, including credential file names; their contents were not read or changed. New worktree was created from the exact author commit without copying working files.

## Independent closure

ROOT final du11-ff-final-integration.md/json is PASS_BOUNDED_ENGINEERING_RECEPTION at the four exact FF/CWP source SHAs. The additive producer port and real HK TXT chain are proven; publication is still ROOT's ordered responsibility.29unique independent cases are28boundary passes plus1separate actual-chain pass, not one29-PASS run.0ET/network, all owned Temp removed, source/raw restored. The older34a7dd71 support-pin concern is closed for this specifically bound new-port integration; the old receipt remains historical evidence only.
