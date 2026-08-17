"""On-demand company filing fetcher (market-routed, reuse-first).

This is a thin client over company-wiki's acquisition engine. It identifies a
company, then resolves (reuses) an existing filing in company-wiki, or — only
when explicitly authorized — delegates a missing-source download to company-wiki
which routes by market: A-share (CN) -> StockInfoDLSimple/cninfo, HK/US ->
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
import subprocess
import sys
import time
from typing import Any


from filing_contracts import (  # noqa: E402  re-export
    FILING_RESPONSE_SCHEMA_VERSION,
    CONFIG_TOKEN_RE,
    COMPANY_WIKI_CONFIG_SCHEMA_VERSION,
    COMPANY_WIKI_IDENTITY_SCHEMA_VERSION,
    SUPPORTED_COMPANY_WIKI_CONTRACTS,
    FilingFetchError,
    validate_handle,
    validate_request,
    validate_resolution_envelope,
    _required_text,
)

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
        raise FilingFetchError(
            "company-wiki config must be a file", code="config_error"
        )
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FilingFetchError(
            f"invalid company-wiki config: {exc}", code="config_error"
        ) from exc
    if not isinstance(payload, dict):
        raise FilingFetchError(
            "company-wiki config must be an object", code="config_error"
        )
    required = {"schema_version", "company_wiki_root"}
    if not set(payload) <= required or not required <= set(payload):
        raise FilingFetchError(
            "company-wiki config must contain exactly schema_version/company_wiki_root "
            "(FC-501: no independent allowed_handle_roots allowlist)",
            code="config_error",
        )
    if payload["schema_version"] != COMPANY_WIKI_CONFIG_SCHEMA_VERSION:
        raise FilingFetchError(
            f"company-wiki config schema_version must be {COMPANY_WIKI_CONFIG_SCHEMA_VERSION}",
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
            "company-wiki config company_wiki_root must be absolute after "
            "token expansion",
            code="config_error",
        )
    return _validate_company_wiki_root(root)



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
    return arguments


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
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    if stats is not None:
        stats["calls"] += 1
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        # A subprocess timeout means the attempt outlived the remaining
        # deadline budget: classify as upstream_error (retryable), not fatal.
        raise FilingFetchError(
            f"company-wiki {action} failed: {exc}", code="upstream_error"
        ) from exc
    except OSError as exc:
        raise FilingFetchError(f"company-wiki {action} failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip()[-2000:] or "no stderr"
        raise FilingFetchError(
            f"company-wiki {action} exited {completed.returncode}: {detail}",
            code=_classify_wiki_error(completed.stderr.strip()),
            stage=action,
            attempts=1,
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise FilingFetchError(f"company-wiki {action} stdout is not JSON") from exc
    if not isinstance(payload, dict):
        raise FilingFetchError(f"company-wiki {action} response must be an object")
    return payload


def _classify_wiki_error(stderr_text: str) -> str:
    """Map a company-wiki structured stderr payload to a filing error code.

    ZR-205: consume the canonical ZR-204 error-taxonomy codes emitted by the
    wiki CLI (``catalog_locked`` / ``catalog_busy`` / ``db_timeout`` /
    ``worker_paused`` / ``fatal``) directly; keep N-1 fallbacks for the
    legacy class-name emission shape (``CatalogOperationLockedError``,
    ``RuntimeError`` + paused text).  Unknown / malformed payloads fail
    closed to ``fatal`` (never retryable).
    """
    try:
        structured = json.loads(stderr_text)
    except json.JSONDecodeError:
        return "fatal"
    if not isinstance(structured, dict):
        return "fatal"
    error_type = structured.get("error_type")
    if error_type in _CATALOG_RETRY_CODES:
        return error_type
    if error_type == "worker_paused":
        return "worker_paused"
    if error_type == "fatal":
        return "fatal"
    # N-1 legacy emission: exception class names from before the taxonomy.
    if error_type == "CatalogOperationLockedError":
        return "catalog_locked"
    if error_type == "RuntimeError" and "paused" in str(structured.get("error", "")):
        return "worker_paused"
    return "fatal"


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
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FilingFetchError(
                f"overall deadline exceeded before {action}",
                code="upstream_error",
                stage=action,
                attempts=attempt - 1,
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
            jittered = backoff * (1.0 + random.uniform(-CATALOG_LOCKED_BACKOFF_JITTER, CATALOG_LOCKED_BACKOFF_JITTER))
            wait = min(jittered, remaining)
            if wait <= 0:
                raise FilingFetchError(
                    f"overall deadline exceeded retrying {action}: {exc}",
                    code="upstream_error",
                    stage=action,
                    attempts=attempt,
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
        raise FilingFetchError(
            "resolved company identity is missing", code="identity_error"
        )
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
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
        ):
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
        raise FilingFetchError(
            "company identity market is unsupported", code="identity_error"
        )
    return dict(resolved)


# ---------------------------------------------------------------------------
# Worker pause-around orchestration
#
# The company-wiki background worker holds the global catalog `operation.lock`
# while running long batches (e.g. backfill_text_fingerprints over 20k+
# documents), which blocks every `ensure --allow-download`. The scope below
# pauses the worker before the download (releasing the lock; `operation.lock`
# is auto-reclaimed once the holder pid is dead) and resumes it afterwards so
# its pending batch continues. Only the worker running and enabled is paused;
# a user-initiated pause is never resumed.
# ---------------------------------------------------------------------------

_PAUSE_REFCOUNT_NAME = "filing_fetch_pause.refcount"
_PAUSE_OWNER_NAME = "filing_fetch_pause.owner"
_WORKER_STATUS_TIMEOUT = 60.0


def _catalog_dir(root: Path) -> Path:
    return root / ".source_catalog"


def _pid_is_alive(pid: int) -> bool:
    """Best-effort pid liveness; unknown states count as alive (conservative)."""
    if os.name == "nt":
        try:
            probe = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return True
        return f"{pid}" in (probe.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _read_pause_entries(root: Path) -> list[dict[str, Any]]:
    path = _catalog_dir(root) / _PAUSE_REFCOUNT_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [e for e in payload if isinstance(e, dict) and isinstance(e.get("pid"), int)]


def _write_pause_entries(root: Path, entries: list[dict[str, Any]]) -> None:
    path = _catalog_dir(root) / _PAUSE_REFCOUNT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _prune_pause_entries(root: Path) -> list[dict[str, Any]]:
    return [e for e in _read_pause_entries(root) if _pid_is_alive(e["pid"])]


class PausedWorkerScope:
    """Context manager pausing the worker around one catalog download.

    - Worker not running or not enabled -> no-op.
    - Worker already paused by an earlier filing-fetch (owner marker present)
      -> join the refcount so the last participant resumes it.
    - Worker already paused by the user (no owner marker) -> respect it: run
      the download (the paused guard is bypassed via the explicit opt-in flag)
      but never resume it.
    - Otherwise (running + enabled) -> the first participant pauses the worker,
      the last participant resumes it. A crash is self-healing via dead-pid
      pruning of the refcount.
    """

    def __init__(
        self,
        *,
        root: Path,
        command_prefix: list[str],
        enabled: bool,
        graceful_timeout_seconds: float,
        resume_wait_seconds: float,
        deadline: float,
        stats: dict[str, int] | None = None,
    ) -> None:
        self.root = root
        self.command_prefix = command_prefix
        self.enabled = enabled
        self.graceful = graceful_timeout_seconds
        self.resume_wait = resume_wait_seconds
        self.deadline = deadline
        self.action = "none"
        self._first = False
        self.stats = stats

    def _run(self, subcommand: str, *args: str, timeout: float) -> dict[str, Any]:
        return _run_company_wiki_json(
            command=[*self.command_prefix, subcommand, *args],
            root=self.root,
            timeout_seconds=timeout,
            action=subcommand,
            stats=self.stats,
        )

    def _remaining(self) -> float:
        return max(
            10.0,
            min(self.deadline - time.monotonic(), _WORKER_STATUS_TIMEOUT),
        )

    def __enter__(self) -> "PausedWorkerScope":
        if not self.enabled:
            self.action = "disabled"
            return self
        try:
            status = self._run("worker-status", timeout=self._remaining())
        except FilingFetchError as exc:
            print(
                f"[filing-fetch] worker-status failed; proceeding without pause: {exc}",
                file=sys.stderr,
            )
            self.action = "no_status"
            return self
        if status.get("runtime_state") != "running":
            self.action = "worker_stopped"
            return self
        if status.get("desired_state") == "paused":
            if (_catalog_dir(self.root) / _PAUSE_OWNER_NAME).is_file():
                self.action = "joined"
                self._register(joined=True)
            else:
                self.action = "respect_paused"
            return self
        self._first = self._register(joined=False)
        if self._first:
            try:
                self._run(
                    "worker-pause",
                    "--graceful-timeout-seconds",
                    str(self.graceful),
                    timeout=self._remaining(),
                )
            except FilingFetchError as exc:
                self.action = "pause_failed"
                self._unregister()
                try:
                    self._run(
                        "worker-resume",
                        "--wait-seconds",
                        str(self.resume_wait),
                        timeout=self._remaining(),
                    )
                except FilingFetchError:
                    pass  # best-effort cleanup; original error below
                raise FilingFetchError(
                    f"worker-pause failed: {exc}", code="worker_pause_failed"
                ) from exc
        self.action = "paused_by_us"
        return self

    def _register(self, *, joined: bool) -> bool:
        entries = _prune_pause_entries(self.root)
        first = not entries
        entries.append({"pid": os.getpid(), "joined": joined})
        _write_pause_entries(self.root, entries)
        if first:
            try:
                (_catalog_dir(self.root) / _PAUSE_OWNER_NAME).write_text(
                    "filing-fetch", encoding="utf-8"
                )
            except OSError:
                pass
        return first

    def _unregister(self) -> bool:
        entries = _prune_pause_entries(self.root)
        entries = [e for e in entries if e.get("pid") != os.getpid()]
        if not entries:
            try:
                (_catalog_dir(self.root) / _PAUSE_REFCOUNT_NAME).unlink(missing_ok=True)
                (_catalog_dir(self.root) / _PAUSE_OWNER_NAME).unlink(missing_ok=True)
            except OSError:
                pass
        else:
            _write_pause_entries(self.root, entries)
        return not entries

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self.action not in {"paused_by_us", "joined"}:
            return
        if not self._unregister():
            return  # other participants still active; keep the worker paused
        try:
            self._run(
                "worker-resume",
                "--wait-seconds",
                str(self.resume_wait),
                timeout=self._remaining(),
            )
        except FilingFetchError as exc:
            print(
                f"[filing-fetch] warning: worker-resume failed; the worker may be "
                f"paused - resume it manually with: python -m "
                f"company_wiki.source_catalog.cli worker-resume ({exc})",
                file=sys.stderr,
            )


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
    events = (handle.get("resolution_envelope") or {}).get("download_events")
    if isinstance(events, int):
        stats["downloads"] = events


def resolve_filing(
    *,
    request: dict[str, Any],
    company_wiki_root: Path | None = None,
    config_path: Path | None = None,
    allow_download: bool = False,
    timeout_seconds: float = 900.0,
    pause_worker: bool = True,
    worker_graceful_timeout_seconds: float = 5.0,
    worker_resume_wait_seconds: float = 5.0,
    stats: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Identify an optional company query, then resolve or explicitly ensure a filing.

    The default path calls the read-only ``resolve`` command and reuses an
    existing company-wiki filing. ``allow_download=True`` calls
    ``ensure --allow-download``; company-wiki then routes the download by market
    (CN -> StockInfo, HK/US -> dayu) and writes any new bytes into
    ``companies/{entity}/raw/{kind}/``. A ``company_query`` is resolved to one
    verified active security before either source command is constructed.

    ``stats`` (optional, mutated in place): ZR-205 reconciliation counters.
    ``stats["calls"]`` counts every company-wiki subprocess invocation
    (including retries and worker pause/resume orchestration);
    ``stats["downloads"]`` is the download event count from the final
    resolution envelope (0 unless a download actually committed).  Final
    success and failure both preserve these counts in the response envelope
    (READ-09/READ-10).
    """
    stats = _normalize_stats(stats)

    if company_wiki_root is not None and config_path is not None:
        raise ValueError("company_wiki_root cannot be combined with config_path")
    if not isinstance(request, dict):
        raise TypeError("request must be a dict")
    if not isinstance(allow_download, bool):
        raise TypeError("allow_download must be boolean")
    if timeout_seconds <= 0 or not math.isfinite(timeout_seconds):
        raise ValueError("timeout_seconds must be positive and finite")
    validate_request(request)
    deadline = time.monotonic() + timeout_seconds
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
        if key not in {"company_query", "exchange"}
    }
    normalized_request.update(
        {
            "entity": company_identity["canonical_name"],
            "market": company_identity["market"],
            "security_id": company_identity["security_id"],
        }
    )
    # FC-802: latest_as_of always consults the provider through the ensure
    # path — the metadata-only gap plan comes back even without download.
    mode = str(request.get("mode") or "").strip().lower()
    is_latest = mode == "latest_as_of"
    action = "ensure" if (allow_download or is_latest) else "resolve"
    command = [
        *command_prefix,
        action,
        *_command_arguments(normalized_request),
    ]
    if allow_download:
        if not normalized_request.get("market") or not normalized_request.get(
            "security_id"
        ):
            raise FilingFetchError(
                "explicit download requires market and security_id"
            )
        command.extend(
            (
                "--allow-download",
                "--acquisition-config",
                str(root / "config" / "source_acquisition.yaml"),
            )
        )
        if pause_worker:
            # Explicit opt-in bypass of the company-wiki paused-guard: we
            # deliberately pause the worker around this download, so the guard
            # must not refuse us. Without pause_worker the legacy guard applies.
            command.append("--allow-acquisition-while-paused")
        scope = PausedWorkerScope(
            root=root,
            command_prefix=command_prefix,
            enabled=pause_worker,
            graceful_timeout_seconds=worker_graceful_timeout_seconds,
            resume_wait_seconds=worker_resume_wait_seconds,
            deadline=deadline,
            stats=stats,
        )
        with scope:
            payload = _run_company_wiki_json_retry(
                command=command,
                root=root,
                action=action,
                deadline=deadline,
                stats=stats,
            )
    else:
        payload = _run_company_wiki_json_retry(
            command=command,
            root=root,
            action=action,
            deadline=deadline,
            stats=stats,
        )
    if action == "ensure":
        # FC-802: the ensure payload carries the top-level status; GAP is a
        # STRUCTURED result (metadata-only plan), never a not_found error.
        if payload.get("status") == "gap":
            gap_plan = (payload.get("acquisition") or {}).get("gap_plan")
            authorization = request.get("authorization")
            # FC-803: the close-gap transaction only runs when the plan is
            # ACTIONABLE (missing items).  An empty plan stays a structured
            # gap so the caller sees the details — reuse handles
            # (LT-01), provider_unavailable retryability (LT-05), future
            # exclusions (LT-07) — never a silently downgraded handle.
            has_missing = bool(gap_plan and gap_plan.get("missing"))
            if allow_download and authorization is not None and has_missing:
                # has_missing implies a dict payload (the .get above would
                # have failed otherwise); narrow for mypy (FC-1204 F1 fix).
                assert isinstance(gap_plan, dict)
                return _close_gap_and_return_handle(
                    payload=payload,
                    gap_plan=gap_plan,
                    authorization=authorization,
                    company_identity=company_identity,
                    command_prefix=command_prefix,
                    normalized_request=normalized_request,
                    root=root,
                    request=request,
                    deadline=deadline,
                    pause_worker=pause_worker,
                    worker_graceful_timeout_seconds=worker_graceful_timeout_seconds,
                    worker_resume_wait_seconds=worker_resume_wait_seconds,
                    stats=stats,
                )
            return {
                "status": "gap",
                "gap_plan": gap_plan,
                "resolution": payload.get("resolution"),
            }
        resolution = payload.get("resolution")
    else:
        resolution = payload
    if not isinstance(resolution, dict):
        raise FilingFetchError(
            "company-wiki resolution is missing", code="upstream_error"
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
        )
    if resolution.get("status") not in {"reused_exact", "reused_equivalent"}:
        raise FilingFetchError(
            f"source is not reusable: {resolution.get('status')} / {resolution.get('reason')}",
            code="not_found",
            debug_trace=resolution.get("debug_trace"),
            resolution_trace=_resolution_trace(resolution),
        )
    handle = _handle_from_resolution(resolution, request, root)
    handle["company_identity"] = company_identity
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
) -> dict:
    """Build + deep-validate the handle from a reused resolution.

    Shared by the reuse path and the FC-802 close-gap path so the handle
    contract (exactly-one match, capture provenance, policy containment,
    FC-704 envelope forwarding) stays single-sourced.
    """
    matches = resolution.get("matches")
    if not isinstance(matches, list) or len(matches) != 1 or not isinstance(matches[0], dict):
        raise FilingFetchError(
            "company-wiki did not return exactly one source handle",
            code="upstream_error",
            resolution_trace=_resolution_trace(resolution),
        )
    handle = dict(matches[0])
    if handle.get("capture_ready") is not True:
        raise FilingFetchError(
            "source lacks capture provenance: "
            + ", ".join(str(item) for item in handle.get("missing_capture_fields", [])),
            code="not_found",
            resolution_trace=_resolution_trace(resolution),
        )
    handle["request_id"] = resolution.get("request_id")
    # FC-501: no independent root allowlist.  Handle containment is
    # validated against the company-wiki RootPolicySnapshot (wired when the
    # upstream returns it; until then the legacy <wiki_root>/companies
    # default applies).  Direct company_wiki_root callers (tests) keep the
    # legacy default.
    # ZR-307: validate handle and resolution envelope; any failure carries
    # the upstream resolution trace so the error envelope never swallows
    # the exact-reuse / download=0 evidence.
    try:
        validate_handle(handle, request, root)
        # FC-704: deep-validate and forward the resolution envelope verbatim —
        # the journal-reconciled outcome + download event evidence the revenue
        # receipt derives from.  N/N-1: an old company-wiki without an envelope
        # resolves normally; the handle simply carries no envelope (revenue then
        # fails closed instead of fabricating evidence).
        if envelope is None:
            envelope = resolution.get("resolution_envelope")
        if envelope is not None:
            # FC-903: validate + normalize (an N-1 company-wiki envelope gains
            # the explicit honest bundle_status='unavailable') and forward the
            # result — never a faked empty-green.
            envelope = validate_resolution_envelope(envelope)
            handle["resolution_envelope"] = dict(envelope)
    except FilingFetchError as exc:
        exc.resolution_trace = _resolution_trace(resolution)
        raise
    return handle


