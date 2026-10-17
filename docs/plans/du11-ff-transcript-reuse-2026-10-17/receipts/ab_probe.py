"""DU11 A/B evidence probe: same real frozen CWP, only the FF implementation differs.

    # both sides in one run (baseline extracted from the base commit):
    python receipts/ab_probe.py --ab --out-dir receipts

    # one side only (e.g. re-measure the current worktree):
    python receipts/ab_probe.py --scripts <dir> --label <text> --out <json>

Each side builds its own owned TemporaryDirectory, extracts the frozen
company-wiki ``src`` (commit ``34a7dd71``) from the local company-wiki
repository, registers one synthetic ``motley_fool`` transcript through the real
``scan`` CLI, then walks:

  1. plain neutral ``SourceRequest`` (provider=null)      -> local query wire
  2. ``lookup-request/1`` envelope with provider=fmp      -> provider-scoped wire
  3. ``lookup-request/1`` envelope with provider=null     -> must be blocked
  4. plain query with provider=fmp                       -> provider-filtered miss
  5. real ``source_reader_cli`` receipt manifest          -> real provider
  6. real FF companion (provider omitted) via ``--scripts``

No network, no LLM, no credential value is read: the ET boundary is an offline
fixture process that records every call. Every temporary tree (including the
frozen-source tar) is removed in the ``finally`` block.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

CWP_REPO = Path(r"C:\Users\郑曾波\Projects\company-wiki")
CWP_COMMIT = "34a7dd71aaa49d18c13fcdd300ce79581114ca5b"
BASE_COMMIT = "f1a939e522c22b23659712a8bd2b344f5eb0a364"
FF_ROOT = Path(__file__).resolve().parents[4]
FIXTURE = (
    FF_ROOT / "tests" / "fixtures" / "du11_transcript_reuse"
    / "fmp_known_publication.fetched.json"
)

AS_OF = "2026-09-30"
ENTITY = "Microsoft Corporation"
SIDECAR = {
    "market": "US",
    "security_id": "MSFT",
    "ticker": "MSFT",
    "source_title": "Microsoft (MSFT) Q3 2026 Earnings Call Transcript",
    "provider": "motley_fool",
    "provider_document_id": "mf:MSFT:2026:Q3",
    "source_url": "https://www.fool.com/earnings/call-transcripts/2026/07/22/microsoft-msft-q3-2026/",
    "published_date": "2026-07-22",
    "fiscal_year": 2026,
    "fiscal_period": "Q3",
    "document_kind": "investor_call_transcript",
    "language": "en",
}
CONFIG = """schema_version: "1.0"
catalog_dir: .source_catalog
roots:
  - root_id: company_raw
    path: companies
    kind: company_raw
    priority: 10
    adapter_id: company_raw_v1
    read_only: false
