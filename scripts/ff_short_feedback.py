"""Project short filing outcomes, native usage evidence and named refusals.

The native outbox and its optional caller-owned JSONL share an occurrence identity.
External document providers inherit their own delivery configuration; short requests
never refer to a durable ff-job/1 or invent spend from the download count.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import uuid
from typing import Any

from ff_runtime_feedback import ATTEMPT_ENV, OUT_ENV, RULE_CODES, RUN_ENV, cause_details, publish
from ff_direct_run import DirectRun, SHORT
from ff_run_input import replay_input
from ff_local_preparation_observation import validated_local_preparation_observation
from ff_provider_cause import (
    validated_acquisition_failure,
    validated_acquisition_observation,
    validated_cause,
    validated_request_diagnostic,
)

SCHEMA_VERSION = "feedback-observation/1"
OWNER = "filing-fetch"

# The start row names its terminal check so a reader pairs the two without
# guessing which check ends this scope.
START_CHECK = "action-started"
OUTCOME_CHECK = "request-outcome"
PROVIDER_START_CHECK = "provider-start"
USAGE_CHECK = "provider-usage"
DOWNLOAD_CHECK = "download-receipt"
TRANSCRIPT_USAGE_CHECK = "transcript-provider-usage"

DISPOSITIONS = frozenset({"expected", "deviation", "unknown"})

# Catalog operations that cannot contact an acquisition provider. The durable
# job owner already projects these phases as a proven no-provider operation;
# the short lane keeps the same owner statement and still prefers any explicit
# producer evidence over it.
_NO_PROVIDER_OPERATIONS = frozenset({"identify", "query", "local_prepare", "resolve"})

# Transcript statuses decided before any provider call. A requested companion
# that never left the local catalog is a known zero for its own scope.
_TRANSCRIPT_NO_PROVIDER = frozenset({
    "not_requested", "not_applicable", "not_run", "period_unresolved",
    "request_error", "reused", "unknown_publication", "contract_pending",
    "ambiguous",
})

# The FF-owned rule signature used when a reuse-only call is observed to have
# started a provider. It is emitted only with evidence, never pre-emptively.
_REUSE_STARTED_PROVIDER = "reuse-started-provider"


@dataclass
class _Facts:
    """Business and metering facts already present on the public paths."""

    status: str = "unknown"
    outcome: str | None = None
    reason: str | None = None
    calls: int | None = None
    downloads: int | None = None
    observation: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
    cause: dict[str, Any] | None = None
    local: dict[str, Any] | None = None
    transcript: dict[str, Any] | None = None


class ShortObservation:
    """Append-only writer for one process-exclusive sidecar."""

    def __init__(
        self, path: Path | None, *, run_id: str, attempt_id: str, operation_id: str,
        jobs_dir: Path | None = None, diagnostics=None,
    ) -> None:
        self._path = path
        self._start_rows: list[dict] = []
        self._jobs_dir = jobs_dir
        self._diagnostics = diagnostics
        self._run = DirectRun(SHORT, run_id=run_id, attempt_id=attempt_id,
                              operation_id=operation_id, jobs_dir=jobs_dir, diagnostics=diagnostics, labels={})

    def started(self) -> None:
        """Write the start row before any business work runs."""
        self._start_rows = [self._run.start_row]
        publish(self._start_rows, file=self._path, jobs_dir=self._jobs_dir, diagnostics=self._diagnostics)

    def request_read(self, raw: bytes, request: Any, request_file: Path | None) -> None:
        self._run.mark("request_read", request_sha256=hashlib.sha256(raw).hexdigest(),
                       input=replay_input(request, request_file=request_file))

    def dispatching(self) -> None:
        self._run.mark("dispatching", external_effect="possible", cost_state="unknown")

    def finished(
        self,
        *,
        output: Any,
        error: BaseException | None = None,
        stats: dict[str, int] | None = None,
        request: dict[str, Any] | None = None,
        allow_download: bool | None = None,
        exit_code: int = 0,
    ) -> None:
        """Write the terminal rows; an observation bug never breaks business."""
        try:
            rows = observation_rows(
                output=output, error=error, stats=stats, request=request,
                allow_download=allow_download, identity=self._identity(),
            )
            reason = rows[0]["actual"]
            detail = cause_details(error, reason=reason) if error is not None else None
            checks = {row["check_id"]: row["actual"] for row in rows}
            cost = "known" if checks.get(USAGE_CHECK) == "known" and checks.get(
                TRANSCRIPT_USAGE_CHECK
            ) != "unknown" else "unknown"
            effect = self._run.external_effect
            if effect == "possible" and error is None:
                effect = "response_received"
            if effect == "not_started":
                cost = "not_applicable"
            self._run.finish(
                outcome={"status": reason, "exit_code": exit_code, "diagnostic": detail, "checks": checks},
                effect=effect, cost=cost, rows=rows, start=self._start_rows, file=self._path,
            )
        except Exception:  # noqa: BLE001 - diagnostics must never change the result
            return

    def _identity(self) -> dict[str, str]:
        return self._run.base

def begin_observation(*, jobs_dir: Path | None = None, diagnostics=None) -> ShortObservation:
    """Claim the parent sidecar if supplied; standalone execution uses the native outbox."""
    path = os.environ.get(OUT_ENV)
    run_id = (os.environ.get(RUN_ENV) or "").strip()
    attempt_id = (os.environ.get(ATTEMPT_ENV) or "").strip()
    operation_id = diagnostics.occurrence if diagnostics else uuid.uuid4().hex
    observation = ShortObservation(
        Path(path) if path else None,
        run_id=run_id or operation_id,
        attempt_id=attempt_id or "1",
        operation_id=operation_id,
        jobs_dir=jobs_dir, diagnostics=diagnostics,
    )
    observation.started()
    return observation


def observation_rows(
    *,
    output: Any,
    error: BaseException | None = None,
    stats: dict[str, int] | None = None,
    request: dict[str, Any] | None = None,
    allow_download: bool | None = None,
    identity: dict[str, str],
) -> list[dict[str, Any]]:
    """Project the existing public result into named checks.

    ``identity`` is copied into every row; the caller owns its stability.
    """
    facts = _facts(output, error, stats)
    intent = _spend_intent(request, allow_download)
    base = _base_row(identity)

    token = _outcome_token(facts)
    reason = facts.reason or _named_failure_code(facts)
    status = facts.status
    if status == "unknown":
        disposition = "unknown"
    elif reason in RULE_CODES or status in {"capture_ready", "source_candidate", "gap", "not_found", "ambiguous"}:
        disposition = "expected"
    else:
        disposition = "deviation"
    metadata = {"refusal_code": reason} if reason in RULE_CODES or (status == "request_error" and facts.reason) else {}
    if disposition == "deviation":
        metadata["issue_key"] = reason or status
    rows = [_check(base, OUTCOME_CHECK, "terminal", token, disposition, **metadata)]

    start_expected = _start_expectation(intent, facts)
    if start_expected is not None:
        started = _start_state(intent, facts)
        disposition = _start_disposition(started)
        extra = {"issue_key": _REUSE_STARTED_PROVIDER} if disposition == "deviation" else {}
        rows.append(_check(base, PROVIDER_START_CHECK, start_expected, started,
                           disposition, **extra))

    usage = _usage_state(intent, facts)
    rows.append(_check(base, USAGE_CHECK, "accounted", usage,
                       "unknown" if usage == "unknown" else "expected"))

    downloads = _download_token(facts)
    rows.append(_check(base, DOWNLOAD_CHECK, "accounted", downloads,
                       "unknown" if downloads == "unknown" else "expected"))

    if isinstance(request, dict) and isinstance(request.get("companion_transcript"), dict):
        transcript_usage = _transcript_usage(facts.transcript, facts)
        rows.append(_check(
            {**base, "step_id": f"{base['step_id']}/transcript", "parent_step_id": base["step_id"]},
            TRANSCRIPT_USAGE_CHECK, "accounted", transcript_usage,
            "unknown" if transcript_usage == "unknown" else "expected",
        ))
    return rows


def _base_row(identity: dict[str, str]) -> dict[str, str]:
    base = {
        "schema_version": identity["schema_version"],
        "owner": identity["owner"],
        "run_id": identity["run_id"],
        "attempt_id": identity["attempt_id"],
        "step_id": identity["step_id"],
        "evidence_ref": identity["evidence_ref"],
    }
    if "version" in identity:
        base["version"] = identity["version"]
    return base


def _check(
    base: dict[str, str], check_id: str, expected: str, actual: str,
    disposition: str, **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        **base,
        "check_id": check_id,
        "expected": expected,
        "actual": actual,
        "disposition": disposition,
    }
    row.update(extra)
    return row


def _facts(
    output: Any, error: BaseException | None, stats: dict[str, int] | None,
) -> _Facts:
    facts = _Facts()
    if isinstance(stats, dict) and type(stats.get("calls")) is int:
        facts.calls = stats["calls"]
    if isinstance(output, dict):
        status = output.get("status")
        if isinstance(status, str) and status:
            facts.status = status
        downloads = output.get("downloads")
        if type(downloads) is int and downloads in (0, 1):
            facts.downloads = downloads
        if output.get("schema_version") == "2.0":
            _v2_facts(facts, output)
        else:
            _v1_facts(facts, output)
    if facts.calls is None and isinstance(output, dict):
        calls = output.get("calls")
        if type(calls) is int:
            facts.calls = calls
    if facts.calls is None and stats is None and isinstance(output, dict):
        # The CLI creates its counter before the first producer can start, so
        # an absent counter on a produced envelope proves no dispatch.
        facts.calls = 0
    if error is not None:
        if facts.status == "unknown":
            code = getattr(error, "code", None)
            facts.status = code if isinstance(code, str) and code else "fatal"
        # A v1 envelope never serializes the operation observation; the typed
        # exception still carries the same validated objects.
        facts.observation = facts.observation or validated_acquisition_observation(
            getattr(error, "acquisition_observation", None)
        )
        facts.receipt = facts.receipt or validated_acquisition_failure(
            getattr(error, "acquisition_failure", None)
        )
        facts.cause = facts.cause or validated_cause(
            getattr(error, "upstream_cause", None)
        )
        facts.local = facts.local or validated_local_preparation_observation(
            getattr(error, "local_preparation_observation", None)
        )
    return facts


def _v2_facts(facts: _Facts, output: dict[str, Any]) -> None:
    filing = output.get("filing")
    filing = filing if isinstance(filing, dict) else {}
    if facts.downloads is None and type(filing.get("download_events")) is int:
        facts.downloads = filing["download_events"]
    if output.get("status") == "source_candidate":
        outcome = filing.get("resolution_outcome")
        if isinstance(outcome, str) and outcome:
            facts.outcome = outcome
    facts.observation = validated_acquisition_observation(
        output.get("acquisition_observation")
    )
    facts.receipt = validated_acquisition_failure(filing.get("acquisition_failure"))
    facts.cause = validated_cause(filing.get("upstream_cause"))
    facts.local = validated_local_preparation_observation(
        output.get("local_preparation_observation")
    )
    diagnostic = validated_request_diagnostic(filing.get("request_diagnostic"))
    if diagnostic is not None:
        facts.reason = diagnostic["reason"]
    transcript = output.get("transcript")
    if isinstance(transcript, dict):
        facts.transcript = transcript


def _v1_facts(facts: _Facts, output: dict[str, Any]) -> None:
    status = output.get("status")
    if status == "capture_ready":
        handle = output.get("handle")
        handle = handle if isinstance(handle, dict) else {}
        envelope = handle.get("resolution_envelope")
        envelope = envelope if isinstance(envelope, dict) else {}
        outcome = envelope.get("outcome")
        if isinstance(outcome, str) and outcome:
            facts.outcome = outcome
        events = envelope.get("download_events")
        if facts.downloads is None and type(events) is int and events in (0, 1):
            facts.downloads = events
        facts.observation = validated_acquisition_observation(
            handle.get("acquisition_observation")
        )
        return
    if status == "gap":
        facts.outcome = "gap"
        # The legacy gap envelope carries no download counter. The v1
        # compatibility rule is explicit: a missing field stays unknown, so
        # the gap contract is not turned into a synthetic zero here.
    facts.receipt = validated_acquisition_failure(output.get("acquisition_failure"))
    facts.cause = validated_cause(output.get("upstream_cause"))
    diagnostic = validated_request_diagnostic(output.get("request_diagnostic"))
    if diagnostic is not None:
        facts.reason = diagnostic["reason"]


def _spend_intent(
    request: dict[str, Any] | None, allow_download: bool | None,
) -> str | None:
    """One fee dimension per call, derived from the existing request contract.

    ``latest_as_of`` performs a bounded metadata lookup even for reuse_only, so
    it owns a provider dimension just like an acquiring request.
    """
    if not isinstance(request, dict):
        return None
    if allow_download is True or request.get("mode") == "latest_as_of":
        return "fetch_if_missing"
    intent = request.get("filing_intent")
    if isinstance(intent, str) and intent in {"reuse_only", "fetch_if_missing"}:
        return intent
    if allow_download is False:
        return "reuse_only"
    return None


def _usage_evidence(
    facts: _Facts,
) -> tuple[bool | None, bool | None, str | None]:
    """Read the validated producer values; never recount or infer a fee."""
    observation = facts.observation
    if isinstance(observation, dict):
        return (
            observation.get("provider_started"),
            observation.get("usage_complete"),
            observation.get("cost_usd"),
        )
    receipt = facts.receipt
    if isinstance(receipt, dict):
        usage = receipt.get("acquisition_usage")
        cost = usage.get("cost_usd") if isinstance(usage, dict) else None
        return receipt.get("provider_started"), receipt.get("usage_complete"), cost
    cause = facts.cause
    if isinstance(cause, dict):
        started = cause.get("provider_started")
        complete = cause.get("usage_complete")
        if (cause.get("operation") in _NO_PROVIDER_OPERATIONS
                and started is None and complete is None):
            return False, True, None
        return started, complete, None
    if facts.local is not None:
        return False, True, None
    return None, None, None


def _usage_state(intent: str | None, facts: _Facts) -> str:
    started, complete, cost = _usage_evidence(facts)
    if intent == "reuse_only" and started is not True:
        # Owner contract: the exact reuse route is read-only and has no fee
        # dimension. An explicit producer "started" still wins over this.
        return "not_applicable"
    if facts.calls == 0 and facts.status != "unknown":
        # No producer process was launched: no provider work could happen.
        return "known"
    if started is False and complete is True:
        return "known"
    if started is True and complete is True and isinstance(cost, str) and cost:
        return "known"
    return "unknown"


def _start_expectation(intent: str | None, facts: _Facts) -> str | None:
    """Only assert a start expectation when the contract makes it decidable."""
    if intent == "reuse_only":
        return "not_started"
    if facts.status == "request_error" and facts.calls == 0:
        return "not_started"
    return None


def _start_state(intent: str | None, facts: _Facts) -> str:
    started, _complete, _cost = _usage_evidence(facts)
    if started is True:
        return "started"
    if started is False:
        return "not_started"
    if intent == "reuse_only":
        # The exact reuse route is the read-only resolve/query command.
        return "not_started"
    if facts.calls == 0 and facts.status != "unknown":
        return "not_started"
    return "unknown"


def _start_disposition(actual: str) -> str:
    if actual == "unknown":
        return "unknown"
    return "expected" if actual == "not_started" else "deviation"


def _outcome_token(facts: _Facts) -> str:
    """A stable business word; a failure keeps its named reason.

    The reason comes from the closed request-diagnostic map or the closed
    producer cause/receipt vocabulary, never from error text.
    """
    if facts.status in {"capture_ready", "source_candidate"} and facts.outcome:
        return f"{facts.status}/{facts.outcome}"
    reason = facts.reason or _named_failure_code(facts)
    if reason:
        return f"{facts.status}/{reason}"
    return facts.status


def _named_failure_code(facts: _Facts) -> str | None:
    if isinstance(facts.cause, dict):
        code = facts.cause.get("code")
        if isinstance(code, str) and code:
            return code
    if isinstance(facts.receipt, dict):
        code = facts.receipt.get("code")
        if isinstance(code, str) and code:
            return code
    return None


def _download_token(facts: _Facts) -> str:
    if facts.downloads is not None:
        return str(facts.downloads)
    if facts.calls == 0 and facts.status != "unknown":
        return "0"
    return "unknown"


def _transcript_usage(transcript: dict[str, Any] | None, facts: _Facts) -> str:
    """The companion scope's fee account, separate from the filing's."""
    if not isinstance(transcript, dict):
        # No transcript block plus no producer dispatch proves the companion
        # scope could not have spent (e.g. a rejected v1 request carrying an
        # unknown companion field).
        if facts.calls == 0 and facts.status != "unknown":
            return "known"
        return "unknown"
    if transcript.get("status") in _TRANSCRIPT_NO_PROVIDER:
        return "known"
    started = transcript.get("provider_started")
    complete = transcript.get("provider_usage_complete")
    requests = transcript.get("provider_requests")
    if started is False and complete is True:
        return "known"
    if complete is True and type(requests) is int and requests == 0:
        return "known"
    # The transcript result exposes request counts but no fee. A started
    # companion can never be certified at zero from the filing's receipt.
    return "unknown"


__all__ = [
    "ATTEMPT_ENV",
    "DISPOSITIONS",
    "OUT_ENV",
    "OWNER",
    "RUN_ENV",
    "SCHEMA_VERSION",
    "ShortObservation",
    "begin_observation",
    "observation_rows",
]
