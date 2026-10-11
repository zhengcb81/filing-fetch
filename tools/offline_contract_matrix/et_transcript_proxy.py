"""FF-owned ET test-proxy for the offline cross-repo contract matrix.

This is a **test proxy**, not an unmodified production binary. It sits where
filing-fetch's ``earnings_transcripts_tool`` points and forwards the real
``transcript_tool.main`` argv unchanged. It starts the REAL retrieval
supervisor / worker / ``transcript_api`` and replaces ONLY the worker's HTTP
session, using the pre-existing private launcher seam
(``tests.test_retrieval_runtime:build_fake_session``). No production CLI flag
and no site-packages modification is introduced.

Environment contract (set by the runner, inherited through filing-fetch):
  W06_ET_ROOT       absolute path to the earnings-transcripts code root
  W06_MATRIX_STATE  absolute path to a JSON scenario file
                    {"scenario", "content_utf8", "call_date", "publication_date",
                     "response_bytes", "calls_file", "et_temp_root"}

Every report line this proxy feeds back must be labeled test-proxy; it must
never be presented as an un-proxied production run.
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path


def _load_state() -> dict:
    state_path = os.environ.get("W06_MATRIX_STATE")
    if not state_path:
        raise SystemExit("W06_MATRIX_STATE is not set")
    return json.loads(Path(state_path).read_text(encoding="utf-8"))


def _build_fmp_payload(request: dict, state: dict) -> bytes:
    """Synthesise a provider response in the requested fiscal identity.

    The content is the ORIGINAL language (no translation). The JSON shape is the
    FMP ``[{symbol, period, year, date, content}]`` array that ``transcript_api``
    consumes. ``response_bytes`` pads the row so byte-budget cases are testable.
    """
    symbol = request.get("ticker", "SYN")
    year = request.get("fiscal_year", 2026)
    quarter = request.get("fiscal_quarter", 1)
    # A wrong_quarter scenario deliberately returns a different period so the
    # consumer's provenance check must reject it.
    if state.get("scenario") == "wrong_quarter":
        period = f"Q{(quarter % 4) + 1}"
    else:
        period = f"Q{quarter}"
    date = state.get("call_date") or request.get("as_of_date", "2026-01-01")
    content = state.get("content_utf8") or (
        "Synthetic offline earnings-call transcript in the original language. "
        "Management discussed demand, product launches, execution, margins and risk. "
    )
    row = {"symbol": symbol, "period": period, "year": year, "date": date,
           "content": content, "padding": ""}
    raw = json.dumps([row], ensure_ascii=False).encode("utf-8")
    size = state.get("response_bytes")
    if isinstance(size, int) and size > len(raw):
        row["padding"] = "x" * (size - len(raw))
        raw = json.dumps([row], ensure_ascii=False).encode("utf-8")
    return raw


def main(argv: list[str] | None = None) -> int:
    et_root = os.environ.get("W06_ET_ROOT")
    if not et_root:
        raise SystemExit("W06_ET_ROOT is not set")
    et_path = Path(et_root)
    if str(et_path) not in sys.path:
        sys.path.insert(0, str(et_path))

    import transcript_tool  # noqa: E402  (from the supplied ET root)
    from tests.test_retrieval_runtime import fake_spec  # noqa: E402
    from tests.test_transcript_api import FakeResponse, FMP_URL  # noqa: E402

    args = list(sys.argv[1:] if argv is None else argv)
    # Capabilities use real ET metadata and create no provider request.
    if "--capabilities" in args:
        return transcript_tool.main(args)

    state = _load_state()
    scenario = state.get("scenario", "success")
    calls_file = state.get("calls_file")
    runtime = Path(state["et_temp_root"])
    runtime.mkdir(parents=True, exist_ok=True)

    original_stdin = sys.stdin.read()
    try:
        request = json.loads(original_stdin)
    except ValueError:
        request = {}
    if not isinstance(request, dict):
        request = {}

    # Scenario -> fake worker HTTP (or worker failure). Only the worker HTTP is
    # replaced; the supervisor / worker / transcript_api run for real.
    if scenario == "worker_loss":
        spec = fake_spec(build_failure="SystemExit:7", calls_file=calls_file)
    else:
        status = 200
        content_type = "application/json"
        payload = _build_fmp_payload(request, state)
        if scenario == "entitlement_402":
            status, payload = 402, b""
        elif scenario == "http_429":
            status, payload = 429, b""
        elif scenario == "http_500":
            status, payload = 500, b""
        response = FakeResponse(FMP_URL, payload, status_code=status,
                                content_type=content_type)
        spec = fake_spec({FMP_URL: response}, calls_file=calls_file)

    try:
        sys.stdin = io.StringIO(original_stdin)
        real_out, real_err = sys.stdout, sys.stderr
        cap_out, cap_err = io.StringIO(), io.StringIO()
        sys.stdout, sys.stderr = cap_out, cap_err
        try:
            rc = transcript_tool.main(
                args,
                _retrieval_launcher="tests.test_retrieval_runtime:build_fake_session",
                _retrieval_spec=spec,
                _retrieval_temp_root=runtime,
            )
        finally:
            sys.stdout, sys.stderr = real_out, real_err
        out_text, err_text = cap_out.getvalue(), cap_err.getvalue()
        # Persist real ET receipts (result JSON on stdout, usage receipt on
        # stderr) as test-proxy artifacts for the report's receipt refs.
        receipts = Path(state.get("receipts_dir") or (runtime.parent / "receipts"))
        receipts.mkdir(parents=True, exist_ok=True)
        tag = state.get("receipt_tag") or "et"
        (receipts / f"{tag}.result.json").write_text(out_text, encoding="utf-8")
        (receipts / f"{tag}.usage.json").write_text(err_text, encoding="utf-8")
        # Re-emit unchanged so filing-fetch's transport sees the real contract.
        real_out.write(out_text)
        real_err.write(err_text)
        return rc
    finally:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
