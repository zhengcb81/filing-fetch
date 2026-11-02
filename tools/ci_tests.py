"""Full CI inventory and a separate fixed local smoke share isolated execution."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CI_TESTS = (
    "tests/test_architecture_quality.py",
    "tests/test_m3_acquisition_usage_ff.py",
    "tests/test_m3_acquisition_usage_acceptance.py",
    "tests/test_failure_usage_continuity.py",
    "tests/test_s3_single_request_limits.py",
    "tests/test_single_intent_acquisition.py",
    "tests/test_s3_install_surface.py",
    "tests/test_selective_installation.py",
    "tests/test_install_runtime_diagnostics.py",
    "tests/test_ff_v2_contract.py",
    "tests/test_provider_cause_contract.py",
    "tests/test_r1_source_business_failure.py",
    "tests/test_acquisition_failure_consumer.py",
    "tests/test_ff_golden.py",
    "tests/test_source_ref_v2.py",
    "tests/test_source_ref_v2_db_query.py",
    "tests/test_local_source_prepare.py",
    "tests/test_decoupled_connection.py",
    "tests/test_process_business_exit.py",
    "tests/test_local_preparation_observation.py",
    "tests/test_transcript_companion.py",
    "tests/test_transcript_companion_transport.py",
    "tests/test_transcript_launch_contract.py",
    "tests/test_transcript_response_budget.py",
    # Pure local reuse/current-reader regressions; the real frozen-CWP matrix
    # remains a separate integration node instead of running on every push.
    "tests/test_du11_transcript_reuse_selection.py",
    "tests/test_du11_transcript_reuse_contract.py",
    "tests/test_du11_verified_reader_revalidation.py",
    "tests/test_fetch_filing.py",
    "tests/test_fc802_gap_orchestration.py",
    "tests/test_fc1204_coverage_gap.py",
    "tests/test_p5_process_lifecycle.py",
    "tests/test_p5_legacy_request_limits.py",
    "tests/test_complexity_diagnostics.py",
    "tests/test_verify_plan_claims.py",
    "tests/test_latest_mode.py",
    "tests/test_dropbox_config_invariants.py",
    "tests/test_bundle_compat.py",
    "tests/e2e_support/test_spy_log.py",
    "tests/test_ci_tests.py",
    "tests/test_w07_matrix_efficiency.py",
    "tests/test_root_w07_matrix_boundaries.py",
)
# Explicit existing pure-unit nodes; additions to a file cannot widen daily work.
LOCAL_SMOKE_TESTS = (
    "tests/test_architecture_quality.py::test_valid_leap_day_is_accepted",
    "tests/test_architecture_quality.py::test_invalid_utf8_config_is_a_named_error",
    "tests/test_ff_v2_contract.py::test_v2_no_companion_is_pathless_and_calls_no_transcript",
    "tests/test_ff_v2_contract.py::test_companion_failure_does_not_rollback_filing",
    "tests/test_ff_v2_contract.py::test_v2_fetch_intent_requires_byte_time_and_cost_caps",
    "tests/test_source_ref_v2.py::test_v2_reuse_keeps_partial_capture_as_diagnostic_only",
    "tests/test_transcript_companion.py::test_no_companion_does_not_touch_transport",
    "tests/test_transcript_companion.py::test_existing_exact_transcript_is_reused_without_fetch",
    "tests/test_transcript_companion.py::test_direct_companion_fetch_without_caps_makes_zero_transport_calls",
    "tests/test_latest_mode.py::test_latest_as_of_mode_valid",
    "tests/test_ci_tests.py::test_shared_ci_table_covers_pure_local_reuse_and_current_reader_regressions",
)

GIT_REPOSITORY_CONTEXT = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_PREFIX", "GIT_NAMESPACE", "GIT_QUARANTINE_PATH",
)


def _wiki_source_directory() -> Path:
    """Honor CI's pin override, otherwise use the public FF project locator."""
    source = os.environ.get("FILING_FETCH_V2_WIKI_SRC")
    if source:
        directory = Path(source)
    else:
        scripts = str(PROJECT_ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from fetch_filing import load_company_wiki_root

        directory = load_company_wiki_root(
            config_path=PROJECT_ROOT / "config" / "company_wiki.json",
        ) / "src"
    directory = directory.resolve(strict=True)
    if not (directory / "company_wiki" / "source_catalog" / "cli.py").is_file():
        raise FileNotFoundError(f"company-wiki runtime lacks source_catalog CLI: {directory}")
    return directory


def subprocess_environment() -> dict[str, str]:
    """Child Git resolves its own cwd; host plugins cannot write checkout state."""
    environment = os.environ.copy()
    for key in GIT_REPOSITORY_CONTEXT:
        environment.pop(key, None)
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                       PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    return environment


def _run_tests(tests, *, scratch_prefix: str, timeout_seconds: int, resolve_wiki: bool) -> int:
    environment = subprocess_environment()
    if resolve_wiki:
        try:
            environment["FILING_FETCH_V2_WIKI_SRC"] = str(_wiki_source_directory())
        except (OSError, RuntimeError) as exc:
            print(f"company-wiki runtime unavailable for CI behavior tests: {exc}", file=sys.stderr)
            return 2
    with tempfile.TemporaryDirectory(prefix=scratch_prefix) as scratch:
        result = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", *tests,
             "-q", "-rs", "--tb=short", "-p", "no:cacheprovider", "--basetemp", scratch],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
        # Preserve every failed node, including the first one in a long report.
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode


def run_tests() -> int:
    """The unchanged full40-file CI mode, with its existing900s deadline."""
    return _run_tests(CI_TESTS, scratch_prefix="ff-ci-", timeout_seconds=900, resolve_wiki=False)


def run_local_smoke() -> int:
    """One fixed pure-unit child; no production/sibling configuration lookup."""
    return _run_tests(LOCAL_SMOKE_TESTS, scratch_prefix="ff-local-", timeout_seconds=180, resolve_wiki=False)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    return run_tests()


if __name__ == "__main__":
    raise SystemExit(main())
