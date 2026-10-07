"""FF-S3: one download intent, real limits on the wire, bounded execution.

Every test here drives the REAL filing-fetch entry points - the CLI as a
subprocess, the library in-process - against a local fake producer
(``tests/fixtures/s3_fake_cwp/fake_source_catalog_cli.py``).  Nothing is
mocked at the ``resolve_filing`` boundary, so the argv, the deadline and the
output ceiling that actually execute are what gets asserted.

No network, no LLM, no real API key, no production company-wiki config.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import fetch_filing  # noqa: E402
import ff_process_transport  # noqa: E402
from filing_contracts import FilingFetchError  # noqa: E402

FIXTURE_CLI = Path(__file__).parent / "fixtures" / "s3_fake_cwp" / "fake_source_catalog_cli.py"
GOLDEN_DIR = Path(__file__).parent / "golden"
LIMITS = {"max_bytes": 5_000_000, "timeout_seconds": 3, "max_cost_usd": "1.25"}
LIMIT_FLAGS = ("--max-download-bytes", "--max-download-seconds", "--max-download-cost-usd")


# --- harness ----------------------------------------------------------------


def _v2_request(**overrides) -> dict:
    request = {
        "schema_version": "2.0",
        "company_query": "ACME",
        "market": "US",
        "document_kind": "annual_report",
        "mode": "exact",
        "fiscal_year": 2025,
        "as_of_date": "2026-09-29",
        "filing_intent": "fetch_if_missing",
        "acquisition_limits": dict(LIMITS),
    }
    request.update(overrides)
    return request


def _wiki_root(tmp: Path) -> Path:
    root = tmp / "company-wiki"
    (root / "config").mkdir(parents=True)
    (root / "config" / "source_catalog.yaml").write_text(
        "schema_version: '1.0'\n", encoding="utf-8"
    )
    return root


def _fake_package(tmp: Path) -> Path:
    package = tmp / "fake_pkgs" / "company_wiki" / "source_catalog"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(FIXTURE_CLI, package / "cli.py")
    return package.parents[1]


def _fake_overrides(
    fake_root: Path, capture: Path, mode: str, **extra: str
) -> dict[str, str]:
    existing = os.environ.get("PYTHONPATH")
    values = {
        "PYTHONPATH": str(fake_root) + ((os.pathsep + existing) if existing else ""),
        "S3_FAKE_CAPTURE": str(capture),
        "S3_FAKE_MODE": mode,
    }
    values.update(extra)
    return values


def _child_env(
    fake_root: Path, capture: Path, mode: str, **extra: str
) -> dict[str, str]:
    env = dict(os.environ)
    env.update(_fake_overrides(fake_root, capture, mode, **extra))
    return env


def _records(capture: Path) -> list[dict]:
    if not capture.is_file():
        return []
    return [
        json.loads(line)
        for line in capture.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _argv_for(capture: Path, subcommand: str) -> list[list[str]]:
    return [r["argv"] for r in _records(capture) if r["subcommand"] == subcommand]


def _flag(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def _ff_config(tmp: Path, wiki_root: Path) -> Path:
    config = tmp / "ff_company_wiki.json"
    config.write_text(
        json.dumps({"schema_version": "1.0", "company_wiki_root": str(wiki_root)}),
        encoding="utf-8",
    )
    return config


def _run_cli(
    request: dict,
    *,
    config: Path,
    env: dict[str, str],
    global_timeout: float = 60.0,
    run_timeout: float = 90.0,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess:
    command = [
        sys.executable,
        str(SKILL_ROOT / "scripts" / "fetch_filing.py"),
        "--config", str(config),
        "--no-pause-worker",
        "--timeout-seconds", str(global_timeout),
    ]
    if extra_args:
        command.extend(extra_args)
    return subprocess.run(
        command,
        input=json.dumps(request, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(SKILL_ROOT),
        timeout=run_timeout,
        check=False,
    )


def _run_library(
    request: dict,
    *,
    wiki_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, str],
    **kwargs,
) -> dict:
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)
    kwargs.setdefault("source_ref_v2", True)
    kwargs.setdefault("pause_worker", False)
    return fetch_filing.resolve_filing(
        request=request, company_wiki_root=wiki_root, **kwargs
    )


def _payload(process: subprocess.CompletedProcess) -> dict:
    return json.loads(process.stdout)


# --- one explicit intent ----------------------------------------------------


def test_limits_reach_the_real_ensure_argv_through_the_cli(tmp_path: Path) -> None:
    root = _wiki_root(tmp_path)
    capture = tmp_path / "argv.jsonl"
    process = _run_cli(
        _v2_request(),
        config=_ff_config(tmp_path, root),
        env=_child_env(_fake_package(tmp_path), capture, "default"),
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert _payload(process)["status"] == "gap"
    ensure = _argv_for(capture, "ensure")
    assert len(ensure) == 1
    assert "--allow-download" in ensure[0]
    assert "--source-ref-v2" in ensure[0]
    assert _flag(ensure[0], "--max-download-bytes") == "5000000"
    assert _flag(ensure[0], "--max-download-seconds") == "3"
    assert _flag(ensure[0], "--max-download-cost-usd") == "1.25"


def test_library_default_and_cli_agree_for_one_fetch_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same v2 request must produce the same download intent and the same
    limits argv through the CLI and straight through the library with no
    explicit ``allow_download`` at all."""
    root = _wiki_root(tmp_path)
    fake = _fake_package(tmp_path)
    config = _ff_config(tmp_path, root)

    cli_capture = tmp_path / "cli_argv.jsonl"
    cli_process = _run_cli(
        _v2_request(), config=config, env=_child_env(fake, cli_capture, "default")
    )
    assert cli_process.returncode == 0, cli_process.stdout + cli_process.stderr

    lib_capture = tmp_path / "lib_argv.jsonl"
    result = _run_library(
        _v2_request(),
        wiki_root=root,
        monkeypatch=monkeypatch,
        overrides=_fake_overrides(fake, lib_capture, "default"),
    )
    assert result["status"] == "gap"

    cli_ensure = _argv_for(cli_capture, "ensure")
    lib_ensure = _argv_for(lib_capture, "ensure")
    assert cli_ensure == lib_ensure
    assert _flag(lib_ensure[0], "--max-download-bytes") == str(LIMITS["max_bytes"])



