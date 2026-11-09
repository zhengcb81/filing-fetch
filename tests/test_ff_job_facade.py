"""ff-job/1 façade unit/contract tests (stubbed transport, zero network).

Covers the OWNERPKG-FILING-FETCH-01 acceptance mechanics against a temp store:
submit validation, idempotency, run transitions, cost projection states,
allowed-actions vocabulary, the retry zero-spend guard, queued-only cancel,
and the unknown→reconcile semantics. Real cross-process CLI behavior lives in
test_ff_job_cross_process.py; real-engine evidence runs are recorded under
planning/ff-job-facade-01/evidence/.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from io import StringIO
from pathlib import Path
from threading import Event
from tempfile import TemporaryDirectory
from unittest.mock import patch

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from ff_job_contracts import (  # noqa: E402
    FFJobError,
    allowed_actions_for,
    build_cost_view,
    build_job_view,
    build_result_view,
    retry_eligible,
    validate_submit_body,
)
from ff_job_runner import act, reconcile, run_job  # noqa: E402
from ff_job_store import JobStore  # noqa: E402
from filing_contracts import FilingFetchError  # noqa: E402

_FILING_REQUEST = {
    "schema_version": "2.0",
    "company_query": "Apple Inc.",
    "document_kind": "annual_report",
    "fiscal_year": 2025,
    "as_of_date": "2026-07-18",
    "filing_intent": "reuse_only",
    "mode": "exact",
}
_FETCH_REQUEST = dict(_FILING_REQUEST, filing_intent="fetch_if_missing", acquisition_limits={
    "max_bytes": 20000000,
    "timeout_seconds": 120,
    "max_cost_usd": "0.50",
})
_STATEMENTS_REQUEST = {
    "schema_version": "financial-statements-request/1",
    "company_query": "宁德时代",
    "intent": "reuse_only",
}
_CANDIDATE_HANDLE = {
    "request_id": "req-1",
    "document_id": "doc-1",
    "source_id": "src-1",
    "title": "Annual Report",
    "published_date": "2025-10-01",
    "content_sha256": "a" * 64,
    "snapshot_sha256": "a" * 64,
    "byte_size": 10,
    "mime_type": "application/pdf",
    "capture_ready": True,
    "document_kind": "annual_report",
    "fiscal_year": 2025,
    "resolution_outcome": "reused_existing",
    "download_events": 0,
    "source_ref": {
        "schema_version": "2.0",
        "document_id": "doc-1",
        "source_id": "src-1",
        "content_sha256": "a" * 64,
        "byte_size": 10,
        "mime_type": "application/pdf",
    },
}
_OBS_ZERO = {
    "schema_version": "acquisition-observation/1",
    "usage_scope": "operation",
    "outcome": "reused_before_download",
    "provider_started": False,
    "usage_complete": True,
    "wire_usage_complete": True,
    "http_exchanges_complete": True,
    "wire_body_bytes": 0,
    "entity_body_bytes": 0,
    "http_exchanges": 0,
    "cost_usd": None,
    "http_observation": None,
}

DEAD_PID = 999999999  # not a valid Windows pid (not %4) and never spawned here


def _submit(store: JobStore, *, kind: str, request: dict, key: str = "k-1",
            command_id: str = "cmd-1") -> tuple[dict, bool]:
    return store.create_job(
        {
            "schema_version": "ff-job/1",
            "command_id": command_id,
            "kind": kind,
            "idempotency_key": key,
            "request": request,
        },
        command_id=command_id,
    )


def _observation(**overrides: object) -> dict:
    return {**_OBS_ZERO, **overrides}


class SubmitContractTests(unittest.TestCase):
    def test_accepts_v2_filing_reuse(self) -> None:
        body = validate_submit_body({
            "schema_version": "ff-job/1", "command_id": "c", "kind": "filing.acquire",
            "idempotency_key": "k", "request": _FILING_REQUEST,
        })
        self.assertEqual(body["kind"], "filing.acquire")

    def test_rejects_legacy_v1_filing_request(self) -> None:
        with self.assertRaises(FFJobError):
            validate_submit_body({
                "schema_version": "ff-job/1", "command_id": "c", "kind": "filing.acquire",
                "idempotency_key": "k",
                "request": dict(_FILING_REQUEST, schema_version="1.2"),
            })

    def test_fetch_intent_requires_limits(self) -> None:
        with self.assertRaises(FFJobError):
            validate_submit_body({
                "schema_version": "ff-job/1", "command_id": "c", "kind": "filing.acquire",
                "idempotency_key": "k",
                "request": {k: v for k, v in _FETCH_REQUEST.items() if k != "acquisition_limits"},
            })

    def test_reuse_intent_forbids_limits(self) -> None:
        with self.assertRaises(FFJobError):
            validate_submit_body({
                "schema_version": "ff-job/1", "command_id": "c", "kind": "filing.acquire",
                "idempotency_key": "k",
                "request": dict(_FILING_REQUEST, acquisition_limits={
                    "max_bytes": 1, "timeout_seconds": 1, "max_cost_usd": "0",
                }),
            })

    def test_unknown_body_field_rejected(self) -> None:
        with self.assertRaises(FFJobError):
            validate_submit_body({
                "schema_version": "ff-job/1", "command_id": "c", "kind": "filing.acquire",
                "idempotency_key": "k", "request": _FILING_REQUEST, "config_path": "/x",
            })

    def test_fee_string_more_than_two_decimals_rejected(self) -> None:
        with self.assertRaises(FFJobError):
            validate_submit_body({
                "schema_version": "ff-job/1", "command_id": "c", "kind": "statements.acquire",
                "idempotency_key": "k",
                "request": dict(_STATEMENTS_REQUEST, intent="fetch_if_missing",
                                acquisition_limits={"max_bytes": 10, "timeout_seconds": 5,
                                                    "max_cost_usd": "0.123"}),
            })

    def test_unknown_kind_rejected(self) -> None:
        with self.assertRaises(FFJobError):
            validate_submit_body({
                "schema_version": "ff-job/1", "command_id": "c", "kind": "other.acquire",
                "idempotency_key": "k", "request": {},
            })

    def test_bad_idempotency_key_rejected(self) -> None:
        with self.assertRaises(FFJobError):
            validate_submit_body({
                "schema_version": "ff-job/1", "command_id": "c", "kind": "filing.acquire",
                "idempotency_key": "bad key!", "request": _FILING_REQUEST,
            })


class CostProjectionTests(unittest.TestCase):
    """G-m8-FF-03: real usage evidence projected into cost / cost_state."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.store = JobStore(Path(self._tmp.name) / "jobs")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _enqueue(self, request: dict | None = None, kind: str = "filing.acquire",
                 key: str = "k-1") -> dict:
        record, _ = _submit(self.store, kind=kind, request=request or _FILING_REQUEST, key=key)
        return record

    def test_second_run_is_idempotent_noop(self) -> None:
        record = self._enqueue()
        envelope = {"schema_version": "2.0", "status": "source_candidate",
                    "source_ref": _CANDIDATE_HANDLE["source_ref"], "calls": 1, "downloads": 0}
        with patch("fetch_filing.resolve_filing", return_value=dict(_CANDIDATE_HANDLE)), \
                patch("ff_v2_envelope.success_envelope", return_value=envelope):
            run_job(self.store, record["owner_job_id"], config_path=None, timeout_seconds=60)
            final, executed = run_job(self.store, record["owner_job_id"], config_path=None,
                                      timeout_seconds=60)
        self.assertFalse(executed)
        self.assertEqual(final["execution_count"], 1)

    def test_engine_failure_lands_failed_with_zero_cost_evidence(self) -> None:
        record = self._enqueue(request=dict(_FETCH_REQUEST))
        with patch("fetch_filing.resolve_filing") as engine, patch(
            "ff_v2_envelope.success_envelope", return_value={},
        ):
            engine.side_effect = FilingFetchError("company-wiki source query not_found",
                                                  code="not_found")
            final, _ = run_job(self.store, record["owner_job_id"], config_path=None,
                               timeout_seconds=60)
        self.assertEqual(final["status"], "failed")
        self.assertEqual(final["error"]["code"], "not_found")
        self.assertEqual(final["error"]["owner"], "filing-fetch")
        # fetch intent, provider phase never reached → provably zero spend.
        self.assertEqual(final["cost_state"], "known")
        self.assertEqual(final["cost"]["value"], "0.00")
        self.assertEqual(final["result"], None)

    def test_provider_started_without_fee_evidence_is_unknown(self) -> None:
        record = self._enqueue(request=dict(_FETCH_REQUEST))
        with patch("fetch_filing.resolve_filing") as engine, patch(
            "ff_v2_envelope.success_envelope", return_value={},
        ):
            engine.side_effect = FilingFetchError(
                "provider failed", code="upstream_error",
                acquisition_observation=_observation(provider_started=True,
                                                     usage_complete=True),
            )
            final, _ = run_job(self.store, record["owner_job_id"], config_path=None,
                               timeout_seconds=60)
        self.assertEqual(final["cost_state"], "unknown")
        self.assertEqual(final["cost"], None)

    def test_provider_reported_cost_is_known(self) -> None:
        record = self._enqueue(request=dict(_FETCH_REQUEST))
        observation = _observation(provider_started=True, usage_complete=True, cost_usd="0.35")
        with patch("fetch_filing.resolve_filing") as engine, patch(
            "ff_v2_envelope.success_envelope", return_value={},
        ):
            engine.side_effect = FilingFetchError(
                "provider failed", code="upstream_error", acquisition_observation=observation,
            )
            final, _ = run_job(self.store, record["owner_job_id"], config_path=None,
                               timeout_seconds=60)
        self.assertEqual(final["cost_state"], "known")
        self.assertEqual(final["cost"]["value"], "0.35")
        self.assertEqual(final["cost"]["basis"], "provider_reported")
        self.assertEqual(final["cost"]["currency"], "USD")

    def test_statements_fetch_zero_provider_cost(self) -> None:
        record = self._enqueue(kind="statements.acquire", request=dict(
            _STATEMENTS_REQUEST, intent="fetch_if_missing",
            acquisition_limits={"max_bytes": 10, "timeout_seconds": 5, "max_cost_usd": "0"},
        ))
        envelope = {"schema_version": "financial-statements-response/1", "status": "complete",
                    "statements": [{"statement_type": "income_statement"}],
                    "usage": {"http_requests": 2, "response_bytes": 4096, "cost_usd": "0.02"}}
        with patch("ff_financial_statements.fetch_statements", return_value=envelope):
            final, _ = run_job(self.store, record["owner_job_id"], config_path=None,
                               timeout_seconds=60)
        self.assertEqual(final["status"], "succeeded")
        # The provider-reported cost is authoritative for statements jobs.
        self.assertEqual(final["cost_state"], "known")
        self.assertEqual(final["cost"]["value"], "0.02")
        self.assertEqual(final["cost"]["basis"], "provider_reported")
        self.assertEqual(final["result"]["statement_count"], 1)
        self.assertEqual(final["result"]["usage"]["http_requests"], 2)
        self.assertEqual(final["result"]["calls"], 1)

    def test_statements_reuse_only_has_no_cost_dimension(self) -> None:
        record = self._enqueue(kind="statements.acquire", request=dict(_STATEMENTS_REQUEST))
        envelope = {"schema_version": "financial-statements-response/1", "status": "complete",
                    "statements": [], "usage": {"http_requests": 0, "response_bytes": 0,
                                               "cost_usd": "0.00"}}
        with patch("ff_financial_statements.fetch_statements", return_value=envelope):
            final, _ = run_job(self.store, record["owner_job_id"], config_path=None,
                               timeout_seconds=60)
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(final["cost_state"], "not_applicable")
        self.assertIsNone(final["cost"])

    def test_cost_rules(self) -> None:
        fresh = {"phase_reached": False, "provider_started": None, "usage_complete": None,
                 "cost_usd": None, "download_events": None}
        self.assertEqual(build_cost_view("reuse_only", fresh), (None, "not_applicable"))
        cost, state = build_cost_view("fetch_if_missing", fresh)
        self.assertEqual((cost["value"], state), ("0.00", "known"))
        ran_free = dict(fresh, phase_reached=True, provider_started=False, usage_complete=True)
        self.assertEqual(build_cost_view("fetch_if_missing", ran_free)[1], "known")
        charged = dict(fresh, phase_reached=True, provider_started=True, usage_complete=True,
                       cost_usd="1.25")
        cost, state = build_cost_view("fetch_if_missing", charged)
        self.assertEqual((cost["value"], state), ("1.25", "known"))
        uncertified = dict(fresh, phase_reached=True, provider_started=True, usage_complete=None)
        self.assertEqual(build_cost_view("fetch_if_missing", uncertified), (None, "unknown"))
        # The projection is the full frozen DecimalValue contract.
        self.assertEqual(
            set(cost if cost is not None else build_cost_view("fetch_if_missing", fresh)[0]),
            {"value", "currency", "unit", "scale", "period_start", "period_end",
             "period_kind", "fiscal_year", "basis", "scenario", "actual_or_forecast",
             "analysis_subject_id"},
        )
        zero_cost, _ = build_cost_view("fetch_if_missing", fresh)
        self.assertEqual(zero_cost["actual_or_forecast"], "actual")


