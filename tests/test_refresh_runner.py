from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ff_refresh_owners import Deployment, OwnerUnavailable
from ff_refresh_runner import run_tick
from ff_refresh_store import RefreshStore
from test_scheduled_refresh import configure_body
from ff_refresh_policy import validate_settings


TIME = datetime(2026, 11, 23, 9, tzinfo=timezone.utc)
IDENTITY = {"entity_id": "issuer-1", "listing_id": "listing-1", "market": "US", "ticker": "CONE"}
SOURCE = {"schema_version": "2.0", "document_id": "document-1", "source_id": "source-1",
          "content_sha256": "e" * 64, "byte_size": 10, "mime_type": "application/pdf"}


class LostOwnerReceipt(BaseException):
    pass


class Owners:
    def __init__(self):
        self.roster_calls = []
        self.discovery_calls = []
        self.jobs = {}
        self.read_calls = []
        self.status_calls = []
        self.interrupt_at = None
        self.before_job = None
        self.partial = False

    def roster(self, scope, cursor, snapshot, *, timeout):
        self.roster_calls.append((cursor, snapshot))
        return {"snapshot_id": "owner-snapshot", "items": [] if cursor else [IDENTITY],
                "next_cursor": None if cursor else "cursor-2", "reason_codes": []}

    def discover(self, request, *, timeout):
        self.discovery_calls.append(request)
        extra = {"fiscal_period": {"fiscal_year": 2026, "fiscal_quarter": 3}}
        candidate = {"provider": "sec", "provider_document_id": "known-accession", "source_market": "US",
                     "document_kind": "annual_report", "published_at": "2026-11-20",
                     "transcript_period_verified": True, **extra}
        return {
            "candidates": [
                {**candidate, "source_ref": SOURCE},
                {**candidate, "provider_document_id": "revised-accession"},
            ],
            "coverage": "partial" if self.partial else "complete", "next_cursor": None,
            "usage": {"http_requests": 1, "response_bytes": 35}, "reason_codes": [],
        }

    def backlog(self, request, *, timeout):
        return {"sources": [], "next_cursor": None, "reason_codes": []}

    def acquire(self, key, kind, request, *, timeout, run_id):
        if self.before_job is not None:
            hook, self.before_job = self.before_job, None
            hook()
        if key in self.jobs:
            return self.jobs[key]
        record = {
            "owner_job_id": f"job-{len(self.jobs)}", "status": "succeeded", "cost_state": "known",
            "result": {"source_ref": {**SOURCE, "document_id": key}, "downloads": 1},
            "kind": kind,
        }
        self.jobs[key] = record
        if self.interrupt_at == "acquire":
            self.interrupt_at = None
            raise LostOwnerReceipt
        return record

    def read(self, request, *, timeout):
        self.read_calls.append(request)
        if self.interrupt_at == "read":
            self.interrupt_at = None
            raise LostOwnerReceipt
        return {"items": [
            {"source_ref": ref, "state": "read", "reused": False, "result_ref": "artifact",
             "reason_codes": []} for ref in request["sources"]
        ], "reason_codes": []}

    def read_status(self, run_id, *, timeout):
        self.status_calls.append(run_id)
        raise OwnerUnavailable("reading_status_unavailable")


def _settings(**overrides):
    return validate_settings(configure_body(**overrides)["settings"])


def test_restart_reuses_frozen_roster_native_job_and_read_request(tmp_path):
    store = RefreshStore(tmp_path)
    store.configure(_settings(), None)
    owners = Owners()
    owners.interrupt_at = "acquire"
    with pytest.raises(LostOwnerReceipt):
        run_tick(store, owners, Deployment(), now=TIME)
    original = store.load()["current"]
    assert len(owners.jobs) == 1 and original["run_id"]
    assert owners.roster_calls == [(None, None), ("cursor-2", "owner-snapshot")]
    owners.interrupt_at = "read"
    with pytest.raises(LostOwnerReceipt):
        run_tick(store, owners, Deployment(), now=TIME)
    run_tick(store, owners, Deployment(), now=TIME)
    done = store.load()["last_run"]
    assert done["run_id"] == original["run_id"] and done["state"] == "completed"
    assert done["counts"]["reused"] == 1 and done["counts"]["downloaded"] == 2
    assert {job["kind"] for job in owners.jobs.values()} == {"filing.acquire", "transcript.acquire"}
    assert len(owners.discovery_calls) == 1 and len(owners.jobs) == 2
    assert owners.read_calls[0] == owners.read_calls[1]
    run_tick(store, owners, Deployment(), now=TIME)
    assert len(owners.jobs) == 2 and len(owners.read_calls) == 2


def test_partial_discovery_does_not_advance_coverage_watermark(tmp_path):
    store = RefreshStore(tmp_path)
    store.configure(_settings(reading_level="off"), None)
    owners = Owners()
    owners.partial = True
    run_tick(store, owners, Deployment(), now=TIME)
    state = store.load()
    assert state["watermarks"] == {}
    assert state["last_run"]["state"] == "partial" and len(owners.jobs) == 2


def test_live_disable_finishes_the_returned_action_and_does_not_start_another(tmp_path):
    store = RefreshStore(tmp_path)
    store.configure(_settings(), None)
    owners = Owners()
    owners.before_job = lambda: store.configure(_settings(enabled=False), None)
    run_tick(store, owners, Deployment(), now=TIME)
    saved = store.load()["current"]
    assert saved["counts"]["downloaded"] == 1 and len(owners.jobs) == 1
    run_tick(store, owners, Deployment(), now=TIME)
    assert len(owners.jobs) == 1
    store.configure(_settings(), None)
    run_tick(store, owners, Deployment(), now=TIME)
    assert len(owners.jobs) == 2 and store.load()["last_run"]["run_id"] == saved["run_id"]


