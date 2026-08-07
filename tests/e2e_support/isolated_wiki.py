"""Build a throwaway company-wiki instance backed by the real company-wiki
code (editable install) with fully temporary state.

Layout (findings.md has the provenance for every rule):

    <root>/                          <- wiki root (config's two parents up)
      config/source_catalog.yaml     <- exact keys: schema_version/catalog_dir/roots;
                                         single company_raw root -> <root>/companies
      config/source_catalog_worker.yaml  <- copied from production; ensure requires
                                            the file to exist (strict resolve), never parses it
      config/source_acquisition.yaml <- no-op adapters (offline): discovery returns
                                        zero candidates -> resolution MISSING
      .source_catalog/security_master/{cn,hk,us}.json <- copied production snapshots,
                                            identify is fully offline without --refresh
      .source_catalog/worker_control.json  <- only for the paused-worker scenario
      companies/<Entity>/raw/...     <- seed files + .source.json sidecars

The production wiki is only ever *read* (shutil.copy2).  Nothing writes into
``company-wiki`` itself; the company-wiki CLI runs as a subprocess against the
temporary root.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PRODUCTION_WIKI = Path.home() / "Projects" / "company-wiki"

# (target_entity_dir, source_entity_dir, relative_path).  The HK target
# directory is the identity canonical name "騰訊控股" (traditional), not the
# production directory "腾讯" (simplified): entity matching compares the
# request canonical_name against directory names / sidecar company_name, and
# the old 4-field HK sidecar has no company_name — so the production layout
# would miss (observed as D15).  Placing it under the canonical name keeps
# the old-sidecar capture_ready case testable.
SEEDS = {
    "CN": (
        "宁德时代",
        "宁德时代",
        "raw/financial_reports/annual/2025-03-14_cninfo_1222806982_2024年年度报告.pdf",
    ),
    "US": (
        "Apple Inc",
        "Apple Inc",
        "raw/financial_reports/annual/2025-10-31_sec_0000320193-25-000079_Apple Inc. 10-K 2025-09-27.htm",
    ),
    "HK": (
        "騰訊控股",
        "腾讯",
        "raw/financial_reports/annual/腾讯：2024年年度报告.pdf",
    ),
}

_CATALOG_YAML = """schema_version: "1.0"
catalog_dir: "${PROJECT_ROOT}/.source_catalog"
roots:
  - root_id: company_raw
    kind: company_raw
    path: "${PROJECT_ROOT}/companies"
    priority: 10
"""

# Offline adapters: discovery always reports zero candidates, so ensure
# resolves MISSING without any network or external tool invocation.  Phase 4
# swaps in the real production acquisition config for live downloads.
# The json_command_v1 contract requires echoing the adapter identity; only
# the CN adapter (e2e-noop-cn) is ever invoked in the Phase 3 scenarios.
_NOOP_ADAPTER = ["${PYTHON_EXECUTABLE}", "-c",
                 "import sys,json;json.dump({'schema_version':'1.0','status':'ok',"
                 "'adapter':{'name':'e2e-noop-cn','version':'1.0.0'},'candidates':[]},sys.stdout)"]

_ACQUISITION_YAML = """schema_version: "1.1"
staging_root: "${PROJECT_ROOT}/.source_catalog/staging"
timeout_seconds: 300
adapters:
  cn:
    name: "e2e-noop-cn"
    version: "1.0.0"
    interface: "json_command_v1"
    project_root: "${PROJECT_ROOT}"
    config_root: null
    command: __NOOP_ADAPTER__
  hk:
    name: "e2e-noop-hk"
    version: "1.0.0"
    interface: "dayu_cli_v1"
    project_root: "${PROJECT_ROOT}"
    config_root: "${PROJECT_ROOT}/config"
    command: __NOOP_ADAPTER__
  us:
    name: "e2e-noop-us"
    version: "1.0.0"
    interface: "dayu_cli_v1"
    project_root: "${PROJECT_ROOT}"
    config_root: "${PROJECT_ROOT}/config"
    command: __NOOP_ADAPTER__
""".replace("__NOOP_ADAPTER__", json.dumps(_NOOP_ADAPTER, ensure_ascii=False))

# Phase 4: real downloads.  Mirrors the production source_acquisition.yaml
# but with absolute USER_PROFILE-based tool paths (the fixture's PROJECT_ROOT
# is a temp dir, so the production relative ".." tokens would not resolve).
_PRODUCTION_ACQUISITION_YAML = """schema_version: "1.1"
staging_root: "${PROJECT_ROOT}/.source_catalog/staging"
timeout_seconds: 1800
adapters:
  cn:
    name: "stockinfo-cninfo"
    version: "1.1.0"
    interface: "json_command_v1"
    project_root: "${USER_PROFILE}/Projects/StockInfoDLSimple/v2-clean-rewrite"
    config_root: null
    command: ["${PYTHON_EXECUTABLE}", "-m", "src.company_wiki_adapter_cli"]
  hk:
    name: "dayu-hkex-cli"
    version: "1.0.0"
    interface: "dayu_cli_v1"
    project_root: "${USER_PROFILE}/Projects/dayu-agent/dayu-agent"
    config_root: "${USER_PROFILE}/Projects/dayu-agent/workspace/config"
    command: ["${USER_PROFILE}/Projects/dayu-agent/dayu-agent/.venv/Scripts/python.exe", "-m", "dayu.cli"]
  us:
    name: "dayu-sec-cli"
    version: "1.0.0"
    interface: "dayu_cli_v1"
    project_root: "${USER_PROFILE}/Projects/dayu-agent/dayu-agent"
    config_root: "${USER_PROFILE}/Projects/dayu-agent/workspace/config"
    command: ["${USER_PROFILE}/Projects/dayu-agent/dayu-agent/.venv/Scripts/python.exe", "-m", "dayu.cli"]