def test_latest_as_of_reuse_only_requires_bounded_metadata_limits(
    tmp_path: Path,
) -> None:
    """latest_as_of checks provider metadata even when downloads are forbidden.

    CWP therefore needs explicit byte/time/fee limits on this read-only
    provider lookup, and FF must pass them without enabling download.
    """
    request = _v2_request(
        filing_intent="reuse_only", mode="latest_as_of", fiscal_year=None,
        acquisition_limits=dict(LIMITS),
    )
    fetch_filing.validate_request(request)

    root = _wiki_root(tmp_path)
    capture = tmp_path / "latest_as_of_argv.jsonl"
    process = _run_cli(
        request,
        config=_ff_config(tmp_path, root),
        env=_child_env(_fake_package(tmp_path), capture, "default"),
        extra_args=["--source-ref-v2"],
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert _payload(process)["status"] == "gap"
    ensure = _argv_for(capture, "ensure")
    assert len(ensure) == 1
    assert "--allow-download" not in ensure[0]
    assert _flag(ensure[0], "--max-download-bytes") == str(LIMITS["max_bytes"])
    assert _flag(ensure[0], "--max-download-seconds") == str(LIMITS["timeout_seconds"])
    assert _flag(ensure[0], "--max-download-cost-usd") == LIMITS["max_cost_usd"]


def test_latest_as_of_reuse_only_without_limits_is_rejected() -> None:
    request = _v2_request(
        filing_intent="reuse_only", mode="latest_as_of", fiscal_year=None,
    )
    del request["acquisition_limits"]
    with pytest.raises(FilingFetchError, match="latest_as_of.*limits"):
        fetch_filing.validate_request(request)


def test_conflicting_explicit_allow_download_is_a_named_request_error(
    tmp_path: Path,
) -> None:
    """A caller passing ``allow_download=False`` for a ``fetch_if_missing``
    request gets a named request error instead of silently diverging from
    what the CLI would have done."""
    with pytest.raises(FilingFetchError) as error:
        fetch_filing.resolve_filing(
            request=_v2_request(),
            company_wiki_root=_wiki_root(tmp_path),
            allow_download=False,
            source_ref_v2=True,
            pause_worker=False,
        )
    assert error.value.code == "request_error"


def test_reuse_only_intent_never_emits_limit_argv() -> None:
    """A v2 ``reuse_only`` request forbids acquisition_limits, so no limit
    flag may ever reach the producer for it."""
    reuse = _v2_request(filing_intent="reuse_only")
    del reuse["acquisition_limits"]
    assert fetch_filing._download_intent(reuse, None) is False
    argv = fetch_filing._command_arguments(
        {"entity": "Acme Inc.", "document_kind": "annual_report",
         "as_of_date": "2026-09-29"}
    )
    assert not any(flag in argv for flag in LIMIT_FLAGS)


# --- three budgets, bounded execution ---------------------------------------


def test_shared_deadline_is_the_minimum_of_the_three_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fetch_filing.time, "monotonic", lambda: 100.0)
    request = _v2_request()
    # remaining global deadline (3600) > configured (900) > request (3)
    assert (
        fetch_filing._shared_deadline(
            request, deadline=100.0 + 3600, timeout_seconds=900
        )
        == 103.0
    )
    reuse = _v2_request(filing_intent="reuse_only")
    del reuse["acquisition_limits"]
    # no request budget: the configured 900 wins over the 3600 global remainder
    assert (
        fetch_filing._shared_deadline(reuse, deadline=100.0 + 3600, timeout_seconds=900)
        == 100.0 + 900
    )
    with pytest.raises(FilingFetchError) as expired:
        fetch_filing._shared_deadline(request, deadline=50.0, timeout_seconds=900)
    assert expired.value.code == "upstream_error"


