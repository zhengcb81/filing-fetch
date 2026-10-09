"""Subprocess transport from filing-fetch to ET and company-wiki."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
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


_KNOWN_ET_ERRORS = frozenset({
    "provider_credentials_missing", "provider_credentials_rejected",
    "provider_credentials_file_unavailable", "provider_credentials_file_empty",
    "provider_credentials_file_invalid", "provider_credentials_leaked",
    "provider_entitlement_required", "provider_entitlement_denied",
    "provider_disabled", "provider_cost_unknown", "provider_cost_budget_exceeded",
    "candidate_discovery_unavailable", "candidate_fetch_unavailable",
    "unsupported_market", "unsupported_exchange", "provider_unavailable",
    "provider_deadline", "byte_limit", "provider_response", "unexpected_provider_failure",
    "retrieval_worker_failure", "request_schema", "invalid_json", "request_too_large",
    "source_payload_flag", "source_payload_not_valid_for_discovery",
    "candidate_request_schema_or_identity", "candidate_effective_url_or_mime",
    "provider_identity_or_host",
}) | frozenset(f"provider_http_{code}" for code in range(100, 600))


class _CredentialExposed(ValueError):
    pass


def _decoded_string_exposed(value: Any, credential: str) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and credential in item:
            return True
        if isinstance(item, (list, tuple)):
            pending.extend(item)
    return False


def _stream_credential_exposed(raw: bytes, credential: str | None) -> bool:
    if not credential:
        return False
    if credential.encode("utf-8") in raw:
        return True
    def checked_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        for name, value in pairs:
            if credential in name or _decoded_string_exposed(value, credential):
                raise _CredentialExposed
        return dict(pairs)
    try:
        decoded = json.loads(raw, object_pairs_hook=checked_pairs)
        return _decoded_string_exposed(decoded, credential)
    except _CredentialExposed:
        return True
    except (ValueError, UnicodeError, RecursionError):
        return False


def _usage_counters(usage: object) -> tuple[int, int] | None:
    """Validate the two measured counters independently from receipt identity."""
    if not isinstance(usage, dict):
        return None
    count, size = usage.get("requests_used"), usage.get("response_bytes_used")
    if type(count) is not int or count < 0 or type(size) is not int or size < 0:
        return None
    return count, size


def _provider_usage(raw: bytes, request_id: str, credential: str | None = None) -> dict[str, Any]:
    """Read one final supervisor receipt; absent/partial usage stays unknown."""
    unknown = {"provider_requests": None, "provider_response_bytes": None, "provider_usage_complete": False}
    if len(raw) > 8192 or _stream_credential_exposed(raw, credential):
        return unknown
    try:
        receipt = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError):
        return unknown
    if not isinstance(receipt, dict) or set(receipt) != {"schema_version", "request_id", "usage_complete", "usage"} or receipt.get("schema_version") != "earnings-retrieval-usage/1":
        return unknown
    if receipt.get("request_id") != request_id or receipt.get("usage_complete") is not True:
        return unknown
    counters = _usage_counters(receipt.get("usage"))
    if counters is None:
        return unknown
    count, size = counters
    return {"provider_requests": count, "provider_response_bytes": size, "provider_usage_complete": True}


def _credential_exposed(stdout: bytes, stderr: bytes, credential: str | None) -> bool:
    """Check wire semantics and unchanged decoded original, not one byte encoding."""
    if not credential:
        return False
    if _stream_credential_exposed(stdout, credential) or _stream_credential_exposed(stderr, credential):
        return True
    try:
        result = json.loads(stdout)
        encoded = result.get("provider_payload_base64") if isinstance(result, dict) else None
        if not isinstance(encoded, str):
            return False
        payload = base64.b64decode(encoded, validate=True)
        return _stream_credential_exposed(payload, credential)
    except (ValueError, binascii.Error, UnicodeError, RecursionError):
        return False


class EarningsTranscriptsTransport:
    """Call the configured ET tool, then let CWP own and verify original bytes."""

    def __init__(
        self,
        *,
        wiki_root: Path,
        transcript_tool: Path | None = None,
        config_path: Path | None = None,
        fmp_api_key_file: Path | None = None,
        deadline: float,
    ) -> None:
        self.wiki_root = wiki_root.resolve(strict=True)
        configured = transcript_tool or (
            Path(os.environ["EARNINGS_TRANSCRIPTS_TOOL"])
            if os.environ.get("EARNINGS_TRANSCRIPTS_TOOL")
            else None
        )
        self.config_path = config_path
        self.fmp_api_key_file = fmp_api_key_file
        self._launch_config_cache: tuple[Path, dict[str, Any]] | None = None
        self._tool_configuration_error = "transcript_tool_not_configured"
        self.transcript_tool = configured.resolve(strict=True) if configured else None
        if configured is None and config_path is not None:
            try:
                launch_config = self._selected_launch_config()
                if "earnings_transcripts_tool" in launch_config:
                    tool = self._launch_path(launch_config["earnings_transcripts_tool"])
                    self.transcript_tool = tool.resolve(strict=True)
                    if not self.transcript_tool.is_file():
                        self.transcript_tool = None
                        self._tool_configuration_error = "transcript_tool_unavailable"
            except ValueError:
                self._tool_configuration_error = "transcript_tool_config_invalid"
            except OSError:
                self._tool_configuration_error = "transcript_tool_unavailable"
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
        env.pop("FMP_API_KEY_FILE", None)
        env["PYTHONUTF8"] = "1"
        src = str(self.wiki_root / "src")
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = src if not existing else src + os.pathsep + existing
        return env

    def _selected_launch_config(self) -> dict[str, Any]:
        """One bounded configuration snapshot per selected file and transport."""
        if self.config_path is None:
            return {}
        try:
            selected = self.config_path.expanduser().resolve(strict=True)
            if self._launch_config_cache and self._launch_config_cache[0] == selected:
                return self._launch_config_cache[1]
            with selected.open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError
            config = json.loads(raw)
            if not isinstance(config, dict):
                raise ValueError
        except (OSError, ValueError):
            raise ValueError("provider_credentials_config_invalid") from None
        self._launch_config_cache = selected, config
        return config

    def _launch_path(self, value: object) -> Path:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError("provider_credentials_config_invalid")
        tokens = {"USER_PROFILE": os.environ.get("USERPROFILE") or str(Path.home()),
                  "SKILL_ROOT": str(Path(__file__).resolve().parents[1])}
        def replace(match: re.Match[str]) -> str:
            if match.group(1) not in tokens:
                raise ValueError("provider_credentials_config_invalid")
            return tokens[match.group(1)]
        expanded = re.sub(r"\$\{([^}]+)\}", replace, value)
        if "${" in expanded:
            raise ValueError("provider_credentials_config_invalid")
        path = Path(expanded).expanduser()
        if path.is_absolute():
            return path
        if self.config_path is None:
            raise ValueError("provider_credentials_config_invalid")
        return self.config_path.expanduser().resolve(strict=True).parent / path

    def _credential_file(self) -> Path | None:
        """Explicit source wins; otherwise reuse the selected config's known file."""
        if self.fmp_api_key_file is not None:
            return self.fmp_api_key_file
        if "FMP_API_KEY_FILE" in os.environ:
            value = os.environ["FMP_API_KEY_FILE"]
            if not value.strip():
                raise ValueError("provider_credentials_file_unavailable")
            return Path(value)
        if "FMP_API_KEY" in os.environ or self.config_path is None:
            return None
        config = self._selected_launch_config()
        if "fmp_api_key_file" in config:
            configured = config["fmp_api_key_file"]
            if not isinstance(configured, str) or not configured.strip():
                raise ValueError("provider_credentials_file_unavailable")
            return self._launch_path(configured)
        # Reuse the user's existing known source; no recursive/key-pattern scan.
        known = self.config_path.expanduser().resolve(strict=True).parent / "FMP_API_KEY.txt"
        return known if known.exists() else None

    def _et_environment(self) -> tuple[dict[str, str], str | None]:
        env = dict(os.environ)
        credential_file = self._credential_file()
        env.pop("FMP_API_KEY_FILE", None)
        if credential_file is not None:
            try:
                with credential_file.open("rb") as stream:
                    raw = stream.read(4097)
            except OSError:
                raise ValueError("provider_credentials_file_unavailable") from None
            if len(raw) > 4096:
                raise ValueError("provider_credentials_file_invalid")
            try:
                value = raw.decode("utf-8-sig").strip()
            except UnicodeError:
                raise ValueError("provider_credentials_file_invalid") from None
            if not value:
                raise ValueError("provider_credentials_file_empty")
            if any(not 33 <= ord(char) <= 126 for char in value):
                raise ValueError("provider_credentials_file_invalid")
            env["FMP_API_KEY"] = value
        key = env.get("FMP_API_KEY")
        return env, key.strip() if key and key.strip() else None

    @staticmethod
    def _provider_started(usage: dict[str, Any]) -> bool | None:
        count = usage.get("provider_requests")
        return count > 0 if type(count) is int else None

    @staticmethod
    def _local_unavailable(reason: str) -> dict[str, Any]:
        return {"status": "provider_unavailable", "reason": reason, "retryable": False,
                "provider_calls": 0, "provider_started": False,
                "provider_requests": 0, "provider_response_bytes": 0,
                "provider_usage_complete": True}


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
        if self.transcript_tool is None:
            return self._local_unavailable(self._tool_configuration_error)
        if not self.transcript_tool.is_file():
            return self._local_unavailable("transcript_tool_unavailable")
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
        try:
            et_env, credential = self._et_environment()
        except (ValueError, OSError) as exc:
            safe = str(exc) if isinstance(exc, ValueError) else "provider_credentials_config_invalid"
            return self._local_unavailable(safe)
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
                env=et_env,
            )
        except (TransportError, ValueError):
            return {
                "status": "provider_unavailable",
                "reason": "provider_result_oversized",
                "retryable": False,
                "provider_calls": 1,
                **_provider_usage(b"", request["request_id"]),
            }
        self._last_provider_usage = _provider_usage(usage_stderr, request["request_id"], credential)
        if _credential_exposed(stdout, usage_stderr, credential):
            return {"status": "provider_unavailable", "reason": "provider_credentials_leaked",
                    "retryable": False, "provider_calls": 1,
                    "provider_started": self._provider_started(self._last_provider_usage),
                    **self._last_provider_usage}
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
        self._last_provider_usage = _provider_usage(usage_stderr, request["request_id"], credential)
        if result.get("status") != "fetched":
            error_code = result.get("error_code")
            safe_code = (
                error_code
                if isinstance(error_code, str) and error_code in _KNOWN_ET_ERRORS
                else "provider_unavailable"
            )
            calls = 0 if safe_code in {"provider_credentials_missing", "provider_disabled", "provider_cost_unknown", "provider_cost_budget_exceeded", "candidate_discovery_unavailable", "candidate_fetch_unavailable", "unsupported_market", "unsupported_exchange", "provider_credentials_file_unavailable", "provider_credentials_file_empty", "provider_credentials_file_invalid"} else 1
            return {
                "status": "provider_unavailable",
                "reason": safe_code,
                "retryable": self._last_provider_usage["provider_usage_complete"] and result.get("status")
                in {"rate_limited", "provider_error"},
                "provider_calls": calls,
                "provider_started": self._provider_started(self._last_provider_usage),
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
            return self._local_unavailable(self._tool_configuration_error)
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
