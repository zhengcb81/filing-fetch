"""On-demand company filing fetcher (market-routed, reuse-first).

This is a thin client over company-wiki's acquisition engine. It identifies a
company, then resolves (reuses) an existing filing in company-wiki, or delegates
a missing-source download according to the task's acquisition intent and limits.
Existing company/session authorization carries forward without another
per-document permission receipt. company-wiki routes by market:
A-share (CN) -> StockInfoDLSimple/cninfo, HK/US ->
dayu-agent. Newly downloaded bytes are written into company-wiki under
``companies/{entity}/raw/{kind}/`` with immutable provenance; the calculation
engines of consuming skills never import a downloader.

Run directly:

    echo '{"company_query":"AMD","document_kind":"annual_report","fiscal_year":2025,"as_of_date":"2026-07-18"}' \\
      | python scripts/fetch_filing.py [--allow-download] [--config PATH] [--request-file PATH]
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import random
import re
import sys
import time
from typing import Any


from filing_contracts import (  # noqa: E402  re-export
    FILING_RESPONSE_SCHEMA_VERSION,
    FILING_V2_REQUEST_SCHEMA_VERSION,
    CONFIG_TOKEN_RE,
    COMPANY_WIKI_CONFIG_SCHEMA_VERSION,
    COMPANY_WIKI_IDENTITY_SCHEMA_VERSION,
    SUPPORTED_COMPANY_WIKI_CONTRACTS,
    FilingFetchError,
    validate_handle,
    validate_handle_metadata,
    validate_request,
    validate_resolution_envelope,
    _required_text,
)

# The shared bounded process layer both JSON runners call; stdout/stderr are
# bounded DURING read at MAX_JSON_OUTPUT_BYTES, all subprocesses share one
# request deadline, and each call reaps the process tree it created.
import ff_process_transport
from ff_process_transport import (  # noqa: E402
    ChildFailed as _ProcessChildFailed,
    ChildStartFailed as _ProcessChildStartFailed,
    ChildTimeout as _ProcessChildTimeout,
    OutputLimitExceeded as _ProcessOutputLimitExceeded,
    run_bounded_json as _run_bounded_json,
)

# R6-FF-CAUSE: the single stderr parse + closed-vocabulary diagnostics shared
# by classification and the optional upstream_cause envelope field.
import ff_provider_cause

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPANY_WIKI_CONFIG = SKILL_ROOT / "config" / "company_wiki.json"

# Exponential backoff for transient catalog lock contention (Phase 15.2,
# ZR-205: jitter + cap + deadline bound, no sleep past the deadline).
CATALOG_LOCKED_BACKOFF_SECONDS = 5.0
CATALOG_LOCKED_BACKOFF_MULTIPLIER = 2.0
CATALOG_LOCKED_BACKOFF_MAX_SECONDS = 60.0
CATALOG_LOCKED_BACKOFF_JITTER = 0.2  # ±20% uniform jitter around the backoff

# ZR-205: canonical error codes emitted by company-wiki's error taxonomy
# (ZR-204).  These are the only codes the deadline-aware auto-retry loop
# spins on; everything else (worker_paused, fatal, ...) is fail-closed.
_CATALOG_RETRY_CODES = frozenset({"catalog_locked", "catalog_busy", "db_timeout"})

# The opt-in v2 result contains only source/business facts. A path in the
# upstream legacy match is a transient storage detail, never a consumer handle.
_SOURCE_CANDIDATE_FIELDS = frozenset(
    {
        "request_id",
        "document_id",
        "source_id",
        "title",
        "document_kind",
        "fiscal_year",
        "fiscal_period",
        "period_end",
        "form_type",
        "market",
        "security_id",
        "language",
        "published_date",
        "https_url",
        "snapshot_sha256",
        "content_sha256",
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
_COMPANY_IDENTITY_FIELDS = frozenset(
    {
        "canonical_name",
        "market",
        "exchange",
        "ticker",
        "security_id",
        "match_basis",
        "matched_value",
        "source_name",
        "source_url",
        "source_record_id",
        "verified",
        "active",
    }
)
_SOURCE_REF_FIELDS = frozenset(
    {"schema_version", "document_id", "source_id", "content_sha256", "byte_size", "mime_type"}
)
_QUERY_REQUEST_FIELDS = frozenset(
    {
        "entity",
        "market",
        "security_id",
        "document_kind",
        "form_type",
        "fiscal_year",
        "fiscal_period",
        "language",
        "provider",
        "provider_document_id",
        "as_of_date",
        "mode",
    }
)


def _validate_company_wiki_root(root: Path) -> Path:
    if not isinstance(root, Path):
        raise TypeError("company_wiki_root must be pathlib.Path")
    try:
        resolved = root.expanduser().resolve(strict=True)
    except OSError as exc:
        raise FilingFetchError(
            f"configured company_wiki_root does not exist: {root}",
            code="config_error",
        ) from exc
    if not resolved.is_dir():
        raise FilingFetchError(
            "configured company_wiki_root must be a directory", code="config_error"
        )
    catalog_config = resolved / "config" / "source_catalog.yaml"
    if not catalog_config.is_file():
        raise FilingFetchError(
            "configured company_wiki_root lacks config/source_catalog.yaml",
            code="config_error",
        )
    return resolved


def load_company_wiki_root(*, config_path: Path | None = None) -> Path:
    """Load and validate the persistent company-wiki root configuration."""

    if config_path is not None and not isinstance(config_path, Path):
        raise TypeError("config_path must be pathlib.Path or None")
    selected = config_path or DEFAULT_COMPANY_WIKI_CONFIG
    try:
        selected = selected.expanduser().resolve(strict=True)
    except OSError as exc:
        raise FilingFetchError(
            f"company-wiki config does not exist: {selected}", code="config_error"
        ) from exc
    if not selected.is_file():
        raise FilingFetchError("company-wiki config must be a file", code="config_error")
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FilingFetchError(f"invalid company-wiki config: {exc}", code="config_error") from exc
    if not isinstance(payload, dict):
        raise FilingFetchError("company-wiki config must be an object", code="config_error")
    required = {"schema_version", "company_wiki_root"}
    if not set(payload) <= required | {"fmp_api_key_file", "earnings_transcripts_tool"} or not required <= set(payload):
        raise FilingFetchError(
            "company-wiki config must contain schema_version/company_wiki_root "
            "and only optional fmp_api_key_file/earnings_transcripts_tool "
            "(FC-501: no independent allowed_handle_roots allowlist)",
            code="config_error",
        )
    if payload["schema_version"] != COMPANY_WIKI_CONFIG_SCHEMA_VERSION:
        raise FilingFetchError(
            f"company-wiki config schema_version must be {COMPANY_WIKI_CONFIG_SCHEMA_VERSION}",
            code="config_error",
        )
    for path_field in ("fmp_api_key_file", "earnings_transcripts_tool"):
        configured_path = payload.get(path_field)
        if path_field in payload and (
            not isinstance(configured_path, str) or not configured_path.strip()
            or configured_path != configured_path.strip()
        ):
            raise FilingFetchError(
                f"company-wiki config {path_field} must be non-empty trimmed text",
                code="config_error",
            )
    configured = payload["company_wiki_root"]
    if (
        not isinstance(configured, str)
        or not configured.strip()
        or configured != configured.strip()
    ):
        raise FilingFetchError(
            "company-wiki config company_wiki_root must be non-empty trimmed text",
            code="config_error",
        )
    tokens = {
        "SKILL_ROOT": str(SKILL_ROOT),
        "USER_PROFILE": os.environ.get("USERPROFILE") or str(Path.home()),
    }

    def replace_token(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in tokens:
            raise FilingFetchError(
                f"unsupported token in company_wiki_root: {name}", code="config_error"
            )
        return tokens[name]

    expanded = CONFIG_TOKEN_RE.sub(replace_token, configured)
    root = Path(expanded).expanduser()
    if not root.is_absolute():
        # FC-1202: a relative root would be resolved implicitly against the
        # config file's parent directory — only explicit absolute (token-
        # expanded) roots are valid.
        raise FilingFetchError(
            "company-wiki config company_wiki_root must be absolute after token expansion",
            code="config_error",
        )
    return _validate_company_wiki_root(root)


def _limit_arguments(request: dict[str, Any]) -> list[str]:
    """Return ceilings for bounded provider work declared by the request.

    They ride every argv built from this request - ``ensure`` and
    ``close-gap`` both. Ordinary reuse_only and legacy v1 requests contribute
    nothing; latest_as_of + reuse_only carries limits for metadata discovery
    while still omitting ``--allow-download``.
    """
    limits = request.get("acquisition_limits")
    if limits is None:
        return []
    seconds = limits["timeout_seconds"]
    rendered = str(int(seconds)) if float(seconds).is_integer() else str(seconds)
    return [
        "--max-download-bytes",
        str(limits["max_bytes"]),
        "--max-download-seconds",
        rendered,
        # The fee ceiling is already a decimal string; pass it through
        # unchanged so the producer sees exactly what the caller wrote.
        "--max-download-cost-usd",
        str(limits["max_cost_usd"]),
    ]


def _command_arguments(request: dict[str, Any]) -> list[str]:
    required = ("entity", "document_kind", "as_of_date")
    for name in required:
        _required_text(request.get(name), name)
    arguments = [
        "--entity",
        request["entity"],
        "--document-kind",
        request["document_kind"],
        "--as-of-date",
        request["as_of_date"],
    ]
    options = {
        "market": "--market",
        "security_id": "--security-id",
        "form_type": "--form-type",
        "fiscal_period": "--fiscal-period",
        "language": "--language",
        "provider": "--provider",
        "provider_document_id": "--provider-document-id",
    }
    for name, flag in options.items():
        value = request.get(name)
        if value is not None:
            arguments.extend((flag, _required_text(value, name)))
    fiscal_year = request.get("fiscal_year")
    if fiscal_year is not None:
        if isinstance(fiscal_year, bool) or not isinstance(fiscal_year, int):
            raise FilingFetchError("fiscal_year must be an integer")
        arguments.extend(("--fiscal-year", str(fiscal_year)))
    mode = request.get("mode")
    if mode is not None:
        arguments.extend(("--mode", str(mode)))
    return arguments + _limit_arguments(request)


def _identity_arguments(request: dict[str, Any]) -> list[str]:
    query = _required_text(request.get("company_query"), "company_query")
    for name in ("document_kind", "as_of_date"):
        _required_text(request.get(name), name)
    arguments = ["--query", query]
    for name, flag in (("market", "--market"), ("exchange", "--exchange")):
        value = request.get(name)
        if value is not None:
            arguments.extend((flag, _required_text(value, name)))
    return arguments


def _run_company_wiki_json(
    *,
    command: list[str],
    root: Path,
    timeout_seconds: float,
    action: str,
    stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    """One company-wiki CLI call through the shared bounded process layer.

    stdout is capped DURING read at ``MAX_JSON_OUTPUT_BYTES`` (actual bytes);
    stderr is concurrently read with its own finite cap and only used for
    structured error classification. The timeout is the caller's remaining
    shared deadline — the layer never renews it. The layer reaps exactly the
    process tree this call created (no other processes are touched).
    """
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    if stats is not None:
        stats["calls"] += 1
    try:
        stdout, stderr, returncode = _run_bounded_json(
            command,
            timeout_seconds=timeout_seconds,
            input_bytes=None,
            cwd=str(root),
            env=environment,
        )
    except _ProcessChildTimeout as exc:
        code, cause = ff_provider_cause.condition_cause(
            action, "producer_deadline_exceeded"
        )
        raise FilingFetchError(
            f"company-wiki {action} exceeded its deadline budget",
            code=code,
            upstream_cause=cause,
        ) from exc
    except _ProcessOutputLimitExceeded as exc:
        code, cause = ff_provider_cause.condition_cause(
            action, "producer_output_exceeded"
        )
        raise FilingFetchError(
            f"company-wiki {action} exceeded the output byte cap",
            code=code,
            stage=action,
            attempts=1,
            upstream_cause=cause,
        ) from exc
    except _ProcessChildFailed as exc:
        # Static child failure: report the exit status and the classified
        # stderr code + safe cause only. The raw stderr body is consumed for
        # classification but never echoed - it routinely carries absolute
        # paths and provider credentials.
        code, cause, receipt = ff_provider_cause.diagnose_stderr_observation(
            action, exc.stderr.decode("utf-8", errors="replace").strip()
        )
        raise FilingFetchError(
            f"company-wiki {action} exited {exc.returncode}",
            code=code,
            stage=action,
            attempts=1,
            upstream_cause=cause,
            acquisition_failure=receipt,
        ) from exc
    except _ProcessChildStartFailed as exc:
        code, cause = ff_provider_cause.condition_cause(action, "producer_start_failed")
        raise FilingFetchError(
            f"company-wiki {action} failed to start", code=code, upstream_cause=cause,
        ) from exc
    except ff_process_transport.TransportError as exc:
        # Broken pipe / encoding failure during bounded read; message stays
        # free of the command line so no root path leaks.
        code, cause = ff_provider_cause.condition_cause(
            action, "producer_transport_failure"
        )
        raise FilingFetchError(
            f"company-wiki {action} transport failure",
            code=code,
            upstream_cause=cause,
        ) from exc
    except OSError as exc:
        # May be cleanup after target execution. Only typed ChildStartFailed
        # proves no start; preserve legacy fatal retry semantics and unknown usage.
        _, cause = ff_provider_cause.condition_cause(action, "producer_transport_failure")
        cause["retry_scope"] = "none"
        raise FilingFetchError(
            f"company-wiki {action} transport failed", code="fatal", upstream_cause=cause,
        ) from exc
    if returncode != 0:
        # Static failure: report the exit status and the classified code +
        # safe cause only. The raw stderr body is consumed for classification
        # but never echoed - it routinely carries absolute paths and provider
        # credentials.
        code, cause, receipt = ff_provider_cause.diagnose_stderr_observation(
            action, stderr.decode("utf-8", errors="replace").strip()
        )
        raise FilingFetchError(
            f"company-wiki {action} exited {returncode}",
            code=code,
            stage=action,
            attempts=1,
            upstream_cause=cause,
            acquisition_failure=receipt,
        )
    try:
        payload = json.loads(stdout.decode("utf-8", errors="strict"))
    except UnicodeError as exc:
        raise FilingFetchError(f"company-wiki {action} stdout is not valid UTF-8", stage=action,
            upstream_cause=ff_provider_cause.source_condition(action, "invalid_producer_schema")) from exc
    except json.JSONDecodeError as exc:
        raise FilingFetchError(f"company-wiki {action} stdout is not JSON", stage=action,
            upstream_cause=ff_provider_cause.source_condition(action, "invalid_producer_schema")) from exc
    if not isinstance(payload, dict):
        raise FilingFetchError(f"company-wiki {action} response must be an object", stage=action,
            upstream_cause=ff_provider_cause.source_condition(action, "invalid_producer_schema"))
    return payload


def _classify_wiki_error(stderr_text: str) -> str:
    """Map a company-wiki structured stderr payload to a filing error code.

    ZR-205: consume the canonical ZR-204 error-taxonomy codes emitted by the
    wiki CLI (``catalog_locked`` / ``catalog_busy`` / ``db_timeout`` /
    ``worker_paused`` / ``fatal``) directly; keep N-1 fallbacks for the
    legacy class-name emission shape (``CatalogOperationLockedError``,
    ``RuntimeError`` + paused text).  Unknown / malformed payloads fail
    closed to ``fatal`` (never retryable).

    R6-FF-CAUSE: the single parse now lives in ff_provider_cause so the
    error code and the optional upstream_cause diagnostic cannot drift apart.
    """
    return ff_provider_cause.classify_stderr(stderr_text)


def _run_company_wiki_json_retry(
    *,
    command: list[str],
    root: Path,
    action: str,
    deadline: float,
    stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Run a company-wiki CLI call, retrying transient catalog lock
    contention with jittered exponential backoff (5s, 10s, ... capped at
    ``CATALOG_LOCKED_BACKOFF_MAX_SECONDS``) bounded by the overall deadline.

    ZR-205: the retry set is the canonical catalog-contention codes
    (catalog_locked / catalog_busy / db_timeout); ``worker_paused`` and
    ``fatal`` are NOT auto-retried (fail closed).  Jitter is ±20% uniform;
    the wait is clamped to the remaining deadline so a sleep never exceeds
    it.  Every company-wiki subprocess invocation is counted in
    ``stats["calls"]`` for final envelope reconciliation (READ-09).
    """
    attempt = 1
    backoff = CATALOG_LOCKED_BACKOFF_SECONDS
    # R6-FF-CAUSE: the last contention attempt's machine cause survives the
    # deadline exhaustion so the envelope still names what was retried.
    last_cause: dict[str, Any] | None = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FilingFetchError(
                f"overall deadline exceeded before {action}",
                code="upstream_error",
                stage=action,
                attempts=attempt - 1,
                upstream_cause=(
                    last_cause
                    if last_cause is not None
                    else ff_provider_cause.condition_cause(
                        action,
                        "producer_deadline_exceeded",
                        provider_started=False,
                        usage_complete=True,
                    )[1]
                ),
            )
        try:
            return _run_company_wiki_json(
                command=command,
                root=root,
                timeout_seconds=remaining,
                action=action,
                stats=stats,
            )
        except FilingFetchError as exc:
            if exc.code not in _CATALOG_RETRY_CODES:
                raise
            last_cause = exc.upstream_cause
            jittered = backoff * (
                1.0 + random.uniform(-CATALOG_LOCKED_BACKOFF_JITTER, CATALOG_LOCKED_BACKOFF_JITTER)
            )
            wait = min(jittered, remaining)
            if wait <= 0:
                raise FilingFetchError(
                    f"overall deadline exceeded retrying {action}: {exc}",
                    code="upstream_error",
                    stage=action,
                    attempts=attempt,
                    upstream_cause=(
                        last_cause
                        if last_cause is not None
                        else ff_provider_cause.condition_cause(
                            action, "producer_deadline_exceeded"
                        )[1]
                    ),
                ) from exc
            print(
                f"[filing-fetch] {action} blocked by a running catalog operation "
                f"(attempt {attempt}); retrying in {wait:.1f}s: {exc}",
                file=sys.stderr,
            )
            time.sleep(wait)
            attempt += 1
            backoff = min(
                backoff * CATALOG_LOCKED_BACKOFF_MULTIPLIER,
                CATALOG_LOCKED_BACKOFF_MAX_SECONDS,
            )