def test_request_deadline_bounds_the_real_child_run(tmp_path: Path) -> None:
    """The request's ``timeout_seconds`` (3) must bind the run, not the
    global ``--timeout-seconds 60`` the CLI also carries.  Elapsed covers the
    bounded tree cleanup whose grace is additive and bounded (not download
    budget), so the honest bound is budget+cleanup-grace (< 15s on CI)."""
    root = _wiki_root(tmp_path)
    capture = tmp_path / "argv.jsonl"
    started = time.monotonic()
    process = _run_cli(
        _v2_request(),
        config=_ff_config(tmp_path, root),
        env=_child_env(_fake_package(tmp_path), capture, "slow", S3_FAKE_SLEEP="20"),
        global_timeout=60.0,
    )
    elapsed = time.monotonic() - started
    assert process.returncode == 2, process.stdout + process.stderr
    assert elapsed < 15.0, f"request budget was ignored (took {elapsed:.1f}s)"
    assert _payload(process)["status"] == "upstream_error"
    assert _argv_for(capture, "ensure")


def test_timeout_reclaims_the_child_but_never_an_unrelated_process(
    tmp_path: Path,
) -> None:
    sentinel = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        root = _wiki_root(tmp_path)
        capture = tmp_path / "argv.jsonl"
        process = _run_cli(
            _v2_request(),
            config=_ff_config(tmp_path, root),
            env=_child_env(_fake_package(tmp_path), capture, "slow", S3_FAKE_SLEEP="20"),
        )
        assert process.returncode == 2, process.stdout + process.stderr
        child_pids = [r["pid"] for r in _records(capture) if r["subcommand"] == "ensure"]
        assert child_pids, "the timed-out child was never started"
        for pid in child_pids:
            assert not ff_process_transport.pid_is_alive(pid), "timed-out child survived"
        assert ff_process_transport.pid_is_alive(sentinel.pid), "an unrelated process was killed"
    finally:
        sentinel.kill()
        sentinel.wait(timeout=30)


def test_child_output_over_the_byte_cap_fails_closed(tmp_path: Path) -> None:
    root = _wiki_root(tmp_path)
    capture = tmp_path / "argv.jsonl"
    process = _run_cli(
        _v2_request(),
        config=_ff_config(tmp_path, root),
        env=_child_env(_fake_package(tmp_path), capture, "flood"),
    )
    assert process.returncode == 2, process.stdout + process.stderr
    reason = _payload(process)["filing"]["reason"]
    assert "byte" in reason, reason
    assert "not JSON" not in reason
    assert len(process.stdout) < 100_000


def test_static_child_failure_does_not_echo_stderr_body(tmp_path: Path) -> None:
    root = _wiki_root(tmp_path)
    capture = tmp_path / "argv.jsonl"
    process = _run_cli(
        _v2_request(),
        config=_ff_config(tmp_path, root),
        env=_child_env(_fake_package(tmp_path), capture, "noisy_failure"),
    )
    assert process.returncode == 2, process.stdout + process.stderr
    assert "FAKE_SECRET_KEY_DO_NOT_LEAK" not in process.stdout
    assert "FAKE_SECRET_KEY_DO_NOT_LEAK" not in process.stderr
    assert "<private-root>" not in process.stdout
    reason = _payload(process)["filing"]["reason"]
    assert "exited 1" in reason, reason


