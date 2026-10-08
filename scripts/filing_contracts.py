"""Schema contracts and validation for filing-fetch request/response/handle."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Sequence

# R6-FF-CAUSE: shape validation for the optional upstream diagnostic (the
# closed-vocabulary builder lives in ff_provider_cause; importing only the
# validator keeps this module free of parsing logic).
from ff_provider_cause import validated_cause


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

SKILL_VERSION = "1.2.0"
FILING_REQUEST_SCHEMA_VERSION = "1.2"
FILING_RESPONSE_SCHEMA_VERSION = "1.1"
FILING_V2_REQUEST_SCHEMA_VERSION = "2.0"
FILING_V2_RESPONSE_SCHEMA_VERSION = "2.0"
COMPANY_WIKI_CONFIG_SCHEMA_VERSION = "1.0"
COMPANY_WIKI_IDENTITY_SCHEMA_VERSION = "1.0"
# WU-4.1: explicit request mode. "exact" requires fiscal_year (a null year
# used to silently mean "latest", producing AMBIGUOUS instead of a gap);
# "latest_as_of" derives the latest period from as_of_date + document_kind
# and forbids an explicit fiscal_year.
REQUEST_MODES = frozenset({"exact", "latest_as_of"})
LEGACY_REQUEST_SCHEMA_VERSIONS = frozenset({"1.1"})

CONFIG_TOKEN_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

SUPPORTED_COMPANY_WIKI_CONTRACTS = {
    "resolve_schema_version": "1.0",
    "ensure_schema_version": "1.0",
    "identity_schema_version": COMPANY_WIKI_IDENTITY_SCHEMA_VERSION,
    "config_schema_version": COMPANY_WIKI_CONFIG_SCHEMA_VERSION,
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FilingFetchError(RuntimeError):
    """Raised when a capture-ready filing cannot be resolved or downloaded."""

    def __init__(
        self,
        message: str,
        code: str = "fatal",
        candidates: list | None = None,
        debug_trace: list | None = None,
        stage: str | None = None,
        attempts: int | None = None,
        resolution_trace: dict | None = None,
        upstream_cause: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        # ZR-205: retryable = the caller may retry. catalog_busy (raw SQLite
        # busy/locked) and db_timeout join catalog_locked/worker_paused; the
        # deadline-aware auto-retry loop in fetch_filing only spins on the
        # bounded catalog-contention codes (worker_paused stays caller-side).
        self.retryable = code in {
            "upstream_error",
            "worker_paused",
            "catalog_locked",
            "catalog_busy",
            "db_timeout",
        }
        # Candidate identities surfaced by company-wiki when the query is
        # ambiguous, so callers can disambiguate from the error response alone.
        self.candidates = candidates
        # Per-candidate exclusion trace from the company-wiki resolve step,
        # surfaced with --debug so a not_found explains itself (Phase 19.6).
        self.debug_trace = debug_trace
        # ZR-205 stage transparency: which company-wiki call failed
        # (identify/ensure/resolve/close-gap) and how many attempts were made,
        # so the final envelope stays reconcilable (READ-09).
        self.stage = stage
        self.attempts = attempts
        # ZR-307 staged-evidence visibility: the upstream resolution summary
        # (request_id/status/reason) survives a downstream failure — the
        # error never swallows the exact-reuse/download=0 evidence.
        self.resolution_trace = resolution_trace
        # R6-FF-CAUSE: optional safe machine diagnostic for a failed
        # company-wiki producer call.  Only a validated
        # filing-upstream-cause/1 object (built by ff_provider_cause from
        # closed vocabularies) is accepted — garbage never rides the envelope.
        if upstream_cause is not None and validated_cause(upstream_cause) is None:
            raise TypeError(
                "upstream_cause must be a validated filing-upstream-cause/1 object"
            )
        self.upstream_cause = upstream_cause


# ---------------------------------------------------------------------------
# Request schema (1.1)
# ---------------------------------------------------------------------------

_REQUEST_SCHEMA_1_1_FIELDS = frozenset(
    {
        "schema_version",
        "company_query",
        "market",
        "exchange",
        "document_kind",
        "fiscal_year",
        "as_of_date",
        "form_type",
        "fiscal_period",
        "language",
        "provider",
        "provider_document_id",
        "acquisition_limits",
    }
)

# WU-4.1: 1.2 adds the explicit mode field; FC-802 adds the optional
# legacy authorization field (optional target scope, never a permission receipt).
_REQUEST_SCHEMA_1_2_FIELDS = _REQUEST_SCHEMA_1_1_FIELDS | {"mode", "authorization"}
_REQUEST_SCHEMA_2_0_FIELDS = (_REQUEST_SCHEMA_1_2_FIELDS - {"authorization"}) | {
    "filing_intent", "companion_transcript", "acquisition_limits",
}

_AUTHORIZATION_REQUIRED_FIELDS = frozenset(
    {
        "provider",
        "allowed_accessions",
        "max_items",
        "max_bytes",
    }
)


def _request_fields(version: Any) -> frozenset[str]:
    if version == FILING_V2_REQUEST_SCHEMA_VERSION:
        return _REQUEST_SCHEMA_2_0_FIELDS
    if version == FILING_REQUEST_SCHEMA_VERSION:
        return _REQUEST_SCHEMA_1_2_FIELDS
    if version in LEGACY_REQUEST_SCHEMA_VERSIONS:
        return _REQUEST_SCHEMA_1_1_FIELDS
    raise FilingFetchError(
        f"unsupported request schema_version: {version} "
        f"(expected {FILING_REQUEST_SCHEMA_VERSION})",
        code="request_error",
    )


def _validate_v2_request(request: dict[str, Any]) -> None:
    if request.get("filing_intent") not in {"reuse_only", "fetch_if_missing"}:
        raise FilingFetchError(
            "filing_intent must be reuse_only or fetch_if_missing",
            code="request_error",
        )
    _validate_acquisition_limits(
        request.get("filing_intent"),
        request.get("acquisition_limits"),
        required_for_reuse_only=request.get("mode") == "latest_as_of",
    )
    _validate_companion_request(request.get("companion_transcript"))


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise FilingFetchError(f"{field_name} must be non-empty trimmed text", code="request_error")
    return value


def validate_request(request: dict[str, Any]) -> None:
    """Validate a filing-fetch request against the 1.2 schema.

    WU-4.1 semantics:
    - ``mode="exact"`` (or a legacy 1.1 request without mode): fiscal_year
      is REQUIRED — a null year must never silently mean "latest".
    - ``mode="latest_as_of"``: fiscal_year is FORBIDDEN; the latest period
      is derived from as_of_date + document_kind + provider calendar.
    """
    version = request.get("schema_version")
    allowed_fields = _request_fields(version)
    unknown = set(request) - allowed_fields
    if unknown:
        raise FilingFetchError(
            f"unknown request field(s): {', '.join(sorted(unknown))}",
            code="request_error",
        )
    _required_text(request.get("company_query"), "company_query")
    market = request.get("market")
    if market is not None and market not in {"CN", "HK", "US"}:
        raise FilingFetchError(
            f"market must be one of CN, HK, US: {market!r}", code="request_error"
        )
    _required_text(request.get("document_kind"), "document_kind")
    _required_text(request.get("as_of_date"), "as_of_date")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", request["as_of_date"]):
        raise FilingFetchError("as_of_date must use YYYY-MM-DD format", code="request_error")
    mode = request.get("mode")
    if mode is not None and mode not in REQUEST_MODES:
        raise FilingFetchError(
            f"mode must be one of {', '.join(sorted(REQUEST_MODES))}: {mode!r}",
            code="request_error",
        )
    if version == FILING_V2_REQUEST_SCHEMA_VERSION:
        _validate_v2_request(request)
    elif "acquisition_limits" in request:
        _validate_acquisition_limits("fetch_if_missing", request["acquisition_limits"])
    authorization = request.get("authorization")
    if authorization is not None:
        # Legacy scope preserves provider/accessions/caps. Expiry and
        # unsigned policy digests do not determine download permission.
        if not isinstance(authorization, dict):
            raise FilingFetchError("authorization must be an object", code="request_error")
        missing = _AUTHORIZATION_REQUIRED_FIELDS - set(authorization)
        if missing:
            raise FilingFetchError(
                f"authorization missing field(s): {', '.join(sorted(missing))}",
                code="request_error",
            )
        _required_text(authorization.get("provider"), "authorization.provider")
        accessions = authorization.get("allowed_accessions")
        if (
            not isinstance(accessions, list)
            or not accessions
            or not all(isinstance(a, str) and a.strip() for a in accessions)
        ):
            raise FilingFetchError(
                "authorization.allowed_accessions must be a non-empty list of non-empty strings",
                code="request_error",
            )
        for name in ("max_items", "max_bytes"):
            value = authorization.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise FilingFetchError(
                    f"authorization.{name} must be a positive integer",
                    code="request_error",
                )
    fiscal_year = request.get("fiscal_year")
    if mode == "exact" or (
        mode is None and version in {FILING_REQUEST_SCHEMA_VERSION, FILING_V2_REQUEST_SCHEMA_VERSION}
    ):
        # schema 1.2: explicit mode is expected; a missing mode defaults to
        # exact and MUST carry fiscal_year (a null year must not silently
        # mean "latest"). Legacy 1.1 requests keep the old exact-any-year
        # behavior.
        if fiscal_year is None:
            raise FilingFetchError(
                "schema 1.2 requests require mode or fiscal_year: pass "
                "mode=exact with fiscal_year, or mode=latest_as_of",
                code="request_error",
            )
    elif mode == "latest_as_of":
        if fiscal_year is not None:
            raise FilingFetchError(
                "mode=latest_as_of forbids fiscal_year; the latest period is "
                "derived from as_of_date + document_kind",
                code="request_error",
            )
    if fiscal_year is not None:
        if isinstance(fiscal_year, bool) or not isinstance(fiscal_year, int):
            raise FilingFetchError("fiscal_year must be an integer", code="request_error")
        if fiscal_year < 1900:
            raise FilingFetchError(
                f"fiscal_year is out of range: {fiscal_year}", code="request_error"
            )



def _validate_acquisition_limits(
    intent: Any, value: Any, *, required_for_reuse_only: bool = False
) -> None:
    """Bind provider work to explicit byte, time and fee ceilings.

    Ordinary reuse_only requests stay provider-free and forbid limits. A
    latest_as_of reuse_only request performs a bounded metadata lookup to prove
    whether the local filing is current, but still cannot download bytes.
    """
    if intent == "reuse_only" and not required_for_reuse_only:
        if value is not None:
            raise FilingFetchError(
                "reuse_only forbids acquisition_limits", code="request_error"
            )
        return
    if not isinstance(value, dict) or set(value) != {
        "max_bytes", "timeout_seconds", "max_cost_usd"
    }:
        if intent == "reuse_only":
            message = "latest_as_of reuse_only requires max_bytes, timeout_seconds and max_cost_usd limits"
        else:
            message = "fetch_if_missing requires max_bytes, timeout_seconds and max_cost_usd"
        raise FilingFetchError(message, code="request_error")
    size = value["max_bytes"]
    if type(size) is not int or size <= 0:
        raise FilingFetchError("invalid acquisition_limits.max_bytes", code="request_error")
    seconds = value["timeout_seconds"]
    if (
        isinstance(seconds, bool) or not isinstance(seconds, (int, float))
        or not math.isfinite(seconds) or seconds <= 0
    ):
        raise FilingFetchError("invalid acquisition_limits.timeout_seconds", code="request_error")
    cost = value["max_cost_usd"]
    if not isinstance(cost, str) or not re.fullmatch(
        r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?", cost
    ):
        raise FilingFetchError("invalid acquisition_limits.max_cost_usd", code="request_error")


def _validate_companion_request(value: Any) -> None:
    """Validate an optional transcript intent without inventing a fiscal quarter."""
    if value is None:
        return
    if not isinstance(value, dict):
        raise FilingFetchError("companion_transcript must be an object", code="request_error")
    allowed = {"intent", "fiscal_year", "fiscal_quarter", "provider", "acquisition_limits"}
    unknown = set(value) - allowed
    if unknown:
        raise FilingFetchError(
            f"unknown companion_transcript field(s): {', '.join(sorted(unknown))}",
            code="request_error",
        )
    if value.get("intent") not in {"reuse_only", "fetch_if_missing"}:
        raise FilingFetchError("invalid companion_transcript.intent", code="request_error")
    year = value.get("fiscal_year")
    if year is not None and (type(year) is not int or not 1900 <= year <= 2100):
        raise FilingFetchError("invalid companion_transcript.fiscal_year", code="request_error")
    quarter = value.get("fiscal_quarter")
    if quarter is not None and (type(quarter) is not int or quarter not in {1, 2, 3, 4}):
        raise FilingFetchError("invalid companion_transcript.fiscal_quarter", code="request_error")
    intent = value["intent"]
    limits = value.get("acquisition_limits")
    if intent == "reuse_only":
        _validate_acquisition_limits(intent, limits)
    elif year is not None and quarter is not None:
        _validate_acquisition_limits(intent, limits)
    elif limits is not None:
        _validate_acquisition_limits(intent, limits)
    provider = value.get("provider")
    if provider is not None and (
        not isinstance(provider, str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", provider)
    ):
        raise FilingFetchError("invalid companion_transcript.provider", code="request_error")


# ---------------------------------------------------------------------------
# Resolution envelope validation (FC-704)
# ---------------------------------------------------------------------------

RESOLUTION_ENVELOPE_SCHEMA_VERSION = "1.0"
RESOLUTION_ENVELOPE_OUTCOMES = frozenset(
    {
        "reused_existing",
        "reused_after_discovery",
        "downloaded_new",
        "gap",
        "ambiguous",
        "rejected",
        "missing",
        "failed",
    }
)
RESOLUTION_ENVELOPE_BUNDLE_STATUSES = frozenset({"unavailable", "available"})
# FC-905-a: diagnostic review state; byte and identity checks decide v2 readiness.
RESOLUTION_ENVELOPE_PROMPT_INJECTION_STATUSES = frozenset(
    {"not_detected", "detected_and_ignored", "not_reviewed"}
)


def validate_resolution_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    """Deep-validate the company-wiki resolution envelope (FC-704 + FC-903).

    The envelope carries the journal-reconciled acquisition outcome and the
    download event count — the evidence the revenue receipt derives from.
    Anything outside the taxonomy or an impossible event count is an
    upstream error: fabricated evidence must never reach a consumer.

    FC-903 (N/N-1): returns the envelope dict, possibly a normalized copy —
    a pre-FC-902 company-wiki envelope that omits ``bundle_status`` gains the
    explicit honest ``bundle_status="unavailable"`` (never a faked
    empty-green ``available``).  ``bundle_status="available"`` requires a
    SHA-256 ``bundle_hash`` and a bundle dict whose hash matches — fail
    closed.  Artifact validity is NOT re-decided: valid/invalid handles are
    forwarded verbatim.
    """
    if not isinstance(envelope, dict):
        raise FilingFetchError("resolution_envelope must be an object", code="upstream_error")
    if envelope.get("envelope_schema_version") != RESOLUTION_ENVELOPE_SCHEMA_VERSION:
        raise FilingFetchError(
            f"resolution_envelope schema_version must be {RESOLUTION_ENVELOPE_SCHEMA_VERSION}",
            code="upstream_error",
        )
    outcome = envelope.get("outcome")
    if outcome not in RESOLUTION_ENVELOPE_OUTCOMES:
        raise FilingFetchError(
            f"resolution_envelope outcome is outside the taxonomy: {outcome!r}",
            code="upstream_error",
        )
    events = envelope.get("download_events")
    if isinstance(events, bool) or events not in (0, 1):
        raise FilingFetchError(
            f"resolution_envelope download_events must be 0 or 1: {events!r}",
            code="upstream_error",
        )
    policy_hash = envelope.get("policy_hash")
    if policy_hash is not None and not (
        isinstance(policy_hash, str) and re.fullmatch(r"[0-9a-f]{64}", policy_hash)
    ):
        raise FilingFetchError(
            "resolution_envelope policy_hash must be a lowercase SHA-256 or null",
            code="upstream_error",
        )
    epoch = envelope.get("activation_epoch")
    if epoch is not None and not (isinstance(epoch, str) and epoch.strip()):
        raise FilingFetchError(
            "resolution_envelope activation_epoch must be text or null",
            code="upstream_error",
        )
    bundle_status = envelope.get("bundle_status")
    if bundle_status is None:
        # FC-903 N-1: a pre-FC-902 company-wiki envelope carries no bundle
        # status.  Normalize a COPY to the explicit honest 'unavailable' —
        # never a faked green — and leave the caller's dict untouched.
        envelope = dict(envelope)
        envelope["bundle_status"] = "unavailable"
        bundle_status = "unavailable"
    if bundle_status not in RESOLUTION_ENVELOPE_BUNDLE_STATUSES:
        raise FilingFetchError(
            f"resolution_envelope bundle_status is outside the enum: {bundle_status!r}",
            code="upstream_error",
        )
    if bundle_status == "available":
        bundle_hash = envelope.get("bundle_hash")
        if not (isinstance(bundle_hash, str) and re.fullmatch(r"[0-9a-f]{64}", bundle_hash)):
            raise FilingFetchError(
                "bundle_status=available requires a SHA-256 bundle_hash",
                code="upstream_error",
            )
        bundle = envelope.get("bundle")
        if not isinstance(bundle, dict) or bundle.get("bundle_hash") != bundle_hash:
            raise FilingFetchError(
                "bundle_status=available requires a bundle dict whose "
                "bundle_hash matches the envelope's",
                code="upstream_error",
            )
        if bundle.get("schema_version") != "1.0":
            raise FilingFetchError(
                "bundle schema_version must be '1.0'",
                code="upstream_error",
            )
    # FC-905-b N-1: normalize missing trusted-evidence fields to their
    # explicit honest defaults on a COPY (never faked, never clobbered).
    changed = False
    if "prompt_injection_status" not in envelope:
        envelope = dict(envelope)
        changed = True
        envelope["prompt_injection_status"] = "not_reviewed"
    for count_key in ("parser_calls", "llm_calls"):
        if count_key not in envelope:
            if not changed:
                envelope = dict(envelope)
                changed = True
            envelope[count_key] = None
    prompt_injection_status = envelope.get("prompt_injection_status")
    if prompt_injection_status not in RESOLUTION_ENVELOPE_PROMPT_INJECTION_STATUSES:
        raise FilingFetchError(
            "resolution_envelope prompt_injection_status is outside the enum: "
            f"{prompt_injection_status!r}",
            code="upstream_error",
        )
    for count_key in ("parser_calls", "llm_calls"):
        value = envelope.get(count_key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise FilingFetchError(
                f"resolution_envelope {count_key} must be a non-negative "
                f"integer or null: {value!r}",
                code="upstream_error",
            )
    return envelope


# ---------------------------------------------------------------------------
# Handle validation
# ---------------------------------------------------------------------------

_HANDLE_REQUIRED_FIELDS = frozenset(
    {
        "request_id",
        "document_id",
        "source_id",
        "title",
        "published_date",
        "https_url",
        "canonical_path",
        "snapshot_sha256",
        "retrieved_at",
        "provider",
        "provider_document_id",
        "collector_name",
        "collector_version",
        "byte_size",
        "mime_type",
        "capture_ready",
    }
)


def validate_handle_metadata(
    handle: dict[str, Any],
    request: dict[str, Any],
) -> None:
    """Validate the identity needed for a pathless source candidate.

    The final consumer opens the SourceRef through company-wiki.  A candidate
    therefore does not interpret root policy or claim that bytes were read.
    Collector, URL, and ``capture_ready`` fields are diagnostic metadata; they
    do not decide whether the consumer may open a locally verified SourceRef.
    """
    required = _HANDLE_REQUIRED_FIELDS - {
        "canonical_path", "https_url", "retrieved_at", "provider",
        "provider_document_id", "collector_name", "collector_version",
        "capture_ready",
    }
    missing = required - set(handle)
    if missing:
        raise FilingFetchError(
            f"handle missing required field(s): {', '.join(sorted(missing))}",
            code="upstream_error",
        )
    for name in ("request_id", "document_id", "source_id", "mime_type"):
        value = handle.get(name)
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise FilingFetchError(
                f"handle {name} must be non-empty trimmed text", code="upstream_error"
            )
    if "capture_ready" in handle and type(handle["capture_ready"]) is not bool:
        raise FilingFetchError("handle capture_ready must be boolean", code="upstream_error")
    digest = handle.get("snapshot_sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise FilingFetchError("handle snapshot_sha256 is invalid", code="upstream_error")
    if handle.get("content_sha256", digest) != digest:
        raise FilingFetchError("handle content_sha256 differs from snapshot_sha256", code="upstream_error")
    size = handle.get("byte_size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise FilingFetchError("handle byte_size is invalid", code="upstream_error")
    published = handle.get("published_date")
    if not isinstance(published, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published):
        raise FilingFetchError("handle published_date must use YYYY-MM-DD", code="upstream_error")
    as_of = request.get("as_of_date")
    if isinstance(as_of, str) and as_of and published > as_of:
        raise FilingFetchError("handle published_date is after as_of_date", code="upstream_error")


def _policy_document_hash(policy_snapshot: dict[str, Any]) -> str:
    """ZR-405: the canonical hash of the policy DOCUMENT — the
    ``policy_hash`` envelope key is excluded from the hashed bytes so the
    wiki's export payload (document + hash) verifies itself."""
    canonical_document = {
        key: value for key, value in policy_snapshot.items() if key != "policy_hash"
    }
    payload = json.dumps(canonical_document, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_handle(
    handle: dict[str, Any],
    request: dict[str, Any],
    wiki_root: Path,
    allowed_roots: Sequence[Path] | None = None,
    policy_snapshot: dict[str, Any] | None = None,
    expected_policy_hash: str | None = None,
) -> None:
    """Deep-validate a capture-ready handle returned by company-wiki.

    FC-501: containment is verified against the RootPolicySnapshot from
    company-wiki — a handle's canonical_path must live under a root the
    snapshot marks ``reusable_for_filing``, and the snapshot's hash must
    match the pinned ``expected_policy_hash``.  The legacy
    ``allowed_roots`` allowance is DEPRECATED (kept only for N/N-1
    compat); a policy snapshot, when supplied, takes precedence and no
    independent allowlist is consulted.
    """
    missing = _HANDLE_REQUIRED_FIELDS - set(handle)
    if missing:
        raise FilingFetchError(
            f"handle missing required field(s): {', '.join(sorted(missing))}", code="upstream_error"
        )
    request_id = handle.get("request_id")
    if (
        not isinstance(request_id, str)
        or not request_id.strip()
        or request_id != request_id.strip()
    ):
        raise FilingFetchError(
            "handle request_id must be non-empty trimmed text", code="upstream_error"
        )
    if handle.get("capture_ready") is not True:
        raise FilingFetchError("handle capture_ready is not True", code="upstream_error")
    canonical = Path(handle["canonical_path"])
    if not canonical.is_absolute():
        canonical = wiki_root / canonical
    try:
        canonical.resolve(strict=False)
    except (OSError, ValueError) as exc:
        raise FilingFetchError(
            f"handle canonical_path is invalid: {canonical}", code="upstream_error"
        ) from exc
    if policy_snapshot is not None:
        # FC-501: policy snapshot is the single containment source.
        if expected_policy_hash is None:
            raise FilingFetchError(
                "policy_snapshot supplied without expected_policy_hash",
                code="upstream_error",
            )
        # ZR-405: the canonical hash is computed over the policy DOCUMENT —
        # the ``policy_hash`` key itself is envelope metadata (like the
        # canonical_hash discipline in uc receipts) and must not be part of
        # the hashed bytes.  The wiki policy-export payload carries both
        # the document and its hash; consumers verify document==hash.
        actual = _policy_document_hash(policy_snapshot)
        if actual != expected_policy_hash:
            raise FilingFetchError(
                f"policy snapshot hash mismatch: {actual[:12]}... != "
                f"{expected_policy_hash[:12]}...",
                code="upstream_error",
            )

        def _expand_path_ref(ref: str) -> Path:
            expanded = re.sub(
                r"\$\{PROJECT_ROOT\}",
                lambda _match: str(wiki_root).replace("\\", "/"),
                ref,
            )
            path = Path(expanded).expanduser()
            if not path.is_absolute():
                path = wiki_root / path
            return path.resolve(strict=False)

        allowance = tuple(
            _expand_path_ref(str(root.get("path_ref", "")))
            for root in policy_snapshot.get("roots", [])
            if root.get("reusable_for_filing") is True
        )
    elif allowed_roots is None:
        allowance = ((wiki_root / "companies").resolve(),)
    else:
        allowance = tuple(Path(item).resolve() for item in allowed_roots)
    resolved = canonical.resolve()
    if not any(
        str(resolved) == str(root) or str(resolved).startswith(str(root) + os.sep)
        for root in allowance
    ):
        raise FilingFetchError(
            "handle canonical_path is outside the policy snapshot's reusable roots",
            code="upstream_error",
        )
    digest = handle.get("snapshot_sha256", "")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise FilingFetchError(
            "handle snapshot_sha256 is not a valid lowercase SHA-256", code="upstream_error"
        )
    url = handle.get("https_url", "")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise FilingFetchError("handle https_url must use HTTPS", code="upstream_error")
    if not canonical.is_file():
        raise FilingFetchError("handle canonical_path is not a regular file", code="upstream_error")
    size = handle.get("byte_size")
    if isinstance(size, bool) or not isinstance(size, int) or size != canonical.stat().st_size:
        raise FilingFetchError(
            "handle byte_size does not match the canonical file", code="upstream_error"
        )
    content = canonical.read_bytes()
    content_digest = hashlib.sha256(content).hexdigest()
    if content_digest != digest:
        raise FilingFetchError(
            "handle snapshot_sha256 does not match the canonical file bytes", code="upstream_error"
        )
    published = handle.get("published_date", "")
    if not isinstance(published, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published):
        raise FilingFetchError(
            "handle published_date must use YYYY-MM-DD format", code="upstream_error"
        )
    as_of = request.get("as_of_date", "")
    if isinstance(as_of, str) and as_of and published > as_of:
        raise FilingFetchError(
            "handle published_date is after the request as_of_date", code="upstream_error"
        )
