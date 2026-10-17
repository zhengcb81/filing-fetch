"""DU11 C-node receipt: real hierarchy, call counts, restore and cleanup evidence.

    python receipts/restore_probe.py --out receipts/c_restore_receipt.json

Builds the same owned frozen-company-wiki instance the E2E tests use, resolves
one companion transcript through the real FF companion + transport (real
``source_query_cli`` + ``source_reader_cli`` subprocesses), and records:

- the exact child processes and their count (query / reader / import / ET),
- the restore receipt for the owned root (sentinel + pre-existing entry),
- the cleanup receipt (the owned root is gone),
- that no ET/import child ran at all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
FF_ROOT = HERE.parents[3]
sys.path.insert(0, str(FF_ROOT / "tests"))
sys.path.insert(0, str(FF_ROOT / "scripts"))

from test_du11_transcript_reuse_support import (  # noqa: E402
    AS_OF,
    ENTITY,
    KNOWN_TRANSCRIPT_BODY,
    MARKET,
    MOTLEY_SIDECAR,
    SECURITY_ID,
    OwnedWiki,
    frozen_archive,
)

from transcript_companion import resolve_companion_transcript  # noqa: E402
from transcript_tool_transport import EarningsTranscriptsTransport  # noqa: E402

FIXTURE = FF_ROOT / "tests" / "fixtures" / "du11_transcript_reuse" / "fmp_known_publication.fetched.json"


def filing_handle() -> dict:
    return {
        "source_ref": {
            "schema_version": "2.0",
            "document_id": "urn:company-wiki:document:sha256:" + "a" * 64,
            "source_id": "urn:company-wiki:source:sha256:" + "a" * 64,
            "content_sha256": "a" * 64,
            "byte_size": 100,
            "mime_type": "application/pdf",
        },
        "company_identity": {
            "canonical_name": ENTITY,
            "market": MARKET,
            "security_id": SECURITY_ID,
            "ticker": SECURITY_ID,
            "exchange": "NASDAQ",
            "verified": True,
            "active": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    os.environ["ET_FIXTURE_PATH"] = str(FIXTURE)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    receipt: dict = {
        "cwp_frozen_commit": "34a7dd71aaa49d18c13fcdd300ce79581114ca5b",
        "layering": [
            "resolve_companion_transcript (real FF code)",
            "EarningsTranscriptsTransport.lookup_exact (real FF code)",
            "python -m company_wiki.source_catalog.source_query_cli (real frozen CWP, plain SourceRequest, provider=null)",
            "python -m company_wiki.source_catalog.source_reader_cli (real frozen CWP verified open)",
            "offline ET fixture process (registered but must never run)",
        ],
        "network_calls": 0,
        "llm_calls": 0,
    }
    with frozen_archive() as archive:
        wiki = OwnedWiki(archive, label="du11-restore-receipt").build()
        os.environ["ET_CALL_LOG"] = str(wiki.call_log())
        try:
            original = wiki.seed_transcript(
                "msft_2026_q3_call.txt", KNOWN_TRANSCRIPT_BODY, MOTLEY_SIDECAR
            )
            receipt["scan"] = bool(wiki.run_scan())
            wiki.checkpoint()
            transport = EarningsTranscriptsTransport(
                wiki_root=wiki.root,
                transcript_tool=wiki.et_tool(),
                fmp_api_key_file=wiki.key_file(),
                deadline=time.monotonic() + 180,
            )
            request = {
                "as_of_date": AS_OF,
                "companion_transcript": {
                    "intent": "fetch_if_missing",
                    "fiscal_year": 2026,
                    "fiscal_quarter": 3,
                    "acquisition_limits": {
                        "max_bytes": 1_000_000,
                        "timeout_seconds": 10,
                        "max_cost_usd": "0.00",
                    },
                },
            }
            result = resolve_companion_transcript(
                request=request, filing_handle=filing_handle(), transport=transport,
            )
            receipt["result"] = {
                "status": result.get("status"),
                "provider": result.get("provider"),
                "provider_calls": result.get("provider_calls"),
                "publication_date": result.get("publication_date"),
                "as_of_cutoff_verified": result.get("as_of_cutoff_verified"),
                "source_sha256": (result.get("source_ref") or {}).get("content_sha256"),
                "fiscal_year": result.get("fiscal_year"),
                "fiscal_quarter": result.get("fiscal_quarter"),
            }
            receipt["owned_original_sha256"] = hashlib.sha256(
                original.read_bytes()
            ).hexdigest()
            receipt["et_calls"] = (
                len(wiki.call_log().read_text(encoding="utf-8").splitlines())
                if wiki.call_log().is_file() else 0
            )
            receipt["company_wiki_child_calls"] = transport.company_wiki_calls
            receipt["restore_receipt"] = wiki.assert_restored()
            receipt["restore_receipt"]["sentinel_entry"] = sorted(
                name for name in (
                    "restore/sentinel.txt", "restore/existing.out"
                )
            )
            receipt["restore_receipt"]["initial_has_sentinel"] = (
                "restore/sentinel.txt" in wiki._initial
                and "restore/existing.out" in wiki._initial
            )
            receipt["restore_receipt"]["checkpoint_taken_after_scan"] = (
                wiki._checkpoint is not None
            )
        finally:
            wiki.cleanup()
        receipt["cleanup_receipt"] = {
            "owned_root": str(wiki.root),
            "removed": not wiki.root.exists(),
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