def _close_gap_and_return_handle(
    *,
    payload: dict,
    gap_plan: dict,
    authorization: dict,
    company_identity: dict,
    command_prefix: list[str],
    normalized_request: dict,
    root: Path,
    request: dict,
    deadline: float,
    pause_worker: bool,
    worker_graceful_timeout_seconds: float,
    worker_resume_wait_seconds: float,
    stats: dict[str, int] | None = None,
) -> dict:
    """FC-802: execute the authorized close-gap transaction and return the
    final handle.  filing-fetch stays thin: the binding is assembled from
    evidence company-wiki already provided (plan hash, envelope policy
    hash) plus the caller's authorization — no provider/root/identity
    rules are re-derived here."""
    resolution = payload.get("resolution") or {}
    envelope = resolution.get("resolution_envelope") or {}
    binding = {
        "request_id": (gap_plan or {}).get("request_id"),
        "gap_plan_hash": (gap_plan or {}).get("gap_hash"),
        "policy_hash": envelope.get("policy_hash"),
        "provider": authorization["provider"],
        "allowed_accessions": authorization["allowed_accessions"],
        "max_items": authorization["max_items"],
        "max_bytes": authorization["max_bytes"],
        "expires_at": authorization["expires_at"],
    }
    import tempfile

    binding_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8")
    try:
        json.dump(binding, binding_file, ensure_ascii=False)
        binding_file.close()
        command = [
            *command_prefix,
            "close-gap",
            "--binding-file",
            str(binding_file.name),
            *_command_arguments(normalized_request),
            "--acquisition-config",
            str(root / "config" / "source_acquisition.yaml"),
        ]
        if pause_worker:
            command.append("--allow-acquisition-while-paused")
        scope = PausedWorkerScope(
            root=root,
            command_prefix=command_prefix,
            enabled=pause_worker,
            graceful_timeout_seconds=worker_graceful_timeout_seconds,
            resume_wait_seconds=worker_resume_wait_seconds,
            deadline=deadline,
            stats=stats,
        )
        with scope:
            closed = _run_company_wiki_json_retry(
                command=command,
                root=root,
                action="close-gap",
                deadline=deadline,
                stats=stats,
            )
    finally:
        Path(binding_file.name).unlink(missing_ok=True)
    if closed.get("status") != "completed":
        raise FilingFetchError(
            f"close-gap did not complete: {closed.get('status')} / "
            f"{closed.get('reason')}",
            code="gap_not_closed",
        )
    closed_resolution = closed.get("resolution")
    if not isinstance(closed_resolution, dict):
        raise FilingFetchError(
            "close-gap resolution is missing", code="upstream_error")
    handle = _handle_from_resolution(
        closed_resolution, request, root, envelope=closed.get("envelope"))
    handle["company_identity"] = company_identity
    _record_download_events(stats, handle)
    return handle


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
    parser.add_argument("--config", type=Path, default=None, help="path to company_wiki.json config")
    parser.add_argument("--request-file", type=Path, default=None, help="read JSON request from file instead of stdin")
    parser.add_argument("--timeout-seconds", type=float, default=900.0, help="overall deadline for the entire request (default: 900)")
    parser.add_argument(
        "--no-pause-worker",
        action="store_true",
        help=(
            "do not pause the company-wiki background worker around downloads; "
            "legacy behavior (the worker's catalog lock can block downloads for "
            "minutes)"
        ),
    )
    parser.add_argument(
        "--worker-graceful-timeout-seconds",
        type=float,
        default=5.0,
        help="graceful stop window for worker-pause before it force-kills (default: 5)",
    )
    parser.add_argument(
        "--worker-resume-wait-seconds",
        type=float,
        default=5.0,
        help="seconds to wait for the worker to come back after worker-resume (default: 5)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="include the per-candidate exclusion trace in the error response",
    )
    args = parser.parse_args(argv)

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
            raise FilingFetchError(
                f"invalid request: {exc}", code="request_error"
            ) from exc
        if not isinstance(request, dict):
            raise FilingFetchError(
                "request must be a JSON object", code="request_error"
            )
        stats = {"calls": 0, "downloads": 0}
        handle = resolve_filing(
            request=request,
            config_path=args.config,
            allow_download=args.allow_download,
            timeout_seconds=args.timeout_seconds,
            pause_worker=not args.no_pause_worker,
            worker_graceful_timeout_seconds=args.worker_graceful_timeout_seconds,
            worker_resume_wait_seconds=args.worker_resume_wait_seconds,
            stats=stats,
        )
        if isinstance(handle, dict) and handle.get("status") == "gap":
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
        if "stats" in locals():
            error_response["calls"] = stats["calls"]
            error_response["downloads"] = stats["downloads"]
        json.dump(error_response, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 2
    except Exception as exc:
        json.dump({"schema_version": FILING_RESPONSE_SCHEMA_VERSION, "status": "fatal", "error": str(exc), "error_code": "fatal", "retryable": False}, sys.stdout, ensure_ascii=False, indent=2)
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
