# ROOT FF repair handoff

Status: **independent bounded engineering review PASS; actual cross-repo port chain PASS; ordered publication pending ROOT**.

Base8a83e27863269b14c897dc2c7ba953f3b9102ef1, branch codex/root-du11-ff-reception. One production source change (transcript_tool_transport.py) and one dedicated new test; exact SHA in handoff.json. No merge/push or installed-skill synchronization by this worker. The normal commit containing this handoff records the source node.

## Shared repairs

Current verified-reader manifest replaces stale query metadata, including null/missing date. Existing strict FF date primitive revalidates current publication/as-of; invalid/future dates cannot reuse. Provider-specific requests cannot accept unknown current provider. Identity normalization remains in CWP: FF requests canonical_identity schema1 and strictly compares against identify's verified identity, without generic zero-stripping or a copied HK rule. No new permission/store/catalogue.

## Engineering and independent evidence

Author repair evidence: initial4actualRED; projection7RED; focused34PASS0.92s (24new+10prior affected). First expanded attempt25PASS2FAIL was only missing fake configured tool files; repaired fixture setup and retained log. No102/109/full-suite repeat.

Distinct independent reviewer final report: ROOT CWP worktree `docs/plans/du11-source-closure-2026-10-18/review/du11-ff-final-integration.md/json` (absolute path and receipt SHA in handoff.json). The four frozen FF/CWP file SHAs matched before/after execution:

- FF transport4bb18006bb608c3dc706a6ca3f70e77fe03513798ff815b464aad208a8f33026.
- FF newtest9ab30a5ba0f02c0753fb785b45b571cac6c5009b757827eb2d5213e959ca8318.
- CWP reader89cbc7ef9d6c99ab9bac743b17505b66328edc4cfb4f1125ae7bd5d6795eea63.
- CWP CLI7510ae0244a61cee61a201a32dff1a21ee637518d8b2e916271414dd6e101876.

Independent executions total **29 unique passing cases across invocations**:28boundary controls passed first; a separate actual HK TXT scan/query/reader -> FF companion/transport chain passed (pytest14.477s;21.83s including archive preparation). This is **not** one29-PASS run. Early independent harness failures (missing synthetic USERPROFILE; wrong expected transport exception for raw tamper) remain in ROOT receipts and did not change product source. Author34PASS and ROOT59PASS are reused, not counted as independent new execution.

The actual chain retained observed HK9896, received canonical09896 from the sole CWP owner, verified the same raw SHA and reused with **0ET /0network**. Default legacy reader receipt remained compatible; raw tamper was rejected and then restored with original SHA/mtime. All owned temp removed and sentinel unchanged; original author worktree stayed read-only.

## Integration and publication boundary

ROOT's optional `source_reader_cli --include-canonical-identity` port is now implemented and independently exercised at the two CWP SHAs above. Earlier frozen CWP34a7dd71 evidence is historical and is not represented as new-port testing. Old CLI rejecting the new flag still fails honestly; FF does not retry dropping validation or trigger a download.

**ROOT publishes CWP producer first, then integrates/publishes this FF consumer.** This worker makes only a normal isolated-branch commit, with source SHA checked before/after hooks. No mother checkout change, merge, push or skill synchronization. Broader PWF physical/coreference work, paid supplier/content C and larger release regression remain separate tasks; this bounded port PASS does not claim full project completion.
