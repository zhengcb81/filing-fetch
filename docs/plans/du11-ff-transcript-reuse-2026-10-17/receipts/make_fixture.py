"""Generate a deterministic FMP transcript-tool fixture with a known publication date."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

OUT = Path(
    r"C:\Users\郑曾波\Projects\filing-fetch-du11-local-transcript-reuse\tests\fixtures"
    r"\du11_transcript_reuse\fmp_known_publication.fetched.json"
)

CONTENT = (
    "Operator: Welcome to the Microsoft fiscal 2026 third quarter earnings call. "
    "Satya Nadella: Demand for our cloud and AI platform grew across every segment. "
    "Amy Hood: Commercial bookings increased and operating margin expanded. "
    "Operator: This concludes the synthetic test call."
)
CALL_DATE = "2026-07-22"
RECORD = {"symbol": "MSFT", "period": "Q3", "year": 2026, "date": CALL_DATE, "content": CONTENT}
ORIGINAL = json.dumps([RECORD], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
CANONICAL = CONTENT.replace("\r\n", "\n").replace("\r", "\n").strip().encode("utf-8")

fixture = {
    "schema_version": "earnings-transcript-result/2",
    "request_id": "du11-fixture-request",
    "status": "fetched",
    "provider": "fmp",
    "ticker": "MSFT",
    "exchange": "nasdaq",
    "fiscal_period": "2026-Q3",
    "as_of_date": "2026-09-30",
    "title": "MSFT 2026 Q3 Earnings Call Transcript",
    "source_url": (
        "https://financialmodelingprep.com/stable/earning-call-transcript"
        "?symbol=MSFT&year=2026&quarter=3"
    ),
    "provider_document_id": f"fmp:MSFT:2026:Q3:{CALL_DATE}",
    "call_date": CALL_DATE,
    "publication_date": CALL_DATE,
    "as_of_cutoff_verified": True,
    "extraction_version": "fmp-api-content/1",
    "provider_payload_sha256": hashlib.sha256(ORIGINAL).hexdigest(),
    "canonical_content_sha256": hashlib.sha256(CANONICAL).hexdigest(),
    "content_bytes": len(CANONICAL),
    "provider_payload_encoding": "base64",
    "provider_payload_base64": base64.b64encode(ORIGINAL).decode("ascii"),
    "provider_payload_mime_type": "application/json",
    "effective_url": (
        "https://financialmodelingprep.com/stable/earning-call-transcript"
        "?symbol=MSFT&year=2026&quarter=3"
    ),
    "http_status": 200,
    "retrieved_at": "2026-09-29T12:00:00Z",
    "adapter_name": "earnings-transcripts-transcript-tool",
    "adapter_version": "1.0.0",
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(fixture, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(OUT)
print("payload sha:", fixture["provider_payload_sha256"])
print("canonical sha:", fixture["canonical_content_sha256"], "bytes:", fixture["content_bytes"])
