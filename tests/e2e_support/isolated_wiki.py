"""Temporary CWP source catalog with owned synthetic data and public commands.

Offline runs use the explicitly pinned release's code and fixture data only.
The manual live suite can opt in to its separately configured acquisition adapter.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

import yaml

from e2e_support.cwp_runtime import cwp_checkout, isolated_environment, run_quiet

def _live_wiki_root() -> Path:
    return Path(os.environ["FILING_FETCH_LIVE_WIKI"]) if "FILING_FETCH_LIVE_WIKI" in os.environ \
        else Path.home() / "Projects" / "company-wiki"


# Fixed timestamp: the synthetic master must be byte-stable across runs
# (double-run determinism), so it cannot use the runtime clock.
_SYNTHETIC_MASTER_RETRIEVED_AT = "2000-01-01T00:00:00Z"

# Aliases mirror the production snapshots' shape (e.g. the HK record carries
# the simplified "腾讯控股" form; the E2E queries it in simplified Chinese).
_SYNTHETIC_MASTER_ALIASES = {
    "CN": ["CATL"],
    "US": ["AAPL", "APPLE"],
    "HK": ["TENCENT", "腾讯", "腾讯控股", "騰訊"],
}

# Canonical names mirror the production snapshots, NOT the seed directory
# names (US dir is "Apple Inc" while the master canonical is "Apple Inc.";
# test_e2e_reuse_us_annual_report pins the deliberate mismatch).
_SYNTHETIC_MASTER_CANONICALS = {
    "CN": "宁德时代",
    "US": "Apple Inc.",
    "HK": "騰訊控股",
}


def _synthetic_security_master(market: str) -> dict:
    """Deterministic minimal security_master built from SYNTHETIC_SEEDS.

    Schema mirrors the CWP owner
    snapshot: {market, record_count, records, retrieved_at, schema_version}.
    """
    upper = market.upper()
    spec = SYNTHETIC_SEEDS[upper]
    provider = spec["sidecar"].get("provider", {"CN": "cninfo", "US": "sec", "HK": "hkexnews"}[upper])
    record = {
        "active": True,
        "aliases": _SYNTHETIC_MASTER_ALIASES[upper],
        "canonical_name": _SYNTHETIC_MASTER_CANONICALS[upper],
        "exchange": {"CN": "SZSE", "US": "NASDAQ", "HK": "HKEX"}[upper],
        "identifiers": {"org_id": f"syn-{market}-0001"},
        "market": upper,
        "schema_version": "1.0",
        "security_id": spec["sidecar"]["security_id"],
        "source_name": provider,
        "source_record_id": f"syn-{market}-0001",
        "source_url": spec["sidecar"]["source_url"],
        "ticker": spec["sidecar"]["security_id"],
    }
    return {
        "schema_version": "1.0",
        "market": upper,
        "retrieved_at": _SYNTHETIC_MASTER_RETRIEVED_AT,
        "sources": [spec["sidecar"]["source_url"]],
        "record_count": 1,
        "records": [record],
    }

# Synthetic seeds: the isolated-wiki E2E must be fully hermetic — it cannot
# depend on production wiki files (the catalog-space-remediation may delete
# or retire them, and CI clones a clean company-wiki with no companies/).
# The HK target directory is the identity canonical name "騰訊控股"
# (traditional): entity matching compares the request canonical_name against
# directory names / sidecar company_name, and the old-style HK sidecar has no
# company_name — placing it under the canonical name keeps the old-sidecar
# capture_ready case testable (D15). The HK sidecar deliberately stays
# minimal (no provider/fiscal_year/form_type) to exercise the old-sidecar
# path; fiscal_year is derived from the title.
SYNTHETIC_SEEDS = {
    "CN": {
        "entity": "宁德时代",
        "filename": "synthetic_cn_2024_annual.pdf",
        "bytes": b"%PDF-1.4 synthetic cn annual fixture 0123456789",
        "sidecar": {
            "market": "CN", "security_id": "300750",
            "source_title": "宁德时代2024年年度报告",
            "provider": "cninfo", "provider_document_id": "syn-cn-0001",
            "source_url": "https://www.cninfo.com.cn/new/disclosure/detail?stockCode=300750",
            "published_date": "2025-03-14", "fiscal_year": 2024, "form_type": "FY",
        },
    },
    "US": {
        "entity": "Apple Inc",
        "filename": "synthetic_us_2025_10k.pdf",
        "bytes": b"%PDF-1.4 synthetic us 10k fixture 9876543210",
        "sidecar": {
            "market": "US", "security_id": "AAPL",
            "source_title": "Apple Inc. 10-K FY2025",
            "provider": "sec", "provider_document_id": "syn-us-0001",
            "source_url": "https://www.sec.gov/Archives/edgar/data/0000320193/syn-10k.htm",
            "published_date": "2025-10-31", "fiscal_year": 2025, "form_type": "FY",
        },
    },
    "HK": {
        "entity": "騰訊控股",
        "filename": "synthetic_hk_2024_annual.pdf",
        "bytes": b"%PDF-1.4 synthetic hk annual fixture abcdef",
        "sidecar": {
            "market": "HK", "security_id": "00700",
            "source_title": "腾讯：2024年年度报告",
            "published_date": "2025-04-08",
            "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0408/2025040800668_c.pdf",
        },
    },
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
                 "'adapter':{'name':'e2e-noop-cn','version':'1.0.0'},'candidates':[],'acquisition_usage':{'schema_version':'1.0','response_bytes':0,'cost_usd':'0'}},sys.stdout)"]

_ACQUISITION_YAML = """schema_version: "1.1"
staging_root: "${PROJECT_ROOT}/.source_catalog/staging"
timeout_seconds: 300
adapters:
  cn:
    name: "e2e-noop-cn"
    version: "1.0.0"
    interface: "json_command_v1"
    supports_acquisition_budget: true
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

