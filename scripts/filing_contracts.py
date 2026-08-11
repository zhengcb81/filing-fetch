"""Schema contracts and validation for filing-fetch request/response/handle."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Sequence


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------

SKILL_VERSION = "1.2.0"
FILING_REQUEST_SCHEMA_VERSION = "1.2"
FILING_RESPONSE_SCHEMA_VERSION = "1.1"
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
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = code in {"upstream_error", "worker_paused", "catalog_locked"}
        # Candidate identities surfaced by company-wiki when the query is
        # ambiguous, so callers can disambiguate from the error response alone.
        self.candidates = candidates
        # Per-candidate exclusion trace from the company-wiki resolve step,
        # surfaced with --debug so a not_found explains itself (Phase 19.6).
        self.debug_trace = debug_trace


# ---------------------------------------------------------------------------
# Request schema (1.1)
# ---------------------------------------------------------------------------

_REQUEST_SCHEMA_1_1_FIELDS = frozenset({
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
})

# WU-4.1: 1.2 adds the explicit mode field.
_REQUEST_SCHEMA_1_2_FIELDS = _REQUEST_SCHEMA_1_1_FIELDS | {"mode"}


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
    if version == FILING_REQUEST_SCHEMA_VERSION:
        allowed_fields = _REQUEST_SCHEMA_1_2_FIELDS
    elif version in LEGACY_REQUEST_SCHEMA_VERSIONS:
        allowed_fields = _REQUEST_SCHEMA_1_1_FIELDS
    else:
        raise FilingFetchError(
            f"unsupported request schema_version: {version} "
            f"(expected {FILING_REQUEST_SCHEMA_VERSION})",
            code="request_error",
        )
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
    fiscal_year = request.get("fiscal_year")
    if mode == "exact" or (mode is None and version == FILING_REQUEST_SCHEMA_VERSION):
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
            raise FilingFetchError(f"fiscal_year is out of range: {fiscal_year}", code="request_error")


# ---------------------------------------------------------------------------
# Resolution envelope validation (FC-704)
# ---------------------------------------------------------------------------

RESOLUTION_ENVELOPE_SCHEMA_VERSION = "1.0"
RESOLUTION_ENVELOPE_OUTCOMES = frozenset({
    "reused_existing", "reused_after_discovery", "downloaded_new", "gap",
    "ambiguous", "rejected", "missing", "failed",
})
RESOLUTION_ENVELOPE_BUNDLE_STATUSES = frozenset({"unavailable", "available"})


def validate_resolution_envelope(envelope: dict[str, Any]) -> None:
    """Deep-validate the company-wiki resolution envelope (FC-704).

    The envelope carries the journal-reconciled acquisition outcome and the
    download event count — the evidence the revenue receipt derives from.
    Anything outside the taxonomy or an impossible event count is an
    upstream error: fabricated evidence must never reach a consumer.
    """
    if not isinstance(envelope, dict):
        raise FilingFetchError(
            "resolution_envelope must be an object", code="upstream_error")
    if envelope.get("envelope_schema_version") != RESOLUTION_ENVELOPE_SCHEMA_VERSION:
        raise FilingFetchError(
            f"resolution_envelope schema_version must be "
            f"{RESOLUTION_ENVELOPE_SCHEMA_VERSION}",
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
        isinstance(policy_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", policy_hash)
    ):
        raise FilingFetchError(
            "resolution_envelope policy_hash must be a lowercase SHA-256 or null",
            code="upstream_error",
        )
    epoch = envelope.get("activation_epoch")
    if epoch is not None and not (
        isinstance(epoch, str) and epoch.strip()
    ):
        raise FilingFetchError(
            "resolution_envelope activation_epoch must be text or null",
            code="upstream_error",
        )
    if envelope.get("bundle_status") not in RESOLUTION_ENVELOPE_BUNDLE_STATUSES:
        raise FilingFetchError(
            "resolution_envelope bundle_status is outside the enum: "
            f"{envelope.get('bundle_status')!r}",
            code="upstream_error",
        )


# ---------------------------------------------------------------------------
# Handle validation
# ---------------------------------------------------------------------------

_HANDLE_REQUIRED_FIELDS = frozenset({
    "request_id", "document_id", "source_id", "title", "published_date",
    "https_url", "canonical_path", "snapshot_sha256", "retrieved_at",
    "provider", "provider_document_id", "collector_name", "collector_version",
    "byte_size", "mime_type", "capture_ready",
})


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
        raise FilingFetchError(f"handle missing required field(s): {', '.join(sorted(missing))}", code="upstream_error")
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
        raise FilingFetchError(f"handle canonical_path is invalid: {canonical}", code="upstream_error") from exc
    if policy_snapshot is not None:
        # FC-501: policy snapshot is the single containment source.
        if expected_policy_hash is None:
            raise FilingFetchError(
                "policy_snapshot supplied without expected_policy_hash",
                code="upstream_error",
            )
        payload = json.dumps(policy_snapshot, sort_keys=True, ensure_ascii=False)
        actual = hashlib.sha256(payload.encode("utf-8")).hexdigest()
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
        raise FilingFetchError("handle snapshot_sha256 is not a valid lowercase SHA-256", code="upstream_error")
    url = handle.get("https_url", "")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise FilingFetchError("handle https_url must use HTTPS", code="upstream_error")
    if not canonical.is_file():
        raise FilingFetchError("handle canonical_path is not a regular file", code="upstream_error")
    size = handle.get("byte_size")
    if isinstance(size, bool) or not isinstance(size, int) or size != canonical.stat().st_size:
        raise FilingFetchError("handle byte_size does not match the canonical file", code="upstream_error")
    content = canonical.read_bytes()
    content_digest = hashlib.sha256(content).hexdigest()
    if content_digest != digest:
        raise FilingFetchError("handle snapshot_sha256 does not match the canonical file bytes", code="upstream_error")
    published = handle.get("published_date", "")
    if not isinstance(published, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published):
        raise FilingFetchError("handle published_date must use YYYY-MM-DD format", code="upstream_error")
    as_of = request.get("as_of_date", "")
    if isinstance(as_of, str) and as_of and published > as_of:
        raise FilingFetchError("handle published_date is after the request as_of_date", code="upstream_error")
