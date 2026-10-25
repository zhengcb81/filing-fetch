#!/usr/bin/env python
"""Fetch A-share historical financial statements (income/balance/cash flow).

Thin filing-fetch CLI over the company-wiki financial statements service:
the request travels on stdin (or --request-file) and one validated
``financial-statements-response/1`` JSON is written to stdout. Business
statuses (complete/partial/not_found/unavailable) exit 0; request/config
errors exit 2 with an error envelope; unexpected failures exit 1.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from ff_financial_statements import fetch_statements
from filing_contracts import FilingFetchError

STATEMENTS_RESPONSE_SCHEMA_VERSION = "financial-statements-response/1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fetch-statements",
        description=(
            "Fetch or reuse A-share historical financial statements through "
            "company-wiki (Sina public provider, zero cost)."
        ),
    )
    parser.add_argument(
        "--config", type=Path, default=None,
        help="path to company_wiki.json config (default: config/company_wiki.json)",
    )
    parser.add_argument(
        "--request-file", type=Path, default=None,
        help="read JSON request from file instead of stdin",
    )
    parser.add_argument(
        "--timeout-seconds", type=float, default=300.0,
        help="overall deadline for the entire request (default: 300)",
    )
    parser.add_argument("--pretty", action="store_true", help="indent the output")
    args = parser.parse_args(argv)

    if args.timeout_seconds <= 0 or not math.isfinite(args.timeout_seconds):
        print("error: timeout-seconds must be positive and finite", file=sys.stderr)
        return 2
    try:
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="strict")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="strict")
        if args.request_file:
            request = json.loads(args.request_file.read_text(encoding="utf-8"))
        else:
            request = json.loads(sys.stdin.read())
    except (OSError, json.JSONDecodeError) as exc:
        json.dump(
            {
                "schema_version": STATEMENTS_RESPONSE_SCHEMA_VERSION,
                "status": "request_error",
                "error": f"invalid request: {exc}",
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
        )
        sys.stdout.write("\n")
        return 2
    try:
        envelope = fetch_statements(
            config_path=args.config,
            request=request,
            timeout_seconds=args.timeout_seconds,
        )
    except FilingFetchError as exc:
        error_envelope = {
            "schema_version": STATEMENTS_RESPONSE_SCHEMA_VERSION,
            "status": exc.code,
            "error": str(exc),
            "retryable": exc.retryable,
        }
        if exc.producer_exit_code is not None:
            error_envelope["producer_exit_code"] = exc.producer_exit_code
        json.dump(
            error_envelope,
            sys.stdout,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
        )
        sys.stdout.write("\n")
        return 2 if exc.code != "fatal" else 1
    except Exception as exc:  # noqa: BLE001 - surfaced as an honest envelope
        json.dump(
            {
                "schema_version": STATEMENTS_RESPONSE_SCHEMA_VERSION,
                "status": "fatal",
                "error": f"{type(exc).__name__}: {exc}",
                "retryable": False,
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
        )
        sys.stdout.write("\n")
        return 1
    json.dump(envelope, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