class IdempotencyTests(unittest.TestCase):
    """G-m8-FF-03: one idempotency key binds one job and never re-acquires."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.store = JobStore(Path(self._tmp.name) / "jobs")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_same_key_same_request_replays_same_job(self) -> None:
        first, replayed1 = _submit(self.store, kind="filing.acquire", request=_FILING_REQUEST)
        second, replayed2 = _submit(self.store, kind="filing.acquire", request=_FILING_REQUEST)
        self.assertFalse(replayed1)
        self.assertTrue(replayed2)
        self.assertEqual(first["owner_job_id"], second["owner_job_id"])
        # The replay returns the stored record untouched: no second execution.
        self.assertEqual(second["attempts"], 0)

    def test_same_key_different_request_conflicts(self) -> None:
        _submit(self.store, kind="filing.acquire", request=_FILING_REQUEST)
        with self.assertRaises(FFJobError):
            _submit(self.store, kind="filing.acquire", request=dict(_FILING_REQUEST, fiscal_year=2024))

    def test_different_key_same_request_creates_new_job(self) -> None:
        first, _ = _submit(self.store, kind="filing.acquire", request=_FILING_REQUEST, key="a")
        second, _ = _submit(self.store, kind="filing.acquire", request=_FILING_REQUEST, key="b")
        self.assertNotEqual(first["owner_job_id"], second["owner_job_id"])

    def test_dangling_pointer_repairs_instead_of_wedging_the_key(self) -> None:
        """Crash debris (a pointer without its job record) must not wedge the
        key forever: past the grace window the lookup removes it and the
        submission can be claimed again."""
        import os
        import time as time_module

        body = {
            "schema_version": "ff-job/1", "command_id": "c", "kind": "filing.acquire",
            "idempotency_key": "crash-key", "request": _FILING_REQUEST,
        }
        store = self.store
        from ff_job_store import _canonical_hash

        request_hash = _canonical_hash({"kind": body["kind"], "request": body["request"]})
        pointer = store._idem_path("crash-key")
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(
            json.dumps({"owner_job_id": "ffjob-aaaaaaaaaaaa", "request_hash": request_hash}),
            encoding="utf-8",
        )
        stale = time_module.time() - 3600.0
        os.utime(pointer, (stale, stale))
        record, replayed = store.create_job(body, command_id="c")
        self.assertFalse(replayed)
        self.assertEqual(record["status"], "queued")
        # The repaired key now resolves to the new job.
        again, replayed2 = store.create_job(body, command_id="c")
        self.assertTrue(replayed2)
        self.assertEqual(again["owner_job_id"], record["owner_job_id"])

    def test_partial_legacy_pointer_recovers_without_wedging(self) -> None:
        for key, content in (("empty", b""), ("partial", b'{"owner_job_id":')):
            with self.subTest(key=key):
                pointer = self.store._idem_path(key)
                pointer.write_bytes(content)
                with patch("ff_job_store._IDEM_BUSY_TIMEOUT_SECONDS", 0.2):
                    first, replayed = _submit(
                        self.store, kind="filing.acquire", request=_FETCH_REQUEST, key=key,
                    )
                second, repeated = _submit(
                    self.store, kind="filing.acquire", request=_FETCH_REQUEST, key=key,
                )
                self.assertFalse(replayed)
                self.assertTrue(repeated)
                self.assertEqual(first["owner_job_id"], second["owner_job_id"])

    def test_damaged_pointer_keeps_previously_bound_job(self) -> None:
        first, _ = _submit(self.store, kind="filing.acquire", request=_FETCH_REQUEST)
        self.store._idem_path("k-1").write_bytes(b'{"owner_job_id":')
        with patch("ff_job_store._IDEM_BUSY_TIMEOUT_SECONDS", 0.2):
            again, replayed = _submit(self.store, kind="filing.acquire", request=_FETCH_REQUEST)
        self.assertTrue(replayed)
        self.assertEqual(first["owner_job_id"], again["owner_job_id"])
        self.assertEqual(list(self.store.iter_job_ids()), [first["owner_job_id"]])

    def test_contested_submit_cannot_steal_a_live_claim_by_age(self) -> None:
        from ff_job_store import _atomic_write_json

        paused, resume = Event(), Event()

        def delayed_write(path, value):
            if path.parent == self.store.jobs and not paused.is_set():
                paused.set()
                if not resume.wait(10):
                    raise TimeoutError("test writer did not resume")
            _atomic_write_json(path, value)

        with patch("ff_job_store._atomic_write_json", side_effect=delayed_write):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(
                    _submit, self.store, kind="filing.acquire", request=_FETCH_REQUEST,
                )
                try:
                    self.assertTrue(paused.wait(5))
                    pointer = self.store._idem_path("k-1")
                    stale = time.time() - 3600
                    os.utime(pointer, (stale, stale))
                    second = pool.submit(
                        _submit, self.store, kind="filing.acquire", request=_FETCH_REQUEST,
                    )
                    try:
                        second.result(timeout=1)
                    except TimeoutError:
                        pass
                finally:
                    resume.set()
                first_record, first_replay = first.result(timeout=5)
                second_record, second_replay = second.result(timeout=5)
        self.assertFalse(first_replay)
        self.assertTrue(second_replay)
        self.assertEqual(first_record["owner_job_id"], second_record["owner_job_id"])
        self.assertEqual(list(self.store.iter_job_ids()), [first_record["owner_job_id"]])


class RunTests(unittest.TestCase):
    """G-m8-FF-01: the bounded engine runs one queued job to a terminal state."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.store = JobStore(Path(self._tmp.name) / "jobs")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _enqueue(self, request: dict | None = None, kind: str = "filing.acquire",
                 key: str = "k-1") -> dict:
        record, _ = _submit(self.store, kind=kind, request=request or _FILING_REQUEST, key=key)
        return record

    def test_filing_success_lands_terminal_view(self) -> None:
        record = self._enqueue()
        envelope = {
            "schema_version": "2.0",
            "status": "source_candidate",
            "filing": {"status": "source_candidate"},
            "resolution_outcome": "reused_existing",
            "download_events": 0,
            "source_ref": _CANDIDATE_HANDLE["source_ref"],
            "calls": 2,
            "downloads": 0,
            "acquisition_observation": _observation(),
        }
        with patch("fetch_filing.resolve_filing", return_value=dict(_CANDIDATE_HANDLE)), \
                patch("ff_v2_envelope.success_envelope", return_value=envelope):
            final, executed = run_job(self.store, record["owner_job_id"], config_path=None,
                                      timeout_seconds=60)
        self.assertTrue(executed)
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(final["execution_count"], 1)
        self.assertEqual(final["result"]["resolution_outcome"], "reused_existing")
        view = build_job_view(final)
        for field in ("owner_job_id", "status", "status_known", "allowed_actions", "cost",
                      "cost_state", "recovery_capability", "error", "command_id", "owner"):
            self.assertIn(field, view)
        self.assertEqual(view["owner"], "filing-fetch")
        self.assertEqual(view["recovery_capability"], "durable_owner_job")
        self.assertEqual(view["allowed_actions"], [])

    def test_running_job_reports_no_actions(self) -> None:
        record = self._enqueue()
        with patch("fetch_filing.resolve_filing") as engine:
            engine.side_effect = lambda **kwargs: self._probe_actions(record["owner_job_id"])
            run_job(self.store, record["owner_job_id"], config_path=None, timeout_seconds=60)

    def _probe_actions(self, owner_job_id: str) -> dict:
        record = self.store.load(owner_job_id)
        self.assertEqual(record["status"], "running")
        self.assertEqual(record["attempts"], 1)
        return dict(_CANDIDATE_HANDLE)