def _resolved_company_identity(payload: dict[str, Any]) -> dict[str, Any]:
    status = payload.get("status")
    reason = payload.get("reason")
    if status != "resolved":
        # Surface any candidate identities company-wiki returned so the caller
        # can disambiguate (e.g. dual-class tickers GOOGL/GOOG) instead of
        # seeing a bare identity_error.
        raw_candidates = payload.get("candidates")
        candidates = raw_candidates if isinstance(raw_candidates, list) else None
        raise FilingFetchError(
            f"company identity is not uniquely resolved: {status} / {reason}",
            code="identity_error",
            candidates=candidates,
        )
    if payload.get("schema_version") != COMPANY_WIKI_IDENTITY_SCHEMA_VERSION:
        raise FilingFetchError(
            "company identity schema_version is unsupported",
            code="identity_error",
        )
    resolved = payload.get("resolved")
    if not isinstance(resolved, dict):
        raise FilingFetchError("resolved company identity is missing", code="identity_error")
    for name in (
        "canonical_name",
        "market",
        "exchange",
        "ticker",
        "security_id",
        "match_basis",
        "matched_value",
        "source_name",
        "source_url",
        "source_record_id",
    ):
        value = resolved.get(name)
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise FilingFetchError(
                f"company_identity.{name} must be non-empty trimmed text",
                code="identity_error",
            )
    if resolved.get("verified") is not True or resolved.get("active") is not True:
        raise FilingFetchError(
            "company identity must be verified and active before source resolution",
            code="identity_error",
        )
    if resolved["market"] not in {"CN", "HK", "US"}:
        raise FilingFetchError("company identity market is unsupported", code="identity_error")
    return dict(resolved)


