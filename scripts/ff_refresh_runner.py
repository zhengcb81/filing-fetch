"""One resumable scheduled refresh. Only the owner ports perform side effects."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import time
from typing import Any, Protocol

from ff_job_feedback import publish_refresh_observation
from ff_refresh_owners import Deployment, OwnerUnavailable, stable_key
from ff_refresh_policy import due_slot, slot_consumed, utc_text, work_scope
from ff_refresh_store import RefreshStore
from ff_source_ref import validate_source_ref
from filing_contracts import FilingFetchError


class Ports(Protocol):
    def roster(self, scope: dict, cursor: str | None, snapshot: str | None, *, timeout: float) -> dict: ...
    def discover(self, request: dict, *, timeout: float) -> dict: ...
    def backlog(self, request: dict, *, timeout: float) -> dict: ...
    def acquire(self, key: str, kind: str, request: dict, *, timeout: float, run_id: str) -> dict: ...
    def read(self, request: dict, *, timeout: float) -> dict: ...
    def read_status(self, run_id: str, *, timeout: float) -> dict: ...


class _AdmissionStopped(Exception):
    pass


def _reference(value: Any) -> dict | None:
    if value is None:
        return None
    try:
        return validate_source_ref(value)
    except FilingFetchError:
        return None


def _reference_key(ref: dict) -> str:
    return stable_key([ref[name] for name in ("document_id", "source_id", "content_sha256")])


def _member_scope(identity: dict) -> tuple[str, str]:
    return identity["entity_id"], identity["listing_id"]


def _period(candidate: dict) -> tuple[int | None, int | None]:
    period = candidate.get("fiscal_period")
    if not isinstance(period, dict):
        return None, None
    year, quarter = period.get("fiscal_year"), period.get("fiscal_quarter")
    return (year if type(year) is int else None, quarter if type(quarter) is int else None)


def _published_date(candidate: dict) -> str | None:
    published = candidate.get("published_at")
    if isinstance(published, str):
        try:
            return date.fromisoformat(published[:10]).isoformat()
        except ValueError:
            pass
    return None


class _Refresh:
    def __init__(self, store: RefreshStore, ports: Ports, options: Deployment, run: dict,
                 now: datetime) -> None:
        self.store = store
        self.ports = ports
        self.options = options
        self.run = run
        self.now = now
        self.deadline = time.monotonic() + options.tick_seconds
        self.pages_left = options.metadata_pages
        self.acquires_left = options.acquisitions
        self.reads_left = options.reading_documents

    def _record(self, *reasons: str, partial: bool = False) -> None:
        self.run["reason_codes"] = list(dict.fromkeys([*self.run["reason_codes"], *reasons]))
        self.run["partial"] |= partial

    def _owner_reasons(self, result: dict) -> list[str]:
        return [str(value) for value in result.get("reason_codes", []) if isinstance(value, str)]

    def _save(self, **kwargs) -> None:
        self.run["updated_at"] = utc_text(self.now)
        self.run["active_action"] = None
        self.store.checkpoint(self.run, **kwargs)

    def _admit(self, stage: str, reference: str) -> None:
        if not self.store.admit(self.run, stage, reference, utc_text(self.now)):
            raise _AdmissionStopped()

    def _advance(self, stage: str) -> bool:
        self.run["state"] = stage
        self._save()
        return True

    def run_stages(self) -> None:
        stages = {
            "discovering": self._discover, "backlog": self._backlog,
            "acquiring": self._acquire, "reading": self._read, "finalizing": self._finish,
        }
        while self.deadline > time.monotonic():
            settings = self.store.load()["settings"]
            if not settings["enabled"]:
                break
            if work_scope(settings) != work_scope(self.run["settings"]):
                self._supersede()
                break
            try:
                again = stages[self.run["state"]]()
            except _AdmissionStopped:
                break
            except OwnerUnavailable as exc:
                self._record(exc.reason)
                self._save()
                break
            if not again:
                break

    def _timeout(self, cap: float) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise OwnerUnavailable("scheduled_tick_deadline")
        return min(cap, remaining)

    def _roster(self) -> bool:
        if self.pages_left == 0:
            return False
        self.pages_left -= 1
        run = self.run
        snapshot, cursor = run["roster_snapshot_id"], run["roster_cursor"]
        try:
            page = self.ports.roster(run["settings"]["roster"], cursor, snapshot,
                                     timeout=self._timeout(self.options.discovery["timeout_seconds"]))
        except OwnerUnavailable as exc:
            if exc.reason == "roster_snapshot_changed":
                run.update(roster_snapshot_id=None, roster_cursor=None, members=[])
            raise
        next_cursor = page.get("next_cursor")
        if (snapshot is not None and snapshot != page["snapshot_id"]
                or next_cursor is not None and next_cursor == cursor):
            run.update(roster_snapshot_id=None, roster_cursor=None, members=[])
            raise OwnerUnavailable("roster_snapshot_changed")
        before = {_member_scope(member) for member in run["members"]}
        for member in page["items"]:
            if _member_scope(member) not in before:
                before.add(_member_scope(member))
                run["members"].append(member)
        run.update(roster_snapshot_id=page["snapshot_id"], roster_cursor=next_cursor)
        if next_cursor is None:
            selected = {_member_scope(member) for member in run["members"]}
            ordered = run["work"]
            run["work"] = {}
            for key, work in ordered.items():
                if tuple(work["listing_scope"]) in selected and self._enabled_kind(work):
                    run["work"][key] = work
                else:
                    run["suspended"][key] = work
            if run["suspended"]:
                self._record("pending_outside_current_scope")
        reasons = self._owner_reasons(page)
        self._record(*reasons, partial=bool(reasons))
        self._save()
        return True

    def _enabled_kind(self, work: dict) -> bool:
        settings = self.run["settings"]
        if work["kind"] == "transcript.acquire":
            return settings["transcripts_enabled"]
        return set(work["document_kinds"]) <= set(settings["document_kinds"])

    def _discover(self) -> bool:
        run = self.run
        if run["roster_snapshot_id"] is None or run["roster_cursor"] is not None:
            return self._roster()
        if run["discovery_index"] == len(run["members"]):
            settings = run["settings"]
            return self._advance("backlog" if settings["backlog_enabled"] and
                                 settings["reading_level"] != "off" else "acquiring")
        if self.pages_left == 0:
            return False
        self.pages_left -= 1
        member = run["members"][run["discovery_index"]]
        settings = run["settings"]
        kinds = settings["document_kinds"].copy()
        if settings["transcripts_enabled"] and "earnings_transcript" not in kinds:
            kinds.append("earnings_transcript")
        if not kinds:
            run["discovery_index"] += 1
            self._save()
            return True
        scope_keys = [stable_key([*_member_scope(member), member["market"], kind]) for kind in kinds]
        since = self._since(scope_keys)
        cursor = run["discovery_cursor"]
        request = {
            "schema_version": "cwp-incremental-discovery-request/1",
            "identity": member, "source_market": member["market"], "document_kinds": kinds,
            "since_date": since, "as_of_date": run["as_of_date"], "cursor": cursor,
            "limits": self.options.discovery,
        }
        request["request_id"] = "sr-discover-" + stable_key(request)[:28]
        try:
            self._admit("discovery", request["request_id"])
            page = self.ports.discover(request, timeout=self._timeout(self.options.discovery["timeout_seconds"]))
        except OwnerUnavailable as exc:
            # Other companies and already-present originals can still progress.
            self._record(exc.reason, partial=True)
            self._next_member()
            self._save()
            return True
        usage = page.get("usage") or {}
        for counter, field in (("metadata_requests", "http_requests"), ("metadata_bytes", "response_bytes")):
            if type(usage.get(field)) is int and usage[field] >= 0:
                run["usage"][counter] += usage[field]
            else:
                run["usage"]["metadata_usage_incomplete"] = True
        candidates_proven = True
        for candidate in page["candidates"]:
            candidates_proven &= self._add_candidate(member, kinds, since, candidate)
        # A continuation is independent of coverage. A later complete page
        # cannot erase an explicitly incomplete earlier page from this scope.
        run["discovery_complete"] &= candidates_proven and page["coverage"] == "complete"
        next_cursor = page.get("next_cursor")
        self._record(*self._owner_reasons(page))
        watermark = None
        if next_cursor is None or next_cursor in run["discovery_cursors"]:
            if run["discovery_complete"] and next_cursor is None and page["coverage"] == "complete":
                watermark = dict.fromkeys(scope_keys, run["as_of_date"])
            else:
                self._record("discovery_partial", partial=True)
            self._next_member()
        else:
            run["discovery_cursor"] = next_cursor
            run["discovery_cursors"].append(next_cursor)
        self._save(watermarks=watermark)
        return True

    def _since(self, keys: list[str]) -> str:
        watermarks = self.store.load()["watermarks"]
        as_of = date.fromisoformat(self.run["as_of_date"])
        dates = [
            date.fromisoformat(watermarks[key]) - timedelta(days=self.options.overlap_days)
            if key in watermarks else as_of - timedelta(days=self.options.lookback_days)
            for key in keys
        ]
        return min(as_of, *dates).isoformat()

    def _next_member(self) -> None:
        self.run["discovery_index"] += 1
        self.run["discovery_cursor"] = None
        self.run["discovery_complete"] = True
        self.run["discovery_cursors"] = []

    def _add_candidate(self, identity: dict, kinds: list[str], since: str, candidate: dict) -> bool:
        if not isinstance(candidate, dict):
            self._record("discovery_candidate_scope_unverified")
            return False
        bound_scope = candidate.get("identity")
        if bound_scope is not None and (not isinstance(bound_scope, dict) or any(
            bound_scope.get(field) != identity[field] for field in ("entity_id", "listing_id")
        )):
            self._record("discovery_candidate_scope_unverified")
            return False
        accession, provider, kind = (candidate.get(field) for field in (
            "provider_document_id", "provider", "document_kind",
        ))
        if (not isinstance(accession, str) or not accession or not isinstance(provider, str)
                or not provider or candidate.get("source_market") != identity["market"]
                or kind not in kinds):
            self._record("discovery_candidate_scope_unverified")
            return False
        published = _published_date(candidate)
        if published is None or not since <= published <= self.run["as_of_date"]:
            self._record("discovery_publication_unverified")
            return False
        year, quarter = _period(candidate)
        ref = _reference(candidate.get("source_ref"))
        scope = [*_member_scope(identity), identity["market"]]
        if kind != "earnings_transcript":
            request = self._filing_request(identity, candidate, year, quarter)
            key = stable_key(["filing", *scope, provider, accession, candidate.get("revision_id")])
            self._queue(key, "filing.acquire", request, ref, _member_scope(identity), [kind])
        call_period = kind in ("earnings_transcript", "quarterly_report") or (
            candidate.get("transcript_period_verified") is True
        )
        if (self.run["settings"]["transcripts_enabled"] and call_period
                and year is not None and quarter in (1, 2, 3, 4)):
            key = stable_key(["transcript", *scope, year, quarter])
            request = {
                "schema_version": "ff-transcript-request/1", "identity": identity,
                "as_of_date": self.run["as_of_date"], "fiscal_year": year, "fiscal_quarter": quarter,
                "intent": "fetch_if_missing", "acquisition_limits": self.options.acquisition,
            }
            self._queue(key, "transcript.acquire", request, ref if kind == "earnings_transcript" else None,
                        _member_scope(identity), [])
        elif kind == "earnings_transcript":
            self._record("exact_fy_q_required", partial=True)
        return True

    def _filing_request(self, identity: dict, candidate: dict, year: int | None,
                        quarter: int | None) -> dict:
        request = {
            "schema_version": "2.0", "company_query": identity["ticker"], "market": identity["market"],
            "as_of_date": self.run["as_of_date"], "document_kind": candidate["document_kind"],
            "provider": candidate["provider"], "provider_document_id": candidate["provider_document_id"],
            "filing_intent": "fetch_if_missing", "acquisition_limits": self.options.acquisition,
            "mode": "exact" if year is not None else "latest_as_of",
        }
        if identity.get("exchange"):
            request["exchange"] = identity["exchange"]
        if year is not None:
            request["fiscal_year"] = year
        if quarter in (1, 2, 3, 4) and candidate["document_kind"] == "quarterly_report":
            request["fiscal_period"] = f"Q{quarter}"
        return request

    def _queue(self, key: str, kind: str | None, request: dict | None, ref: dict | None,
               scope: tuple[str, str], document_kinds: list[str]) -> None:
        work = self.run["work"]
        if key in work:
            return
        work[key] = {"kind": kind, "request": request, "source_ref": ref, "listing_scope": list(scope),
                     "document_kinds": document_kinds,
                     "acquire_state": "ready" if ref is not None else "pending"}
        if kind is not None:
            self.run["counts"]["candidates"] += 1
            if ref is not None:
                self.run["counts"]["reused"] += 1

    def _backlog(self) -> bool:
        run = self.run
        if run["backlog_index"] == len(run["members"]):
            return self._advance("acquiring")
        if self.pages_left == 0:
            return False
        self.pages_left -= 1
        member = run["members"][run["backlog_index"]]
        cursor = run["backlog_cursor"]
        try:
            result = self.ports.backlog({
                "schema_version": "cwp-incremental-backlog-request/1",
                "identity": member, "reading_level": run["settings"]["reading_level"],
                "document_kinds": run["settings"]["document_kinds"],
                "since_date": (date.fromisoformat(run["as_of_date"])
                               - timedelta(days=self.options.lookback_days)).isoformat(),
                "as_of_date": run["as_of_date"], "cursor": cursor,
                "limits": self.options.reading,
            }, timeout=self._timeout(self.options.reading["timeout_seconds"]))
            self._record(*self._owner_reasons(result))
            refs_in_work = {_reference_key(work["source_ref"]) for work in run["work"].values()
                            if work["source_ref"] is not None}
            for value in result["sources"]:
                ref = _reference(value)
                if ref is None:
                    self._record("backlog_source_unverified", partial=True)
                elif _reference_key(ref) not in refs_in_work:
                    self._queue("backlog-" + _reference_key(ref), None, None, ref, _member_scope(member),
                                run["settings"]["document_kinds"])
            next_cursor = result.get("next_cursor")
        except OwnerUnavailable as exc:
            self._record(exc.reason, partial=True)
            next_cursor = None
        if next_cursor is None or next_cursor in run["backlog_cursors"]:
            if next_cursor is not None:
                self._record("backlog_cursor_repeated", partial=True)
            run["backlog_index"] += 1
            run["backlog_cursors"] = []
            next_cursor = None
        else:
            run["backlog_cursors"].append(next_cursor)
        run["backlog_cursor"] = next_cursor
        self._save()
        return True

    def _acquire(self) -> bool:
        run = self.run
        pending = next(((key, work) for key, work in run["work"].items()
                        if work["acquire_state"] == "pending" and work.get("acquire_run") != run["run_id"]), None)
        if pending is None:
            if run["settings"]["reading_level"] == "off":
                return self._advance("finalizing")
            return self._advance("reading")
        if self.acquires_left == 0:
            return False
        self.acquires_left -= 1
        key, work = pending
        # Work and its native idempotency key are already durable before this call.
        try:
            self._admit("acquisition", "sr-source-" + key)
            job = self.ports.acquire("sr-source-" + key, work["kind"], work["request"],
                                     timeout=self._timeout(self.options.acquisition["timeout_seconds"]),
                                     run_id=run["run_id"])
        except OwnerUnavailable as exc:
            work["acquire_run"] = run["run_id"]
            self._record(exc.reason, partial=True)
            self._save()
            return True
        work["owner_job_id"] = job["owner_job_id"]
        work["acquire_run"] = run["run_id"]
        if job.get("cost_state") == "unknown":
            run["usage"]["owner_cost_unknown"] += 1
        result = job.get("result") or {}
        ref = _reference(result.get("source_ref"))
        if job["status"] == "succeeded" and ref is not None:
            done = "downloaded" if result.get("downloads") and not job.get("reused_job") else "reused"
            run["counts"][done] += 1
            work.update(source_ref=ref, acquire_state="ready")
        elif job["status"] in ("failed", "cancelled", "succeeded"):
            run["counts"]["failed"] += 1
            work["acquire_state"] = "pending" if job.get("safe_retry") else "failed"
            reason = (job.get("error") or {}).get("code") or result.get("reason") or "acquisition_failed"
            self._record(reason, partial=True)
        else:
            self._record("acquisition_pending" if ref is None else "acquisition_unconfirmed", partial=True)
        self._save()
        return True

    def _read(self) -> bool:
        run = self.run
        eligible = [work for work in run["work"].values() if work["acquire_state"] == "ready"
                    and work.get("read_state") not in {"read", "summarized", "failed", "skipped"}
                    and work.get("read_attempt") != run["run_id"]]
        if not eligible:
            return self._advance("finalizing")
        if self.reads_left == 0:
            return False
        saved_groups = {
            _reference_key(work["source_ref"]): work["reading_batch"]
            for work in eligible if work.get("reading_batch") is not None
        }
        for work in eligible:
            if work.get("reading_batch") is None:
                batch = saved_groups.get(_reference_key(work["source_ref"]))
                if batch is not None:
                    work["reading_batch"] = batch
        active = run["reading_batch"]
        if active is None:
            saved = eligible[0].get("reading_batch")
            if saved is None:
                saved = self._new_read_batch(eligible)
            run["reading_batch"] = active = saved
            group_keys = {_reference_key(source) for source in active["request"]["sources"]}
            for work in eligible:
                if (work.get("reading_batch") is None
                        and _reference_key(work["source_ref"]) in group_keys):
                    work["reading_batch"] = active
            self._save()
        request = active["request"]
        keys = {_reference_key(source) for source in request["sources"]}
        self.reads_left = max(0, self.reads_left - len(keys))
        try:
            if self._same_read_range(active):
                self._admit("reading", request["run_id"])
                response = self.ports.read(request, timeout=self._timeout(self.options.reading["timeout_seconds"]))
            else:
                self._record("reading_scope_changed")
                response = self.ports.read_status(
                    request["run_id"], timeout=self._timeout(self.options.reading["timeout_seconds"]),
                )
            items = {}
            for item in response["items"]:
                ref = _reference(item.get("source_ref"))
                if ref is not None and _reference_key(ref) in keys:
                    items[_reference_key(ref)] = item
            self._record(*self._owner_reasons(response))
        except OwnerUnavailable as exc:
            self._record(exc.reason, partial=True)
            items = {}
        for work in eligible:
            key = _reference_key(work["source_ref"])
            if key not in keys or work.get("reading_batch") != active:
                continue
            item = items.get(key, {})
            status = item.get("state")
            work.update(read_attempt=run["run_id"], reading_batch=active)
            if status in ("read", "summarized") and not item.get("result_ref"):
                self._record("reading_result_reference_missing")
                status = "deferred"
            if status in ("read", "summarized", "skipped", "failed"):
                work.update(read_state=status, result_ref=item.get("result_ref"))
                run["counts"][status] += 1
                self._record(*self._owner_reasons(item), partial=status == "failed")
            else:
                work["read_state"] = "deferred"
                self._record(*self._owner_reasons(item), "reading_pending", partial=True)
        run["reading_batch"] = None
        self._save()
        return True

    def _new_read_batch(self, eligible: list[dict]) -> dict:
        pending = [work for work in eligible if work.get("reading_batch") is None]
        unique = {_reference_key(work["source_ref"]): work["source_ref"] for work in pending}
        sources = list(unique.values())[:self.reads_left]
        keys = {_reference_key(ref) for ref in sources}
        level = self.run["settings"]["reading_level"]
        return {
            "request": {
                "schema_version": "cwp-incremental-read-request/1",
                "run_id": "sr-read-" + stable_key([self.run["run_id"], level, sources])[:24],
                "reading_level": level, "sources": sources, "limits": self.options.reading,
            },
            "listing_scopes": [work["listing_scope"] for work in pending if _reference_key(work["source_ref"]) in keys],
            "scope": work_scope(self.run["settings"]),
        }

    def _same_read_range(self, active: dict) -> bool:
        allowed = {_member_scope(member) for member in self.run["members"]}
        return (active["scope"] == work_scope(self.run["settings"])
                and all(tuple(member) in allowed for member in active["listing_scopes"]))

    def _supersede(self) -> None:
        run = self.run
        self._record("settings_scope_changed", partial=True)
        run["state"] = "superseded"
        remaining = {key: work for key, work in run["work"].items() if work["acquire_state"] == "pending"
                     or work["acquire_state"] == "ready" and work.get("read_state") not in {
                         "read", "summarized", "skipped", "failed",
                     }}
        run["counts"]["pending"] = len(remaining) + len(run["suspended"])
        self.store.finish(run, {**run["suspended"], **remaining})
        publish_refresh_observation(run)

    def _finish(self) -> bool:
        run = self.run
        pending = {
            key: work for key, work in run["work"].items()
            if work["acquire_state"] == "pending" or work.get("read_state") == "deferred"
        }
        run["counts"]["pending"] = len(pending)
        run["state"] = "partial" if pending or run["partial"] else "completed"
        self.store.finish(run, {**run["suspended"], **pending})
        publish_refresh_observation(run)
        return False


def run_tick(store: RefreshStore, ports: Ports, options: Deployment, *, now: datetime) -> None:
    state = store.load()
    if not state["settings"]["enabled"]:
        return
    slot = due_slot(state["settings"]["cadence"], now)
    if state["current"] is None and slot_consumed(state["last_slot"], slot, state["settings"]):
        return
    with store.execution():
        current = store.begin(slot, state["revision"], now)
        if current is not None:
            _Refresh(store, ports, options, current, now).run_stages()