def test_job_uses_one_deadline_for_filing_and_companion() -> None:
    from ff_job_runner import _run_filing_engine

    request = dict(_FILING_REQUEST, companion_transcript={"fiscal_year": 2025, "fiscal_quarter": 4})
    with patch("fetch_filing.resolve_filing", return_value=dict(_CANDIDATE_HANDLE)) as filing:
        with patch("fetch_filing._resolve_v2_companion",
                   return_value={"status": "not_requested", "retryable": False}) as companion:
            _run_filing_engine(
                request, config_path=None, timeout_seconds=10, stats={"calls": 0, "downloads": 0},
            )
    assert filing.call_args.kwargs.get("deadline") == companion.call_args.kwargs["deadline"]


class ActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.store = JobStore(Path(self._tmp.name) / "jobs")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cancel_queued_lands_cancelled(self) -> None:
        record, _ = _submit(self.store, kind="filing.acquire", request=dict(_FETCH_REQUEST))
        final, replayed = act(self.store, record["owner_job_id"], action="cancel",
                              idempotency_key="act-1")
        self.assertFalse(replayed)
        self.assertEqual(final["status"], "cancelled")
        self.assertEqual(final["cost_state"], "known")
        self.assertEqual(final["cost"]["value"], "0.00")
        self.assertEqual(allowed_actions_for(final), ["retry"])

    def test_cancel_is_replayable_by_receipt(self) -> None:
        record, _ = _submit(self.store, kind="filing.acquire", request=_FILING_REQUEST)
        act(self.store, record["owner_job_id"], action="cancel", idempotency_key="act-1")
        final, replayed = act(self.store, record["owner_job_id"], action="cancel",
                              idempotency_key="act-1")
        self.assertTrue(replayed)
        self.assertEqual(final["status"], "cancelled")

    def test_cancel_refused_on_terminal_and_unknown(self) -> None:
        record, _ = _submit(self.store, kind="filing.acquire", request=_FILING_REQUEST)
        act(self.store, record["owner_job_id"], action="cancel", idempotency_key="a")
        with self.assertRaises(FFJobError):
            act(self.store, record["owner_job_id"], action="cancel", idempotency_key="b")

    def test_retry_after_zero_spend_failure_then_run(self) -> None:
        record, _ = _submit(self.store, kind="filing.acquire", request=dict(_FETCH_REQUEST))
        with patch("fetch_filing.resolve_filing") as engine, patch(
            "ff_v2_envelope.success_envelope", return_value={},
        ):
            engine.side_effect = FilingFetchError("missing", code="not_found")
            run_job(self.store, record["owner_job_id"], config_path=None, timeout_seconds=60)
        final, _ = act(self.store, record["owner_job_id"], action="retry",
                       idempotency_key="r-1")
        self.assertEqual(final["status"], "queued")
        self.assertEqual(final["error"], None)
        self.assertEqual(allowed_actions_for(final), ["cancel"])
        envelope = {"schema_version": "2.0", "status": "source_candidate",
                    "source_ref": _CANDIDATE_HANDLE["source_ref"], "calls": 1, "downloads": 0}
        with patch("fetch_filing.resolve_filing", return_value=dict(_CANDIDATE_HANDLE)), \
                patch("ff_v2_envelope.success_envelope", return_value=envelope):
            final, _ = run_job(self.store, record["owner_job_id"], config_path=None,
                               timeout_seconds=60)
        self.assertEqual(final["status"], "succeeded")
        self.assertEqual(final["attempts"], 2)

    def test_retry_refused_without_zero_spend_evidence(self) -> None:
        record, _ = _submit(self.store, kind="filing.acquire", request=dict(_FETCH_REQUEST))
        with patch("fetch_filing.resolve_filing") as engine, patch(
            "ff_v2_envelope.success_envelope", return_value={},
        ):
            engine.side_effect = FilingFetchError(
                "provider failed", code="upstream_error",
                acquisition_observation=_observation(provider_started=True,
                                                     usage_complete=True),
            )
            run_job(self.store, record["owner_job_id"], config_path=None, timeout_seconds=60)
        with self.assertRaises(FFJobError):
            act(self.store, record["owner_job_id"], action="retry", idempotency_key="r-1")


class UnknownReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.store = JobStore(Path(self._tmp.name) / "jobs")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _crashed_fetch_job(self) -> dict:
        record, _ = _submit(self.store, kind="filing.acquire", request=dict(_FETCH_REQUEST))
        with patch("fetch_filing.resolve_filing") as engine:
            # Simulate the run process dying mid-engine: the running record is
            # written, then the process vanishes (dead pid) with no receipt.
            def die(**kwargs):
                stored = self.store.load(record["owner_job_id"])
                self.assertEqual(stored["status"], "running")
                stored["owner_pid"] = DEAD_PID
                self.store.write_locked(stored)
                raise SystemExit(9)
            engine.side_effect = die
            with self.assertRaises(SystemExit):
                run_job(self.store, record["owner_job_id"], config_path=None, timeout_seconds=60)
        return record

    def test_dead_pid_runner_flips_to_unknown(self) -> None:
        record = self._crashed_fetch_job()
        final, _ = self.store.load_checked(record["owner_job_id"], fix=True)
        self.assertEqual(final["status"], "unknown")
        self.assertFalse(final["status_known"])
        self.assertEqual(allowed_actions_for(final), ["reconcile"])
        self.assertEqual(final["cost_state"], "unknown")

    def test_unknown_only_allows_reconcile_and_run_refused(self) -> None:
        record = self._crashed_fetch_job()
        with self.assertRaises(FFJobError):
            act(self.store, record["owner_job_id"], action="cancel", idempotency_key="x")
        with self.assertRaises(FFJobError):
            run_job(self.store, record["owner_job_id"], config_path=None, timeout_seconds=60)

    def test_reconcile_lands_succeeded_without_reacquisition(self) -> None:
        record = self._crashed_fetch_job()
        envelope = {
            "schema_version": "2.0", "status": "source_candidate",
            "filing": {"status": "source_candidate"}, "resolution_outcome": "reused_existing",
            "download_events": 0, "source_ref": _CANDIDATE_HANDLE["source_ref"],
            "calls": 2, "downloads": 0,
        }
        seen = {}

        def engine(**kwargs):
            seen["request"] = kwargs["request"]
            seen["stats"] = kwargs["stats"]
            return dict(_CANDIDATE_HANDLE)

        with patch("fetch_filing.resolve_filing", side_effect=engine), patch(
            "ff_v2_envelope.success_envelope", return_value=envelope,
        ):
            final, replayed = reconcile(self.store, record["owner_job_id"],
                                        idempotency_key="rec-1", config_path=None,
                                        timeout_seconds=60)
        self.assertFalse(replayed)
        self.assertEqual(final["status"], "succeeded")
        self.assertTrue(final["status_known"])
        self.assertEqual(final["derived_by"], "reconcile_read_only")
        # The read-only query stripped the download intent and its limits.
        self.assertEqual(seen["request"]["filing_intent"], "reuse_only")
        self.assertNotIn("acquisition_limits", seen["request"])
        self.assertEqual(seen["stats"]["downloads"], 0)
        # Cost stays unknown: the interrupted run's spend cannot be certified.
        self.assertEqual(final["cost_state"], "unknown")

    def test_reconcile_replay_is_idempotent(self) -> None:
        record = self._crashed_fetch_job()
        envelope = {"schema_version": "2.0", "status": "source_candidate",
                    "source_ref": _CANDIDATE_HANDLE["source_ref"], "calls": 1, "downloads": 0}
        with patch("fetch_filing.resolve_filing", return_value=dict(_CANDIDATE_HANDLE)), patch(
            "ff_v2_envelope.success_envelope", return_value=envelope,
        ):
            first, _ = reconcile(self.store, record["owner_job_id"], idempotency_key="rec-1",
                                 config_path=None, timeout_seconds=60)
            second, replayed = reconcile(self.store, record["owner_job_id"],
                                         idempotency_key="rec-1", config_path=None,
                                         timeout_seconds=60)
        self.assertTrue(replayed)
        self.assertEqual(first["owner_job_id"], second["owner_job_id"])
        self.assertEqual(first["updated_at"], second["updated_at"])

    def test_reconcile_query_absence_lands_failed(self) -> None:
        record = self._crashed_fetch_job()
        envelope = {
            "schema_version": "2.0", "status": "gap", "filing": {"status": "gap",
                                                                 "reason": "metadata_only"},
            "download_events": 0, "calls": 2, "downloads": 0,
        }
        with patch("fetch_filing.resolve_filing", return_value={}), patch(
            "ff_v2_envelope.success_envelope", return_value=envelope,
        ):
            final, _ = reconcile(self.store, record["owner_job_id"], idempotency_key="rec-2",
                                 config_path=None, timeout_seconds=60)
        self.assertEqual(final["status"], "failed")
        self.assertEqual(final["error"]["code"], "not_found")
        self.assertTrue(final["status_known"])

    def test_reconcile_refused_on_terminal(self) -> None:
        record, _ = _submit(self.store, kind="filing.acquire", request=_FILING_REQUEST)
        act(self.store, record["owner_job_id"], action="cancel", idempotency_key="a")
        with self.assertRaises(FFJobError):
            reconcile(self.store, record["owner_job_id"], idempotency_key="r",
                      config_path=None, timeout_seconds=60)


class DeadlineStalenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.store = JobStore(Path(self._tmp.name) / "jobs")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_expired_deadline_with_live_pid_marks_unknown(self) -> None:
        record, _ = _submit(self.store, kind="filing.acquire", request=dict(_FETCH_REQUEST))
        record["status"] = "running"
        record["owner_pid"] = os.getpid()  # alive, but its deadline has passed
        record["run_deadline_at"] = "2000-01-01T00:00:00.000Z"
        self.store.write_locked(record)
        final, _ = self.store.load_checked(record["owner_job_id"], fix=True)
        self.assertEqual(final["status"], "unknown")
        self.assertEqual(allowed_actions_for(final), ["reconcile"])

    def test_within_budget_runner_stays_running(self) -> None:
        from ff_job_runner import _iso_deadline

        record, _ = _submit(self.store, kind="filing.acquire", request=_FILING_REQUEST)
        record["status"] = "running"
        record["owner_pid"] = os.getpid()
        record["run_deadline_at"] = _iso_deadline(3600)
        self.store.write_locked(record)
        final, _ = self.store.load_checked(record["owner_job_id"], fix=True)
        self.assertEqual(final["status"], "running")
        self.assertTrue(final["status_known"])


class ProjectionUnitTests(unittest.TestCase):
    """G-m8-FF-02/03: the retry guard and the pathless result projection."""

    def test_retry_eligibility(self) -> None:
        never_ran = {"attempts": 0, "spend_evidence": {"provider_started": None}}
        self.assertTrue(retry_eligible(never_ran))
        provably_free = {"attempts": 1, "spend_evidence": {"provider_started": False,
                                                           "download_events": 0}}
        self.assertTrue(retry_eligible(provably_free))
        uncertified = {"attempts": 1, "spend_evidence": {"provider_started": True,
                                                         "download_events": 0}}
        self.assertFalse(retry_eligible(uncertified))
        absent = {"attempts": 1, "spend_evidence": {"provider_started": None,
                                                    "download_events": None}}
        self.assertFalse(retry_eligible(absent))

    def test_result_view_drops_unknown_fields_and_rejects_nested_leak(self) -> None:
        envelope = {
            "status": "source_candidate", "source_ref": {"schema_version": "2.0"},
            "canonical_path": str(SKILL_ROOT / "fixtures" / "leak.pdf"), "resolution_outcome": "downloaded_new",
            "download_events": 1, "calls": 3, "downloads": 1,
        }
        # The closed whitelist is the primary guard: an unknown field can
        # never reach the projection.
        result = build_result_view("filing.acquire", envelope, {"calls": 3, "downloads": 1})
        self.assertNotIn("canonical_path", result)
        self.assertEqual(result["download_events"], 1)
        # Defence in depth: a physical field nested inside a whitelisted
        # field fails the projection instead of leaking.
        leaky = dict(envelope, source_ref={
            "schema_version": "2.0", "canonical_path": str(SKILL_ROOT / "fixtures" / "x.pdf"),
        })
        with self.assertRaises(FFJobError):
            build_result_view("filing.acquire", leaky, {"calls": 3, "downloads": 1})

    def test_filing_result_reads_the_nested_filing_block(self) -> None:
        """The v2 envelope keeps the filing facts in envelope['filing']."""
        envelope = {
            "schema_version": "2.0",
            "status": "source_candidate",
            "filing": {
                "status": "source_candidate",
                "resolution_outcome": "reused_existing",
                "download_events": 0,
                "source_ref": {"schema_version": "2.0", "document_id": "doc-1"},
            },
            "calls": 2,
            "downloads": 0,
        }
        result = build_result_view("filing.acquire", envelope, {"calls": 2, "downloads": 0})
        self.assertEqual(result["status"], "source_candidate")
        self.assertEqual(result["resolution_outcome"], "reused_existing")
        self.assertEqual(result["download_events"], 0)
        self.assertEqual(result["source_ref"]["document_id"], "doc-1")
        self.assertEqual(result["calls"], 2)

    def test_statements_result_reads_the_nested_usage_block(self) -> None:
        envelope = {
            "schema_version": "financial-statements-response/1",
            "status": "complete",
            "statements": [{"a": 1}, {"b": 2}],
            "usage": {"http_requests": 3, "response_bytes": 10, "cost_usd": "0.01"},
        }
        result = build_result_view("statements.acquire", envelope, {"calls": 1, "downloads": 0})
        self.assertEqual(result["statement_count"], 2)
        self.assertEqual(result["usage"], {"http_requests": 3, "response_bytes": 10,
                                           "cost_usd": "0.01"})
        self.assertEqual(result["calls"], 1)
        self.assertNotIn("statements", result)


