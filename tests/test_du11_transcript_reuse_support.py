"""Owned temporary company-wiki instances built from the frozen CWP commit (DU11).

Only *needed source files* are extracted from the exact commit named by the task
card (``src/`` plus ``pyproject.toml`` via ``git archive``); no companies,
transcripts, real config, receipts or production state is copied. Everything the
tests create lives inside one owned ``TemporaryDirectory`` that is verified and
removed, and the company-wiki repository is only ever read.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

import pytest

CWP_COMMIT = "34a7dd71aaa49d18c13fcdd300ce79581114ca5b"
FF_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CWP_REPO = FF_ROOT.parent / "company-wiki"

AS_OF = "2026-09-30"
ENTITY = "Microsoft Corporation"
SECURITY_ID = "MSFT"
MARKET = "US"
TRANSCRIPT_DIR = ("companies", ENTITY, "raw", "investor_relations", "transcripts")
FILING_DIR = ("companies", ENTITY, "raw", "financial_reports", "annual")

CATALOG_YAML = """schema_version: "1.0"
catalog_dir: .source_catalog
roots:
  - root_id: company_raw
    path: companies
    kind: company_raw
    priority: 10
    adapter_id: company_raw_v1
    read_only: false
"""

MOTLEY_SIDECAR = {
    "market": MARKET,
    "security_id": SECURITY_ID,
    "ticker": SECURITY_ID,
    "source_title": "Microsoft (MSFT) Q3 2026 Earnings Call Transcript",
    "provider": "motley_fool",
    "provider_document_id": "mf:MSFT:2026:Q3",
    "source_url": (
        "https://www.fool.com/earnings/call-transcripts/2026/07/22/microsoft-msft-q3-2026/"
    ),
    "published_date": "2026-07-22",
    "fiscal_year": 2026,
    "fiscal_period": "Q3",
    "document_kind": "investor_call_transcript",
    "language": "en",
}

FILING_SIDECAR = {
    "market": MARKET,
    "security_id": SECURITY_ID,
    "source_title": "Microsoft Corporation FY2025 Form 10-K",
    "provider": "sec",
    "provider_document_id": "sec:MSFT:2025:10-K",
    "source_url": "https://www.sec.gov/Archives/edgar/data/789019/synthetic-10k.htm",
    "published_date": "2025-10-31",
    "fiscal_year": 2025,
    "form_type": "FY",
    "document_kind": "annual_report",
    "language": "en",
}

SECURITY_MASTER = {
    "schema_version": "1.0",
    "market": "US",
    "retrieved_at": "2000-01-01T00:00:00Z",
    "sources": ["https://www.sec.gov/"],
    "record_count": 1,
    "records": [
        {
            "active": True,
            "aliases": ["MSFT", "MICROSOFT"],
            "canonical_name": ENTITY,
            "exchange": "NASDAQ",
            "identifiers": {"org_id": "syn-us-0001"},
            "market": MARKET,
            "schema_version": "1.0",
            "security_id": SECURITY_ID,
            "source_name": "sec",
            "source_record_id": "syn-us-0001",
            "source_url": "https://www.sec.gov/",
            "ticker": SECURITY_ID,
        }
    ],
}

KNOWN_TRANSCRIPT_BODY = (
    b"Microsoft Q3 2026 earnings call transcript. Operator: welcome. "
    b"CEO: demand grew across cloud and AI.\n"
)
OTHER_TRANSCRIPT_BODY = (
    b"Microsoft Q3 2026 earnings call transcript (second local observation). "
    b"Operator: welcome.\n"
)
UNKNOWN_TRANSCRIPT_BODY = (
    b"Microsoft Q3 2026 earnings call transcript with no publication date.\n"
)
AFTER_AS_OF_BODY = (
    b"Microsoft Q3 2026 earnings call transcript published after the as-of date.\n"
)

ET_TOOL_SCRIPT = """import json, os, sys

request = json.loads(sys.stdin.read())
log = os.environ.get("ET_CALL_LOG")
if log:
    with open(log, "a", encoding="utf-8") as stream:
        stream.write(json.dumps({
            "provider": request.get("provider"),
            "ticker": request.get("ticker"),
            "fiscal_year": request.get("fiscal_year"),
            "fiscal_quarter": request.get("fiscal_quarter"),
        }, sort_keys=True) + "\\n")
with open(os.environ["ET_FIXTURE_PATH"], encoding="utf-8") as stream:
    result = json.load(stream)