def _normalize_stats(stats: dict[str, int] | None) -> dict[str, int]:
    """Return a mutable reconciliation stats dict (ZR-205)."""
    if stats is None:
        stats = {}
    stats.setdefault("calls", 0)
    stats.setdefault("downloads", 0)
    return stats


def _record_download_events(stats: dict[str, int] | None, handle: dict) -> None:
    """Mirror the final resolution envelope's download_events count into the
    reconciliation stats so the response preserves zero-download evidence."""
    if stats is None:
        return
    events = handle.get("download_events")
    if events is None:
        events = (handle.get("resolution_envelope") or {}).get("download_events")
    if isinstance(events, int) and not isinstance(events, bool):
        stats["downloads"] = events


def _source_candidate(handle: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    """Project one source reference without physical storage or bundle fields."""
    candidate = {key: value for key, value in handle.items() if key in _SOURCE_CANDIDATE_FIELDS}
    candidate["source_ref"] = {
        "schema_version": "2.0",
        "document_id": handle["document_id"],
        "source_id": handle["source_id"],
        "content_sha256": handle["snapshot_sha256"],
        "byte_size": handle["byte_size"],
        "mime_type": handle["mime_type"],
    }
    candidate["resolution_outcome"] = envelope["outcome"]
    candidate["download_events"] = envelope["download_events"]
    candidate["prompt_injection_status"] = envelope["prompt_injection_status"]
    return candidate


def _candidate_company_identity(identity: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in identity.items() if key in _COMPANY_IDENTITY_FIELDS}


def _run_source_query(
    *,
    root: Path,
    normalized_request: dict[str, Any],
    deadline: float,
    stats: dict[str, int],
) -> dict[str, Any]:
    """Transport one DB-only query and classify its result."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise FilingFetchError(
            "overall deadline exceeded before source query",
            code="upstream_error",
            upstream_cause=ff_provider_cause.condition_cause(
                "query",
                "producer_deadline_exceeded",
                provider_started=False,
                usage_complete=True,
            )[1],
        )
    query = {
        key: value for key, value in normalized_request.items() if key in _QUERY_REQUEST_FIELDS
    }
    query["schema_version"] = "1.0"
    query["allow_download"] = False
    command = [
        sys.executable,
        "-m",
        "company_wiki.source_catalog.source_query_cli",
        "--config",
        str(root / "config" / "source_catalog.yaml"),
    ]
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    stats["calls"] += 1
    try:
        stdout, stderr, returncode = _run_bounded_json(
            command,
            timeout_seconds=remaining,
            input_bytes=json.dumps(query, ensure_ascii=False).encode("utf-8"),
            cwd=str(root),
            env=environment,
        )
    except _ProcessChildTimeout as exc:
        code, cause = ff_provider_cause.condition_cause(
            "query", "producer_deadline_exceeded"
        )
        raise FilingFetchError(
            "company-wiki source query exceeded its deadline budget",
            code=code,
            upstream_cause=cause,
        ) from exc
    except _ProcessOutputLimitExceeded as exc:
        code, cause = ff_provider_cause.condition_cause(
            "query", "producer_output_exceeded"
        )
        raise FilingFetchError(
            "company-wiki source query exceeded the output byte cap",
            code=code,
            upstream_cause=cause,
        ) from exc
    except _ProcessChildStartFailed as exc:
        _, cause = ff_provider_cause.condition_cause("query", "producer_start_failed")
        raise FilingFetchError(
            "company-wiki source query could not be started",
            code="upstream_error", upstream_cause=cause,
        ) from exc
    except ff_process_transport.TransportError as exc:
        code, cause = ff_provider_cause.condition_cause(
            "query", "producer_transport_failure"
        )
        raise FilingFetchError(
            "company-wiki source query transport failure",
            code=code,
            upstream_cause=cause,
        ) from exc
    except OSError as exc:
        # A plain OSError may occur after execution; no usage/start guess.
        _, cause = ff_provider_cause.condition_cause("query", "producer_transport_failure")
        raise FilingFetchError(
            "company-wiki source query transport failed",
            code="upstream_error", upstream_cause=cause,
        ) from exc
    try:
        payload = json.loads(stdout.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FilingFetchError(
            "company-wiki source query stdout is not JSON",
            code="upstream_error",
            stage="source_query",
            upstream_cause=ff_provider_cause.source_condition("query", "invalid_producer_schema"),
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "2.0":
        raise FilingFetchError(
            "company-wiki source query schema is unsupported",
            code="upstream_error",
            stage="source_query",
            upstream_cause=ff_provider_cause.source_condition("query", "invalid_producer_schema"),
        )
    status = payload.get("status")
    if status != "found":
        errors = {
            "not_found": "not_found",
            "ambiguous": "ambiguous",
            "blocked": "source_blocked",
            "unavailable": "upstream_error",
        }
        if status not in errors:
            raise FilingFetchError(
                "company-wiki source query status is invalid", code="upstream_error"
            )
        raise FilingFetchError(
            f"company-wiki source query {status}",
            code=errors[status],
            stage="source_query",
            upstream_cause=ff_provider_cause.source_condition("query", payload.get("reason")),
        )
    if returncode != 0:
        raise FilingFetchError(
            "company-wiki source query returned found with nonzero exit",
            code="upstream_error",
        )
    return payload


def _source_query_candidate(
    *,
    root: Path,
    normalized_request: dict[str, Any],
    request: dict[str, Any],
    company_identity: dict[str, Any],
    deadline: float,
    stats: dict[str, int],
) -> dict[str, Any]:
    """Get a provisional pathless candidate from CWP's DB-only query CLI.

    No source bytes or root paths cross this boundary. The downstream CWP
    ``open_version(filing_reuse)`` remains the sole verified source read.
    """
    try:
        payload = _run_source_query(
            root=root, normalized_request=normalized_request, deadline=deadline, stats=stats,
        )
    except FilingFetchError as exc:
        if (exc.code != "not_found"
                or request.get("schema_version") != FILING_V2_REQUEST_SCHEMA_VERSION
                or request.get("filing_intent") != "reuse_only"):
            raise
        from ff_local_source_prepare import prepare_existing_local_source

        prepare_existing_local_source(
            root=root,
            source_request={key: value for key, value in normalized_request.items()
                            if key in _QUERY_REQUEST_FIELDS},
            deadline=deadline, stats=stats, transport=_run_bounded_json,
            physical_fields=_contains_physical_field,
        )
        payload = _run_source_query(
            root=root, normalized_request=normalized_request, deadline=deadline, stats=stats,
        )
    matches = payload.get("matches")
    candidates = payload.get("candidates")
    if (
        not isinstance(matches, list)
        or len(matches) != 1
        or not isinstance(candidates, list)
        or len(candidates) != 1
        or not isinstance(matches[0], dict)
        or not isinstance(candidates[0], dict)
    ):
        raise FilingFetchError(
            "company-wiki source query did not return one candidate",
            code="upstream_error",
        )
    source_ref = matches[0]
    candidate = candidates[0]
    if (
        set(source_ref) != _SOURCE_REF_FIELDS
        or source_ref.get("schema_version") != "2.0"
        or candidate.get("source_ref") != source_ref
    ):
        raise FilingFetchError(
            "company-wiki source query SourceRef mismatch",
            code="upstream_error",
        )
    if any(
        forbidden in key.lower()
        for key in candidate
        for forbidden in ("path", "location", "root", "bundle")
    ):
        raise FilingFetchError(
            "company-wiki source query leaked a physical location",
            code="upstream_error",
        )
    from ff_v2_envelope import _reference

    _reference(source_ref)
    handle = dict(candidate)
    handle["request_id"] = payload.get("request_id")
    review_status = handle.get("prompt_injection_status")
    # Review state is diagnostic. The SourceRef is still an unverified candidate;
    # the consumer must use CWP verified-open before treating the bytes as evidence.
    validate_handle_metadata(handle, request)
    if (
        handle.get("document_id") != source_ref["document_id"]
        or handle.get("source_id") != source_ref["source_id"]
        or handle.get("snapshot_sha256") != source_ref["content_sha256"]
        or handle.get("byte_size") != source_ref["byte_size"]
        or handle.get("mime_type") != source_ref["mime_type"]
    ):
        raise FilingFetchError(
            "company-wiki source query candidate identity mismatch",
            code="upstream_error",
        )
    if handle.get("document_kind") != request.get("document_kind"):
        raise FilingFetchError(
            "company-wiki source query document_kind mismatch",
            code="upstream_error",
        )
    if (
        request.get("fiscal_year") is not None
        and handle.get("fiscal_year") != request["fiscal_year"]
    ):
        raise FilingFetchError(
            "company-wiki source query fiscal_year mismatch",
            code="upstream_error",
        )
    for key in ("market", "security_id"):
        if key in handle and handle[key] != company_identity[key]:
            raise FilingFetchError(
                f"company-wiki source query {key} mismatch",
                code="upstream_error",
            )
    handle["company_identity"] = _candidate_company_identity(company_identity)
    handle["resolution_outcome"] = "reused_existing"
    handle["download_events"] = 0
    handle["byte_verified"] = False
    handle["prompt_injection_status"] = review_status
    return handle


_SOURCE_OPERATION_VERSION = "1.0"
_SOURCE_OPERATION_FIELDS = frozenset(
    {
        "operation_schema_version",
        "operation",
        "status",
        "request_id",
        "outcome",
        "download_events",
        "policy_hash",
        "source_ref",
        "candidate",
        "gap_plan",
        "acquisition_failure",
    }
)
_SOURCE_OPERATION_STATUSES = frozenset(
    {
        "completed",
        "gap",
        "ambiguous",
        "not_found",
        "unavailable",
    }
)


def _contains_physical_field(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            any(token in str(key).lower() for token in ("path", "location", "root", "bundle"))
            or _contains_physical_field(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_physical_field(child) for child in value)
    return False


def _validated_operation(payload: dict[str, Any], operation: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise FilingFetchError(
            "company-wiki operation result must be an object", code="upstream_error",
            upstream_cause=ff_provider_cause.source_condition(operation, "invalid_producer_schema"),
        )
    upstream_cause = ff_provider_cause.diagnose_acquisition_failure(
        operation, payload.get("acquisition_failure")
    )
    receipt = ff_provider_cause.validated_acquisition_failure(payload.get("acquisition_failure"))
    if (
        payload.get("operation_schema_version") != _SOURCE_OPERATION_VERSION
        or payload.get("operation") != operation
        or not set(payload) <= _SOURCE_OPERATION_FIELDS
    ):
        raise FilingFetchError(
            "company-wiki operation contract is unsupported", code="upstream_error",
            upstream_cause=upstream_cause or ff_provider_cause.source_condition(operation, "invalid_producer_schema"),
            acquisition_failure=receipt,
        )
    if payload.get("status") not in _SOURCE_OPERATION_STATUSES:
        raise FilingFetchError(
            "company-wiki operation status is invalid", code="upstream_error",
            upstream_cause=upstream_cause or ff_provider_cause.source_condition(operation, "invalid_producer_schema"),
            acquisition_failure=receipt,
        )
    if _contains_physical_field({
        key: value for key, value in payload.items() if key != "acquisition_failure"
    }):
        raise FilingFetchError(
            "company-wiki operation result leaked a physical location", code="upstream_error",
            upstream_cause=upstream_cause,
            acquisition_failure=receipt,
        )
    request_id = payload.get("request_id")
    if (
        not isinstance(request_id, str)
        or not request_id.strip()
        or request_id != request_id.strip()
    ):
        raise FilingFetchError(
            "company-wiki operation request_id is invalid", code="upstream_error",
            upstream_cause=upstream_cause,
            acquisition_failure=receipt,
        )
    policy_hash = payload.get("policy_hash")
    if policy_hash is not None and (
        not isinstance(policy_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", policy_hash)
    ):
        raise FilingFetchError(
            "company-wiki operation policy_hash is invalid", code="upstream_error",
            upstream_cause=upstream_cause,
            acquisition_failure=receipt,
        )
    return payload


def _pathless_operation_gap(
    payload: dict[str, Any],
    *,
    operation: str,
) -> dict[str, Any]:
    result = _validated_operation(payload, operation)
    if result["status"] != "gap":
        raise FilingFetchError("company-wiki operation is not a gap", code="upstream_error")
    plan = result.get("gap_plan")
    if (
        not isinstance(plan, dict)
        or plan.get("schema_version") != "1.0"
        or not isinstance(plan.get("gap_hash"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", plan["gap_hash"])
        or plan.get("request_id") != result["request_id"]
    ):
        raise FilingFetchError("company-wiki gap plan is incomplete", code="upstream_error")
    if (
        result.get("outcome") != "gap"
        or isinstance(result.get("download_events"), bool)
        or result.get("download_events") != 0
    ):
        raise FilingFetchError("company-wiki gap receipt is inconsistent", code="upstream_error")
    if plan.get("request_id") not in (None, result["request_id"]):
        raise FilingFetchError("company-wiki gap request binding changed", code="upstream_error")
    resolution = {
        "status": "missing",
        "reason": "metadata_only_gap_plan",
        "request_id": result["request_id"],
        "resolution_envelope": {"policy_hash": result.get("policy_hash")},
    }
    gap = {"status": "gap", "gap_plan": plan, "resolution": resolution}
    upstream_cause = ff_provider_cause.diagnose_acquisition_failure(
        operation, result.get("acquisition_failure")
    )
    if upstream_cause is not None:
        gap["upstream_cause"] = upstream_cause
    receipt = ff_provider_cause.validated_acquisition_failure(result.get("acquisition_failure"))
    if receipt is not None:
        gap["acquisition_failure"] = receipt
    return gap


def _pathless_operation_handle(
    payload: dict[str, Any],
    *,
    operation: str,
    request: dict[str, Any],
    company_identity: dict[str, Any],
    stats: dict[str, int] | None,
) -> dict[str, Any]:
    result = _validated_operation(payload, operation)
    if result["status"] != "completed":
        errors = {
            "ambiguous": ("ambiguous", "ambiguous"),
            "not_found": ("not_found", "not_found"),
            "unavailable": ("upstream_error", "upstream_error"),
        }
        code, stage = errors.get(result["status"], ("upstream_error", "source_operation"))
        raise FilingFetchError(
            f"company-wiki {operation} {result['status']}",
            code=code,
            stage=stage,
            upstream_cause=ff_provider_cause.diagnose_acquisition_failure(
                operation, result.get("acquisition_failure")
            ) or ff_provider_cause.source_condition(operation, "source_not_found" if result["status"] == "not_found" else "unknown"),
            acquisition_failure=ff_provider_cause.validated_acquisition_failure(result.get("acquisition_failure")),
        )
    outcome = result.get("outcome")
    events = result.get("download_events")
    if outcome not in {"reused_existing", "reused_after_discovery", "downloaded_new"}:
        raise FilingFetchError("company-wiki operation outcome is invalid", code="upstream_error")
    if isinstance(events, bool) or events not in (0, 1):
        raise FilingFetchError(
            "company-wiki operation download_events is invalid", code="upstream_error"
        )
    if (outcome == "downloaded_new") != (events == 1):
        raise FilingFetchError(
            "company-wiki operation download receipt is inconsistent", code="upstream_error"
        )

    source_ref = result.get("source_ref")
    candidate = result.get("candidate")
    if (
        not isinstance(source_ref, dict)
        or set(source_ref) != _SOURCE_REF_FIELDS
        or source_ref.get("schema_version") != "2.0"
        or not isinstance(candidate, dict)
        or candidate.get("source_ref") != source_ref
    ):
        raise FilingFetchError("company-wiki operation SourceRef mismatch", code="upstream_error")
    handle = {key: value for key, value in candidate.items() if key in _SOURCE_CANDIDATE_FIELDS}
    handle["source_ref"] = dict(source_ref)
    handle["request_id"] = result["request_id"]
    if (
        handle.get("document_id") != source_ref.get("document_id")
        or handle.get("source_id") != source_ref.get("source_id")
        or handle.get("snapshot_sha256") != source_ref.get("content_sha256")
        or handle.get("byte_size") != source_ref.get("byte_size")
        or handle.get("mime_type") != source_ref.get("mime_type")
        or handle.get("content_sha256", source_ref.get("content_sha256"))
        != source_ref.get("content_sha256")
    ):
        raise FilingFetchError(
            "company-wiki operation candidate identity mismatch", code="upstream_error"
        )
    review_status = candidate.get("prompt_injection_status")
    # The operation supplies logical metadata; byte verification remains CWP's
    # verified-open responsibility at the consumer boundary.
    validate_handle_metadata(handle, request)
    if handle.get("document_kind") != request.get("document_kind"):
        raise FilingFetchError(
            "company-wiki operation document_kind mismatch", code="upstream_error"
        )
    if (
        request.get("fiscal_year") is not None
        and handle.get("fiscal_year") != request["fiscal_year"]
    ):
        raise FilingFetchError("company-wiki operation fiscal_year mismatch", code="upstream_error")
    for key in ("market", "security_id"):
        if key in handle and handle[key] != company_identity[key]:
            raise FilingFetchError(f"company-wiki operation {key} mismatch", code="upstream_error")

    handle["company_identity"] = _candidate_company_identity(company_identity)
    handle["resolution_outcome"] = outcome
    handle["download_events"] = events
    handle["prompt_injection_status"] = review_status
    handle["byte_verified"] = False
    handle["operation_receipt"] = {
        "operation_schema_version": _SOURCE_OPERATION_VERSION,
        "operation": operation,
        "request_id": result["request_id"],
        "outcome": outcome,
        "download_events": events,
        "policy_hash": result.get("policy_hash"),
    }
    _record_download_events(stats, handle)
    return handle


def _resolve_source_ref_v2(
    *,
    source_query_route: bool,
    root: Path,
    command_prefix: list[str],
    normalized_request: dict[str, Any],
    request: dict[str, Any],
    company_identity: dict[str, Any],
    deadline: float,
    allow_download: bool,
    stats: dict[str, int],
) -> dict[str, Any]:
    # Own every opt-in SourceRef route behind one isolated dispatcher.
    if source_query_route:
        return _source_query_candidate(
            root=root,
            normalized_request=normalized_request,
            request=request,
            company_identity=company_identity,
            deadline=deadline,
            stats=stats,
        )

    command = [
        *command_prefix,
        "ensure",
        *_command_arguments(normalized_request),
        "--source-ref-v2",
    ]
    if allow_download:
        if not normalized_request.get("market") or not normalized_request.get("security_id"):
            raise FilingFetchError("explicit download requires market and security_id")
        command.extend(
            (
                "--allow-download",
                "--acquisition-config",
                str(root / "config" / "source_acquisition.yaml"),
            )
        )
    payload = _run_company_wiki_json_retry(
        command=command,
        root=root,
        action="ensure",
        deadline=deadline,
        stats=stats,
    )

    if payload.get("status") != "gap":
        return _pathless_operation_handle(
            payload,
            operation="ensure",
            request=request,
            company_identity=company_identity,
            stats=stats,
        )

    # V2 emits the exact CWP gap as a pathless result. All versions use
    # one ensure transaction; a producer GAP is never a second download.
    # The request's byte/time/fee ceilings are already on this ensure argv;
    # a gap the producer still reports is returned as the honest gap, never
    # rewritten into a capture that did not happen.
    gap_result = _pathless_operation_gap(payload, operation="ensure")
    stats["downloads"] = 0
    return gap_result


def _run_legacy_filing_command(
    *, action: str, command_prefix: list[str], normalized_request: dict[str, Any],
    root: Path, deadline: float, allow_download: bool, stats: dict[str, int],
) -> dict[str, Any]:
    """Send one legacy request; old authorization only narrows target/caps."""
    scope = normalized_request.get("authorization") if allow_download else None
    effective_request = normalized_request
    if scope is not None and "acquisition_limits" not in effective_request:
        # The old request supplied bytes but no separate provider deadline.
        # Share the existing request deadline, and allow no provider fees.
        effective_request = dict(normalized_request, acquisition_limits={
            "max_bytes": scope["max_bytes"],
            "timeout_seconds": max(0, deadline - time.monotonic()),
            "max_cost_usd": "0",
        })
    command = [*command_prefix, action, *_command_arguments(effective_request)]
    if allow_download:
        if not normalized_request.get("market") or not normalized_request.get("security_id"):
            raise FilingFetchError("explicit download requires market and security_id")
        command.extend(("--allow-download", "--acquisition-config",
                        str(root / "config" / "source_acquisition.yaml")))
    scope_path = None
    try:
        if scope is not None:
            import tempfile

            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False,
                                             encoding="utf-8") as scope_file:
                scope_path = Path(scope_file.name)
                json.dump({key: scope[key] for key in
                           ("provider", "allowed_accessions", "max_items", "max_bytes")},
                          scope_file)
            command.extend(("--binding-file", str(scope_path)))
        return _run_company_wiki_json_retry(
            command=command, root=root, action=action, deadline=deadline, stats=stats,
        )
    finally:
        if scope_path is not None:
            scope_path.unlink(missing_ok=True)




def _use_source_query(source_ref_v2: bool, allow_download: bool, request: dict) -> bool:
    """Keep the opt-in reuse decision out of the legacy orchestrator."""
    if not isinstance(source_ref_v2, bool):
        raise TypeError("source_ref_v2 must be boolean")
    mode = str(request.get("mode") or "").strip().lower()
    return source_ref_v2 and not allow_download and mode != "latest_as_of"


def _download_intent(request: dict[str, Any], explicit: bool | None) -> bool:
    """One download intent per request, derived in exactly one place.

    v2 declares it as ``filing_intent``; that is the authority, and both the
    CLI and the library go through here.  v1 keeps the caller's flag as a thin
    compatibility input.  An explicit value that contradicts a v2 request is a
    named request error rather than a second, silently different decision.
    """
    if request.get("schema_version") != FILING_V2_REQUEST_SCHEMA_VERSION:
        return bool(explicit)
    derived = request.get("filing_intent") == "fetch_if_missing"
    if explicit is not None and bool(explicit) != derived:
        raise FilingFetchError(
            "allow_download contradicts filing_intent; a v2 request carries "
            "exactly one download intent",
            code="request_error",
        )
    return derived


def _shared_deadline(
    request: dict[str, Any], *, deadline: float | None, timeout_seconds: float
) -> float:
    """The single budget every subprocess of this request shares.

    It is the smallest of what remains of the caller's global deadline, the
    configured ``--timeout-seconds`` budget, and - when the request declares
    one - its own ``acquisition_limits.timeout_seconds``.  One monotonic
    sample feeds all three so the three candidates are measured together.
    """
    now = time.monotonic()
    if deadline is None:
        deadline = now + timeout_seconds
    elif deadline <= now:
        raise FilingFetchError("overall deadline expired", code="upstream_error")
    budget = min(deadline, now + timeout_seconds)
    limits = request.get("acquisition_limits")
    if isinstance(limits, dict):
        budget = min(budget, now + float(limits["timeout_seconds"]))
    return budget


def resolve_filing(
    *,
    request: dict[str, Any],
    company_wiki_root: Path | None = None,
    config_path: Path | None = None,
    allow_download: bool | None = None,
    timeout_seconds: float = 900.0,
    # P5-FF compat no-ops: the old worker pause-around orchestration was
    # retired upstream; these kwargs stay accepted because revenue-forecast
    # reps and older callers still pass them. They no longer probe, pause,
    # resume, or write any pause state.
    pause_worker: bool = True,
    worker_graceful_timeout_seconds: float = 5.0,
    worker_resume_wait_seconds: float = 5.0,
    stats: dict[str, int] | None = None,
    source_ref_v2: bool = False,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Identify an optional company query, then resolve or explicitly ensure a filing.

    The default path calls the read-only ``resolve`` command and reuses an
    existing company-wiki filing. An explicit download intent calls
    ``ensure --allow-download``; company-wiki then routes the download by market
    (CN -> StockInfo, HK/US -> dayu) and writes any new bytes into
    ``companies/{entity}/raw/{kind}/``. A ``company_query`` is resolved to one
    verified active security before either source command is constructed.

    The download intent is derived once, in :func:`_download_intent`: a v2
    request declares it as ``filing_intent`` and ``allow_download`` may only
    confirm it, never contradict it; a v1 request keeps the caller's flag.
    The deadline every subprocess shares is :func:`_shared_deadline`, the
    smallest of the remaining global deadline, the configured
    ``timeout_seconds`` and the request's own ``acquisition_limits``.

    ``pause_worker`` / ``worker_graceful_timeout_seconds`` /
    ``worker_resume_wait_seconds`` are accepted as inert compatibility
    arguments since the CWP worker route was retired; they no longer spawn
    worker-status/pause/resume subprocesses nor write pause files.

    ``stats`` (optional, mutated in place): ZR-205 reconciliation counters.
    ``stats["calls"]`` counts every real company-wiki subprocess invocation
    (including retries); ``stats["downloads"]`` is the download event count
    from the final resolution envelope (0 unless a download actually
    committed).  Final success and failure both preserve these counts in the
    response envelope (READ-09/READ-10).
    """
    stats = _normalize_stats(stats)

    if company_wiki_root is not None and config_path is not None:
        raise ValueError("company_wiki_root cannot be combined with config_path")
    if not isinstance(request, dict):
        raise TypeError("request must be a dict")
    if allow_download is not None and not isinstance(allow_download, bool):
        raise TypeError("allow_download must be boolean")
    if timeout_seconds <= 0 or not math.isfinite(timeout_seconds):
        raise ValueError("timeout_seconds must be positive and finite")
    validate_request(request)
    allow_download = _download_intent(request, allow_download)
    source_query_route = _use_source_query(source_ref_v2, allow_download, request)
    if request.get("schema_version") == FILING_V2_REQUEST_SCHEMA_VERSION and not source_ref_v2:
        raise FilingFetchError(
            "v2 requests require the pathless SourceRef route",
            code="request_error",
        )
    deadline = _shared_deadline(request, deadline=deadline, timeout_seconds=timeout_seconds)
    root = (
        _validate_company_wiki_root(company_wiki_root)
        if company_wiki_root is not None
        else load_company_wiki_root(config_path=config_path)
    )
    command_prefix = [
        sys.executable,
        "-m",
        "company_wiki.source_catalog.cli",
        "--config",
        str(root / "config" / "source_catalog.yaml"),
    ]
    # Every request passes through verified/active identity before source
    # resolution; validate_request guarantees company_query is present.
    identity_payload = _run_company_wiki_json_retry(
        command=[
            *command_prefix,
            "identify",
            *_identity_arguments(request),
        ],
        root=root,
        action="identify",
        deadline=deadline,
        stats=stats,
    )
    company_identity = _resolved_company_identity(identity_payload)
    normalized_request = {
        key: value
        for key, value in request.items()
        if key not in {"company_query", "exchange", "filing_intent", "companion_transcript"}
    }
    normalized_request.update(
        {
            "entity": company_identity["canonical_name"],
            "market": company_identity["market"],
            "security_id": company_identity["security_id"],
        }
    )
    # All explicit v2 requests are handled by one pathless dispatcher.
    mode = str(request.get("mode") or "").strip().lower()
    is_latest = mode == "latest_as_of"
    if source_ref_v2:
        return _resolve_source_ref_v2(
            source_query_route=source_query_route,
            root=root,
            command_prefix=command_prefix,
            normalized_request=normalized_request,
            request=request,
            company_identity=company_identity,
            deadline=deadline,
            allow_download=allow_download,
            stats=stats,
        )

    action = "ensure" if (allow_download or is_latest) else "resolve"
    payload = _run_legacy_filing_command(
        action=action,
        command_prefix=command_prefix,
        normalized_request=normalized_request,
        root=root,
        deadline=deadline,
        allow_download=allow_download,
        stats=stats,
    )
    if action == "ensure":
        # FC-802: the ensure payload carries the top-level status; GAP is a
        # STRUCTURED result (metadata-only plan), never a not_found error.
        if payload.get("status") == "gap":
            gap_plan = (payload.get("acquisition") or {}).get("gap_plan")
            gap = {
                "status": "gap",
                "gap_plan": gap_plan,
                "resolution": payload.get("resolution"),
            }
            upstream_cause = ff_provider_cause.diagnose_acquisition_failure(
                action, payload.get("acquisition_failure")
            )
            if upstream_cause is not None:
                gap["upstream_cause"] = upstream_cause
            receipt = ff_provider_cause.validated_acquisition_failure(payload.get("acquisition_failure"))
            if receipt is not None:
                gap["acquisition_failure"] = receipt
            return gap
        resolution = payload.get("resolution")
    else:
        resolution = payload
    if not isinstance(resolution, dict):
        raise FilingFetchError(
            "company-wiki resolution is missing", code="upstream_error",
            upstream_cause=ff_provider_cause.diagnose_acquisition_failure(
                action, payload.get("acquisition_failure")
            ),
            acquisition_failure=ff_provider_cause.validated_acquisition_failure(payload.get("acquisition_failure")),
        )
    expected_schema = (
        SUPPORTED_COMPANY_WIKI_CONTRACTS["ensure_schema_version"]
        if allow_download
        else SUPPORTED_COMPANY_WIKI_CONTRACTS["resolve_schema_version"]
    )
    if resolution.get("schema_version") != expected_schema:
        raise FilingFetchError(
            "company-wiki resolution schema_version is unsupported",
            code="upstream_error",
            upstream_cause=ff_provider_cause.source_condition(action, "invalid_producer_schema"),
            acquisition_failure=ff_provider_cause.validated_acquisition_failure(payload.get("acquisition_failure")),
        )
    if resolution.get("status") not in {"reused_exact", "reused_equivalent"}:
        raise FilingFetchError(
            f"source is not reusable: {resolution.get('status')} / {resolution.get('reason')}",
            code="not_found",
            debug_trace=resolution.get("debug_trace"),
            resolution_trace=_resolution_trace(resolution),
            upstream_cause=ff_provider_cause.diagnose_acquisition_failure(
                action, payload.get("acquisition_failure")
            ) or ff_provider_cause.source_condition(action, resolution.get("reason") if resolution.get("reason") == "local_metadata_gap" else "source_not_found"),
            acquisition_failure=ff_provider_cause.validated_acquisition_failure(payload.get("acquisition_failure")),
        )
    handle = _handle_from_resolution(
        resolution,
        request,
        root,
        source_ref_v2=source_ref_v2,
    )
    handle["company_identity"] = (
        _candidate_company_identity(company_identity) if source_ref_v2 else company_identity
    )
    # ZR-205: record the download event count from the final resolution
    # envelope (0 = pure reuse, 1 = committed download) so the final
    # envelope preserves the zero-download / call-count evidence (READ-10).
    _record_download_events(stats, handle)
    return handle


def _resolution_trace(resolution: dict | None) -> dict[str, Any] | None:
    """Build a compact trace of the upstream resolution evidence.

    ZR-307: the trace survives downstream handle/validation failures so the
    error envelope never swallows the exact-reuse / download=0 evidence.
    """
    if not isinstance(resolution, dict):
        return None
    return {
        "request_id": resolution.get("request_id"),
        "status": resolution.get("status"),
        "reason": resolution.get("reason"),
    }


def _handle_from_resolution(
    resolution: dict,
    request: dict,
    root: Path,
    *,
    envelope: dict | None = None,
    source_ref_v2: bool = False,
) -> dict:
    """Build either the legacy local handle or a pathless source candidate.

    Shared by the reuse path and the FC-802 close-gap path so the handle
    contract (exactly-one match and capture provenance) stays single-sourced.
    """
    matches = resolution.get("matches")
    if not isinstance(matches, list) or len(matches) != 1 or not isinstance(matches[0], dict):
        raise FilingFetchError(
            "company-wiki did not return exactly one source handle",
            code="upstream_error",
            resolution_trace=_resolution_trace(resolution),
        )
    handle = dict(matches[0])
    if not source_ref_v2 and handle.get("capture_ready") is not True:
        raise FilingFetchError(
            "source lacks capture provenance: "
            + ", ".join(str(item) for item in handle.get("missing_capture_fields", [])),
            code="not_found",
            resolution_trace=_resolution_trace(resolution),
        )
    handle["request_id"] = resolution.get("request_id")
    # The old local-file contract still uses policy_export for containment.
    # The source-ref contract leaves physical eligibility to the one final
    # company-wiki open performed by the consumer.
    policy_snapshot = resolution.get("policy_export") if not source_ref_v2 else None
    expected_policy_hash = None
    if isinstance(policy_snapshot, dict):
        expected_policy_hash = policy_snapshot.get("policy_hash")
    # ZR-307: validate handle and resolution envelope; any failure carries
    # the upstream resolution trace so the error envelope never swallows
    # the exact-reuse / download=0 evidence.
    try:
        if source_ref_v2:
            validate_handle_metadata(handle, request)
        else:
            validate_handle(
                handle,
                request,
                root,
                policy_snapshot=policy_snapshot,
                expected_policy_hash=expected_policy_hash,
            )
        # Validate the upstream acquisition outcome. Legacy mode forwards the
        # full envelope; source-ref mode projects only pathless audit scalars.
        if envelope is None:
            envelope = resolution.get("resolution_envelope")
        if source_ref_v2 and envelope is None:
            raise FilingFetchError(
                "resolution envelope is required for SourceRef v2",
                code="upstream_error",
            )
        if envelope is not None:
            # FC-903: normalize N-1 fields and validate the outcome taxonomy.
            envelope = validate_resolution_envelope(envelope)
            # ZR-405: legacy local handles keep their root-policy hash fence.
            # SourceRef candidates leave current read policy to the consumer.
            envelope_policy_hash = envelope.get("policy_hash")
            if (
                not source_ref_v2
                and envelope_policy_hash is not None
                and expected_policy_hash is not None
                and envelope_policy_hash != expected_policy_hash
            ):
                raise FilingFetchError(
                    "resolution envelope policy_hash does not match the exported root policy",
                    code="upstream_error",
                    resolution_trace=_resolution_trace(resolution),
                )
            if not source_ref_v2:
                handle["resolution_envelope"] = dict(envelope)
        if source_ref_v2:
            assert envelope is not None
            return _source_candidate(handle, envelope)
    except FilingFetchError as exc:
        exc.resolution_trace = _resolution_trace(resolution)
        raise
    return handle




def _resolve_v2_companion(
    *,
    request: dict[str, Any],
    handle: dict[str, Any],
    config_path: Path | None,
    deadline: float,
    stats: dict[str, int],
) -> dict[str, Any]:
    """Resolve one exact-period companion without changing filing success."""
    if handle.get("status") == "gap":
        return {
            "status": "not_applicable",
            "reason": "filing_not_capture_ready",
            "retryable": False,
        }
    option = request.get("companion_transcript")
    if option is None:
        return {"status": "not_requested", "retryable": False}
    if (
        not isinstance(option, dict)
        or option.get("fiscal_year") is None
        or option.get("fiscal_quarter") is None
    ):
        return {"status": "period_unresolved", "reason": "exact_fy_q_required", "retryable": False}
    try:
        wiki_root = load_company_wiki_root(config_path=config_path)
        from transcript_companion import resolve_companion_transcript
        from transcript_tool_transport import EarningsTranscriptsTransport

        transport = EarningsTranscriptsTransport(
            wiki_root=wiki_root,
            config_path=config_path or DEFAULT_COMPANY_WIKI_CONFIG,
            deadline=deadline,
        )
        result = resolve_companion_transcript(
            request=request,
            filing_handle=handle,
            transport=transport,
        )
        stats["calls"] = stats.get("calls", 0) + transport.company_wiki_calls
        return result
    except Exception as exc:
        return {
            "status": "upstream_error",
            "reason": f"transcript_transport_unavailable:{type(exc).__name__}",
            "retryable": True,
        }


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for on-demand filing fetch.

    Exit codes: 0 = capture-ready filing found/reused, 1 = fatal error,
    2 = filing not reusable / not found (or config/identity problem).
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="filing-fetch",
        description="Resolve or download a company filing into company-wiki.",
    )
    parser.add_argument(
        "--allow-download",
        action="store_true",
        help="allow a market-routed download if the filing is missing (default: read-only reuse)",
    )
    parser.add_argument(
        "--config", type=Path, default=None, help="path to company_wiki.json config"
    )
    parser.add_argument(
        "--request-file",
        type=Path,
        default=None,
        help="read JSON request from file instead of stdin",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=900.0,
        help="overall deadline for the entire request (default: 900)",
    )
    parser.add_argument(
        "--no-pause-worker",
        action="store_true",
        help=(
            "accepted for compatibility; inert since the company-wiki worker "
            "pause-around was retired upstream (no worker-status probe, no "
            "pause files, no resume)"
        ),
    )
    parser.add_argument(
        "--worker-graceful-timeout-seconds",
        type=float,
        default=5.0,
        help="accepted for compatibility; inert (see --no-pause-worker)",
    )
    parser.add_argument(
        "--worker-resume-wait-seconds",
        type=float,
        default=5.0,
        help="accepted for compatibility; inert (see --no-pause-worker)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="include the per-candidate exclusion trace in the error response",
    )
    parser.add_argument(
        "--source-ref-v2",
        action="store_true",
        help="return a pathless source reference for a later company-wiki read",
    )
    args = parser.parse_args(argv)
    v2_response = False

    if args.timeout_seconds <= 0 or not math.isfinite(args.timeout_seconds):
        print("error: timeout-seconds must be positive and finite", file=sys.stderr)
        return 2

    try:
        if hasattr(sys.stdin, "reconfigure"):
            # Phase 16.4: Windows pipes decode stdin with the locale codepage
            # (GBK), corrupting UTF-8 Chinese queries. Force UTF-8 so piped
            # requests behave like --request-file.
            sys.stdin.reconfigure(encoding="utf-8", errors="strict")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="strict")
        try:
            if args.request_file:
                request = json.loads(args.request_file.read_text(encoding="utf-8"))
            else:
                request = json.loads(sys.stdin.read())
        except (OSError, json.JSONDecodeError) as exc:
            raise FilingFetchError(f"invalid request: {exc}", code="request_error") from exc
        if not isinstance(request, dict):
            raise FilingFetchError("request must be a JSON object", code="request_error")
        v2_response = request.get("schema_version") == FILING_V2_REQUEST_SCHEMA_VERSION
        if v2_response:
            validate_request(request)
        stats = {"calls": 0, "downloads": 0}
        deadline = time.monotonic() + args.timeout_seconds
        # One derivation point: v2 declares the intent in the request itself
        # (the --allow-download flag only ever applies to v1 requests).
        allow_download = _download_intent(request, None if v2_response else args.allow_download)
        handle = resolve_filing(
            request=request,
            config_path=args.config,
            allow_download=allow_download,
            timeout_seconds=args.timeout_seconds,
            pause_worker=not args.no_pause_worker,
            worker_graceful_timeout_seconds=args.worker_graceful_timeout_seconds,
            worker_resume_wait_seconds=args.worker_resume_wait_seconds,
            stats=stats,
            source_ref_v2=(args.source_ref_v2 or v2_response),
            deadline=deadline,
        )
        if v2_response:
            from ff_v2_envelope import success_envelope

            output = success_envelope(
                request,
                handle,
                _resolve_v2_companion(
                    request=request,
                    handle=handle,
                    config_path=args.config,
                    deadline=deadline,
                    stats=stats,
                ),
                stats,
            )
        elif isinstance(handle, dict) and handle.get("status") == "gap":
            # FC-802: a structured gap passes through unwrapped — it is NOT
            # a capture-ready handle and must never be wrapped as one.
            output = handle
        else:
            output = {
                "schema_version": FILING_RESPONSE_SCHEMA_VERSION,
                "status": "capture_ready",
                "handle": handle,
                # ZR-205: preserve the call/download counts in the final
                # success envelope for reconciliation (READ-09/READ-10).
                "calls": stats["calls"],
                "downloads": stats["downloads"],
            }
        json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except FilingFetchError as exc:
        if v2_response:
            from ff_v2_envelope import error_envelope

            output = error_envelope(
                exc.code,
                str(exc),
                retryable=exc.retryable,
                stats=stats if "stats" in locals() else None,
                request=request if "request" in locals() and isinstance(request, dict) else None,
                upstream_cause=exc.upstream_cause,
                acquisition_failure=exc.acquisition_failure,
                stage=exc.stage,
                attempts=exc.attempts,
            )
            json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
            return 2
        error_response: dict[str, Any] = {
            "schema_version": FILING_RESPONSE_SCHEMA_VERSION,
            "status": exc.code,
            "error": str(exc),
            "error_code": exc.code,
            "retryable": exc.retryable,
        }
        if exc.candidates:
            error_response["candidates"] = exc.candidates
            error_response["hint"] = (
                "identity is ambiguous; disambiguate by adding market/exchange "
                "or by using a specific ticker in company_query"
            )
        if args.debug and exc.debug_trace:
            error_response["debug_trace"] = exc.debug_trace
        # ZR-205 stage-error transparency: the failing stage and attempt
        # count ride on the error envelope when known (READ-09), and the
        # call/download counts stay visible on failure too (READ-10).
        if exc.stage is not None:
            error_response["stage"] = exc.stage
        if exc.attempts is not None:
            error_response["attempts"] = exc.attempts
        # ZR-307: the upstream resolution trace survives downstream
        # handle/validation failures — the error envelope never swallows
        # the exact-reuse / download=0 evidence.
        if exc.resolution_trace is not None:
            error_response["resolution_trace"] = exc.resolution_trace
        # R6-FF-CAUSE: the optional safe machine diagnostic for the failed
        # producer call (v1 keeps it top-level; absent when no operation ran).
        if exc.upstream_cause is not None:
            error_response["upstream_cause"] = exc.upstream_cause
        if exc.acquisition_failure is not None:
            error_response["acquisition_failure"] = exc.acquisition_failure
        if "stats" in locals():
            error_response["calls"] = stats["calls"]
            error_response["downloads"] = stats["downloads"]
        json.dump(error_response, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 2
    except Exception as exc:
        if v2_response:
            from ff_v2_envelope import error_envelope

            output = error_envelope(
                "fatal",
                str(exc),
                retryable=False,
                stats=stats if "stats" in locals() else None,
                request=request if "request" in locals() and isinstance(request, dict) else None,
            )
            json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
            return 1
        json.dump(
            {
                "schema_version": FILING_RESPONSE_SCHEMA_VERSION,
                "status": "fatal",
                "error": str(exc),
                "error_code": "fatal",
                "retryable": False,
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
        return 1


__all__ = [
    "COMPANY_WIKI_CONFIG_SCHEMA_VERSION",
    "COMPANY_WIKI_IDENTITY_SCHEMA_VERSION",
    "DEFAULT_COMPANY_WIKI_CONFIG",
    "FilingFetchError",
    "load_company_wiki_root",
    "main",
    "resolve_filing",
]


if __name__ == "__main__":
    raise SystemExit(main())
