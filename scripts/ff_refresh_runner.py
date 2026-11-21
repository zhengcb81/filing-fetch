"""One resumable scheduled refresh. Only the owner ports perform side effects."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import time
from typing import Any, Protocol

from ff_job_feedback import publish_refresh_failure, publish_refresh_observation
from ff_refresh_owners import Deployment, OwnerUnavailable, stable_key
from ff_refresh_policy import due_slot, slot_consumed, utc_text, work_scope
from ff_refresh_store import RefreshStore
from ff_source_ref import validate_source_ref
from filing_contracts import CWP_TRANSCRIPT_DOCUMENT_KIND, FilingFetchError


class Ports(Protocol):
    def roster(self, scope: dict, cursor: str | None, snapshot: str | None, *, timeout: float) -> dict: ...
    def discover(self, request: dict, *, timeout: float) -> dict: ...
    def backlog(self, request: dict, *, timeout: float) -> dict: ...
    def acquire(self, key: str, kind: str, request: dict, *, timeout: float, run_id: str) -> dict: ...
    def read(self, request: dict, *, timeout: float) -> dict: ...
    def read_status(self, run_id: str, *, timeout: float) -> dict: ...


class _AdmissionStopped(Exception):
    pass


_READ_FINISHED = {"read", "summarized", "failed", "skipped"}


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


def _filing_kinds(settings: dict) -> list[str]:
    return [
        kind for kind in settings["document_kinds"]
        if kind not in (CWP_TRANSCRIPT_DOCUMENT_KIND, "earnings_transcript")
    ]


def _reading_kinds(settings: dict) -> list[str]:
    kinds = _filing_kinds(settings)
    if settings["transcripts_enabled"]:
        kinds.append(CWP_TRANSCRIPT_DOCUMENT_KIND)
    return kinds


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

    def _record(self, *reasons: str, partial: bool = False, error=None, item=None, stage=None) -> None:
        if partial or error is not None:
            action = self.run.get("active_action") or {}
            reference = item or action.get("reference") or self.run["run_id"]
            phase = stage or action.get("stage") or self.run["state"]
            for reason in reasons:
                publish_refresh_failure(self.run, jobs_dir=self.store.root.parent, reason=reason,
                                        reference=reference, stage=phase, error=error)
        self.run["reason_codes"] = list(dict.fromkeys([*self.run["reason_codes"], *reasons]))
        self.run["partial"] |= partial

    def _owner_reasons(self, result: dict) -> list[str]:
        reasons = result.get("reason_codes")
        return [value for value in reasons if isinstance(value, str)] if isinstance(reasons, list) else []

    def _observe_usage(self, kind: str, owner_id: str, reported: object) -> None:
        if not isinstance(reported, dict):
            return
        counts = ("model_requests", "model_attempts", "tokens", "estimated_micro_usd",
                  "unknown_reservations", "unsettled_reservations")
        snapshot: dict[str, int | str] = {
            name: reported[name] for name in counts
            if type(reported.get(name)) is int and reported[name] >= 0
        }
        state = reported.get("cost_state")
        if state in ("known", "settled", "unknown", "not_applicable"):
            snapshot["cost_state"] = state
        amount = reported.get("cost_usd")
        if isinstance(amount, str):
            try:
                dollars = Decimal(amount)
            except InvalidOperation:
                pass
            else:
                if dollars.is_finite() and dollars >= 0:
                    snapshot["cost_usd"] = amount
        if snapshot:
            usage = self.run["usage"]
            # Native values are cumulative snapshots of the same owner run/job.
            usage.setdefault(kind, {}).setdefault(owner_id, {}).update(snapshot)
            usage["owner_cost_unknown"] = sum(
                value.get("cost_state") == "unknown"
                for group in ("acquisition_jobs", "reading_runs")
                for value in usage.get(group, {}).values()
            )

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
                self._record(exc.reason, error=exc)
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
        return set(work["document_kinds"]) <= set(_reading_kinds(settings))

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
        kinds = _filing_kinds(settings)
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
            self._record(exc.reason, partial=True, error=exc)
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
        request = self._filing_request(identity, candidate, year, quarter)
        revision = candidate.get("revision_id") if ref is not None else None
        key = stable_key(["filing", *scope, provider, accession, revision])
        self._queue(key, "filing.acquire", request, ref, _member_scope(identity), [kind])
        call_period = kind == "quarterly_report" or candidate.get("transcript_period_verified") is True
        if (self.run["settings"]["transcripts_enabled"] and call_period
                and year is not None and quarter in (1, 2, 3, 4)):
            key = stable_key(["transcript", *scope, year, quarter])
            request = {
                "schema_version": "ff-transcript-request/1", "identity": identity,
                "as_of_date": self.run["as_of_date"], "fiscal_year": year, "fiscal_quarter": quarter,
                "intent": "fetch_if_missing", "acquisition_limits": self.options.acquisition,
            }
            self._queue(key, "transcript.acquire", request, None, _member_scope(identity), [])
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
        existing = work.get(key)
        if existing is not None:
            # A later discovered verified ref can satisfy unloaded work. An
            # already attempted acquisition still reconciles its native job.
            if ref is not None and not existing.get("acquire_run") and existing["acquire_state"] == "pending":
                existing.update(source_ref=ref, acquire_state="ready")
                self.run["counts"]["reused"] += 1
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
        kinds = _reading_kinds(run["settings"])
        if not kinds:
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
                "document_kinds": kinds,
                "since_date": (date.fromisoformat(run["as_of_date"])
                               - timedelta(days=self.options.lookback_days)).isoformat(),
                "as_of_date": run["as_of_date"], "cursor": cursor,
                "limits": self.options.reading,
            }, timeout=self._timeout(self.options.reading["timeout_seconds"]))
            incomplete = result.get("coverage") in ("partial", "unavailable")
            self._record(*self._owner_reasons(result), partial=incomplete)
            refs_in_work = {_reference_key(work["source_ref"]) for work in run["work"].values()
                            if work["source_ref"] is not None}
            for value in result["sources"]:
                ref = _reference(value)
                if ref is None:
                    self._record("backlog_source_unverified", partial=True)
                elif _reference_key(ref) not in refs_in_work:
                    self._queue("backlog-" + _reference_key(ref), None, None, ref, _member_scope(member), kinds)
            next_cursor = result.get("next_cursor")
        except OwnerUnavailable as exc:
            self._record(exc.reason, partial=True, error=exc)
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
            self._record(exc.reason, partial=True, error=exc)
            self._save()
            return True
        work["owner_job_id"] = job["owner_job_id"]
        work["acquire_run"] = run["run_id"]
        cost = job.get("cost")
        self._observe_usage("acquisition_jobs", job["owner_job_id"], {
            "cost_state": job.get("cost_state"),
            "cost_usd": cost.get("value") if isinstance(cost, dict) else None,
        })
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
            self._record(reason, partial=True, item=key, stage="acquisition")
        else:
            self._record("acquisition_pending" if ref is None else "acquisition_unconfirmed", partial=True)
        self._save()
        return True

    def _read(self) -> bool:
        run = self.run
        eligible = [work for work in run["work"].values() if work["acquire_state"] == "ready"
                    and work.get("read_state") not in _READ_FINISHED
                    and work.get("read_attempt") != run["run_id"]]
        if not eligible:
            return self._advance("finalizing")
        if self.reads_left == 0:
            return False
        # A suspended paid group must retain its original ID. A suspended
        # local group cannot bind a new alias back into an obsolete batch.
        saved_groups = {
            _reference_key(work["source_ref"]): batch for work in run["suspended"].values()
            if (batch := work.get("reading_batch")) is not None and batch["request"]["reading_level"] == "summary"
        }
        saved_groups.update({_reference_key(work["source_ref"]): batch for work in eligible
                             if (batch := work.get("reading_batch")) is not None})
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
        local = request["reading_level"] == "local"
        legacy_local_batch = local and len(keys) > 1
        same_scope = self._same_read_range(active)
        if not same_scope:
            self._record("reading_scope_changed")
        group = [work for work in eligible if work.get("reading_batch") == active
                 and _reference_key(work["source_ref"]) in keys]
        interrupted = (run.get("active_action") or {}).get("reference") == request["run_id"]
        local_retry = local and any(work.get("read_attempt") for work in group)
        share = min(self.reads_left, len({_reference_key(work["source_ref"]) for work in eligible})) if local else 1
        try:
            items = self._read_owner_receipt(
                request, keys, share=share, status_only=legacy_local_batch or not same_scope,
                check_status=interrupted or local_retry,
            )
        except OwnerUnavailable as exc:
            self._record(exc.reason, error=exc)
            if time.monotonic() >= self.deadline:
                # A later tick must read back the same admitted owner run.
                # Discarding it here could delay recovery until the next slot.
                self.store.checkpoint(run)
                return False
            items = {}
        # Discovery and backlog can hold different work rows for one exact
        # original. Keep every row's result while counting the source once,
        # including when an alias was already completed before a restart.
        counted = {_reference_key(work["source_ref"])
                   for work in (*run["work"].values(), *run["suspended"].values())
                   if work.get("read_attempt") == run["run_id"] and work.get("read_state") in _READ_FINISHED}
        for work in group:
            key = _reference_key(work["source_ref"])
            item = items.get(key, {})
            status = self._read_state(item)
            if status is None and legacy_local_batch and run["settings"]["reading_level"] == "local":
                work["reading_batch"] = None
                work.pop("read_attempt", None)
                continue
            work["read_attempt"] = run["run_id"]
            if status is not None:
                work.update(read_state=status, result_ref=item.get("result_ref"))
                if key not in counted:
                    run["counts"][status] += 1
                    counted.add(key)
                self._record(*(self._owner_reasons(item) or (["reading_failed"] if status == "failed" else [])),
                             partial=status == "failed", item=key, stage="reading")
            else:
                work["read_state"] = "deferred"
                self._record(*self._owner_reasons(item), "reading_pending", partial=True, item=key, stage="reading")
        run["reading_batch"] = None
        self._save()
        return True

    def _read_owner_receipt(self, request, keys, *, share, status_only, check_status):
        def timeout() -> float:
            # Divide the remaining tick among waiting local sources. A slow
            # source cannot spend the time needed to admit its siblings.
            return min(self.options.reading["timeout_seconds"], self._timeout(self.options.tick_seconds) / share)

        def items_of(response: dict) -> dict:
            self._observe_usage("reading_runs", request["run_id"], response.get("usage"))
            self._record(*self._owner_reasons(response))
            items = {}
            for item in response["items"]:
                ref = _reference(item.get("source_ref")) if isinstance(item, dict) else None
                if ref is not None and _reference_key(ref) in keys:
                    items[_reference_key(ref)] = item
            return items

        def read_status() -> dict:
            return items_of(self.ports.read_status(request["run_id"], timeout=timeout()))

        if status_only:
            return read_status()
        recovered = {}
        if check_status:
            try:
                recovered = read_status()
            except OwnerUnavailable as exc:
                self._record(exc.reason, error=exc)
            else:
                if all(self._read_state(recovered.get(key, {})) is not None for key in keys):
                    return recovered
        timeout()
        self._admit("reading", request["run_id"])
        self.reads_left = max(0, self.reads_left - len(keys))
        try:
            return {**recovered, **items_of(self.ports.read(request, timeout=timeout()))}
        except OwnerUnavailable as exc:
            self._record(exc.reason, error=exc)
            try:
                return {**recovered, **read_status()}
            except OwnerUnavailable as status_error:
                if not recovered or time.monotonic() >= self.deadline:
                    raise
                self._record(status_error.reason, error=status_error)
                return recovered

    def _read_state(self, item: dict) -> str | None:
        status = item.get("state")
        if status in ("read", "summarized") and not item.get("result_ref"):
            self._record("reading_result_reference_missing")
            return None
        return status if isinstance(status, str) and status in _READ_FINISHED else None

    def _new_read_batch(self, eligible: list[dict]) -> dict:
        pending = [work for work in eligible if work.get("reading_batch") is None]
        unique = {_reference_key(work["source_ref"]): work["source_ref"] for work in pending}
        level = self.run["settings"]["reading_level"]
        max_sources = 1 if level == "local" else min(
            self.reads_left, self.options.reading.get("max_sources", self.reads_left),
        )
        sources = list(unique.values())[:max_sources]
        keys = {_reference_key(ref) for ref in sources}
        return {
            "request": {
                "schema_version": "cwp-incremental-read-request/1",
                "run_id": "sr-read-" + stable_key([self.run["run_id"], level, sources])[:24],
                "reading_level": level, "sources": sources,
                "limits": {**self.options.reading, "max_sources": len(sources)},
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
        self._record("settings_scope_changed")
        run["state"] = "superseded"
        remaining = {key: work for key, work in run["work"].items() if work["acquire_state"] == "pending"
                     or work["acquire_state"] == "ready" and work.get("read_state") not in {
                         "read", "summarized", "skipped", "failed",
                     }}
        run["counts"]["pending"] = len(remaining) + len(run["suspended"])
        self.store.finish(run, {**run["suspended"], **remaining})
        publish_refresh_observation(run, jobs_dir=self.store.root.parent)

    def _finish(self) -> bool:
        run = self.run
        pending = {
            key: work for key, work in run["work"].items()
            if work["acquire_state"] == "pending" or work.get("read_state") == "deferred"
        }
        run["counts"]["pending"] = len(pending)
        run["state"] = "partial" if pending or run["partial"] else "completed"
        self.store.finish(run, {**run["suspended"], **pending})
        publish_refresh_observation(run, jobs_dir=self.store.root.parent)
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
