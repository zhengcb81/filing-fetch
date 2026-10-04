"""Subprocess transport from filing-fetch to ET and company-wiki."""

from __future__ import annotations

import hashlib
import json
import math
import os
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


_LOOKUP_SCHEMA = "company-wiki-transcript-import-lookup-request/1"
_IMPORT_SCHEMA = "company-wiki-transcript-import-request/2"
_IMPORT_RESPONSE_SCHEMA = "company-wiki-transcript-import-response/3"
_SOURCE_REQUEST_SCHEMA = "1.0"
# One ceiling for every JSON subprocess this repo spawns.  The filing-fetch
# company-wiki runner imports it so both transports fail closed at one number.
MAX_JSON_OUTPUT_BYTES = 32 * 1024 * 1024
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
        completed = subprocess.run(
            command,
            input=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=self._remaining(),
            check=False,
            shell=False,
            creationflags=self._creationflags(),
        )
        if len(completed.stdout) > maximum:
            raise ValueError("child JSON output exceeded its byte limit")
        try:
            result = json.loads(completed.stdout.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("child output was not bounded UTF-8 JSON") from exc
        if not isinstance(result, dict):
            raise ValueError("child JSON result was not an object")
        return result, completed.returncode

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
        completed = subprocess.run(
            command,
            input=None,
            cwd=self.wiki_root,
            env=self._wiki_env(),
            capture_output=True,
            timeout=self._remaining(),
            check=False,
            shell=False,
            creationflags=self._creationflags(),
        )
        if completed.returncode != 0 or len(completed.stdout) != ref["byte_size"]:
            raise ValueError("company-wiki verified open failed")
        if hashlib.sha256(completed.stdout).hexdigest() != ref["content_sha256"]:
            raise ValueError("company-wiki verified bytes do not match SourceRef")
        if len(completed.stderr) > 64 * 1024:
            raise ValueError("company-wiki verified-open receipt is oversized")
        try:
            receipt = json.loads(completed.stderr.decode("utf-8", errors="strict"))
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
        timeout = min(float(limits["timeout_seconds"]), self._remaining())
        timeout_seconds = max(1, int(math.ceil(timeout)))
        et_request = {
            "schema_version": "earnings-transcript-request/1",
            "request_id": request["request_id"],
            "ticker": request["security_id"],
            "exchange": request["exchange"],
            "fiscal_year": request["fiscal_year"],
            "fiscal_quarter": request["fiscal_quarter"],
            "as_of_date": request["as_of_date"],
            "provider": "fmp",
            "download_authorized": True,
            "timeout_seconds": timeout_seconds,
            "max_body_bytes": limits["max_bytes"],
        }
        command = [
            sys.executable,
            str(self.transcript_tool),
            "--request-stdin",
            "--include-source-payload",
        ]
        completed = subprocess.run(
            command,
            input=json.dumps(et_request, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            cwd=self.transcript_tool.parent,
            env=dict(os.environ),
            capture_output=True,
            timeout=min(timeout, self._remaining()),
            check=False,
            shell=False,
            creationflags=self._creationflags(),
        )
        if len(completed.stdout) > MAX_JSON_OUTPUT_BYTES:
            return {
                "status": "provider_unavailable",
                "reason": "provider_result_oversized",
                "retryable": False,
                "provider_calls": 1,
            }
        try:
            result = json.loads(completed.stdout.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError):
            return {
                "status": "provider_unavailable",
                "reason": "provider_result_invalid",
                "retryable": True,
                "provider_calls": 1,
            }
        if not isinstance(result, dict):
            return {
                "status": "provider_unavailable",
                "reason": "provider_result_invalid",
                "retryable": True,
                "provider_calls": 1,
            }
        if result.get("status") != "fetched":
            code = result.get("error_code")
            safe_code = (
                code
                if isinstance(code, str) and code.replace("_", "").isalnum()
                else "provider_unavailable"
            )
            calls = 0 if safe_code in {"provider_credentials_missing", "provider_disabled"} else 1
            return {
                "status": "provider_unavailable",
                "reason": safe_code,
                "retryable": result.get("status")
                in {"deadline_exceeded", "rate_limited", "provider_error"},
                "provider_calls": calls,
            }
        if completed.returncode != 0:
            return {
                "status": "provider_unavailable",
                "reason": "provider_tool_failed",
                "retryable": True,
                "provider_calls": 1,
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
        if Decimal(limits["max_cost_usd"]) == 0:
            return {
                "status": "provider_unavailable",
                "reason": "zero_cost_budget",
                "retryable": False,
                "provider_calls": 0,
            }
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
                "retryable": True,
                "provider_calls": 1,
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
            }
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
        }