def test_producer_rejecting_the_limit_flags_fails_once_without_stripping_them(
    tmp_path: Path,
) -> None:
    """A producer that does not know the three flags fails by name.  The
    request is never re-sent without them and never silently downgraded."""
    root = _wiki_root(tmp_path)
    capture = tmp_path / "argv.jsonl"
    process = _run_cli(
        _v2_request(),
        config=_ff_config(tmp_path, root),
        env=_child_env(_fake_package(tmp_path), capture, "reject_limits"),
    )
    assert process.returncode == 2, process.stdout + process.stderr
    payload = _payload(process)
    assert payload["status"] == "fatal"
    assert payload["filing"]["status"] == "fatal"
    ensure = _argv_for(capture, "ensure")
    assert len(ensure) == 1, "the limits-bearing request must not be retried"
    for flag in LIMIT_FLAGS:
        assert flag in ensure[0]
    assert payload["calls"] == 2


# --- close-gap carries the same limits --------------------------------------


def test_legacy_scope_argv_carries_the_same_limits(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        argv = kwargs["command"]
        scope_path = Path(argv[argv.index("--binding-file") + 1])
        captured["scope_path"] = scope_path
        captured["scope"] = json.loads(scope_path.read_text(encoding="utf-8"))
        return {"status": "gap"}

    monkeypatch.setattr(fetch_filing, "_run_company_wiki_json_retry", fake_run)
    request = _v2_request()
    normalized = dict(request, entity="Acme Inc.", market="US", security_id="ACME",
        authorization={"provider": "sec", "allowed_accessions": ["x"], "max_items": 1,
                       "max_bytes": 1000, "expires_at": "2000-01-01T00:00:00Z"})
    payload = fetch_filing._run_legacy_filing_command(action="ensure",
        command_prefix=[sys.executable, "-m", "fixture"], normalized_request=normalized,
        root=_wiki_root(tmp_path), deadline=time.monotonic() + 30, allow_download=True,
        stats={"calls": 0, "downloads": 0})
    assert payload == {"status": "gap"}
    argv = captured["command"]
    assert "ensure" in argv and "close-gap" not in argv
    assert _flag(argv, "--max-download-bytes") == "5000000"
    assert _flag(argv, "--max-download-seconds") == "3"
    assert _flag(argv, "--max-download-cost-usd") == "1.25"
    assert captured["scope"]["max_bytes"] == 1000
    assert "expires_at" not in captured["scope"]
    assert not captured["scope_path"].exists()


# --- limits -> argv golden --------------------------------------------------


def _argv_golden() -> dict:
    base = {
        "entity": "Acme Inc.",
        "document_kind": "annual_report",
        "as_of_date": "2026-09-29",
        "fiscal_year": 2025,
        "mode": "exact",
    }
    return {
        "v1_reuse": fetch_filing._command_arguments(dict(base)),
        "v2_fetch_if_missing": fetch_filing._command_arguments(
            {**base, "acquisition_limits": dict(LIMITS)}
        ),
        "v2_fetch_fractional_seconds": fetch_filing._command_arguments(
            {**base, "acquisition_limits": {
                "max_bytes": 1, "timeout_seconds": 12.5, "max_cost_usd": "0.05",
            }}
        ),
        "full_options": fetch_filing._command_arguments(
            {**base, "market": "US", "security_id": "ACME", "provider": "sec",
             "form_type": "10-K", "fiscal_period": "FY", "language": "en"}
        ),
    }


def test_limits_argv_matches_the_committed_golden() -> None:
    expected = json.loads(
        (GOLDEN_DIR / "s3_ff_limits_argv.json").read_text(encoding="utf-8")
    )
    assert _argv_golden() == expected


if __name__ == "__main__":
    if sys.argv[1:] != ["--write-golden"]:
        raise SystemExit("usage: python tests/test_s3_single_request_limits.py --write-golden")
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    (GOLDEN_DIR / "s3_ff_limits_argv.json").write_text(
        json.dumps(_argv_golden(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="",
    )