def test_owner_outage_defers_roster_without_selecting_another_universe(tmp_path):
    store = RefreshStore(tmp_path)
    store.configure(_settings(), None)

    class Offline(Owners):
        def roster(self, scope, cursor, snapshot, *, timeout):
            raise OwnerUnavailable("roster_unavailable")

    owners = Offline()
    run_tick(store, owners, Deployment(), now=TIME)
    state = store.load()
    assert state["current"]["roster_snapshot_id"] is None
    assert "roster_unavailable" in state["current"]["reason_codes"]
    assert not owners.discovery_calls and not owners.jobs


def test_partial_intermediate_page_stays_partial_after_a_complete_tail(tmp_path):
    store = RefreshStore(tmp_path)
    store.configure(_settings(reading_level="off"), None)

    class Paged(Owners):
        def discover(self, request, *, timeout):
            result = super().discover(request, timeout=timeout)
            if request["cursor"] is None:
                result.update(coverage="partial", next_cursor="page-two")
            return result

    owners = Paged()
    run_tick(store, owners, Deployment(), now=TIME)
    assert len(owners.discovery_calls) == 2
    assert store.load()["watermarks"] == {}
    assert store.load()["last_run"]["state"] == "partial"


def test_editing_the_hour_does_not_repeat_the_completed_slot(tmp_path):
    store = RefreshStore(tmp_path)
    store.configure(_settings(reading_level="off"), None)
    owners = Owners()
    run_tick(store, owners, Deployment(), now=TIME)
    first = store.load()["last_run"]
    store.configure(_settings(reading_level="off", cadence={
        "frequency": "daily", "local_time": "08:00", "time_zone": "Europe/London",
    }), None)
    run_tick(store, owners, Deployment(), now=TIME)
    assert store.load()["last_run"] == first
    assert len(owners.discovery_calls) == 1


def test_disable_while_a_stage_is_about_to_be_admitted_blocks_new_provider_work(tmp_path, monkeypatch):
    store = RefreshStore(tmp_path)
    store.configure(_settings(), None)
    admit = store.admit

    def stop_before_admission(run, stage, reference, when):
        store.configure(_settings(enabled=False), None)
        return admit(run, stage, reference, when)

    monkeypatch.setattr(store, "admit", stop_before_admission)
    owners = Owners()
    run_tick(store, owners, Deployment(), now=TIME)
    assert not owners.discovery_calls and not owners.jobs


def test_changed_scope_does_not_run_unsubmitted_items_from_paused_roster(tmp_path):
    store = RefreshStore(tmp_path)
    store.configure(_settings(), None)
    changed = {"mode": "universe", "universe_id": "the-new-universe"}

    class TwoScopes(Owners):
        def roster(self, scope, cursor, snapshot, *, timeout):
            if scope == changed:
                return {"snapshot_id": "new-verified-empty", "items": [], "next_cursor": None}
            return super().roster(scope, cursor, snapshot, timeout=timeout)

    owners = TwoScopes()
    owners.before_job = lambda: store.configure(_settings(enabled=False), None)
    run_tick(store, owners, Deployment(), now=TIME)
    previous = store.load()["current"]["run_id"]
    store.configure(_settings(roster=changed, reading_level="off"), None)
    run_tick(store, owners, Deployment(), now=TIME)
    assert store.load()["last_run"]["state"] == "superseded" and len(owners.jobs) == 1
    run_tick(store, owners, Deployment(), now=TIME)
    done = store.load()["last_run"]
    assert done["run_id"] != previous and done["roster_snapshot_id"] == "new-verified-empty"
    assert not owners.read_calls and len(owners.jobs) == 1


def test_paid_read_group_does_not_receive_new_id_or_include_removed_company(tmp_path):
    store = RefreshStore(tmp_path)
    store.configure(_settings(reading_level="summary", transcripts_enabled=False,
                              backlog_enabled=False), None)
    second = {**IDENTITY, "entity_id": "issuer-2", "listing_id": "listing-2"}
    extra = {**IDENTITY, "entity_id": "issuer-3", "listing_id": "listing-3"}

    class ReadingOwners(Owners):
        members = [IDENTITY, second]
        lose_reply = True

        def roster(self, scope, cursor, snapshot, *, timeout):
            return {"snapshot_id": "roster-snapshot", "items": self.members, "next_cursor": None}

        def discover(self, request, *, timeout):
            entity = request["identity"]["entity_id"]
            return {
                "coverage": "complete", "next_cursor": None, "usage": {},
                "candidates": [{"provider": "sec", "provider_document_id": entity,
                                "source_market": "US", "document_kind": "annual_report",
                                "published_at": request["as_of_date"],
                                "source_ref": {**SOURCE, "document_id": entity}}],
            }

        def read(self, request, *, timeout):
            if self.lose_reply:
                self.read_calls.append(request)
                raise OwnerUnavailable("original_read_reply_lost")
            return super().read(request, timeout=timeout)

    owners = ReadingOwners()
    run_tick(store, owners, Deployment(), now=TIME)
    original = owners.read_calls[0]
    assert {ref["document_id"] for ref in original["sources"]} == {"issuer-1", "issuer-2"}
    owners.members = [extra, IDENTITY]
    owners.lose_reply = False
    run_tick(store, owners, Deployment(), now=TIME + timedelta(days=1))
    assert owners.status_calls == [original["run_id"]]
    assert len(owners.read_calls) == 2
    assert [ref["document_id"] for ref in owners.read_calls[-1]["sources"]] == ["issuer-3"]
