# Contract ownership — filing-fetch is a consumer, not an owner

filing-fetch is a thin orchestrator (see company-wiki
`docs/adr/ADR-010-fcap-contract-ownership.md` and the machine-readable single
source at `revenue-forecast/compatibility/contract_registry.json`). It owns
**none** of the seven data-lake contracts and must not grow a second strategy
source.

## What filing-fetch does

- Validate a `FilingRequest`.
- Call company-wiki `identify` / `resolve` / `ensure` / `close-gap`.
- Forward a download authorization to company-wiki only after explicit user
  authorization; filing-fetch never decides whether a root is safe.
- Deeply validate and forward `ResolutionEnvelope`, `SourceHandle`,
  `SourceBundle`, and `AcquisitionTrace` unchanged.

## What filing-fetch must NOT do (forbidden second strategy source)

- Declare ownership of, or a second version of, any of: `RootPolicySnapshot`,
  `NormalizedFilingMetadata`, `ResolutionEnvelope`, `AcquisitionTrace`,
  `SourceBundle`, `ArtifactHandle`, `ActivationSnapshot`.
- Keep an independent `allowed_handle_roots` / root allowlist security policy.
  Verify the company-wiki policy snapshot hash and canonical-path containment
  instead (FC-501/FC-1202).
- Re-implement identity, latest/gap, artifact, or admission logic.
- Copy provider / root / identity rules out of company-wiki.

## Compat surface filing-fetch relies on

- `RootPolicySnapshot` 2.0: verify snapshot hash only.
- `ResolutionEnvelope` 1.0 / `SourceBundle` 1.0: when the upstream company-wiki
  has no bundle, surface `bundle_status=unavailable` explicitly — never
  synthesize a green response (FC-903).
- `AcquisitionTrace` 1.0: report download/provider counts from the trace, never
  inferred from handle presence.

Any change to the consumed contract versions requires a new FC with an N-1
window declared in `contract_registry.json`.
