"""Public roster, acquisition and reading ports used by one scheduled tick."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import http.client
import json
import math
from pathlib import Path
import sys
import time
from urllib.parse import urlencode, urlsplit

from ff_company_wiki_connection import command_for, connection_cwd, connection_environment
from ff_configuration import expand_config_path, load_connection_root, read_json_object
from ff_job_contracts import FF_JOB_SCHEMA_VERSION, allowed_actions_for, validate_submit_body
from ff_job_runner import act, run_job
from ff_job_store import JobStore
from ff_process_transport import MAX_JSON_OUTPUT_BYTES, TransportError, run_bounded_json
from filing_contracts import FilingFetchError, validate_acquisition_limits


class OwnerUnavailable(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class IdentityDeployment:
    root: Path
    workspace: Path
    python: str


@dataclass(frozen=True)
class Deployment:
    universe_origin: str | None = None
    pinned_rosters: Path | None = None
    identity: IdentityDeployment | None = None
    tick_seconds: float = 240
    metadata_pages: int = 64
    acquisitions: int = 8
    reading_documents: int = 6
    lookback_days: int = 30
    overlap_days: int = 7
    discovery: dict = field(default_factory=lambda: {
        "max_bytes": 8 * 1024 * 1024, "timeout_seconds": 45, "max_cost_usd": "0.00",
        "max_requests": 6,
    })
    acquisition: dict = field(default_factory=lambda: {
        "max_bytes": 64 * 1024 * 1024, "timeout_seconds": 120, "max_cost_usd": "0.00",
    })
    reading: dict = field(default_factory=lambda: {"timeout_seconds": 120})

    def status_limits(self) -> dict:
        return {
            "tick_seconds": self.tick_seconds, "metadata_pages": self.metadata_pages,
            "acquisitions": self.acquisitions, "reading_documents": self.reading_documents,
            "discovery": self.discovery, "acquisition": self.acquisition, "reading": self.reading,
        }


def _positive(value: object, name: str, *, integer: bool = True):
    ok_type = type(value) is int or (not integer and type(value) is float and math.isfinite(value))
    if not ok_type or value <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return value


def _limits(value: object, defaults: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("schedule limits must be an object")
    result = {**defaults, **value}
    _positive(result["timeout_seconds"], "timeout_seconds", integer=False)
    if "max_requests" in result:
        _positive(result["max_requests"], "max_requests")
    if "max_sources" in result:
        _positive(result["max_sources"], "max_sources")
    if "max_cost_usd" in defaults:
        native = {field: result[field] for field in ("max_bytes", "timeout_seconds", "max_cost_usd")}
        try:
            validate_acquisition_limits("fetch_if_missing", native, request_diagnostics=False)
        except FilingFetchError as exc:
            raise ValueError("invalid configured source limits") from exc
        if "max_requests" not in defaults:
            return native
    return result


def _local_origin(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("universe_origin must be a loopback origin")
    parts = urlsplit(value)
    if (parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "::1", "localhost")
            or parts.username or parts.password or parts.path not in ("", "/")
            or parts.query or parts.fragment or parts.port is None):
        raise ValueError("universe_origin must be a loopback HTTP origin with a port")
    return value.rstrip("/")


def load_deployment(path: Path) -> Deployment:
    try:
        config = read_json_object(path, label="scheduled refresh deployment")
    except FilingFetchError as exc:
        raise ValueError("scheduled refresh deployment is unreadable") from exc
    if config.get("schema_version") != "ff-scheduled-refresh-deployment/1":
        raise ValueError("unsupported scheduled refresh deployment")
    base = Deployment()
    limits = config.get("limits", {})
    if not isinstance(limits, dict):
        raise ValueError("schedule deployment limits must be an object")
    def location(value, label):
        try:
            return expand_config_path(value, field=label, skill_root=Path(__file__).resolve().parents[1],
                                      config_path=path)
        except FilingFetchError as exc:
            raise ValueError(f"invalid schedule location: {label}") from exc

    roster_path = location(config["pinned_rosters"], "pinned rosters") if "pinned_rosters" in config else None
    identity = None
    if "stockwiki_identity" in config:
        registered = config["stockwiki_identity"]
        if not isinstance(registered, dict) or not {"root", "workspace"} <= set(registered):
            raise ValueError("stockwiki_identity needs a code root and owner workspace")
        identity = IdentityDeployment(
            root=location(registered["root"], "StockWiki root"),
            workspace=location(registered["workspace"], "StockWiki workspace"),
            python=str(location(registered["python"], "StockWiki interpreter"))
            if "python" in registered else sys.executable,
        )
    return Deployment(
        universe_origin=_local_origin(config["universe_origin"]) if "universe_origin" in config else None,
        pinned_rosters=roster_path,
        identity=identity,
        tick_seconds=_positive(limits.get("tick_seconds", base.tick_seconds),
                               "tick_seconds", integer=False),
        metadata_pages=_positive(limits.get("metadata_pages", base.metadata_pages), "metadata_pages"),
        acquisitions=_positive(limits.get("acquisitions", base.acquisitions), "acquisitions"),
        reading_documents=_positive(limits.get("reading_documents", base.reading_documents),
                                    "reading_documents"),
        lookback_days=_positive(config.get("lookback_days", base.lookback_days), "lookback_days"),
        overlap_days=_positive(config.get("overlap_days", base.overlap_days), "overlap_days"),
        discovery=_limits(limits.get("discovery", {}), base.discovery),
        acquisition=_limits(limits.get("acquisition", {}), base.acquisition),
        reading=_limits(limits.get("reading", {}), base.reading),
    )


def stable_key(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
    ).hexdigest()


def _safe_reason(value: object, default: str) -> str:
    if isinstance(value, str) and value and all(char.isascii() and (char.isalnum() or char in "_-.") for char in value):
        return value
    return default


def _read_loopback(origin: str, path: str, query: dict, timeout: float) -> dict:
    parts = urlsplit(origin)
    host = parts.hostname
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise OwnerUnavailable("roster_origin_invalid")
    deadline = time.monotonic() + timeout
    connection = http.client.HTTPConnection(host, parts.port, timeout=timeout)
    try:
        connection.request("GET", f"{path}?{urlencode(query)}", headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise OwnerUnavailable("roster_unavailable")
        chunks = bytearray()
        while len(chunks) <= MAX_JSON_OUTPUT_BYTES:
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise OwnerUnavailable("roster_timeout")
            if connection.sock is not None:
                connection.sock.settimeout(seconds)
            data = response.read1(min(65536, MAX_JSON_OUTPUT_BYTES + 1 - len(chunks)))
            if not data:
                result = json.loads(chunks)
                if isinstance(result, dict) and result.get("ok") is True and isinstance(result.get("data"), dict):
                    return result["data"]
                break
            chunks.extend(data)
    except (OSError, UnicodeError, ValueError, http.client.HTTPException) as exc:
        raise OwnerUnavailable("roster_unavailable") from exc
    finally:
        connection.close()
    raise OwnerUnavailable("roster_response_unavailable")


def _listing(entity_id: str, row: dict) -> dict | None:
    market, listing_id, ticker = (row.get(name) for name in ("market", "listing_id", "ticker"))
    exchange = row.get("exchange_raw") or row.get("exchange") or row.get("exchange_mic")
    issuer_link_id = row.get("issuer_link_id")
    if (row.get("entity_id", entity_id) != entity_id or market not in ("CN", "HK", "US")
            or any(not isinstance(value, str) or not value.strip() for value in (listing_id, ticker))):
        return None
    scope = {"entity_id": entity_id, "listing_id": listing_id, "market": market, "ticker": ticker}
    for name, value in (("exchange", exchange), ("issuer_link_id", issuer_link_id)):
        if isinstance(value, str) and value.strip():
            scope[name] = value
    return scope


class OwnerPorts:
    def __init__(self, config_path: Path, jobs_dir: Path, deployment: Deployment) -> None:
        self.config_path = config_path
        self._jobs_dir = jobs_dir
        self.deployment = deployment
        self._universe: tuple[str, dict] | None = None

    def roster(self, scope: dict, cursor: str | None, snapshot: str | None, *, timeout: float) -> dict:
        if scope["mode"] == "pinned":
            return self._pinned_roster(scope["roster_ref"])
        origin = self.deployment.universe_origin
        if origin is None:
            raise OwnerUnavailable("roster_origin_not_configured")
        universe_id = scope["universe_id"]
        until = time.monotonic() + timeout
        if cursor is None or self._universe is None or self._universe[0] != universe_id:
            self._universe = (universe_id, _read_loopback(
                origin, "/api/product/universe", {"universe_id": universe_id}, timeout,
            ))
        native = self._universe[1]
        universe, members = native.get("universe"), native.get("members")
        if (not isinstance(universe, dict) or universe.get("universe_id") != universe_id
                or not isinstance(members, list) or native.get("member_count") != len(members)):
            raise OwnerUnavailable("roster_scope_unverified")
        active = [member for member in members
                  if isinstance(member, dict) and member.get("membership_status") == "active"]
        if any(not isinstance(member.get("entity_id"), str) for member in active):
            raise OwnerUnavailable("roster_scope_unverified")
        active.sort(key=lambda member: member["entity_id"])
        revision = stable_key({"universe": universe_id, "members": active})
        if snapshot is not None and revision != snapshot:
            raise OwnerUnavailable("roster_snapshot_changed")
        start = int(cursor) if cursor is not None else 0
        subset = active[start:start + 20]
        items = []
        reasons = []
        for member in subset:
            remaining = until - time.monotonic()
            if remaining <= 0:
                raise OwnerUnavailable("roster_timeout")
            entity_id = member["entity_id"]
            try:
                listing = self._resolve_listing(origin, entity_id, member.get("listing_id"), remaining)
            except OwnerUnavailable as exc:
                if exc.reason not in reasons:
                    reasons.append(exc.reason)
            else:
                items.append(listing)
        next_cursor = str(start + len(subset)) if start + len(subset) < len(active) else None
        return {"snapshot_id": revision, "items": items, "next_cursor": next_cursor, "reason_codes": reasons}

    def _resolve_listing(self, origin: str, entity_id: str, listing_id: str | None, timeout: float) -> dict:
        deployment = self.deployment.identity
        if deployment is None:
            data = _read_loopback(origin, "/api/product/entity", {"id": entity_id}, timeout)
        else:
            command = [deployment.python, "-B", str(deployment.root / "dashboard_identity_bridge_cli.py"),
                       "resolve", "--entity-id", entity_id, "--root", str(deployment.workspace)]
            if listing_id is not None:
                command.extend(("--listing-id", listing_id))
            try:
                stdout, _, _ = run_bounded_json(command, timeout_seconds=timeout, cwd=str(deployment.root))
                data = json.loads(stdout)
            except (OSError, TransportError, ValueError, UnicodeError) as exc:
                raise OwnerUnavailable("roster_identity_unavailable") from exc
            if (not isinstance(data, dict) or data.get("authority") != "stockwiki"
                    or data.get("resolution_status") != "resolved"):
                raise OwnerUnavailable("roster_listing_required")
        entity = data.get("entity")
        if not isinstance(entity, dict) or entity.get("entity_id") != entity_id:
            raise OwnerUnavailable("roster_identity_unavailable")
        selected_id = listing_id or entity.get("selected_listing_id")
        rows = data.get("listings") or entity.get("listings")
        if not isinstance(rows, list):
            raise OwnerUnavailable("roster_listing_required")
        verified = [_listing(entity_id, row) for row in rows
                    if isinstance(row, dict) and row.get("listing_status") == "active"]
        matching = [row for row in verified if row is not None
                    and (selected_id is None or row["listing_id"] == selected_id)]
        if len(matching) != 1:
            raise OwnerUnavailable("roster_listing_required")
        return matching[0]

    def _pinned_roster(self, reference: str) -> dict:
        path = self.deployment.pinned_rosters
        if path is None:
            raise OwnerUnavailable("pinned_rosters_not_configured")
        try:
            payload = read_json_object(path, label="pinned schedule rosters")
        except FilingFetchError as exc:
            raise OwnerUnavailable("pinned_rosters_unavailable") from exc
        records = payload.get("rosters")
        row = records.get(reference) if isinstance(records, dict) else None
        if not isinstance(row, dict) or not isinstance(row.get("snapshot_id"), str):
            raise OwnerUnavailable("pinned_roster_not_found")
        rows = row.get("items")
        if not isinstance(rows, list):
            raise OwnerUnavailable("roster_scope_unverified")
        members = [_listing(item.get("entity_id"), item) if isinstance(item, dict) and
                   isinstance(item.get("entity_id"), str) else None for item in rows]
        if any(item is None for item in members):
            raise OwnerUnavailable("roster_scope_unverified")
        return {"snapshot_id": row["snapshot_id"], "items": members, "next_cursor": None, "reason_codes": []}

    def _cwp(self, operation: str, schema: str, request: dict, timeout: float) -> dict:
        try:
            endpoint = load_connection_root(self.config_path, skill_root=Path(__file__).resolve().parents[1])
            stdout, stderr, code = run_bounded_json(
                command_for(endpoint, operation), timeout_seconds=timeout, cwd=str(connection_cwd(endpoint)),
                input_bytes=json.dumps(request, ensure_ascii=False).encode("utf-8"),
                env=connection_environment(endpoint), allow_nonzero_exit=True,
            )
            result = json.loads(stdout if code == 0 or stdout.strip() else stderr)
        except (TransportError, FilingFetchError, OSError, UnicodeError, ValueError) as exc:
            raise OwnerUnavailable(f"{operation}_unavailable") from exc
        if not isinstance(result, dict):
            raise OwnerUnavailable(f"{operation}_incompatible")
        if code != 0:
            error = result.get("error")
            reason = error.get("code") if isinstance(error, dict) else error
            raise OwnerUnavailable(_safe_reason(reason, f"{operation}_unavailable"))
        if result.get("schema_version") != schema:
            raise OwnerUnavailable(f"{operation}_incompatible")
        return result

    def discover(self, request: dict, *, timeout: float) -> dict:
        result = self._cwp("incremental_discover", "cwp-incremental-discovery/1",
                           request, timeout)
        if result.get("request_id") != request["request_id"]:
            raise OwnerUnavailable("discovery_request_mismatch")
        scope = result.get("scope")
        identity = scope.get("identity", scope) if isinstance(scope, dict) else None
        if (not isinstance(identity, dict) or any(
            identity.get(field) != request["identity"][field] for field in ("entity_id", "listing_id")
        ) or scope.get("source_market") != request["source_market"]):
            raise OwnerUnavailable("discovery_scope_mismatch")
        if not isinstance(result.get("candidates"), list) or result.get("coverage") not in (
            "complete", "partial", "unavailable",
        ):
            raise OwnerUnavailable("incremental_discover_incompatible")
        return result

    def backlog(self, request: dict, *, timeout: float) -> dict:
        result = self._cwp("incremental_backlog", "cwp-incremental-backlog/1", request, timeout)
        cursor = result.get("next_cursor")
        if not isinstance(result.get("sources"), list) or (cursor is not None and not isinstance(cursor, str)):
            raise OwnerUnavailable("incremental_backlog_incompatible")
        return result

    def read(self, request: dict, *, timeout: float) -> dict:
        result = self._cwp("incremental_read", "cwp-incremental-read/1", request, timeout)
        return self._bound_read(result, request["run_id"])

    def read_status(self, run_id: str, *, timeout: float) -> dict:
        result = self._cwp("incremental_read_status", "cwp-incremental-read/1", {
            "schema_version": "cwp-incremental-read-status-request/1", "run_id": run_id,
        }, timeout)
        return self._bound_read(result, run_id)

    @staticmethod
    def _bound_read(result: dict, run_id: str) -> dict:
        if result.get("run_id") != run_id or not isinstance(result.get("items"), list):
            raise OwnerUnavailable("reading_run_mismatch")
        return result

    def acquire(self, key: str, kind: str, request: dict, *, timeout: float, run_id: str) -> dict:
        jobs = JobStore(self._jobs_dir)
        try:
            job = jobs.find_submission(key)
            if job is None:
                body = validate_submit_body({
                    "schema_version": FF_JOB_SCHEMA_VERSION, "command_id": run_id,
                    "kind": kind, "idempotency_key": key, "request": request,
                })
                job, _ = jobs.create_job(body, command_id=run_id)
            job_id = job["owner_job_id"]
            job, _ = jobs.load_checked(job_id, fix=True)
            executed_now = False
            retry_key = f"{run_id}-retry-{job_id}"
            if job["status"] == "failed" and "retry" in allowed_actions_for(job):
                job, _ = act(jobs, job_id, action="retry", idempotency_key=retry_key)
            if job["status"] == "queued":
                job, executed_now = run_job(jobs, job_id, config_path=self.config_path, timeout_seconds=timeout)
            elif "reconcile" in allowed_actions_for(job):
                job, _ = act(
                    jobs, job_id, action="reconcile", idempotency_key=f"sr-reconcile-{job_id}",
                    config_path=self.config_path, timeout_seconds=timeout,
                )
            attributed = executed_now or job["command_id"] == run_id or any(
                event["action"] == "retry" and event["idempotency_key"] == retry_key
                for event in job.get("actions", [])
            )
            return {**job, "reused_job": not attributed,
                    "safe_retry": job["status"] == "failed" and "retry" in allowed_actions_for(job)}
        except FilingFetchError as exc:
            raise OwnerUnavailable(_safe_reason(exc.code, "acquisition_unavailable")) from exc
