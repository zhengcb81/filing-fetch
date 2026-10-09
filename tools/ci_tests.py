"""Run the same focused offline behavior suite for CI and the push hook."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CI_TESTS = (
    "tests/test_s3_single_request_limits.py",
    "tests/test_single_intent_acquisition.py",
    "tests/test_s3_install_surface.py",
    "tests/test_selective_installation.py",
    "e2e/test_source_ref_v2_cli.py",
    "tests/test_ff_v2_contract.py",
    "tests/test_provider_cause_contract.py",
    "tests/test_acquisition_failure_consumer.py",
    "tests/test_ff_golden.py",
    "tests/test_source_ref_v2.py",
    "tests/test_source_ref_v2_db_query.py",
    "tests/test_local_source_prepare.py",
    "tests/test_transcript_companion.py",
    "tests/test_transcript_companion_transport.py",
    "tests/test_transcript_launch_contract.py",
    "tests/test_transcript_response_budget.py",
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


def run_tests() -> int:
    """Keep scratch owned, child Git relative to its cwd, and failures visible."""
    environment = os.environ.copy()
    try:
        environment["FILING_FETCH_V2_WIKI_SRC"] = str(_wiki_source_directory())
    except (OSError, RuntimeError) as exc:
        print(f"company-wiki runtime unavailable for CI behavior tests: {exc}", file=sys.stderr)
        return 2
    for key in GIT_REPOSITORY_CONTEXT:
        environment.pop(key, None)
    # CI installs plain pytest; unrelated host plugins can write checkout state.
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                       PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    with tempfile.TemporaryDirectory(prefix="ff-ci-") as scratch:
        result = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", *CI_TESTS,
             "-q", "-rs", "--tb=short", "-p", "no:cacheprovider", "--basetemp", scratch],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
        # Preserve every failed node, including the first one in a long report.
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return result.returncode


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    return run_tests()


if __name__ == "__main__":
    raise SystemExit(main())
