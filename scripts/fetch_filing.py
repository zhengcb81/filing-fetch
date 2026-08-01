"""On-demand company filing fetcher (market-routed, reuse-first).

This is a thin client over company-wiki's acquisition engine. It identifies a
company, then resolves (reuses) an existing filing in company-wiki, or — only
when explicitly authorized — delegates a missing-source download to company-wiki
which routes by market: A-share (CN) -> StockInfoDLSimple/cninfo, HK/US ->
dayu-agent. Newly downloaded bytes are written into company-wiki under
``companies/{entity}/raw/{kind}/`` with immutable provenance; the calculation
engines of consuming skills never import a downloader.

Run directly:

    echo '{"company_query":"AMD","document_kind":"annual_report","fiscal_year":2025,"as_of_date":"2026-07-18"}' \\
      | python scripts/fetch_filing.py [--allow-download] [--config PATH] [--request-file PATH]
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any


from filing_contracts import (  # noqa: E402  re-export
    FILING_RESPONSE_SCHEMA_VERSION,
    CONFIG_TOKEN_RE,
    COMPANY_WIKI_CONFIG_SCHEMA_VERSION,
    COMPANY_WIKI_IDENTITY_SCHEMA_VERSION,
    FilingFetchError,
    validate_handle,
    validate_request,
    _required_text,
)

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPANY_WIKI_CONFIG = SKILL_ROOT / "config" / "company_wiki.json"

# Exponential backoff for transient catalog lock contention (Phase 15.2).
CATALOG_LOCKED_BACKOFF_SECONDS = 5.0
CATALOG_LOCKED_BACKOFF_MULTIPLIER = 2.0


def _validate_company_wiki_root(root: Path) -> Path:
    if not isinstance(root, Path):
        raise TypeError("company_wiki_root must be pathlib.Path")
    try:
        resolved = root.expanduser().resolve(strict=True)
    except OSError as exc:
        raise FilingFetchError(
            f"configured company_wiki_root does not exist: {root}"
        ) from exc
    if not resolved.is_dir():
        raise FilingFetchError("configured company_wiki_root must be a directory")
    catalog_config = resolved / "config" / "source_catalog.yaml"
    if not catalog_config.is_file():
        raise FilingFetchError(
            "configured company_wiki_root lacks config/source_catalog.yaml"
        )
    return resolved


def load_company_wiki_root(*, config_path: Path | None = None) -> Path:
    """Load and validate the persistent company-wiki root configuration."""

    if config_path is not None and not isinstance(config_path, Path):
        raise TypeError("config_path must be pathlib.Path or None")
    selected = config_path or DEFAULT_COMPANY_WIKI_CONFIG
    try:
        selected = selected.expanduser().resolve(strict=True)
    except OSError as exc:
        raise FilingFetchError(
            f"company-wiki config does not exist: {selected}"
        ) from exc
    if not selected.is_file():
        raise FilingFetchError("company-wiki config must be a file")
    try:
        payload = json.loads(selected.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FilingFetchError(f"invalid company-wiki config: {exc}") from exc
    if not isinstance(payload, dict):
        raise FilingFetchError("company-wiki config must be an object")
    if set(payload) != {"schema_version", "company_wiki_root"}:
        raise FilingFetchError(
            "company-wiki config must contain exact schema_version/company_wiki_root fields"
        )
    if payload["schema_version"] != COMPANY_WIKI_CONFIG_SCHEMA_VERSION:
        raise FilingFetchError(
            f"company-wiki config schema_version must be {COMPANY_WIKI_CONFIG_SCHEMA_VERSION}"
        )
    configured = payload["company_wiki_root"]
    if (
        not isinstance(configured, str)
        or not configured.strip()
        or configured != configured.strip()
    ):
        raise FilingFetchError(
            "company-wiki config company_wiki_root must be non-empty trimmed text"
        )
    tokens = {
        "SKILL_ROOT": str(SKILL_ROOT),
        "USER_PROFILE": os.environ.get("USERPROFILE") or str(Path.home()),
    }

    def replace_token(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in tokens:
            raise FilingFetchError(f"unsupported token in company_wiki_root: {name}")
        return tokens[name]

    expanded = CONFIG_TOKEN_RE.sub(replace_token, configured)
    root = Path(expanded).expanduser()
    if not root.is_absolute():
        root = selected.parent / root
    return _validate_company_wiki_root(root)


def _command_arguments(request: dict[str, Any]) -> list[str]:
    required = ("entity", "document_kind", "as_of_date")
    for name in required:
        _required_text(request.get(name), name)
    arguments = [
        "--entity",
        request["entity"],
        "--document-kind",
        request["document_kind"],
        "--as-of-date",
        request["as_of_date"],
    ]
    options = {
        "market": "--market",
        "security_id": "--security-id",
        "form_type": "--form-type",
        "fiscal_period": "--fiscal-period",
        "language": "--language",
        "provider": "--provider",
        "provider_document_id": "--provider-document-id",
    }
    for name, flag in options.items():
        value = request.get(name)
        if value is not None:
            arguments.extend((flag, _required_text(value, name)))
    fiscal_year = request.get("fiscal_year")
    if fiscal_year is not None:
        if isinstance(fiscal_year, bool) or not isinstance(fiscal_year, int):
            raise FilingFetchError("fiscal_year must be an integer")
        arguments.extend(("--fiscal-year", str(fiscal_year)))
    return arguments


def _identity_arguments(request: dict[str, Any]) -> list[str]:
    query = _required_text(request.get("company_query"), "company_query")
    if "entity" in request or "security_id" in request:
        raise FilingFetchError(
            "company_query cannot be combined with entity or security_id"
        )
    for name in ("document_kind", "as_of_date"):
        _required_text(request.get(name), name)
    arguments = ["--query", query]
    for name, flag in (("market", "--market"), ("exchange", "--exchange")):
        value = request.get(name)
        if value is not None:
            arguments.extend((flag, _required_text(value, name)))
    return arguments


def _run_company_wiki_json(
    *,
    command: list[str],
    root: Path,
    timeout_seconds: float,
    action: str,
) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
            creationflags=creationflags,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FilingFetchError(f"company-wiki {action} failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip()[-2000:] or "no stderr"
        code = "fatal"
        try:
            structured = json.loads(completed.stderr.strip())
        except json.JSONDecodeError:
            structured = None
        if (
            isinstance(structured, dict)
            and structured.get("error_type") == "CatalogOperationLockedError"
        ):
            code = "catalog_locked"
        raise FilingFetchError(
            f"company-wiki {action} exited {completed.returncode}: {detail}",
            code=code,
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise FilingFetchError(f"company-wiki {action} stdout is not JSON") from exc
    if not isinstance(payload, dict):
        raise FilingFetchError(f"company-wiki {action} response must be an object")
    return payload


def _run_company_wiki_json_retry(
    *,
    command: list[str],
    root: Path,
    action: str,
    deadline: float,
) -> dict[str, Any]:
    """Run a company-wiki CLI call, retrying transient catalog lock
    contention with exponential backoff bounded by the overall deadline."""
    attempt = 1
    backoff = CATALOG_LOCKED_BACKOFF_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FilingFetchError(
                f"overall deadline exceeded before {action}", code="upstream_error"
            )
        try:
            return _run_company_wiki_json(
                command=command,
                root=root,
                timeout_seconds=remaining,
                action=action,
            )
        except FilingFetchError as exc:
            if exc.code != "catalog_locked":
                raise
            wait = min(backoff, remaining)
            if wait <= 0:
                raise FilingFetchError(
                    f"overall deadline exceeded retrying {action}: {exc}",
                    code="upstream_error",
                ) from exc
            print(
                f"[filing-fetch] {action} blocked by a running catalog operation "
                f"(attempt {attempt}); retrying in {wait:.1f}s: {exc}",
                file=sys.stderr,
            )
            time.sleep(wait)
            attempt += 1
            backoff *= CATALOG_LOCKED_BACKOFF_MULTIPLIER


def _resolved_company_identity(payload: dict[str, Any]) -> dict[str, Any]:
    status = payload.get("status")
    reason = payload.get("reason")
    if status != "resolved":
        raise FilingFetchError(
            f"company identity is not uniquely resolved: {status} / {reason}"
        )
    if payload.get("schema_version") != COMPANY_WIKI_IDENTITY_SCHEMA_VERSION:
        raise FilingFetchError("company identity schema_version is unsupported")
    resolved = payload.get("resolved")
    if not isinstance(resolved, dict):
        raise FilingFetchError("resolved company identity is missing")
    for name in (
        "canonical_name",
        "market",
        "exchange",
        "ticker",
        "security_id",
        "match_basis",
        "matched_value",
        "source_name",
        "source_url",
        "source_record_id",
    ):
        _required_text(resolved.get(name), f"company_identity.{name}")
    if resolved.get("verified") is not True or resolved.get("active") is not True:
        raise FilingFetchError(
            "company identity must be verified and active before source resolution"
        )
    if resolved["market"] not in {"CN", "HK", "US"}:
        raise FilingFetchError("company identity market is unsupported")
    return dict(resolved)


def resolve_filing(
    *,
    request: dict[str, Any],
    company_wiki_root: Path | None = None,
    config_path: Path | None = None,
    allow_download: bool = False,
    timeout_seconds: float = 900.0,
) -> dict[str, Any]:
    """Identify an optional company query, then resolve or explicitly ensure a filing.

    The default path calls the read-only ``resolve`` command and reuses an
    existing company-wiki filing. ``allow_download=True`` calls
    ``ensure --allow-download``; company-wiki then routes the download by market
    (CN -> StockInfo, HK/US -> dayu) and writes any new bytes into
    ``companies/{entity}/raw/{kind}/``. A ``company_query`` is resolved to one
    verified active security before either source command is constructed.
    """

    if company_wiki_root is not None and config_path is not None:
        raise ValueError("company_wiki_root cannot be combined with config_path")
    if not isinstance(request, dict):
        raise TypeError("request must be a dict")
    if not isinstance(allow_download, bool):
        raise TypeError("allow_download must be boolean")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    validate_request(request)
    deadline = time.monotonic() + timeout_seconds
    root = (
        _validate_company_wiki_root(company_wiki_root)
        if company_wiki_root is not None
        else load_company_wiki_root(config_path=config_path)
    )
    command_prefix = [
        sys.executable,
        "-m",
        "company_wiki.source_catalog.cli",
        "--config",
        str(root / "config" / "source_catalog.yaml"),
    ]
    normalized_request = request
    company_identity = None
    # Every request must pass through verified/active identity before source
    # resolution.  Legacy explicit-identity requests are rejected; callers must
    # provide a ``company_query`` so the identity is independently verified.
    if "company_query" not in request:
        raise FilingFetchError(
            "explicit entity/security_id request is unsupported in schema 1.1; "
            "provide a company_query instead"
        )
    if "company_query" in request:
        identity_payload = _run_company_wiki_json_retry(
            command=[
                *command_prefix,
                "identify",
                *_identity_arguments(request),
            ],
            root=root,
            action="identify",
            deadline=deadline,
        )
        company_identity = _resolved_company_identity(identity_payload)
        normalized_request = {
            key: value
            for key, value in request.items()
            if key not in {"company_query", "exchange"}
        }
        normalized_request.update(
            {
                "entity": company_identity["canonical_name"],
                "market": company_identity["market"],
                "security_id": company_identity["security_id"],
            }
        )
    action = "ensure" if allow_download else "resolve"
    command = [
        *command_prefix,
        action,
        *_command_arguments(normalized_request),
    ]
    if allow_download:
        if not normalized_request.get("market") or not normalized_request.get(
            "security_id"
        ):
            raise FilingFetchError(
                "explicit download requires market and security_id"
            )
        command.extend(
            (
                "--allow-download",
                "--acquisition-config",
                str(root / "config" / "source_acquisition.yaml"),
            )
        )
    payload = _run_company_wiki_json_retry(
        command=command,
        root=root,
        action=action,
        deadline=deadline,
    )
    resolution = payload.get("resolution") if allow_download else payload
    if not isinstance(resolution, dict):
        raise FilingFetchError("company-wiki resolution is missing")
    if resolution.get("status") not in {"reused_exact", "reused_equivalent"}:
        raise FilingFetchError(
            f"source is not reusable: {resolution.get('status')} / {resolution.get('reason')}"
        )
    matches = resolution.get("matches")
    if not isinstance(matches, list) or len(matches) != 1 or not isinstance(matches[0], dict):
        raise FilingFetchError("company-wiki did not return exactly one source handle")
    handle = dict(matches[0])
    if handle.get("capture_ready") is not True:
        raise FilingFetchError(
            "source lacks capture provenance: "
            + ", ".join(str(item) for item in handle.get("missing_capture_fields", []))
        )
    handle["request_id"] = resolution.get("request_id")
    validate_handle(handle, request, root)
    if company_identity is not None:
        handle["company_identity"] = company_identity
    return handle


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for on-demand filing fetch.

    Exit codes: 0 = capture-ready filing found/reused, 1 = fatal error,
    2 = filing not reusable / not found (or config/identity problem).
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="filing-fetch",
        description="Resolve or download a company filing into company-wiki.",
    )
    parser.add_argument(
        "--allow-download",
        action="store_true",
        help="allow a market-routed download if the filing is missing (default: read-only reuse)",
    )
    parser.add_argument("--config", type=Path, default=None, help="path to company_wiki.json config")
    parser.add_argument("--request-file", type=Path, default=None, help="read JSON request from file instead of stdin")
    parser.add_argument("--timeout-seconds", type=float, default=900.0, help="overall deadline for the entire request (default: 900)")
    args = parser.parse_args(argv)

    if args.timeout_seconds <= 0 or not math.isfinite(args.timeout_seconds):
        print("error: timeout-seconds must be positive and finite", file=sys.stderr)
        return 2

    try:
        if hasattr(sys.stdin, "reconfigure"):
            # Phase 16.4: Windows pipes decode stdin with the locale codepage
            # (GBK), corrupting UTF-8 Chinese queries. Force UTF-8 so piped
            # requests behave like --request-file.
            sys.stdin.reconfigure(encoding="utf-8", errors="strict")
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="strict")
        if args.request_file:
            request = json.loads(args.request_file.read_text(encoding="utf-8"))
        else:
            request = json.loads(sys.stdin.read())
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        handle = resolve_filing(
            request=request,
            config_path=args.config,
            allow_download=args.allow_download,
            timeout_seconds=args.timeout_seconds,
        )
        output = {
            "schema_version": FILING_RESPONSE_SCHEMA_VERSION,
            "status": "capture_ready",
            "handle": handle,
        }
        json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except FilingFetchError as exc:
        error_response: dict[str, Any] = {
            "schema_version": FILING_RESPONSE_SCHEMA_VERSION,
            "status": exc.code,
            "error": str(exc),
            "error_code": exc.code,
            "retryable": exc.retryable,
        }
        json.dump(error_response, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 2
    except Exception as exc:
        json.dump({"schema_version": FILING_RESPONSE_SCHEMA_VERSION, "status": "fatal", "error": str(exc), "error_code": "fatal", "retryable": False}, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 1


__all__ = [
    "COMPANY_WIKI_CONFIG_SCHEMA_VERSION",
    "COMPANY_WIKI_IDENTITY_SCHEMA_VERSION",
    "DEFAULT_COMPANY_WIKI_CONFIG",
    "FilingFetchError",
    "load_company_wiki_root",
    "main",
    "resolve_filing",
]


if __name__ == "__main__":
    raise SystemExit(main())
