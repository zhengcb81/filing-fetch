"""Offline FF↔ET↔CWP contract-matrix runner (explicit manual entry point).

Run::

    python -B tools/offline_contract_matrix/run.py \
        --cwp-project <explicit-code-root> \
        --et-project  <explicit-code-root> \
        --owned-root  <new-root> \
        --out-root    <new-attempt-root>

The runner builds a fully isolated scratch (owned fixture wiki + configs), binds
the supplied CWP/ET code read-only via child PYTHONPATH, exercises the real
three-layer transcript chain and the coverage matrix, writes a
``ff-et-cwp-offline-matrix/1`` report plus per-case artifacts, runs the failure
vector oracle, and restores the pre-placed sentinel and baseline.

Every child runs with a minimal synthetic environment; there is no real network
and no real charge. Provider requests are fixture requests and are reported
separately from the real-cost ledger. Unknown usage/cost stays ``null``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fixture_builder import (  # noqa: E402
    ScratchEnvironment, Identity,
    FAKE_FMP_KEY,
)
from report import sha256_file  # noqa: E402

SENTINEL_NAME = ".w06_matrix_sentinel"
SENTINEL_CONTENT = b"w06-matrix-sentinel-do-not-modify\n"
CASE_TIMEOUT = 30          # seconds per FF child (bounded, no fixed sleeps)
BATCH_DEADLINE = 180       # seconds for the whole in-process batch (excluding manual run)


# ── small helpers ──────────────────────────────────────────────────────────


def _stat_meta(path: Path) -> dict[str, Any]:
    """Existence + size + mtime only (never reads file content)."""
    try:
        st = path.stat()
        return {"exists": True, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
    except OSError:
        return {"exists": False}


def _hash_meta(path: Path) -> dict[str, Any]:
    meta = _stat_meta(path)
    if meta.get("exists") and path.is_file():
        try:
            meta["sha256"] = sha256_file(path)
        except OSError:
            meta["sha256"] = None
    return meta


class ProductionGuard:
    """Records production config/original metadata before and after a run.

    The user's ``config/FMP_API_KEY.txt`` is never read — only stat metadata is
    captured so a write would still be visible without exposing the secret.
    """

    def __init__(self, ff_root: Path, cwp_root: Path, et_root: Path) -> None:
        self.paths = [
            ff_root / "config" / "company_wiki.json",
            ff_root / "config" / "FMP_API_KEY.txt",
            cwp_root / "config" / "source_catalog.yaml",
            cwp_root / "config" / "source_acquisition.yaml",
            et_root / "config.yaml",
            et_root / "transcripts",
        ]
        self.before = {str(p): _hash_meta(p) for p in self.paths}

    def snapshot(self) -> dict[str, Any]:
        return {str(p): _hash_meta(p) for p in self.paths}

    def unchanged(self, after: dict[str, Any]) -> bool:
        for key, before in self.before.items():
            if before != after.get(key):
                return False
        return True


# ── execution context ─────────────────────────────────────────────────────


class Context:
    def __init__(self, *, ff_root: Path, cwp_root: Path, et_root: Path,
                 scratch: Path, out_root: Path) -> None:
        self.ff_root = ff_root
        self.cwp_root = cwp_root
        self.et_root = et_root
        self.out_root = out_root
        self.artifacts = out_root / "artifacts"
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.scratch = scratch
        self.env = ScratchEnvironment(
            scratch,
            adapter_script=HERE / "fixture_provider_adapter.py",
            et_proxy=HERE / "et_transcript_proxy.py",
        )
        self.scans = 0

    # -- environment -------------------------------------------------------

    def child_env(self, *, with_fmp_key: bool = True) -> dict[str, str]:
        # Inherit the host environment (CWP/FF need USERPROFILE & friends for
        # ${USER_PROFILE}/home resolution) but run every child with a synthetic,
        # non-secret credential and scratch-only paths. The user's real
        # config/FMP_API_KEY.txt is never read or propagated.
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = os.pathsep.join([str(self.cwp_root / "src"), str(self.et_root)])
        env["W06_ET_ROOT"] = str(self.et_root)
        env["W06_MATRIX_SCRATCH"] = str(self.scratch)
        env["W06_MATRIX_STATE"] = str(self.env.proxy_state / "state.json")
        env.pop("FMP_API_KEY_FILE", None)
        if with_fmp_key:
            env["FMP_API_KEY"] = FAKE_FMP_KEY
        else:
            env.pop("FMP_API_KEY", None)
        return env

    def write_state(self, *, scenario: str, calls_file: Path, content_utf8: str = "",
                    call_date: str = "2025-12-01", response_bytes: int = 512,
                    provider_scenario: str = "serve", receipt_tag: str = "et") -> Path:
        state = {
            "scenario": scenario,
            "provider_scenario": provider_scenario,
            "content_utf8": content_utf8,
            "call_date": call_date,
            "response_bytes": response_bytes,
            "calls_file": str(calls_file),
            "et_temp_root": str(self.env.et_temp_root()),
            "receipts_dir": str(self.artifacts),
            "receipt_tag": receipt_tag,
        }
        path = self.env.proxy_state / "state.json"
        path.write_text(json.dumps(state), encoding="utf-8")
        return path

    # -- CWP scan (populate catalog from seeded originals) -----------------

    def scan(self) -> None:
        self.scans += 1
        subprocess.run(
            [sys.executable, "-m", "company_wiki.source_catalog.cli",
             "--config", str(self.env.wiki / "config" / "source_catalog.yaml"), "scan"],
            capture_output=True, env=self.child_env(), cwd=str(self.env.wiki),
            timeout=CASE_TIMEOUT,
        )

    # -- FF public CLI -----------------------------------------------------

    def run_ff(self, request: dict[str, Any], *, case_id: str, run_label: str = "run1",
               with_fmp_key: bool = True, timeout: int = CASE_TIMEOUT) -> dict[str, Any]:
        req_path = self.artifacts / f"{case_id}.{run_label}.request.json"
        req_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        cmd = [
            sys.executable, str(self.ff_root / "scripts" / "fetch_filing.py"),
            "--config", str(self.env.ff_config), "--timeout-seconds", str(timeout),
        ]
        proc = subprocess.run(
            cmd, input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
            capture_output=True, env=self.child_env(with_fmp_key=with_fmp_key),
            cwd=str(self.scratch), timeout=timeout + 20,
        )
        resp_path = self.artifacts / f"{case_id}.{run_label}.response.json"
        try:
            response = json.loads(proc.stdout.decode("utf-8", errors="replace"))
        except ValueError:
            response = {"_unparsed_stdout": proc.stdout.decode("utf-8", errors="replace")[:2000]}
        resp_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        stderr_path = self.artifacts / f"{case_id}.{run_label}.stderr.txt"
        stderr_path.write_text(proc.stderr.decode("utf-8", errors="replace"), encoding="utf-8")
        return {
            "exit_code": proc.returncode,
            "response": response,
            "stderr": proc.stderr.decode("utf-8", errors="replace"),
            "request_ref": req_path.name,
            "response_ref": resp_path.name,
            "stderr_ref": stderr_path.name,
        }

    # -- counters / evidence ----------------------------------------------

    def fixture_requests(self, calls_file: Path) -> int:
        """Count real worker HTTP GET records (fixture provider requests)."""
        if not calls_file.is_file():
            return 0
        count = 0
        for line in calls_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                if json.loads(line).get("op") == "get":
                    count += 1
            except ValueError:
                continue
        return count

    def worker_ran(self, calls_file: Path) -> bool:
        if not calls_file.is_file():
            return False
        ops = set()
        for line in calls_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ops.add(json.loads(line).get("op"))
            except ValueError:
                continue
        return "envelope" in ops and "get" in ops


def _mk_filing_request(identity: Identity, *, document_kind: str, fiscal_year: int,
                       fiscal_period: str | None, intent: str,
                       limits: dict[str, Any] | None = None,
                       as_of_date: str = "2026-12-31",
                       companion: dict[str, Any] | None = None) -> dict[str, Any]:
    req: dict[str, Any] = {
        "schema_version": "2.0",
        "company_query": identity.canonical_name,
        "market": identity.market,
        "document_kind": document_kind,
        "fiscal_year": fiscal_year,
        "as_of_date": as_of_date,
        "filing_intent": intent,
    }
    if fiscal_period is not None:
        req["fiscal_period"] = fiscal_period
    if intent == "fetch_if_missing":
        req["acquisition_limits"] = limits or {"max_bytes": 2_000_000, "timeout_seconds": 25, "max_cost_usd": "0"}
    if companion is not None:
        req["companion_transcript"] = companion
    return req


def _companion(year: int, quarter: int | None, intent: str,
               limits: dict[str, Any] | None = None) -> dict[str, Any]:
    comp: dict[str, Any] = {"intent": intent, "fiscal_year": year, "provider": "fmp"}
    if quarter is not None:
        comp["fiscal_quarter"] = quarter
    if intent == "fetch_if_missing":
        comp["acquisition_limits"] = limits or {"max_bytes": 1_000_000, "timeout_seconds": 25, "max_cost_usd": "0"}
    return comp


if __name__ == "__main__":
    from cli_main import main as _main

    raise SystemExit(_main())