def _configured_code_path(value: str) -> str:
    """Keep deployed code entry points resolvable from a temporary wiki."""
    if value.startswith(("${PROJECT_ROOT}/../", "${PROJECT_ROOT}/tools/")):
        return value.replace("${PROJECT_ROOT}", _live_wiki_root().as_posix(), 1)
    return value


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
        self.root = root.resolve(strict=True)
        self.src = cwp_checkout() / "src"
        (root / "companies").mkdir(exist_ok=True)
        config = root / "config"
        config.mkdir(parents=True, exist_ok=True)
        (config / "source_catalog.yaml").write_text(_CATALOG_YAML, encoding="utf-8")
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
                (master / f"{market}.json").write_text(
                    json.dumps(_synthetic_security_master(market), ensure_ascii=False),
                    encoding="utf-8",
                )
        if paused:
            self.catalog_dir.mkdir(parents=True, exist_ok=True)
            (self.catalog_dir / "worker_control.json").write_text(
                json.dumps(_WORKER_CONTROL), encoding="utf-8"
            )
        self.config_path = config / "source_catalog.yaml"

    def use_production_adapters(self) -> None:
        """Use the owner's adapter configuration with isolated writable state."""
        source = _live_wiki_root() / "config" / "source_acquisition.yaml"
        config = yaml.safe_load(source.read_text(encoding="utf-8"))
        config["staging_root"] = str(self.catalog_dir / "staging")
        for adapter in config["adapters"].values():
            for field in ("project_root", "config_root"):
                if adapter[field] is not None:
                    adapter[field] = _configured_code_path(adapter[field])
            command = [_configured_code_path(value) for value in adapter["command"]]
            if "--provider-state-root" in command:
                state_arg = command.index("--provider-state-root") + 1
                command[state_arg] = str(self.catalog_dir / "provider-state" / "dayu")
            adapter["command"] = command
        (self.root / "config" / "source_acquisition.yaml").write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8"
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
        """Write the synthetic seed document + sidecar into the instance."""
        spec = SYNTHETIC_SEEDS[market]
        target = (
            self.root / "companies" / spec["entity"] / "raw"
            / "financial_reports" / "annual" / spec["filename"]
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(spec["bytes"])
        (target.parent / (target.name + ".source.json")).write_text(
            json.dumps(spec["sidecar"], ensure_ascii=False), encoding="utf-8"
        )
        return target

    def read(self, source_ref: dict) -> tuple[int, bytes, bytes]:
        result = run_quiet(
            [sys.executable, "-B", "-m", "company_wiki.source_catalog.source_reader_cli",
             "--config", str(self.config_path), "--document-id", source_ref["document_id"],
             "--source-id", source_ref["source_id"], "--content-sha256", source_ref["content_sha256"],
             "--purpose", "preview"], cwd=self.root, env=isolated_environment(self.root, self.src),
        )
        return result.returncode, result.stdout, result.stderr

    def scan(self) -> None:
        """Run the real ``scan`` CLI (acquires and releases the catalog lock)."""
        proc = run_quiet(
            [sys.executable, "-B", "-m", "company_wiki.source_catalog.cli",
             "--config", str(self.config_path), "scan", "--root-id", "company_raw"],
            cwd=self.root, env=isolated_environment(self.root, self.src),
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
            "--jobs-dir",
            str(self.root / "ff-jobs"),
        ]
        if allow_download:
            command.append("--allow-download")
        if extra_args:
            command.extend(extra_args)
        proc = run_quiet(
            command, cwd=self.root, env=isolated_environment(self.root, self.src),
            input=json.dumps(request, ensure_ascii=False).encode("utf-8"), timeout=timeout + 15,
        )
        return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8", "replace")
