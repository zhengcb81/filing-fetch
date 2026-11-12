"""Independent ET CLI stand-in for MB-FF isolation tests.

The real earnings-transcripts tool owns provider HTTP, extraction and usage
accounting.  This fixture only emits the *public* result/usage wires so the FF
transport can be observed launching it as its own command, with its own cwd,
without importing any provider implementation.

It is deliberately a plain ``.py`` file: the legacy deployment configuration
``earnings_transcripts_tool`` names a script path and the current interpreter
launches it.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ORIGINAL = (
    b'{"symbol":"AMD","period":"Q3","year":2026,'
    b'"content":"fixture transcript body"}'
)
DIGEST = hashlib.sha256(ORIGINAL).hexdigest()


def _log(entry: dict[str, Any]) -> None:
    path = os.environ.get("MBFF_CALL_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _usage(request_id: str) -> dict[str, Any]:
    if os.environ.get("MBFF_ET_USAGE", "known") == "unknown":
        return {"schema_version": "earnings-retrieval-usage/1", "request_id": request_id,
                "usage_complete": False, "usage": None}
    return {
        "schema_version": "earnings-retrieval-usage/1",
        "request_id": request_id,
        "usage_complete": True,
        "usage": {
            "requests_used": 1,
            "response_bytes_used": len(ORIGINAL),
            "exhausted": None,
        },
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    raw = sys.stdin.buffer.read()
    request = json.loads(raw.decode("utf-8")) if raw else {}
    _log(
        {
            "operation": "et_tool",
            "argv": argv,
            "full_argv": list(sys.argv),
            "cwd": str(Path.cwd()),
            "has_fmp_key": bool(os.environ.get("FMP_API_KEY")),
            "has_fmp_key_file": bool(os.environ.get("FMP_API_KEY_FILE")),
            "pythonpath": os.environ.get("PYTHONPATH"),
            "scenario": os.environ.get("MBFF_SCENARIO"),
            "stdin": request,
            "pid": os.getpid(),
            "executable": sys.executable,
        }
    )
    request_id = request["request_id"]
    if os.environ.get("MBFF_ET_RESULT", "fetched") == "bad_json":
        sys.stdout.write("not-json")
        sys.stdout.flush()
        sys.stderr.write(json.dumps(_usage(request_id), ensure_ascii=False))
        sys.stderr.flush()
        return 0

    result = {
        "schema_version": "earnings-transcript-result/2",
        "request_id": request_id,
        "status": "fetched",
        "provider": "fmp",
        "ticker": "AMD",
        "exchange": "nasdaq",
        "fiscal_period": f"{request['fiscal_year']}-Q{request['fiscal_quarter']}",
        "as_of_date": request["as_of_date"],
        "title": "AMD fixture earnings call transcript",
        "source_url": "https://example.test/transcripts/amd",
        "provider_document_id": "fmp:AMD:2026:Q3",
        "call_date": "2026-07-22",
        "publication_date": None,
        "as_of_cutoff_verified": False,
        "extraction_version": "fixture/1",
        "provider_payload_sha256": DIGEST,
        "canonical_content_sha256": DIGEST,
        "content_bytes": len(ORIGINAL),
        "provider_payload_encoding": "base64",
        "provider_payload_base64": base64.b64encode(ORIGINAL).decode("ascii"),
        "provider_payload_mime_type": "application/json",
        "effective_url": "https://example.test/transcripts/amd",
        "http_status": 200,
        "retrieved_at": "2026-11-12T00:00:00Z",
        "adapter_name": "fixture-transcript-tool",
        "adapter_version": "1.0.0",
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()
    sys.stderr.write(json.dumps(_usage(request_id), ensure_ascii=False))
    sys.stderr.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