"""


_WORKER_CONTROL = {
    "schema_version": "1.0",
    "desired_state": "paused",
    "updated_at": 0,
    "stop_requested_for": None,
}


def cleanup_temporary(temporary: tempfile.TemporaryDirectory) -> None:
    """Best-effort cleanup with retries.

    A deadline-killed company-wiki CLI can leave an orphaned PowerShell
    grandchild (spawned by the worker-control inventory scan) whose cwd is
    the temp wiki root; it holds a directory handle until it exits, which
    makes rmtree fail with WinError 32 on Windows.  Retrying covers that.
    """
    for attempt in range(6):
        try:
            temporary.cleanup()
            return
        except PermissionError:
            if attempt < 5:
                time.sleep(1)


class IsolatedWiki:
    """A real-code company-wiki instance rooted at ``root``."""

    def __init__(
        self,
        root: Path,
        *,
        paused: bool = False,
        with_security_master: bool = True,
    ) -> None:
        self.root = root
        config = root / "config"
        config.mkdir(parents=True, exist_ok=True)
        (config / "source_catalog.yaml").write_text(_CATALOG_YAML, encoding="utf-8")
        shutil.copy2(
            PRODUCTION_WIKI / "config" / "source_catalog_worker.yaml",
            config / "source_catalog_worker.yaml",
        )
        (config / "source_acquisition.yaml").write_text(
            _ACQUISITION_YAML, encoding="utf-8"
        )
        # filing-fetch's --config is the company_wiki.json launcher config;
        # the company-wiki CLI's --config is the source_catalog.yaml below.
        (root / "company_wiki.json").write_text(
            json.dumps({"schema_version": "1.0", "company_wiki_root": str(root)}),
            encoding="utf-8",
        )
        self.catalog_dir = root / ".source_catalog"
        if with_security_master:
            master = self.catalog_dir / "security_master"
            master.mkdir(parents=True, exist_ok=True)
            for market in ("cn", "hk", "us"):
                shutil.copy2(
                    PRODUCTION_WIKI
                    / ".source_catalog"
                    / "security_master"
                    / f"{market}.json",
                    master / f"{market}.json",
                )
        if paused:
            self.catalog_dir.mkdir(parents=True, exist_ok=True)
            (self.catalog_dir / "worker_control.json").write_text(
                json.dumps(_WORKER_CONTROL), encoding="utf-8"
            )
        self.config_path = config / "source_catalog.yaml"

    def use_production_adapters(self) -> None:
        """Point the acquisition config at the REAL download tools (Phase 4).

        Absolute USER_PROFILE-based paths, mirroring the production
        source_acquisition.yaml; only staging stays inside the temp instance.
        """
        (self.root / "config" / "source_acquisition.yaml").write_text(
            _PRODUCTION_ACQUISITION_YAML, encoding="utf-8"
        )

    def journal_outcomes(self) -> list[str]:
        """Outcome of every acquisition-journal record (in order)."""
        path = self.catalog_dir / "acquisition_attempts.jsonl"
        if not path.is_file():
            return []
        outcomes = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                outcomes.append(str(json.loads(line).get("outcome")))
            except json.JSONDecodeError:
                outcomes.append("<unparseable>")
        return outcomes

    def set_worker_state(self, desired_state: str) -> None:
        """Flip the persistent worker control state (enabled/paused)."""
        payload = dict(_WORKER_CONTROL)
        payload["desired_state"] = desired_state
        self.catalog_dir.mkdir(parents=True, exist_ok=True)
        (self.catalog_dir / "worker_control.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def seed_market(self, market: str) -> Path:
        """Copy a production seed document + sidecar into the instance."""
        target_entity, source_entity, relative = SEEDS[market]
        source = PRODUCTION_WIKI / "companies" / source_entity / relative
        target = self.root / "companies" / target_entity / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        shutil.copy2(
            PRODUCTION_WIKI / "companies" / source_entity / (relative + ".source.json"),
            target.parent / (target.name + ".source.json"),
        )
        return target

    def scan(self) -> None:
        """Run the real ``scan`` CLI (acquires and releases the catalog lock)."""
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "company_wiki.source_catalog.cli",
                "--config",
                str(self.config_path),
                "scan",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"isolated scan failed rc={proc.returncode}: {proc.stderr}"
            )

    def run_fetch(
        self,
        request: dict,
        *,
        allow_download: bool = False,
        timeout: float = 120,
        extra_args: list[str] | None = None,
    ) -> tuple[int, str, str]:
        """Run the real filing-fetch CLI as a subprocess; returns
        (exit_code, stdout_json, stderr)."""
        script = Path(__file__).resolve().parents[2] / "scripts" / "fetch_filing.py"
        command = [
            sys.executable,
            str(script),
            "--config",
            str(self.root / "company_wiki.json"),
            "--timeout-seconds",
            str(timeout),
        ]
        if allow_download:
            command.append("--allow-download")
        if extra_args:
            command.extend(extra_args)
        proc = subprocess.run(
            command,
            input=json.dumps(request, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=timeout + 60,
        )
        return proc.returncode, proc.stdout, proc.stderr
