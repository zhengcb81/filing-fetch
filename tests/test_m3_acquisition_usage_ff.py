"""M3-USAGE FF projection: faithful pass-through of acquisition-observation/1.

FF validates the producer sibling once and copies it verbatim — no recount, no
inferred fee, no MIME/identity re-verification. Any malformed observation is
dropped whole and never erases the independent cause/receipt channels. v1
output stays frozen; the sibling rides the v2 envelope top level (like calls/downloads).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_filing as fetch  # noqa: E402
import ff_provider_cause as cause  # noqa: E402
import ff_v2_envelope as envelope  # noqa: E402


def observation(**overrides):
    value = {
        "schema_version": "acquisition-observation/1",
        "usage_scope": "operation",
        "outcome": "downloaded_new",
        "provider_started": True,
        "usage_complete": True,
        "wire_body_bytes": 2841,
        "wire_usage_complete": True,
        "entity_body_bytes": 8192,
        "http_exchanges": 3,
        "http_exchanges_complete": True,
        "cost_usd": "0.0004",
        "http_observation": {"status_code": 200, "mime_type": "application/pdf",
                             "content_encoding": "gzip", "wire_content_length": 2841},
    }
    value.update(overrides)
    return value


def diagnostic():
    return {"schema_version": "acquisition-failure/1", "code": "upstream_unavailable",
            "retryable": False, "provider_started": True, "usage_complete": True,
            "usage_scope": "operation",
            "acquisition_usage": {"schema_version": "1.0", "response_bytes": 17, "cost_usd": "0.03"}}


def gap_payload(dto, obs):
    return {"operation_schema_version": "1.0", "operation": "ensure", "status": "gap",
            "request_id": "synthetic-one", "outcome": "gap", "download_events": 0,
            "policy_hash": None, "source_ref": None, "candidate": None,
            "gap_plan": {"schema_version": "1.0", "request_id": "synthetic-one",
                         "gap_hash": "a" * 64},
            "acquisition_failure": dto, "acquisition_observation": obs}


SHA = "b" * 64


def completed_payload(obs):
    ref = {"schema_version": "2.0",
           "document_id": f"urn:company-wiki:document:sha256:{SHA}",
           "source_id": f"urn:company-wiki:source:sha256:{SHA}",
           "content_sha256": SHA, "byte_size": 8192, "mime_type": "application/pdf"}
    return {"operation_schema_version": "1.0", "operation": "ensure", "status": "completed",
            "request_id": "synthetic-one", "outcome": "downloaded_new", "download_events": 1,
            "policy_hash": None, "source_ref": ref, "gap_plan": None,
            "candidate": {"request_id": "synthetic-one", "document_id": ref["document_id"],
                          "source_id": ref["source_id"], "snapshot_sha256": SHA,
                          "source_ref": ref,
                          "byte_size": 8192, "mime_type": "application/pdf",
                          "document_kind": "annual_report", "fiscal_year": 2025,
                          "fiscal_period": "FY", "published_date": "2026-03-20",
                          "title": "Fixture Annual Report"},
            "acquisition_observation": obs}


REQUEST = {"document_kind": "annual_report", "fiscal_year": 2025, "as_of_date": "2026-10-10",
           "company_query": "Fixture", "market": "US"}
IDENTITY = {"market": "US", "security_id": "FIXTURE"}


class TestValidatedObservation:
    def test_passes_producer_values_verbatim(self):
        published = observation()
        assert cause.validated_acquisition_observation(published) == published

    def test_absent_value_stays_absent(self):
        assert cause.validated_acquisition_observation(None) is None

    @pytest.mark.parametrize("mutate", [
        lambda v: v.pop("cost_usd"),
        lambda v: v.update(extra=1),
        lambda v: v.update(schema_version="acquisition-observation/2"),
        lambda v: v.update(usage_scope="invocation"),
        lambda v: v.update(outcome="invented"),
        lambda v: v.update(wire_body_bytes=-3),
        lambda v: v.update(http_exchanges=True),
        lambda v: v.update(cost_usd="NaN"),
        lambda v: v.update(cost_usd=0.01),
        lambda v: v.update(http_observation={"status_code": 200, "authorization": "Bearer secret"}),
    ])
    def test_any_deviation_drops_the_whole_object(self, mutate):
        value = observation()
        mutate(value)
        assert cause.validated_acquisition_observation(value) is None

    def test_null_cost_is_unknown_not_zero(self):
        assert cause.validated_acquisition_observation(
            observation(cost_usd=None))["cost_usd"] is None


class TestEnvelopeProjection:
    def test_gap_envelope_keeps_observation_alongside_receipt(self):
        dto, obs = diagnostic(), observation(outcome="gap_plan")
        handle = fetch._pathless_operation_gap(gap_payload(dto, obs), operation="ensure")
        assert handle["acquisition_observation"] == obs
        result = envelope.success_envelope({}, handle, {"status": "not_applicable"},
                                           {"calls": 2, "downloads": 0})
        assert result["acquisition_observation"] == obs
        assert result["filing"]["acquisition_failure"] == dto

    def test_source_candidate_envelope_keeps_observation(self):
        obs = observation()
        handle = fetch._pathless_operation_handle(
            completed_payload(obs), operation="ensure", request=REQUEST,
            company_identity=IDENTITY, stats={"calls": 0, "downloads": 0})
        assert handle["acquisition_observation"] == obs
        result = envelope.success_envelope(REQUEST, handle, {"status": "not_requested"},
                                           {"calls": 2, "downloads": 1})
        assert result["acquisition_observation"] == obs
        assert result["filing"]["download_events"] == 1

    def test_absent_observation_adds_no_key(self):
        handle = fetch._pathless_operation_handle(
            completed_payload(None), operation="ensure", request=REQUEST,
            company_identity=IDENTITY, stats={"calls": 0, "downloads": 0})
        result = envelope.success_envelope(REQUEST, handle, {"status": "not_requested"},
                                           {"calls": 2, "downloads": 1})
        assert "acquisition_observation" not in result

    def test_error_envelope_keeps_observation(self):
        obs = observation(outcome="failed")
        error = fetch.FilingFetchError("safe fixed text", code="fatal", stage="ensure",
                                       attempts=1, acquisition_observation=obs)
        assert error.acquisition_observation == obs
        result = envelope.error_envelope(error.code, str(error), retryable=error.retryable,
            stats={"calls": 1, "downloads": 0}, stage=error.stage, attempts=error.attempts,
            acquisition_observation=error.acquisition_observation)
        assert result["acquisition_observation"] == obs

    def test_malformed_observation_never_rides_the_envelope(self):
        obs = observation(cost_usd="Infinity")
        handle = fetch._pathless_operation_gap(gap_payload(None, obs), operation="ensure")
        assert "acquisition_observation" not in handle
        result = envelope.success_envelope({}, handle, {"status": "not_applicable"},
                                           {"calls": 2, "downloads": 0})
        assert "acquisition_observation" not in result

    def test_invalid_observation_on_error_is_dropped_not_raised(self):
        error = fetch.FilingFetchError("safe fixed text", code="fatal",
                                       acquisition_observation={"schema_version": "x"})
        assert error.acquisition_observation is None


class TestActualChildChannel:
    def test_child_failure_keeps_observation_without_replay(self, tmp_path):
        dto, obs = diagnostic(), observation(outcome="failed")
        output = {"status": "failed", "error_type": "fatal",
                  "error": "https://invalid/?api_key=synthetic-m3-secret",
                  "acquisition_failure": dto, "acquisition_observation": obs}
        marker = tmp_path / "attempts.txt"
        script = tmp_path / "producer.py"
        script.write_text(
            "import sys\nfrom pathlib import Path\n"
            "p=Path(" + repr(str(marker)) + ")\n"
            "p.write_text(p.read_text()+'x' if p.exists() else 'x')\n"
            "sys.stderr.write(" + repr(json.dumps(output)) + ")\nraise SystemExit(1)\n",
            encoding="utf-8")
        stats = {"calls": 0, "downloads": 0}
        with pytest.raises(fetch.FilingFetchError) as caught:
            fetch._run_company_wiki_json_retry(
                command=[sys.executable, "-B", str(script)], root=tmp_path,
                action="ensure", deadline=time.monotonic() + 10, stats=stats)
        error = caught.value
        assert error.acquisition_observation == obs
        assert error.acquisition_failure == dto
        assert stats == {"calls": 1, "downloads": 0} and marker.read_text() == "x"
        assert "synthetic-m3-secret" not in str(error)
        assert "synthetic-m3-secret" not in json.dumps(error.acquisition_observation)

    def test_child_malformed_observation_keeps_independent_receipt(self, tmp_path):
        dto = diagnostic()
        output = {"status": "failed", "error_type": "fatal", "error": "safe text",
                  "acquisition_failure": dto,
                  "acquisition_observation": observation(http_exchanges="three")}
        script = tmp_path / "producer.py"
        script.write_text(
            "import sys\nsys.stderr.write(" + repr(json.dumps(output)) + ")\nraise SystemExit(1)\n",
            encoding="utf-8")
        stats = {"calls": 0, "downloads": 0}
        with pytest.raises(fetch.FilingFetchError) as caught:
            fetch._run_company_wiki_json_retry(
                command=[sys.executable, "-B", str(script)], root=tmp_path,
                action="ensure", deadline=time.monotonic() + 10, stats=stats)
        error = caught.value
        assert error.acquisition_observation is None
        assert error.acquisition_failure == dto