result["request_id"] = request["request_id"]
sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\\n")
sys.stderr.write(json.dumps({
    "schema_version": "earnings-retrieval-usage/1",
    "request_id": request["request_id"],
    "usage_complete": True,
    "usage": {"requests_used": 1, "response_bytes_used": 1727},
}) + "\\n")
"""


def cwp_repo() -> Path:
    explicit = os.environ.get("COMPANY_WIKI_REPO")
    return Path(explicit) if explicit else DEFAULT_CWP_REPO


def _git(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwp_repo()), *arguments], capture_output=True, timeout=120
    )


def _require_frozen_commit() -> None:
    if not (cwp_repo() / ".git").exists():
        pytest.skip(f"company-wiki repository is unavailable: {cwp_repo()}")
    if _git("cat-file", "-e", f"{CWP_COMMIT}^{{commit}}").returncode != 0:
        pytest.skip(f"frozen company-wiki commit {CWP_COMMIT} is unavailable")


@contextmanager
def frozen_archive() -> Iterator[Path]:
    """One ``git archive`` of only ``src/`` and ``pyproject.toml`` from the frozen commit."""
    _require_frozen_commit()
    holder = Path(tempfile.mkdtemp(prefix="du11-cwp-frozen-"))
    tar = holder / "cwp.tar"
    try:
        result = subprocess.run(
            [
                "git", "-C", str(cwp_repo()), "archive", "--format=tar",
                "-o", str(tar), CWP_COMMIT, "src", "pyproject.toml",
            ],
            capture_output=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise AssertionError(
                "git archive of the frozen company-wiki commit failed: "
                + result.stderr.decode("utf-8", "replace")
            )
        yield tar
    finally:
        shutil.rmtree(holder, ignore_errors=True)


class OwnedWiki:
    """One verified, disposable company-wiki instance inside an owned directory."""

    def __init__(self, source_tar: Path, *, label: str = "du11") -> None:
        self.root = Path(tempfile.mkdtemp(prefix=f"{label}-owned-"))
        self.source_tar = source_tar
        self._initial: dict[str, tuple[int, str, int]] | None = None
        self._checkpoint: dict[str, tuple[int, str, int]] | None = None
        self._company_additions_expected = False
        # Only catalogue state and the harness's own runtime files may grow.
        self._growable_prefixes = (".source_catalog/", "runtime/")
        # Paths that legitimately change during a run (the catalogue database and
        # the fixture processes' own files); everything else must stay identical.
        self._activity_prefixes = (".source_catalog/", "runtime/", "companies/")

    # -- construction -----------------------------------------------------
    def build(self, *, with_security_master: bool = True) -> "OwnedWiki":
        with tarfile.open(self.source_tar) as archive:
            archive.extractall(self.root, filter="data")
        config = self.root / "config"
        config.mkdir()
        (config / "source_catalog.yaml").write_text(CATALOG_YAML, encoding="utf-8")
        (self.root / "companies").mkdir()
        if with_security_master:
            master = self.root / ".source_catalog" / "security_master"
            master.mkdir(parents=True)
            (master / "us.json").write_text(
                json.dumps(SECURITY_MASTER, ensure_ascii=False), encoding="utf-8"
            )
        restore = self.root / "restore"
        restore.mkdir()
        (restore / "sentinel.txt").write_text("du11 sentinel\n", encoding="utf-8")
        (restore / "existing.out").write_text("pre-existing output entry\n", encoding="utf-8")
        runtime = self.root / "runtime"
        runtime.mkdir()
        self.et_tool().write_text(ET_TOOL_SCRIPT, encoding="utf-8")
        self.key_file().write_text("SYNTHETIC-TEST-KEY-0123456789", encoding="utf-8")
        self._initial = self.manifest()
        return self

    def checkpoint(self) -> "OwnedWiki":
        """Snapshot the tree *after* the test's own seeding and catalog scan.

        The restore comparison then treats only genuinely new catalogue/import
        artifacts as additions, so an overwritten seed or a stray company file
        cannot hide behind a "companies/" prefix.
        """
        self._checkpoint = self.manifest()
        return self

    def expect_canonical_imports(self) -> "OwnedWiki":
        """Allow exactly one canonical import pair (original + sidecar) later."""
        self._company_additions_expected = True
        return self

    def launcher_config(self, **optional: str) -> Path:
        payload = {"schema_version": "1.0", "company_wiki_root": str(self.root), **optional}
        path = self.root / "runtime" / "company_wiki.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    # -- seeds ------------------------------------------------------------
    def _write(self, parts: tuple[str, ...], name: str, body: bytes, sidecar: dict) -> Path:
        target = self.root.joinpath(*parts)
        target.mkdir(parents=True, exist_ok=True)
        source = target / name
        source.write_bytes(body)
        (target / f"{name}.source.json").write_text(
            json.dumps(sidecar, ensure_ascii=False), encoding="utf-8"
        )
        return source

    def seed_transcript(self, name: str, body: bytes, sidecar: dict) -> Path:
        return self._write(TRANSCRIPT_DIR, name, body, sidecar)

    def seed_filing(self, name: str, body: bytes) -> Path:
        return self._write(FILING_DIR, name, body, FILING_SIDECAR)

    # -- real company-wiki CLI -------------------------------------------
    def _env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.root / "src")
        env["PYTHONUTF8"] = "1"
        env.pop("FMP_API_KEY", None)
        env.pop("FMP_API_KEY_FILE", None)
        if extra:
            env.update(extra)
        return env

    def run_module(
        self, module: str, arguments: list[str], payload: bytes | None = None,
        *, timeout: float = 300, extra_env: dict[str, str] | None = None,
    ) -> tuple[int, bytes, bytes]:
        process = subprocess.run(
            [
                sys.executable, "-m", module,
                "--config", str(self.root / "config" / "source_catalog.yaml"),
                *arguments,
            ],
            input=payload,
            cwd=self.root,
            env=self._env(extra_env),
            capture_output=True,
            timeout=timeout,
        )
        return process.returncode, process.stdout, process.stderr

    def run_scan(self) -> dict:
        process = subprocess.run(
            [
                sys.executable, "-m", "company_wiki.source_catalog.cli",
                "--config", str(self.root / "config" / "source_catalog.yaml"),
                "scan", "--root-id", "company_raw",
            ],
            cwd=self.root,
            env=self._env(),
            capture_output=True,
            timeout=300,
        )
        if process.returncode != 0:
            raise AssertionError(
                "real scan failed rc="
                f"{process.returncode}: {process.stderr.decode('utf-8', 'replace')[:800]}"
            )
        return json.loads(process.stdout.decode("utf-8"))

    def query_local(self, source_request: dict) -> dict:
        code, out, err = self.run_module(
            "company_wiki.source_catalog.source_query_cli",
            [],
            json.dumps(source_request).encode("utf-8"),
        )
        if code not in (0, 2):
            raise AssertionError(f"source_query_cli failed rc={code}: {err[:400]!r}")
        return json.loads(out.decode("utf-8"))

    def read_version(self, source_ref: dict) -> tuple[int, bytes, dict]:
        code, out, err = self.run_module(
            "company_wiki.source_catalog.source_reader_cli",
            [
                "--document-id", source_ref["document_id"],
                "--source-id", source_ref["source_id"],
                "--content-sha256", source_ref["content_sha256"],
                "--purpose", "preview",
            ],
        )
        receipt = json.loads(err.decode("utf-8")) if err.strip() else {}
        return code, out, receipt

    def et_tool(self) -> Path:
        return self.root / "runtime" / "offline-et-tool.py"

    def key_file(self) -> Path:
        return self.root / "runtime" / "synthetic_key.txt"

    def call_log(self) -> Path:
        return self.root / "runtime" / "et-calls.log"

    # -- restore receipts -------------------------------------------------
    def manifest(self) -> dict[str, tuple[int, str, int]]:
        listing: dict[str, tuple[int, str, int]] = {}
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            listing[path.relative_to(self.root).as_posix()] = (
                stat.st_size,
                hashlib.sha256(path.read_bytes()).hexdigest(),
                stat.st_mtime_ns,
            )
        return listing

    def restore_receipt(self) -> dict[str, object]:
        assert self._initial is not None, "build() must run before the receipt"
        assert self._checkpoint is not None, "checkpoint() must run before the receipt"
        checkpoint = self._checkpoint
        current = self.manifest()

        # 1. The pre-test inventory: anything outside the catalogue/runtime
        #    activity area (frozen source, config, sentinel, existing output)
        #    must be byte- and mtime-identical.
        frozen_changed = [
            name
            for name, entry in self._initial.items()
            if not name.startswith(self._activity_prefixes)
            and current.get(name) != entry
        ]
        # 2. Everything seeded and scanned before the action must be untouched.
        changed = [
            name
            for name, entry in checkpoint.items()
            if name in current and current[name] != entry
        ]
        removed = [name for name in checkpoint if name not in current]
        added = [name for name in current if name not in checkpoint]
        growable = [name for name in added if name.startswith(self._growable_prefixes)]
        company_added = [name for name in added if name not in growable]
        transcript_prefix = "/".join(TRANSCRIPT_DIR) + "/"
        if self._company_additions_expected:
            # One canonical import writes exactly the original and its sidecar.
            unexpected_company = [
                name
                for name in company_added
                if not name.startswith(transcript_prefix)
            ]
            assert len(company_added) == 2, company_added
            assert len(unexpected_company) == 0, unexpected_company
            assert sum(name.endswith(".source.json") for name in company_added) == 1
        else:
            unexpected_company = company_added
        restore_changed = [
            name for name in changed + removed if name.startswith("restore/")
        ]
        return {
            "initial_entries": len(self._initial),
            "checkpoint_entries": len(checkpoint),
            "current_entries": len(current),
            "changed_since_checkpoint": changed,
            "removed_since_checkpoint": removed,
            "catalogue_or_runtime_added": growable,
            "canonical_import_added": company_added,
            "unexpected_added": unexpected_company,
            "restore_entry_changed": restore_changed,
            "frozen_source_changed": frozen_changed,
            "root": str(self.root),
        }

    def assert_restored(self) -> dict[str, object]:
        receipt = self.restore_receipt()
        assert receipt["restore_entry_changed"] == [], receipt
        assert receipt["frozen_source_changed"] == [], receipt
        assert receipt["unexpected_added"] == [], receipt
        assert receipt["removed_since_checkpoint"] == [], receipt
        return receipt

    def cleanup(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        assert not self.root.exists(), f"owned temporary root survived cleanup: {self.root}"