class ListJobsTests(unittest.TestCase):
    """G-m8-FF-02: the real list_jobs CLI path (in-process main()), bounded."""

    def test_pagination_is_bounded_ordered_and_pageinfo_shaped(self) -> None:
        with TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs")
            ids = []
            for index in range(5):
                record, _ = _submit(store, kind="filing.acquire", request=_FILING_REQUEST,
                                    key=f"k-{index}")
                ids.append(record["owner_job_id"])
            ordered = sorted(ids)
            page1 = self._list(store, limit="2")
            page2 = self._list(store, limit="2", cursor=page1["page"]["next_cursor"])
            page3 = self._list(store, limit="2", cursor=page2["page"]["next_cursor"])
            self.assertTrue(len(page1["items"]) == 2)
            self.assertEqual([item["owner_job_id"] for item in page1["items"]], ordered[:2])
            self.assertEqual([item["owner_job_id"] for item in page2["items"]], ordered[2:4])
            self.assertEqual([item["owner_job_id"] for item in page3["items"]], ordered[4:])
            self.assertIsNotNone(page1["page"]["next_cursor"])
            self.assertIsNone(page3["page"]["next_cursor"])
            for page in (page1, page2, page3):
                self.assertEqual(page["page"]["total"], 5)
                self.assertEqual(page["page"]["total_status"], "exact")
                self.assertTrue(page["page"]["snapshot_id"].startswith("ffjobs-"))
            # Same store contents -> same snapshot id.
            self.assertEqual(page1["page"]["snapshot_id"], page3["page"]["snapshot_id"])

    @staticmethod
    def _list(store: JobStore, *, limit: str, cursor: str | None = None) -> dict:
        """Drive the real CLI handler through the real parser (no re-implementation)."""
        import ff_job

        argv = ["--jobs-dir", str(store.jobs_dir), "list_jobs", "--limit", limit]
        if cursor is not None:
            argv.extend(("--cursor", cursor))
        ff_job.build_parser().parse_args(argv)  # argv shape check
        buffer = StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = ff_job.main(argv)
        assert exit_code == 0
        return json.loads(buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
