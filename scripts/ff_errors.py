"""Typed filing failures and their pathless owner diagnostics."""
from __future__ import annotations

from typing import Any

from ff_local_preparation_observation import validated_local_preparation_observation
from ff_provider_cause import (
    STAGES,
    validated_acquisition_failure,
    validated_acquisition_observation,
    validated_cause,
    validated_request_diagnostic,
)


class FilingFetchError(RuntimeError):
    """Raised when a capture-ready filing cannot be resolved or downloaded."""

    def __init__(
        self,
        message: str,
        code: str = "fatal",
        candidates: list | None = None,
        debug_trace: list | None = None,
        stage: str | None = None,
        attempts: int | None = None,
        resolution_trace: dict | None = None,
        upstream_cause: dict[str, Any] | None = None,
        acquisition_failure: dict[str, Any] | None = None,
        acquisition_observation: dict[str, Any] | None = None,
        request_diagnostic: dict[str, Any] | None = None,
        producer_exit_code: int | None = None,
        local_preparation_observation: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.producer_exit_code = producer_exit_code if type(producer_exit_code) is int else None
        # ZR-205: retryable = the caller may retry. catalog_busy (raw SQLite
        # busy/locked) and db_timeout join catalog_locked/worker_paused; the
        # deadline-aware auto-retry loop in fetch_filing only spins on the
        # bounded catalog-contention codes (worker_paused stays caller-side).
        self.retryable = code in {
            "upstream_error",
            "worker_paused",
            "catalog_locked",
            "catalog_busy",
            "db_timeout",
        }
        # Candidate identities surfaced by company-wiki when the query is
        # ambiguous, so callers can disambiguate from the error response alone.
        self.candidates = candidates
        # Per-candidate exclusion trace from the company-wiki resolve step,
        # surfaced with --debug so a not_found explains itself (Phase 19.6).
        self.debug_trace = debug_trace
        # ZR-205 stage transparency: which company-wiki call failed
        # (identify/ensure/resolve/close-gap) and how many attempts were made,
        # so the final envelope stays reconcilable (READ-09).
        self.stage = stage if isinstance(stage, str) and stage in STAGES else None
        self.attempts = attempts if type(attempts) is int and attempts >= 0 else None
        # ZR-307 staged-evidence visibility: the upstream resolution summary
        # (request_id/status/reason) survives a downstream failure — the
        # error never swallows the exact-reuse/download=0 evidence.
        self.resolution_trace = resolution_trace
        # R6-FF-CAUSE: optional safe machine diagnostic for a failed
        # company-wiki producer call.  Only a validated
        # filing-upstream-cause/1 object (built by ff_provider_cause from
        # closed vocabularies) is accepted — garbage never rides the envelope.
        if upstream_cause is not None and validated_cause(upstream_cause) is None:
            raise TypeError(
                "upstream_cause must be a validated filing-upstream-cause/1 object"
            )
        self.upstream_cause = upstream_cause
        self.acquisition_failure = validated_acquisition_failure(acquisition_failure)
        # M3-USAGE: same fail-closed pass-through as the failure receipt —
        # only a validated operation observation rides, garbage is dropped.
        self.acquisition_observation = validated_acquisition_observation(acquisition_observation)
        # A request subtype is separate from the unchanged producer cause.
        # Keep a verified copy; serializers validate again before emission.
        diagnostic = validated_request_diagnostic(request_diagnostic)
        if request_diagnostic is not None and diagnostic is None:
            raise TypeError("request_diagnostic must be a validated filing-request-diagnostic/1 object")
        self.request_diagnostic = diagnostic
        # Optional local evidence never decides eligibility or paid usage.
        self.local_preparation_observation = validated_local_preparation_observation(local_preparation_observation)
