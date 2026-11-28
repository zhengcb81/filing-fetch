"""Full CI inventory and a separate fixed local smoke share isolated execution."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_POLICY = Path(__file__).with_name('ci_test_policy.json')
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
    "tests/test_ci_tests.py::test_offline_scope_is_directory_discovery_and_local_smoke_is_fixed",
)

GIT_REPOSITORY_CONTEXT = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_PREFIX", "GIT_NAMESPACE", "GIT_QUARANTINE_PATH",
)


def subprocess_environment() -> dict[str, str]:
    """Child Git resolves its own cwd; host plugins cannot write checkout state."""
    environment = os.environ.copy()
    for key in GIT_REPOSITORY_CONTEXT:
        environment.pop(key, None)
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                       PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    return environment


_TEST_ENVIRONMENT = {
    "COMSPEC", "COMPANY_WIKI_REPO", "FILING_FETCH_V2_WIKI_SRC",
    "GITHUB_ACTIONS", "PATH", "PATHEXT", "PROGRAMDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "WINDIR",
    "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONDONTWRITEBYTECODE", "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
}


def _test_environment() -> dict[str, str]:
    return {key: value for key, value in subprocess_environment().items()
            if key.upper() in _TEST_ENVIRONMENT}


def _annotate_failures(report: Path) -> None:
    """Expose node names in GitHub Checks; missing diagnostics never alter exit."""
    try:
        suite = ET.parse(report).getroot()
    except (OSError, ET.ParseError):
        return
    for case in suite.iter("testcase"):
        if case.find("failure") is None and case.find("error") is None:
            continue
        node = "::".join(filter(None, (case.get("classname"), case.get("name"))))
        node = node.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error title=pytest failure::" + node)


def _run_tests(tests, *, scratch_prefix: str, timeout_seconds: int) -> int:
    environment = _test_environment()
    with tempfile.TemporaryDirectory(prefix=scratch_prefix) as scratch:
        root = Path(scratch)
        test_tmp = root / "t"
        profile = root / "profile"
        appdata = profile / "AppData" / "Roaming"
        local = profile / "AppData" / "Local"
        for directory in (test_tmp, appdata, local):
            directory.mkdir(parents=True)
        environment.update(HOME=str(profile), USERPROFILE=str(profile), APPDATA=str(appdata),
                           LOCALAPPDATA=str(local), TMP=str(root), TEMP=str(root), TMPDIR=str(root),
                           RESEARCH_FEEDBACK_DIR=str(root / "observations"),
                           RESEARCH_FEEDBACK_STATE_ROOT=str(root / "feedback-state"))
        command = [sys.executable, "-B", "-m", "pytest", *tests,
                   "-q", "-rs", "--capture=sys", "--tb=short", "-p", "no:cacheprovider", "--basetemp", str(test_tmp)]
        report = Path(scratch) / "junit.xml"
        annotated = environment.get("GITHUB_ACTIONS") == "true"
        if annotated:
            command.extend(("--junitxml", str(report)))
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # Preserve every failed node, including the first one in a long report.
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if annotated and result.returncode:
            _annotate_failures(report)
        return result.returncode


def offline_selection(platform: str) -> list[str]:
    """Read the same reviewed owner policy independently checked against CI evidence."""
    policy = json.loads(TEST_POLICY.read_text(encoding="utf-8"))
    selection = policy["platforms"][platform]
    return [*selection["roots"], "-m", selection["markexpr"]]


def run_tests(*, collect_only: bool = False, evidence: Path | None = None,
              revision: str | None = None, shard: str | None = None) -> int:
    """Discover and run all applicable non-live tests, without using owner state."""
    platform = "windows" if os.name == "nt" else "linux"
    command = [*offline_selection(platform), "--strict-markers"]
    if collect_only:
        command.append("--collect-only")
    if shard is not None:
        command.extend(("-p", "tools.pytest_shards", "--ff-shard", shard))
    if evidence is not None:
        if not revision:
            raise ValueError("test evidence requires the checkout revision")
        command.extend(("-p", "tools.anti_trick_gate_spec.pytest_probe",
                        "--s6-evidence", str(evidence.resolve()), "--s6-revision", revision))
    return _run_tests(command, scratch_prefix="ff-ci-", timeout_seconds=900)

def run_local_smoke() -> int:
    """One fixed pure-unit child; no production/sibling configuration lookup."""
    return _run_tests(LOCAL_SMOKE_TESTS, scratch_prefix="ff-local-", timeout_seconds=180)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--shard", metavar="SHARD/COUNT")
    settings = parser.parse_args()
    if settings.evidence is not None and not settings.revision:
        parser.error("--evidence requires --revision")
    if settings.collect_only and settings.shard is not None:
        parser.error("canonical collection cannot be sharded")
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    return run_tests(collect_only=settings.collect_only, evidence=settings.evidence,
                     revision=settings.revision, shard=settings.shard)


if __name__ == "__main__":
    raise SystemExit(main())
