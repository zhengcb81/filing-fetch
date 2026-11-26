"""Configure the public CWP and transcript ports for a standalone FF job."""

from __future__ import annotations

from pathlib import Path

from ff_errors import FilingFetchError
from transcript_companion import resolve_standalone_transcript, validate_standalone_transcript_request


def fetch_standalone_transcript(
    request: dict, *, config_path: Path | None, timeout_seconds: float, stats: dict[str, int],
) -> dict:
    """Use the original transcript transport after verified listing lookup."""
    from fetch_filing import (
        DEFAULT_COMPANY_WIKI_CONFIG, filing_operation_deadline, identify_company, load_company_wiki_root,
    )
    from transcript_tool_transport import EarningsTranscriptsTransport

    validate_standalone_transcript_request(request)
    deadline = filing_operation_deadline(request, timeout_seconds=timeout_seconds)
    selected = request["identity"]
    try:
        root = load_company_wiki_root(config_path=config_path)
        query = {
            "company_query": selected["ticker"], "market": selected["market"],
            "exchange": selected.get("exchange"), "document_kind": "earnings_transcript",
            "as_of_date": request["as_of_date"],
        }
        identity = identify_company(request=query, root=root, deadline=deadline, stats=stats)
        if identity["ticker"].casefold() != selected["ticker"].casefold():
            raise FilingFetchError("transcript listing ticker differs from resolved ticker",
                                   code="identity_error")
        transport = EarningsTranscriptsTransport(
            wiki_root=root, config_path=config_path or DEFAULT_COMPANY_WIKI_CONFIG, deadline=deadline,
        )
    except FilingFetchError as exc:
        exc.stage = "identify"
        raise
    result = resolve_standalone_transcript(request, identity, transport)
    stats["calls"] += transport.company_wiki_calls
    stats["downloads"] += int(result["status"] == "downloaded")
    return result