"""
BASE_REQUEST = {
    "entity": ENTITY,
    "document_kind": "investor_call_transcript",
    "as_of_date": AS_OF,
    "market": "US",
    "security_id": "MSFT",
    "form_type": None,
    "fiscal_year": 2026,
    "fiscal_period": "Q3",
    "language": None,
    "provider_document_id": None,
    "mode": "exact",
    "allow_download": False,
    "schema_version": "1.0",
}
ENVELOPE = "company-wiki-transcript-import-lookup-request/1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def script_hashes(directory: Path) -> dict[str, str]:
    return {
        path.name: sha256(path)
        for path in sorted(directory.glob("transcript_*.py"))
    }


def _run(command: list[str], payload: bytes | None, root: Path) -> tuple[int, bytes, bytes]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("FMP_API_KEY", None)
    env.pop("FMP_API_KEY_FILE", None)
    proc = subprocess.run(
        command, input=payload, cwd=root, env=env, capture_output=True, timeout=300
    )
    return proc.returncode, proc.stdout, proc.stderr


def _wire(root: Path, config: Path, payload: dict) -> dict:
    code, out, err = _run(
        [
            sys.executable,
            "-m",
            "company_wiki.source_catalog.source_query_cli",
            "--config",
            str(config),
        ],
        json.dumps(payload).encode("utf-8"),
        root,
    )
    try:
        result = json.loads(out.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return {"exit": code, "invalid_stdout": err[:200].decode("utf-8", "replace")}
    return {
        "exit": code,
        "status": result.get("status"),
        "reason": result.get("reason"),
        "candidates": len(result.get("candidates") or []),
        "excluded": [
            {
                "publication_status": item["qualification"]["publication_status"],
                "local_bytes_status": item["qualification"]["local_bytes_status"],
            }
            for item in result.get("excluded_candidates") or []
        ],
        "candidate_provider": (
            (result.get("candidates") or [{}])[0].get("provider")
            if result.get("candidates")
            else None
        ),
    }


def _extract(tar: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar) as archive:
        archive.extractall(target, filter="data")


def run_side(
    *,
    scripts: Path,
    label: str,
    cwp_tar: Path,
    cwp_tar_sha: str,
    ff_commit: dict[str, str],
) -> dict:
    root = Path(tempfile.mkdtemp(prefix="du11-ab-probe-"))
    summary: dict = {
        "label": label,
        "ff_scripts": str(scripts),
        "ff_scripts_sha256": script_hashes(scripts),
        "ff_commit": ff_commit,
        "cwp_commit": CWP_COMMIT,
        "cwp_src_tar_sha256": cwp_tar_sha,
        "network_calls": 0,
        "llm_calls": 0,
        "cases": {},
    }
    try:
        _extract(cwp_tar, root)
        config = root / "config"
        config.mkdir()
        config_file = config / "source_catalog.yaml"
        config_file.write_text(CONFIG, encoding="utf-8")
        seed = root / "companies" / ENTITY / "raw" / "investor_relations" / "transcripts"
        seed.mkdir(parents=True)
        body = b"Microsoft Q3 2026 earnings call transcript. Operator: welcome. CEO: demand grew.\n"
        (seed / "msft_2026_q3_call.txt").write_bytes(body)
        summary["seed_sha256"] = hashlib.sha256(body).hexdigest()
        summary["seed_bytes"] = len(body)
        (seed / "msft_2026_q3_call.txt.source.json").write_text(
            json.dumps(SIDECAR, ensure_ascii=False), encoding="utf-8"
        )
        code, _, err = _run(
            [
                sys.executable,
                "-m",
                "company_wiki.source_catalog.cli",
                "--config",
                str(config_file),
                "scan",
                "--root-id",
                "company_raw",
            ],
            None,
            root,
        )
        summary["scan"] = {"exit": code}
        if code != 0:
            summary["scan"]["stderr"] = err[:500].decode("utf-8", "replace")
            return summary

        summary["cases"]["neutral_plain_request"] = _wire(
            root, config_file, {**BASE_REQUEST, "provider": None}
        )
        summary["cases"]["envelope_provider_fmp"] = _wire(
            root, config_file,
            {"schema_version": ENVELOPE, "source_request": {**BASE_REQUEST, "provider": "fmp"}},
        )
        summary["cases"]["envelope_provider_null"] = _wire(
            root, config_file,
            {"schema_version": ENVELOPE, "source_request": {**BASE_REQUEST, "provider": None}},
        )
        summary["cases"]["neutral_plain_provider_fmp"] = _wire(
            root, config_file, {**BASE_REQUEST, "provider": "fmp"}
        )

        if summary["cases"]["neutral_plain_request"].get("status") == "found":
            code, out, _ = _run(
                [
                    sys.executable,
                    "-m",
                    "company_wiki.source_catalog.source_query_cli",
                    "--config",
                    str(config_file),
                ],
                json.dumps({**BASE_REQUEST, "provider": None}).encode(),
                root,
            )
            source_ref = json.loads(out.decode())["candidates"][0]["source_ref"]
            code, opened, receipt_raw = _run(
                [
                    sys.executable,
                    "-m",
                    "company_wiki.source_catalog.source_reader_cli",
                    "--config",
                    str(config_file),
                    "--document-id", source_ref["document_id"],
                    "--source-id", source_ref["source_id"],
                    "--content-sha256", source_ref["content_sha256"],
                    "--purpose", "preview",
                ],
                None,
                root,
            )
            receipt = json.loads(receipt_raw.decode())
            summary["cases"]["reader_receipt"] = {
                "exit": code,
                "bytes_sha256_matches_ref": hashlib.sha256(opened).hexdigest()
                == source_ref["content_sha256"],
                "byte_size_matches_ref": len(opened) == source_ref["byte_size"],
                "manifest_provider": receipt["manifest"]["provider"],
                "manifest_published_date": receipt["manifest"]["published_date"],
                "manifest_fiscal_period": receipt["manifest"]["fiscal_period"],
                "manifest_security_id": receipt["manifest"]["security_id"],
            }

        sys.path.insert(0, str(scripts))
        for name in ("transcript_companion", "transcript_tool_transport"):
            sys.modules.pop(name, None)
        from transcript_companion import resolve_companion_transcript
        from transcript_tool_transport import EarningsTranscriptsTransport

        tool = root / "et_tool.py"
        tool.write_text(
            "import json,sys,os\n"
            "request=json.loads(sys.stdin.read())\n"
            "open(os.environ['ET_CALL_LOG'],'a',encoding='utf-8').write('call\\n')\n"
            "result=json.load(open(os.environ['ET_FIXTURE_PATH'],encoding='utf-8'))\n"
            "result['request_id']=request['request_id']\n"
            "print(json.dumps(result,separators=(',',':')))\n"
            "sys.stderr.write(json.dumps({'schema_version':'earnings-retrieval-usage/1',"
            "'request_id':request['request_id'],'usage_complete':True,"
            "'usage':{'requests_used':1,'response_bytes_used':len(json.dumps(result))}}))\n",
            encoding="utf-8",
        )
        call_log = root / "et_calls.log"
        os.environ["ET_CALL_LOG"] = str(call_log)
        os.environ["ET_FIXTURE_PATH"] = str(FIXTURE)
        key_file = root / "synthetic_key.txt"
        key_file.write_text("SYNTHETIC-TEST-KEY-0123456789", encoding="utf-8")
        request = {
            "as_of_date": AS_OF,
            "companion_transcript": {
                "intent": "fetch_if_missing",
                "fiscal_year": 2026,
                "fiscal_quarter": 3,
                "acquisition_limits": {
                    "max_bytes": 1_000_000, "timeout_seconds": 10, "max_cost_usd": "0.00",
                },
            },
        }
        filing_handle = {
            "source_ref": {
                "schema_version": "2.0",
                "document_id": "urn:company-wiki:document:sha256:" + "a" * 64,
                "source_id": "urn:company-wiki:source:sha256:" + "a" * 64,
                "content_sha256": "a" * 64,
                "byte_size": 100,
                "mime_type": "application/pdf",
            },
            "company_identity": {
                "canonical_name": ENTITY, "market": "US", "security_id": "MSFT",
                "ticker": "MSFT", "exchange": "NASDAQ", "verified": True, "active": True,
            },
        }
        transport = EarningsTranscriptsTransport(
            wiki_root=root, transcript_tool=tool, fmp_api_key_file=key_file,
            deadline=time.monotonic() + 120,
        )
        result = resolve_companion_transcript(
            request=request, filing_handle=filing_handle, transport=transport,
        )
        calls = call_log.read_text(encoding="utf-8").splitlines() if call_log.exists() else []
        summary["cases"]["ff_companion_provider_omitted"] = {
            "status": result.get("status"),
            "reason": result.get("reason"),
            "provider": result.get("provider"),
            "provider_calls": result.get("provider_calls"),
            "as_of_cutoff_verified": result.get("as_of_cutoff_verified"),
            "et_calls": len(calls),
            "company_wiki_calls": transport.company_wiki_calls,
            "source_ref": result.get("source_ref"),
            "fiscal_year": result.get("fiscal_year"),
            "fiscal_quarter": result.get("fiscal_quarter"),
        }
        return summary
    finally:
        shutil.rmtree(root, ignore_errors=True)
        summary["owned_temp_removed"] = not root.exists()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ab", action="store_true", help="run baseline and after-fix sides")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--scripts", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--label", default="")
    parser.add_argument(
        "--source-commit", default=None,
        help=(
            "FF source commit the measured scripts belong to; required for a stable "
            "binding because the worktree HEAD may already be a later docs commit"
        ),
    )
    args = parser.parse_args(argv)

    holder = Path(tempfile.mkdtemp(prefix="du11-ab-holder-"))
    try:
        cwp_tar = holder / "cwp.tar"
        subprocess.run(
            ["git", "-C", str(CWP_REPO), "archive", "--format=tar", "-o", str(cwp_tar),
             CWP_COMMIT, "src", "pyproject.toml"],
            check=True,
            capture_output=True,
        )
        cwp_tar_sha = sha256(cwp_tar)

        if args.ab:
            if args.out_dir is None:
                raise SystemExit("--ab requires --out-dir")
            args.out_dir.mkdir(parents=True, exist_ok=True)
            baseline_tree = holder / "baseline"
            archive = holder / "baseline.tar"
            subprocess.run(
                ["git", "-C", str(FF_ROOT), "archive", "--format=tar", "-o", str(archive),
                 BASE_COMMIT, "scripts", "pyproject.toml"],
                check=True,
                capture_output=True,
            )
            _extract(archive, baseline_tree)
            baseline = run_side(
                scripts=baseline_tree / "scripts",
                label=f"baseline {BASE_COMMIT}",
                cwp_tar=cwp_tar,
                cwp_tar_sha=cwp_tar_sha,
                ff_commit={
                    "source_commit": BASE_COMMIT,
                    "archive_tar_sha256": sha256(archive),
                },
            )
            after = run_side(
                scripts=FF_ROOT / "scripts",
                label="worktree du11 implementation",
                cwp_tar=cwp_tar,
                cwp_tar_sha=cwp_tar_sha,
                ff_commit={
                    "source_commit": args.source_commit or subprocess.run(
                        ["git", "-C", str(FF_ROOT), "rev-parse", "HEAD"],
                        capture_output=True, text=True, check=True,
                    ).stdout.strip(),
                    "worktree": True,
                },
            )
            (args.out_dir / "A_RED_baseline.json").write_text(
                json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            (args.out_dir / "A_RED_after_fix.json").write_text(
                json.dumps(after, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(json.dumps({"baseline": baseline, "after_fix": after}, indent=2, sort_keys=True))
            return 0

        if args.scripts is None or args.out is None:
            raise SystemExit("single-side mode requires --scripts and --out")
        summary = run_side(
            scripts=args.scripts,
            label=args.label or str(args.scripts),
            cwp_tar=cwp_tar,
            cwp_tar_sha=cwp_tar_sha,
            ff_commit={"worktree": True},
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    finally:
        shutil.rmtree(holder, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
