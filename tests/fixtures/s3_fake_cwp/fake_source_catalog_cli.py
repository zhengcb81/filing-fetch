"""Fake ``company_wiki.source_catalog.cli`` for the FF-S3 bounded-run tests.

The real company-wiki producer does not accept the three ``--max-download-*``
flags yet (root implements them).  This fixture stands in for the producer so
filing-fetch's own behaviour - the argv it actually builds, the deadline it
actually applies, the output it actually tolerates - can be observed from the
outside without any network, LLM, real API key or production CWP config.

Modes (``S3_FAKE_MODE``):

``default``           answer identify/ensure with a well-formed payload
``reject_limits``     exit 2 the way argparse does on an unknown flag
``slow``              sleep ``S3_FAKE_SLEEP`` seconds before answering
``flood``             write ``S3_FAKE_FLOOD_BYTES`` bytes to stdout
``noisy_failure``     exit 1 with a secret-looking stderr body
"""

from __future__ import annotations

import json
import os
import sys
import time

LIMIT_FLAGS = ("--max-download-bytes", "--max-download-seconds", "--max-download-cost-usd")
SUBCOMMANDS = ("identify", "ensure", "resolve", "close-gap")
DIGEST = "e" * 64

IDENTITY = {
    "schema_version": "1.0",
    "query": "ACME",
    "normalized_query": "acme",
    "market_hint": "US",
    "exchange_hint": None,
    "status": "resolved",
    "reason": "fixture identity",
    "resolved": {
        "canonical_name": "Acme Inc.",
        "market": "US",
        "exchange": "NASDAQ",
        "ticker": "ACME",
        "security_id": "ACME",
        "match_basis": "ticker",
        "matched_value": "ACME",
        "source_name": "fixture",
        "source_url": "https://example.test/security/ACME",
        "source_record_id": "urn:fixture:security:US:ACME",
        "verified": True,
        "active": True,
    },
    "candidates": [],
}


def _subcommand(argv: list[str]) -> str | None:
    for token in argv:
        if token in SUBCOMMANDS:
            return token
    return None


def _record(argv: list[str], subcommand: str | None, stdin: str | None) -> None:
    capture = os.environ.get("S3_FAKE_CAPTURE")
    if not capture:
        return
    payload = {
        "subcommand": subcommand,
        "argv": argv,
        "cwd": os.getcwd(),
        "pid": os.getpid(),
        "stdin": stdin,
    }
    with open(capture, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _stdin_text() -> str | None:
    if os.environ.get("S3_FAKE_READ_STDIN") != "1":
        return None
    data = sys.stdin.buffer.read(1_000_000)
    return data.decode("utf-8", errors="replace")


def _gap_payload(operation: str) -> dict:
    request_id = "urn:fixture:source-request:sha256:" + "1" * 64
    return {
        "operation_schema_version": "1.0",
        "operation": operation,
        "status": "gap",
        "request_id": request_id,
        "outcome": "gap",
        "download_events": 0,
        "policy_hash": DIGEST,
        "gap_plan": {
            "schema_version": "1.0",
            "gap_hash": DIGEST,
            "request_id": request_id,
        },
    }


def main() -> int:
    argv = sys.argv[1:]
    subcommand = _subcommand(argv)
    _record(argv, subcommand, _stdin_text())
    mode = os.environ.get("S3_FAKE_MODE", "default")

    if mode == "noisy_failure":
        sys.stderr.write(
            "FMP_API_KEY=FAKE_SECRET_KEY_DO_NOT_LEAK "
            "path=<private-root>/config/FMP_API_KEY.txt\n"
        )
        return 1

    if mode == "flood":
        sys.stdout.flush()
        sys.stdout.buffer.write(b"x" * int(os.environ.get("S3_FAKE_FLOOD_BYTES", "34603008")))
        sys.stdout.buffer.flush()
        return 0

    if mode == "slow" and subcommand == "ensure":
        time.sleep(float(os.environ.get("S3_FAKE_SLEEP", "20")))

    if mode == "reject_limits" and any(flag in argv for flag in LIMIT_FLAGS):
        sys.stderr.write(
            "usage: cli.py error: unrecognized arguments: "
            + " ".join(flag for flag in LIMIT_FLAGS if flag in argv)
            + "\n"
        )
        return 2

    if subcommand == "identify":
        payload = IDENTITY
    elif subcommand in ("ensure", "close-gap"):
        payload = _gap_payload(subcommand)
    else:
        payload = {"status": "ok"}
    sys.stdout.write(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
