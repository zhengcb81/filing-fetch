"""R6-FF-CAUSE contract tests: safe upstream-cause propagation.

RED baseline: a named company-wiki machine failure (error-taxonomy code on
stderr) collapses to ``ensure exited 1`` + ``fatal`` and the machine cause is
dropped.  These tests pin the fixed six-key ``filing-upstream-cause/1``
diagnostic, the fail-closed ``unknown`` behavior for malformed/oversized/
mixed stderr, the no-leak rule for secret-laden payloads, and the honest
provider_started/usage_complete evidence rule — without changing any existing
status/error_code/retryable/calls/downloads semantics or the auto-retry set.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))
sys.path.insert(0, str(SKILL_ROOT / "tests"))

import fetch_filing  # noqa: E402
from fetch_filing import (  # noqa: E402
    FilingFetchError,
    _run_company_wiki_json,
    _run_company_wiki_json_retry,
)
from support import bounded_response  # noqa: E402


def _wiki_root(parent: Path, name: str = "company-wiki") -> Path:
    root = parent / name
    config = root / "config"
    config.mkdir(parents=True)
    (config / "source_catalog.yaml").write_text("schema_version: '1.0'\n", encoding="utf-8")
    (config / "source_acquisition.yaml").write_text("schema_version: '1.1'\n", encoding="utf-8")
    return root


def _structured(error_type: str, error: str = "boom", **extra: object) -> str:
    payload = {"status": "failed", "error_type": error_type, "error": error}
    payload.update(extra)
    return json.dumps(payload)


def _expected_cause(
    operation: str,
    code: str,
    scope: str,
    *,
    provider_started: object = None,
    usage_complete: object = None,
) -> dict:
    return {
        "schema_version": "filing-upstream-cause/1",
        "operation": operation,
        "code": code,
        "provider_started": provider_started,
        "usage_complete": usage_complete,
        "retry_scope": scope,
    }


def _raise_through_runner(
    root: Path,
    completed: subprocess.CompletedProcess | None = None,
    *,
    side_effect: BaseException | None = None,
    action: str = "ensure",
) -> FilingFetchError:
    with patch("fetch_filing._run_bounded_json") as run:
        if side_effect is not None:
            run.side_effect = side_effect
        else:
            run.return_value = bounded_response(completed)
        with pytest.raises(FilingFetchError) as ctx:
            _run_company_wiki_json(
                command=["company_wiki.source_catalog.cli"],
                root=root,
                timeout_seconds=30,
                action=action,
            )
    return ctx.value


# ---------------------------------------------------------------------------
# Named machine causes must survive the failure envelope
# ---------------------------------------------------------------------------

NAMED_CAUSES = [
    # (stderr error_type, FF error code, cause code, retry scope, retryable)
    ("legacy_evidence_archived", "fatal", "legacy_evidence_archived", "none", False),
    ("maintenance_operation_retired", "fatal", "maintenance_operation_retired", "none", False),
    ("catalog_locked", "catalog_locked", "catalog_locked", "catalog_contention", True),
    ("catalog_busy", "catalog_busy", "catalog_busy", "catalog_contention", True),
    ("db_timeout", "db_timeout", "db_timeout", "catalog_contention", True),
    ("worker_paused", "worker_paused", "worker_paused", "caller_decision", True),
    ("fatal", "fatal", "fatal", "none", False),
    # N-1 legacy class-name emission keeps its limited mapping.
    ("CatalogOperationLockedError", "catalog_locked", "catalog_locked", "catalog_contention", True),
    (
        "RuntimeError",
        "worker_paused",
        "worker_paused",
        "caller_decision",
        True,
    ),
]


@pytest.mark.parametrize(
    "error_type,ff_code,cause_code,scope,retryable",
    NAMED_CAUSES,
    ids=[row[0] if row[0] != "RuntimeError" else "RuntimeError+paused" for row in NAMED_CAUSES],
)
def test_named_machine_cause_survives_the_failure_envelope(
    error_type: str, ff_code: str, cause_code: str, scope: str, retryable: bool
) -> None:
    error_text = (
        "source acquisition is paused; start the worker"
        if error_type == "RuntimeError"
        else "catalog operation already running: pid=15536"
    )
    with TemporaryDirectory() as temporary:
        root = _wiki_root(Path(temporary))
        failed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=_structured(error_type, error_text)
        )
        exc = _raise_through_runner(root, failed)
    assert exc.code == ff_code
    assert exc.retryable is retryable
    assert exc.stage == "ensure"
    assert exc.upstream_cause == _expected_cause("ensure", cause_code, scope)
    if scope != "none":
        assert exc.retryable is True


# ---------------------------------------------------------------------------
# Fail closed: malformed / oversized / mixed stderr stays unknown
# ---------------------------------------------------------------------------

def test_unparseable_or_oversized_stderr_stays_unknown() -> None:
    payloads = [
        "not json at all",
        "",
        "[]",
        "[1, 2]",
        '{"status": "failed"}',
        "warn: something noisy\n" + _structured("catalog_locked"),
        # Valid JSON, trim-insensitive, still above the 64 KiB parse cap.
        _structured("catalog_locked", "x" * 70_000),
    ]
    with TemporaryDirectory() as temporary:
        root = _wiki_root(Path(temporary))
        for payload in payloads:
            failed = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=payload
            )
            exc = _raise_through_runner(root, failed)
            assert exc.code == "fatal", payload[:24]
            assert exc.retryable is False
            assert exc.upstream_cause == _expected_cause("ensure", "unknown", "none")


def test_unknown_error_type_is_never_copied_into_the_cause() -> None:
    with TemporaryDirectory() as temporary:
        root = _wiki_root(Path(temporary))
        for error_type in ("SomeOtherUpstreamError", "", 42, None, {"nested": 1}):
            failed = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=_structured(str(error_type))
                if not isinstance(error_type, str)
                else _structured(error_type)
            )
            exc = _raise_through_runner(root, failed)
            assert exc.upstream_cause is not None
            assert exc.upstream_cause["code"] == "unknown"


# ---------------------------------------------------------------------------
# No-leak rule for secret-laden stderr
# ---------------------------------------------------------------------------

_SECRET = "sk-live-abcdef0123456789"
_LEAKY_TEXT = (
    f"FMP key file C:\\Users\\leaker\\FMP_API_KEY.txt api_key={_SECRET} "
    "curl --header 'Authorization: Bearer hush' https://provider.example/v3/x?q=secret"
)


def test_stderr_secrets_and_paths_never_reach_the_cause() -> None:
    with TemporaryDirectory() as temporary:
        root = _wiki_root(Path(temporary))
        # The raw error text is full of secrets, but the taxonomy code itself
        # is publishable; the emitted cause must carry the code and nothing else.
        failed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=_structured("catalog_busy", _LEAKY_TEXT)
        )
        exc = _raise_through_runner(root, failed)
    rendered = json.dumps(exc.upstream_cause)
    assert exc.upstream_cause == _expected_cause("ensure", "catalog_busy", "catalog_contention")
    assert _SECRET not in rendered
    assert "FMP_API_KEY" not in rendered
    assert "api_key" not in rendered
    assert "curl" not in rendered
    assert "Authorization" not in rendered
    assert _LEAKY_TEXT not in rendered


@pytest.mark.parametrize(
    "error_type",
    [
        "api_key=" + _SECRET,
        "..\\..\\windows\\system32\\config",
        "catalog_locked\nDROP TABLE sources",
        "GET /admin?token=abc HTTP/1.1",
        "${USERPROFILE}/Projects/company-wiki/config",
    ],
)
def test_malicious_error_type_is_rejected_not_echoed(error_type: str) -> None:
    with TemporaryDirectory() as temporary:
        root = _wiki_root(Path(temporary))
        failed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr=_structured(error_type, _LEAKY_TEXT)
        )
        exc = _raise_through_runner(root, failed)
    rendered = json.dumps(exc.upstream_cause)
    assert exc.upstream_cause["code"] == "unknown"
    assert error_type not in rendered
    assert _SECRET not in rendered


# ---------------------------------------------------------------------------
# FF-observed producer conditions (transport layer, no stderr at all)
# ---------------------------------------------------------------------------

def test_producer_conditions_map_to_honest_causes() -> None:
    with TemporaryDirectory() as temporary:
        root = _wiki_root(Path(temporary))
        cases = [
            (
                fetch_filing._ProcessChildTimeout("deadline went past"),
                "upstream_error",
                "producer_deadline_exceeded",
                None,
                None,
                "caller_decision",
            ),
            (
                fetch_filing._ProcessOutputLimitExceeded("huge stdout"),
                "upstream_error",
                "producer_output_exceeded",
                None,
                None,
                "caller_decision",
            ),
            (
                fetch_filing.ff_process_transport.TransportError("pipe broke"),
                "upstream_error",
                "producer_transport_failure",
                None,
                None,
                "caller_decision",
            ),
            (
                OSError(2, "no such file or directory"),
                "fatal",
                "producer_start_failed",
                False,
                True,
                "none",
            ),
        ]
        for raised, ff_code, cause_code, started, usage, scope in cases:
            exc = _raise_through_runner(root, side_effect=raised)
            assert exc.code == ff_code, cause_code
            assert exc.upstream_cause == _expected_cause(
                "ensure", cause_code, scope, provider_started=started, usage_complete=usage
            )


# ---------------------------------------------------------------------------
# Deadline boundaries: honest no-start vs contention exhaustion
# ---------------------------------------------------------------------------

def test_deadline_expired_before_first_attempt_is_an_honest_no_start() -> None:
    with TemporaryDirectory() as temporary:
        root = _wiki_root(Path(temporary))
        with patch("fetch_filing._run_bounded_json") as run:
            with pytest.raises(FilingFetchError) as ctx:
                _run_company_wiki_json_retry(
                    command=["cli"], root=root, action="ensure",
                    deadline=time.monotonic() - 1.0,
                )
        run.assert_not_called()
    exc = ctx.value
    assert exc.code == "upstream_error"
    assert exc.upstream_cause == _expected_cause(
        "ensure",
        "producer_deadline_exceeded",
        "caller_decision",
        provider_started=False,
        usage_complete=True,
    )


def test_contention_retry_exhaustion_keeps_last_catalog_cause() -> None:
    locked = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr=_structured("catalog_busy", "database is locked")
    )
    start = 1000.0
    clock = iter((start, start + 100.0))  # pre-attempt, post-failure loop check
    with TemporaryDirectory() as temporary:
        root = _wiki_root(Path(temporary))
        with patch(
            "fetch_filing._run_bounded_json", return_value=bounded_response(locked)
        ) as run, patch(
            "fetch_filing.time.monotonic", side_effect=lambda: next(clock)
        ), patch(
            "fetch_filing.time.sleep"
        ) as sleep, patch(
            "fetch_filing.random.uniform", return_value=0.0
        ):
            with pytest.raises(FilingFetchError) as ctx:
                _run_company_wiki_json_retry(
                    command=["cli"], root=root, action="ensure", deadline=start + 10.0
                )
    # Hard cutoff: exactly one producer request, no re-request past the deadline.
    assert run.call_count == 1
    assert sleep.call_count == 1  # the bounded backoff waited once, then gave up
    exc = ctx.value
    assert exc.code == "upstream_error"
    assert exc.attempts == 1
    assert exc.upstream_cause == _expected_cause(
        "ensure", "catalog_busy", "catalog_contention"
    )


def test_catalog_contention_still_auto_retries_within_the_shared_deadline() -> None:
    locked = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr=_structured("catalog_locked")
    )
    ok = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="{}", stderr=""
    )
    with TemporaryDirectory() as temporary:
        root = _wiki_root(Path(temporary))
        with patch(
            "fetch_filing._run_bounded_json",
            side_effect=[bounded_response(locked), bounded_response(ok)],
        ) as run, patch("fetch_filing.time.sleep") as sleep, patch(
            "fetch_filing.random.uniform", return_value=0.0
        ):
            payload = _run_company_wiki_json_retry(
                command=["cli"], root=root, action="ensure",
                deadline=time.monotonic() + 60.0,
            )
    assert payload == {}
    assert run.call_count == 2
    assert sleep.call_args_list[0].args[0] <= 60.0


# ---------------------------------------------------------------------------
# Direct parser/builder contracts
# ---------------------------------------------------------------------------

def test_diagnose_stderr_direct_contract() -> None:
    import ff_provider_cause

    ff_code, cause = ff_provider_cause.diagnose_stderr(
        "close-gap", _structured("legacy_evidence_archived")
    )
    assert ff_code == "fatal"
    assert cause == _expected_cause("close-gap", "legacy_evidence_archived", "none")
    assert set(cause) == {
        "schema_version", "operation", "code",
        "provider_started", "usage_complete", "retry_scope",
    }


def test_builder_rejects_open_vocabulary() -> None:
    import ff_provider_cause

    with pytest.raises(ValueError):
        ff_provider_cause.build_cause("ensure", "definitely not a real code")
    with pytest.raises(ValueError):
        ff_provider_cause.build_cause("download", "fatal")


def test_validated_cause_rejects_tampered_shapes() -> None:
    import ff_provider_cause

    ok = ff_provider_cause.build_cause("ensure", "fatal")
    assert ff_provider_cause.validated_cause(ok) == ok
    tampered = [
        {},
        [ok],
        {**ok, "code": "../../etc/passwd"},
        {**ok, "code": 7},
        {**ok, "retry_scope": "yolo"},
        {**ok, "provider_started": "yes"},
        {**ok, "usage_complete": 1},
        {**ok, "operation": "download"},
        {**ok, "schema_version": "filing-upstream-cause/2"},
        {**ok, "extra": "field"},
    ]
    for value in tampered:
        assert ff_provider_cause.validated_cause(value) is None, value


def test_filing_fetch_error_rejects_non_cause_payload() -> None:
    with pytest.raises(TypeError):
        FilingFetchError("boom", code="fatal", upstream_cause={"code": "evil"})


def test_error_without_upstream_cause_keeps_none_default() -> None:
    exc = FilingFetchError("plain", code="fatal")
    assert exc.upstream_cause is None
