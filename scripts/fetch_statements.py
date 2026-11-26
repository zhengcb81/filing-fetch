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
import hashlib
import json
import math
import sys
from pathlib import Path

from ff_financial_statements import fetch_statements
from ff_run_input import read_request_bytes, replay_input
from ff_statement_feedback import begin_statement_run, publish_statement_response
from ff_errors import FilingFetchError

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
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code:
            publish_statement_response(begin_statement_run(), "argument_error", exc.code, error=exc)
        raise

    run = begin_statement_run()
    if args.timeout_seconds <= 0 or not math.isfinite(args.timeout_seconds):
        publish_statement_response(run, "invalid_timeout", 2)
        print("error: timeout-seconds must be positive and finite", file=sys.stderr)
        return 2
    try:
        if hasattr(sys.stdin, "reconfigure"):
            sys.stdin.reconfigure(encoding="utf-8", errors="strict")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="strict")
        raw = read_request_bytes(args.request_file)
        request_sha256 = hashlib.sha256(raw).hexdigest()
        try:
            request = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            run.mark("request_read", request_sha256=request_sha256)
            raise
        run.mark("request_read", request_sha256=request_sha256,
                 input=replay_input(request, request_file=args.request_file))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        publish_statement_response(run, "request_error", 2, error=exc)
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
            before_dispatch=lambda: run.mark("dispatching", external_effect="possible", cost_state="unknown"),
            on_child_exit=run.child_exited,
        )
    except FilingFetchError as exc:
        exit_code = 2 if exc.code != "fatal" else 1
        publish_statement_response(run, exc.code, exit_code, error=exc)
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
        return exit_code
    except Exception as exc:  # noqa: BLE001 - surfaced as an honest envelope
        publish_statement_response(run, "fatal", 1, error=exc)
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
    # W19-R3: a structured CWP error status maps to its own exit code.
    status = envelope["status"]
    exit_code = 2 if status in ("request_error", "config_error") else 1 if status == "fatal" else 0
    publish_statement_response(run, status, exit_code, envelope=envelope)
    json.dump(envelope, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
