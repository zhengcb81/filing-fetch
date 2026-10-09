"""Subprocess transport from filing-fetch to ET and company-wiki."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


_LOOKUP_SCHEMA = "company-wiki-transcript-import-lookup-request/1"
_IMPORT_SCHEMA = "company-wiki-transcript-import-request/2"
_IMPORT_RESPONSE_SCHEMA = "company-wiki-transcript-import-response/3"
_SOURCE_REQUEST_SCHEMA = "1.0"
# One ceiling for every JSON subprocess this repo spawns; the shared bounded
# transport enforces it DURING read, so no transport buffers an unbounded child.
from ff_process_transport import (  # noqa: E402
    MAX_JSON_OUTPUT_BYTES,
    TransportError,
    run_bounded_json as _run_bounded_json,
)

# The ET CLI supervises a worker whose own deadline is ``timeout_seconds``.
# FF must leave time for ET to terminate/reap that worker and remove its result
# directory before the outer subprocess timeout expires.
_ET_CLEANUP_GRACE_SECONDS = 3.0
_ET_MAX_TIMEOUT_SECONDS = 60
# Public ET earnings-transcript-request/1 canonical UTF-8 body ceiling.
# The operation raw-response budget is separate and may legitimately be wider.
_ET_MAX_BODY_BYTES = 10 * 1024 * 1024
_MAX_REF_FIELDS = frozenset(
    {
        "schema_version",
        "document_id",
        "source_id",
        "content_sha256",
        "byte_size",
        "mime_type",
    }
)


def _usage_counters(usage: object) -> tuple[int, int] | None:
    """Validate the two measured counters independently from receipt identity."""
    if not isinstance(usage, dict):
        return None
    count, size = usage.get("requests_used"), usage.get("response_bytes_used")
    if type(count) is not int or count < 0 or type(size) is not int or size < 0:
        return None
    return count, size


def _provider_usage(raw: bytes, request_id: str) -> dict[str, Any]:
    """Read one final supervisor receipt; absent/partial usage stays unknown."""
    unknown = {"provider_requests": None, "provider_response_bytes": None, "provider_usage_complete": False}
    if len(raw) > 8192:
        return unknown
    try:
        receipt = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError):
        return unknown
    if not isinstance(receipt, dict) or receipt.get("schema_version") != "earnings-retrieval-usage/1":
        return unknown
    if receipt.get("request_id") != request_id or receipt.get("usage_complete") is not True:
        return unknown
    counters = _usage_counters(receipt.get("usage"))
    if counters is None:
        return unknown
    count, size = counters
    return {"provider_requests": count, "provider_response_bytes": size, "provider_usage_complete": True}


class EarningsTranscriptsTransport:
    """Call the configured ET tool, then let CWP own and verify original bytes."""

    def __init__(
        self,
        *,
        wiki_root: Path,
        transcript_tool: Path | None = None,
        deadline: float,
    ) -> None:
        self.wiki_root = wiki_root.resolve(strict=True)
        configured = transcript_tool or (
            Path(os.environ["EARNINGS_TRANSCRIPTS_TOOL"])
            if os.environ.get("EARNINGS_TRANSCRIPTS_TOOL")
            else None
        )
        self.transcript_tool = configured.resolve(strict=True) if configured else None
        self.deadline = deadline
        self.company_wiki_calls = 0
        self._pending: dict[str, Any] | None = None
        self._last_provider_usage: dict[str, Any] = {}

    def _remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        return remaining

    def _source_request(
        self,
        *,
        identity: dict[str, Any],
        fiscal_year: int,
        fiscal_quarter: int,
        as_of_date: str,
        allow_download: bool,
    ) -> dict[str, Any]:
        return {
            "entity": identity["canonical_name"],
            "document_kind": "investor_call_transcript",
            "as_of_date": as_of_date,
            "market": identity["market"],
            "security_id": identity["security_id"],
            "form_type": None,
            "fiscal_year": fiscal_year,
            "fiscal_period": f"Q{fiscal_quarter}",
            "language": None,
            "provider": "fmp",
            "provider_document_id": None,
            "mode": "exact",
            "allow_download": allow_download,
            "schema_version": _SOURCE_REQUEST_SCHEMA,
        }

    def _wiki_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("FMP_API_KEY", None)
        env["PYTHONUTF8"] = "1"
        src = str(self.wiki_root / "src")
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = src if not existing else src + os.pathsep + existing
        return env

    @staticmethod
    def _creationflags() -> int:
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0

    def _run_json(
        self,
        command: list[str],
        payload: dict[str, Any],
        *,
        cwd: Path,
        env: dict[str, str],
        maximum: int = MAX_JSON_OUTPUT_BYTES,
    ) -> tuple[dict[str, Any], int]:
        self.company_wiki_calls += 1
        stdout, stderr, code = _run_bounded_json(
            command,
            timeout_seconds=self._remaining(),
            input_bytes=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            ),
            cwd=str(cwd),
            env=env,
            stdout_cap_bytes=maximum,
        )
        try:
            result = json.loads(stdout.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("child output was not bounded UTF-8 JSON") from exc
        if not isinstance(result, dict):
            raise ValueError("child JSON result was not an object")
        if code != 0:
            _ = stderr  # bounded; classification stays the caller's job
        return result, code

    def _query(self, source_request: dict[str, Any]) -> dict[str, Any]:
        request = {
            "schema_version": _LOOKUP_SCHEMA,
            "source_request": source_request,
        }
        command = [
            sys.executable,
            "-m",
            "company_wiki.source_catalog.source_query_cli",
            "--config",
            str(self.wiki_root / "config" / "source_catalog.yaml"),
        ]
        payload, code = self._run_json(
            command,
            request,
            cwd=self.wiki_root,
            env=self._wiki_env(),
        )
        if payload.get("schema_version") != "2.0":
            raise ValueError("company-wiki source query schema is unsupported")
        if code not in (0, 2):
            raise ValueError("company-wiki source query failed")
        return payload

    @staticmethod
    def _valid_ref(value: object) -> dict[str, Any]:
        import re

        if not isinstance(value, dict) or set(value) != _MAX_REF_FIELDS:
            raise ValueError("company-wiki SourceRef shape is invalid")
        if value.get("schema_version") != "2.0":
            raise ValueError("company-wiki SourceRef version is unsupported")
        sha = value.get("content_sha256")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("company-wiki SourceRef SHA is invalid")
        if type(value.get("byte_size")) is not int or value["byte_size"] < 0:
            raise ValueError("company-wiki SourceRef byte size is invalid")
        for key, kind in (("document_id", "document"), ("source_id", "source")):
            prefix = f"urn:company-wiki:{kind}:sha256:"
            item = value.get(key)
            if not isinstance(item, str) or not item:
                raise ValueError("company-wiki SourceRef id is invalid")
            if item.startswith("urn:company-wiki:") and item != prefix + sha:
                raise ValueError("company-wiki SourceRef id does not match SHA")
        if not isinstance(value.get("mime_type"), str) or not value["mime_type"]:
            raise ValueError("company-wiki SourceRef MIME type is invalid")
        return dict(value)

    def _verified_open(self, ref: dict[str, Any]) -> None:
        command = [
            sys.executable,
            "-m",
            "company_wiki.source_catalog.source_reader_cli",
            "--config",
            str(self.wiki_root / "config" / "source_catalog.yaml"),
            "--document-id",
            ref["document_id"],
            "--source-id",
            ref["source_id"],
            "--content-sha256",
            ref["content_sha256"],
            "--purpose",
            "preview",
        ]
        self.company_wiki_calls += 1
        stdout, stderr, code = _run_bounded_json(
            command,
            timeout_seconds=self._remaining(),
            input_bytes=None,
            cwd=str(self.wiki_root),
            env=self._wiki_env(),
        )
        if code != 0 or len(stdout) != ref["byte_size"]:
            raise ValueError("company-wiki verified open failed")
        if hashlib.sha256(stdout).hexdigest() != ref["content_sha256"]:
            raise ValueError("company-wiki verified bytes do not match SourceRef")
        try:
            receipt = json.loads(stderr.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("company-wiki verified-open receipt is invalid") from exc
        expected = {
            "status": "ok",
            "document_id": ref["document_id"],
            "source_id": ref["source_id"],
            "content_sha256": ref["content_sha256"],
            "byte_size": ref["byte_size"],
        }
        if not isinstance(receipt, dict) or any(
            receipt.get(key) != value for key, value in expected.items()
        ):
            raise ValueError("company-wiki verified-open receipt mismatches SourceRef")

    def lookup_exact(self, **kwargs: Any) -> dict[str, Any] | None:
        source_request = self._source_request(
            identity=kwargs["identity"],
            fiscal_year=kwargs["fiscal_year"],
            fiscal_quarter=kwargs["fiscal_quarter"],
            as_of_date=kwargs["as_of_date"],
            allow_download=False,
        )
        result = self._query(source_request)
        self._pending = {
            "source_request": source_request,
            "request_id": result.get("request_id"),
            "kwargs": kwargs,
        }
        status = result.get("status")
        if status == "not_found":
            return None
        if status not in {"found", "unknown_publication"}:
            return {
                "status": status
                if status in {"ambiguous", "blocked", "unavailable"}
                else "upstream_error",
                "reason": result.get("reason") or "transcript_lookup_unavailable",
            }
        candidates = result.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != 1:
            raise ValueError("exact company-wiki transcript lookup is not unique")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise ValueError("company-wiki transcript candidate is invalid")
        ref = self._valid_ref(candidate.get("source_ref"))
        self._verified_open(ref)
        unknown = status == "unknown_publication" or candidate.get("published_date") is None
        return {
            "status": "unknown_publication" if unknown else "found",
            "source_ref": ref,
            "publication_date": candidate.get("published_date"),
            "as_of_cutoff_verified": not unknown,
            "provider": "fmp",
            "fiscal_year": kwargs["fiscal_year"],
            "fiscal_quarter": kwargs["fiscal_quarter"],
            "provider_calls": 0,
        }

    def _et_result(
        self,
        *,
        request: dict[str, Any],
        limits: dict[str, Any],
    ) -> dict[str, Any]:
        if self.transcript_tool is None or not self.transcript_tool.is_file():
            return {
                "status": "provider_unavailable",
                "reason": "transcript_tool_not_configured",
                "retryable": False,
                "provider_calls": 0,
            }
        remaining = self._remaining()
        # The provider deadline is a cap; reserve bounded time for the ET
        # process to start, enforce its worker deadline and clean up. If the
        # enclosing FF request is already too close to its deadline, do not
        # start a child that FF would have to kill before ET can reap it.
        provider_budget = min(
            float(limits["timeout_seconds"]),
            remaining - _ET_CLEANUP_GRACE_SECONDS,
            float(_ET_MAX_TIMEOUT_SECONDS),
        )
        timeout_seconds = int(math.floor(provider_budget))
        if timeout_seconds < 1:
            return {
                "status": "provider_unavailable",
                "reason": "provider_deadline",
                "retryable": True,
                "provider_calls": 0,
            }
        et_request = {
            "schema_version": "earnings-transcript-request/1",
            "request_id": request["request_id"],
            "ticker": request["security_id"],
            # FF's canonical identity uses uppercase exchange names while
            # ET's public CLI contract uses lowercase exchange slugs.
            "exchange": (
                request["exchange"].strip().lower()
                if isinstance(request.get("exchange"), str)
                else request.get("exchange")
            ),
            "fiscal_year": request["fiscal_year"],
            "fiscal_quarter": request["fiscal_quarter"],
            "as_of_date": request["as_of_date"],
            "provider": "fmp",
            "download_authorized": True,
            "timeout_seconds": timeout_seconds,
            "max_body_bytes": min(limits["max_bytes"], _ET_MAX_BODY_BYTES),
            "max_response_bytes": limits["max_bytes"],
            "max_cost_usd": limits["max_cost_usd"],
        }
        command = [
            sys.executable,
            str(self.transcript_tool),
            "--request-stdin",
            "--include-source-payload",
            "--report-usage",
        ]
        try:
            stdout, usage_stderr, code = _run_bounded_json(
                command,
                timeout_seconds=min(
                    float(timeout_seconds) + _ET_CLEANUP_GRACE_SECONDS,
                    self._remaining(),
                ),
                input_bytes=json.dumps(
                    et_request, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8"),
                cwd=str(self.transcript_tool.parent),
                env=dict(os.environ),
            )
        except (TransportError, ValueError):
            return {
                "status": "provider_unavailable",
                "reason": "provider_result_oversized",
                "retryable": False,
                "provider_calls": 1,
                **_provider_usage(b"", request["request_id"]),
            }
        try:
            result = json.loads(stdout.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError):
            return {
                "status": "provider_unavailable",
                "reason": "provider_result_invalid",
                "retryable": False,
                "provider_calls": 1,
                **_provider_usage(b"", request["request_id"]),
            }
        if not isinstance(result, dict):
            return {
                "status": "provider_unavailable",
                "reason": "provider_result_invalid",
                "retryable": False,
                "provider_calls": 1,
                **_provider_usage(b"", request["request_id"]),
            }
        self._last_provider_usage = _provider_usage(usage_stderr, request["request_id"])
        if result.get("status") != "fetched":
            error_code = result.get("error_code")
            safe_code = (
                error_code
                if isinstance(error_code, str) and error_code.replace("_", "").isalnum()
                else "provider_unavailable"
            )
            calls = 0 if safe_code in {"provider_credentials_missing", "provider_disabled", "provider_cost_unknown", "provider_cost_budget_exceeded", "candidate_discovery_unavailable", "candidate_fetch_unavailable"} else 1
            return {
                "status": "provider_unavailable",
                "reason": safe_code,
                "retryable": self._last_provider_usage["provider_usage_complete"] and result.get("status")
                in {"rate_limited", "provider_error"},
                "provider_calls": calls,
                **self._last_provider_usage,
            }
        if code != 0:
            return {
                "status": "provider_unavailable",
                "reason": "provider_tool_failed",
                "retryable": False,
                "provider_calls": 1,
                **self._last_provider_usage,
            }
        return result

    def _candidate(
        self, result: dict[str, Any], request: dict[str, Any], company_identity: dict[str, Any]
    ) -> dict[str, Any]:
        provider_document_id = result.get("provider_document_id")
        source_url = result.get("source_url")
        if not isinstance(provider_document_id, str) or not provider_document_id:
            raise ValueError("ET provider document identity is missing")
        if not isinstance(source_url, str) or not source_url.startswith("https://"):
            raise ValueError("ET provider URL is invalid")
        identity = {
            "market": company_identity["market"],
            "security_id": company_identity["security_id"],
            "exchange": company_identity["exchange"],
        }
        return {
            "candidate_id": provider_document_id,
            "provider": "fmp",
            "provider_document_id": provider_document_id,
            "market": company_identity["market"],
            "entity": request["entity"],
            "title": result.get("title") or provider_document_id,
            "source_url": source_url,
            "document_kind": "investor_call_transcript",
            "filing_date": result.get("publication_date"),
            "fiscal_year": request["fiscal_year"],
            "form_type": None,
            "fiscal_period": request["fiscal_period"],
            "language": result.get("language") if isinstance(result.get("language"), str) else None,
            "amended": False,
            "etag": None,
            "last_modified": None,
            "remote_size": None,
            "adapter_payload_json": json.dumps(
                identity,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "schema_version": "1.0",
        }

    def acquire_exact(self, **kwargs: Any) -> dict[str, Any]:
        limits = kwargs.pop("acquisition_limits")
        self._last_provider_usage = {}
        pending = self._pending
        if pending is None or pending.get("kwargs") != kwargs:
            source_request = self._source_request(
                identity=kwargs["identity"],
                fiscal_year=kwargs["fiscal_year"],
                fiscal_quarter=kwargs["fiscal_quarter"],
                as_of_date=kwargs["as_of_date"],
                allow_download=False,
            )
            query = self._query(source_request)
            if query.get("status") != "not_found":
                return {
                    "status": "upstream_error",
                    "reason": "transcript_lookup_changed",
                    "retryable": False,
                    "provider_calls": 0,
                }
            pending = {
                "source_request": source_request,
                "request_id": query.get("request_id"),
                "kwargs": kwargs,
            }
        request = dict(pending["source_request"])
        request["allow_download"] = True
        identity = kwargs["identity"]
        request.update(
            {
                "entity": identity["canonical_name"],
                "market": identity["market"],
                "security_id": identity["security_id"],
                "as_of_date": kwargs["as_of_date"],
            }
        )
        if not isinstance(pending.get("request_id"), str):
            return {
                "status": "upstream_error",
                "reason": "source_request_id_missing",
                "retryable": False,
                "provider_calls": 0,
            }
        if self.transcript_tool is None:
            return {
                "status": "provider_unavailable",
                "reason": "transcript_tool_not_configured",
                "retryable": False,
                "provider_calls": 0,
            }
        et_request = {
            "request_id": pending["request_id"],
            "security_id": identity["security_id"],
            "exchange": identity["exchange"],
            "fiscal_year": kwargs["fiscal_year"],
            "fiscal_quarter": kwargs["fiscal_quarter"],
            "as_of_date": kwargs["as_of_date"],
        }
        try:
            fetched = self._et_result(request=et_request, limits=limits)
        except subprocess.TimeoutExpired:
            return {
                "status": "provider_unavailable",
                "reason": "provider_deadline",
                "retryable": False,
                "provider_calls": 1,
                **_provider_usage(b"", pending["request_id"]),
            }
        except OSError:
            return {
                "status": "provider_unavailable",
                "reason": "transcript_tool_unavailable",
                "retryable": False,
                "provider_calls": 0,
            }
        if fetched.get("status") != "fetched":
            return fetched
        if fetched.get("request_id") != pending["request_id"]:
            return {
                "status": "upstream_error",
                "reason": "provider_request_id_mismatch",
                "retryable": False,
                "provider_calls": 1,
                **self._last_provider_usage,
            }
        try:
            result = self._import_fetched(fetched, request, identity, kwargs)
        except (TransportError, ValueError, OSError, subprocess.TimeoutExpired):
            result = {
                "status": "upstream_error",
                "reason": "transcript_import_failed",
                "retryable": False,
                "provider_calls": 1,
            }
        # ET has already finished and supplied one measured receipt. Import or
        # verified-open failures cannot erase it or invite another download.
        result.update(self._last_provider_usage)
        return result

    def _import_fetched(
        self, fetched: dict[str, Any], request: dict[str, Any],
        identity: dict[str, Any], kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        candidate = self._candidate(fetched, request, identity)
        envelope = {
            "schema_version": _IMPORT_SCHEMA,
            "source_request": request,
            "candidate": candidate,
            "transcript_result": fetched,
        }
        command = [
            sys.executable,
            "-m",
            "company_wiki.source_catalog.transcript_import_cli",
            "--wiki-root",
            str(self.wiki_root),
        ]
        imported, code = self._run_json(
            command,
            envelope,
            cwd=self.wiki_root,
            env=self._wiki_env(),
        )
        if code != 0 or imported.get("schema_version") != _IMPORT_RESPONSE_SCHEMA:
            return {
                "status": "upstream_error",
                "reason": "transcript_import_failed",
                "retryable": False,
                "provider_calls": 1,
            }
        if imported.get("status") != "imported":
            return {
                "status": "upstream_error",
                "reason": "transcript_import_rejected",
                "retryable": False,
                "provider_calls": 1,
            }
        ref = self._valid_ref(imported.get("source_ref"))
        if ref["content_sha256"] != fetched.get("provider_payload_sha256"):
            return {
                "status": "upstream_error",
                "reason": "transcript_import_hash_mismatch",
                "retryable": False,
                "provider_calls": 1,
            }
        self._verified_open(ref)
        return {
            "status": "downloaded",
            "source_ref": ref,
            "provider": "fmp",
            "fiscal_year": kwargs["fiscal_year"],
            "fiscal_quarter": kwargs["fiscal_quarter"],
            "provider_document_id": fetched.get("provider_document_id"),
            "call_date": fetched.get("call_date"),
            "publication_date": fetched.get("publication_date"),
            "as_of_cutoff_verified": fetched.get("as_of_cutoff_verified") is True,
            "provider_calls": fetched.get("provider_calls", 1),
            **self._last_provider_usage,
        }
