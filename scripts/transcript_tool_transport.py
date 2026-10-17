"""Subprocess transport from filing-fetch to ET and company-wiki."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from et_v2_contract import ET_NOT_FOUND_DIAGNOSTICS
from ff_configuration import expand_config_path, read_json_object
from filing_contracts import FilingFetchError
from ff_source_ref import validate_source_ref
from transcript_reuse_selection import (
    LocalQueryContractError,
    Selection,
    select_local_outcome,
)


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
        provider: str | None,
    ) -> dict[str, Any]:
        # The reuse scope is source-neutral: ``provider`` stays None unless the
        # caller explicitly constrained it. The acquisition provider is decided
        # separately (FMP only) and is never written back into this request.
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
            "provider": provider,
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
            config = read_json_object(selected, label="ET launch config")
        except (OSError, ValueError, FilingFetchError):
            raise ValueError("provider_credentials_config_invalid") from None
        self._launch_config_cache = selected, config
        return config

    def _launch_path(self, value: object) -> Path:
        try:
            return expand_config_path(value, field="ET launch path",
                skill_root=Path(__file__).resolve().parents[1], config_path=self.config_path)
        except (FilingFetchError, OSError, ValueError):
            raise ValueError("provider_credentials_config_invalid") from None

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

    def _run_source_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One bounded call to the public local source-query CLI."""
        command = [
            sys.executable,
            "-m",
            "company_wiki.source_catalog.source_query_cli",
            "--config",
            str(self.wiki_root / "config" / "source_catalog.yaml"),
        ]
        result, code = self._run_json(
            command,
            payload,
            cwd=self.wiki_root,
            env=self._wiki_env(),
        )
        if result.get("schema_version") != "2.0":
            raise ValueError("company-wiki source query schema is unsupported")
        if code not in (0, 2):
            raise ValueError("company-wiki source query failed")
        return result

    def _query(self, source_request: dict[str, Any]) -> dict[str, Any]:
        """Provider-scoped duplicate-suppression lookup through its own envelope.

        This entry exists for the explicit-provider import-dedup path and keeps
        requiring a concrete provider; it is not a cross-source query.
        """
        return self._run_source_query(
            {"schema_version": _LOOKUP_SCHEMA, "source_request": source_request}
        )

    def _query_local(self, source_request: dict[str, Any]) -> dict[str, Any]:
        """Source-neutral exact local query: a plain ``SourceRequest`` object.

        The CLI constructs ``SourceRequest`` directly and calls
        ``SourceVersionReader.query_local``; no lookup envelope is wrapped.
        """
        return self._run_source_query(dict(source_request))

    @staticmethod
    def _valid_ref(value: object) -> dict[str, Any]:
        """Use the same logical reference contract as filing result serialization."""
        try:
            return validate_source_ref(value)
        except FilingFetchError as exc:
            raise ValueError(str(exc)) from None

    def _verified_open(self, ref: dict[str, Any]) -> dict[str, Any]:
        """Read verified bytes; return the public receipt that names their source."""
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
        manifest = receipt.get("manifest")
        if manifest is not None and not isinstance(manifest, dict):
            raise ValueError("company-wiki verified-open manifest is invalid")
        return receipt

    @staticmethod
    def _manifest_provider(receipt: object) -> str | None:
        """Real provider of the verified bytes; unknown stays unknown, never a default."""
        if not isinstance(receipt, dict):
            return None
        manifest = receipt.get("manifest")
        if not isinstance(manifest, dict):
            return None
        value = manifest.get("provider")
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("company-wiki manifest provider is invalid")
        return value.strip() or None

    @staticmethod
    def _manifest_published_date(
        receipt: object, observed: str | None,
    ) -> str | None:
        """Publication date of the verified manifest, else the qualified observation."""
        if not isinstance(receipt, dict):
            return observed
        manifest = receipt.get("manifest")
        if not isinstance(manifest, dict):
            return observed
        value = manifest.get("published_date")
        if value is None:
            return observed
        if not isinstance(value, str):
            raise ValueError("company-wiki manifest publication date is invalid")
        return value.strip() or None

    @staticmethod
    def _manifest_conflicts(receipt: object, expected: dict[str, Any]) -> bool:
        """A verified manifest that contradicts the exact request cannot be reused."""
        if not isinstance(receipt, dict):
            return False
        manifest = receipt.get("manifest")
        if not isinstance(manifest, dict):
            return False

        def text(name: str) -> str | None:
            value = manifest.get(name)
            return value.strip() if isinstance(value, str) and value.strip() else None

        def key(value: str) -> str:
            return value.strip().lstrip("0").casefold()

        period = text("fiscal_period")
        if period is not None and str(expected.get("fiscal_period") or "").strip():
            if period.casefold() != str(expected["fiscal_period"]).strip().casefold():
                return True
        year = manifest.get("fiscal_year")
        if type(year) is int and expected.get("fiscal_year") is not None:
            if year != expected["fiscal_year"]:
                return True
        market = text("market")
        if market is not None and expected.get("market"):
            if market.casefold() != str(expected["market"]).strip().casefold():
                return True
        security = text("security_id")
        if security is not None and expected.get("security_id"):
            if key(security) != key(str(expected["security_id"])):
                return True
        return False

    def _verified_lookup(
        self,
        selection: Selection,
        *,
        provider_constraint: str | None,
        expected: dict[str, Any],
    ) -> dict[str, Any]:
        """Reuse one local candidate only after its bytes are read and verified."""
        if selection.source_ref is None:
            return {"status": "upstream_error", "reason": "transcript_lookup_contract"}
        try:
            ref = self._valid_ref(selection.source_ref.to_dict())
        except (FilingFetchError, ValueError):
            return {"status": "upstream_error", "reason": "transcript_lookup_source_ref"}
        receipt = self._verified_open(ref)
        if self._manifest_conflicts(receipt, expected):
            # Verified bytes for another period/security are not this request.
            return {"status": "upstream_error", "reason": "transcript_lookup_identity_mismatch"}
        provider = self._manifest_provider(receipt)
        if (
            provider_constraint is not None
            and provider is not None
            and provider != provider_constraint
        ):
            # The explicit constraint is a request condition, not a label: a
            # verified source from another provider cannot satisfy it.
            return {"status": "upstream_error", "reason": "transcript_provider_mismatch"}
        published = self._manifest_published_date(receipt, selection.published_date)
        unknown = selection.kind == "unknown_publication" or published is None
        result: dict[str, Any] = {
            "status": "unknown_publication" if unknown else "found",
            "source_ref": ref,
            "publication_date": published,
            "as_of_cutoff_verified": not unknown,
            "provider_calls": 0,
        }
        if provider is not None:
            result["provider"] = provider
        return result

    def _read_lookup(
        self,
        result: dict[str, Any],
        *,
        provider_constraint: str | None,
        unknown_publication_is_excluded: bool,
        expected: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Read one public query result without inventing a source or a provider."""
        try:
            selection = select_local_outcome(result)
        except LocalQueryContractError:
            return {"status": "upstream_error", "reason": "transcript_lookup_contract"}
        if selection.kind == "missing":
            return None
        if selection.kind == "status":
            return {
                "status": (
                    selection.provider_status
                    if selection.provider_status in {"ambiguous", "blocked", "unavailable"}
                    else "upstream_error"
                ),
                "reason": selection.reason or "transcript_lookup_unavailable",
            }
        if selection.kind == "gap":
            return {
                "status": "upstream_error",
                "reason": selection.reason or "transcript_lookup_unavailable",
                "provider_calls": 0,
                **selection.exclusions(),
            }
        if (
            selection.kind == "unknown_publication"
            and unknown_publication_is_excluded
            and selection.qualification is not None
            and selection.source_ref is not None
        ):
            try:
                ref = self._valid_ref(selection.source_ref.to_dict())
            except (FilingFetchError, ValueError):
                return {"status": "upstream_error", "reason": "transcript_lookup_source_ref"}
            # A query observation, not a byte proof: no reader call, so no GET.
            return {
                "status": "unknown_publication",
                "source_ref": ref,
                "publication_date": None,
                "as_of_cutoff_verified": False,
                "qualification": selection.qualification,
                "provider_calls": 0,
            }
        return self._verified_lookup(
            selection,
            provider_constraint=provider_constraint,
            expected=expected,
        )

    def lookup_exact(self, **kwargs: Any) -> dict[str, Any] | None:
        provider = kwargs.get("provider")
        if provider not in (None, "fmp"):
            return {
                "status": "upstream_error",
                "reason": "unsupported_transcript_provider",
                "provider_calls": 0,
            }
        identity = kwargs["identity"]
        source_request = self._source_request(
            identity=identity,
            fiscal_year=kwargs["fiscal_year"],
            fiscal_quarter=kwargs["fiscal_quarter"],
            as_of_date=kwargs["as_of_date"],
            allow_download=False,
            provider=provider,
        )
        expected = {
            "fiscal_year": kwargs["fiscal_year"],
            "fiscal_period": f"Q{kwargs['fiscal_quarter']}",
            "market": identity.get("market"),
            "security_id": identity.get("security_id"),
        }
        # Omitted provider: cross-source local reuse first. Explicit provider:
        # the existing provider-scoped import-dedup envelope.
        result = (
            self._query_local(source_request)
            if provider is None
            else self._query(source_request)
        )
        self._pending = {
            "source_request": source_request,
            "request_id": result.get("request_id"),
            "kwargs": kwargs,
        }
        return self._read_lookup(
            result,
            provider_constraint=provider,
            unknown_publication_is_excluded=provider is None,
            expected=expected,
        )

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
        # Transport usage is independent of whether stdout is a valid document.
        # Parse the bounded, request-bound receipt once and preserve that snapshot
        # in all later failure projections, including malformed JSON/type errors.
        provider_usage = _provider_usage(usage_stderr, request["request_id"], credential)
        self._last_provider_usage = provider_usage

        def unavailable(
            reason: str, *, calls: int = 1, retryable: bool = False,
        ) -> dict[str, Any]:
            return {
                "status": "provider_unavailable",
                "reason": reason,
                "retryable": retryable,
                "provider_calls": calls,
                "provider_started": self._provider_started(provider_usage),
                **provider_usage,
            }

        if _credential_exposed(stdout, usage_stderr, credential):
            return unavailable("provider_credentials_leaked")
        try:
            result = json.loads(stdout.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError):
            return unavailable("provider_result_invalid")
        if not isinstance(result, dict):
            return unavailable("provider_result_invalid")
        if result.get("status") == "not_found":
            # Bind this one process receipt to the current request. This is not
            # another company-identity lookup or a source-byte validation.
            invalid = (
                result.get("schema_version") not in (
                    "earnings-transcript-result/1", "earnings-transcript-result/2",
                )
                or result.get("request_id") != et_request["request_id"]
                or result.get("provider") != et_request["provider"]
                or result.get("fiscal_period")
                != f"{et_request['fiscal_year']}-Q{et_request['fiscal_quarter']}"
                or type(result.get("candidate_count")) is not int
                or result["candidate_count"] != 0
            )
            if code != 0 or invalid:
                return unavailable(
                    "provider_tool_failed" if code != 0 else "provider_result_invalid",
                )
            # A completed lookup with no eligible transcript is not a provider
            # outage. Only a producer-declared finite date diagnostic can name
            # a cutoff; neither zero candidates nor child free text proves one.
            diagnostic = result.get("error_code")
            reason = (diagnostic if isinstance(diagnostic, str)
                      and diagnostic in ET_NOT_FOUND_DIAGNOSTICS else "exact_transcript_missing")
            return {
                "status": "not_found",
                "reason": reason,
                "retryable": False,
                "provider_calls": 1,
                "provider_started": self._provider_started(provider_usage),
                **provider_usage,
            }
        if result.get("status") != "fetched":
            error_code = result.get("error_code")
            safe_code = (
                error_code
                if isinstance(error_code, str) and error_code in _KNOWN_ET_ERRORS
                else "provider_unavailable"
            )
            calls = 0 if safe_code in {"provider_credentials_missing", "provider_disabled", "provider_cost_unknown", "provider_cost_budget_exceeded", "candidate_discovery_unavailable", "candidate_fetch_unavailable", "unsupported_market", "unsupported_exchange", "provider_credentials_file_unavailable", "provider_credentials_file_empty", "provider_credentials_file_invalid"} else 1
            return unavailable(
                safe_code, calls=calls,
                retryable=provider_usage["provider_usage_complete"] and result.get("status")
                in ("rate_limited", "provider_error"),
            )
        if code != 0:
            return unavailable("provider_tool_failed")
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
            provider = kwargs.get("provider")
            identity = kwargs["identity"]
            source_request = self._source_request(
                identity=identity,
                fiscal_year=kwargs["fiscal_year"],
                fiscal_quarter=kwargs["fiscal_quarter"],
                as_of_date=kwargs["as_of_date"],
                allow_download=False,
                provider=provider,
            )
            query = (
                self._query_local(source_request)
                if provider is None
                else self._query(source_request)
            )
            try:
                selection = select_local_outcome(query)
            except LocalQueryContractError:
                return {
                    "status": "upstream_error",
                    "reason": "transcript_lookup_contract",
                    "retryable": False,
                    "provider_calls": 0,
                }
            if selection.kind != "missing":
                # A concurrent write, an as-of-restricted local observation or an
                # ambiguous catalog is a change of answer, never a download
                # trigger; the bytes are deliberately not opened again here.
                changed_answer: dict[str, Any] = {
                    "status": "upstream_error",
                    "reason": "transcript_lookup_changed",
                    "retryable": False,
                    "provider_calls": 0,
                }
                # Keep the pathless local duplicate-suppression evidence that
                # turned the answer into a named gap instead of a download.
                if selection.qualification is not None:
                    changed_answer["qualification"] = selection.qualification
                changed_answer.update(selection.exclusions())
                return changed_answer
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
        receipt = self._verified_open(ref)
        # The verified manifest names the committed provenance. Only when it
        # does not is the tool result's own declaration used, and that is still
        # a CWP-validated fact rather than a request default: the import
        # contract requires tool_result.provider == candidate.provider, and FF
        # builds the candidate from this same fetched result. If neither
        # exists the provider stays unknown (the key is omitted).
        provider = self._manifest_provider(receipt)
        if provider is None:
            declared = fetched.get("provider")
            provider = declared if isinstance(declared, str) and declared.strip() else None
        result: dict[str, Any] = {
            "status": "downloaded",
            "source_ref": ref,
            "fiscal_year": kwargs["fiscal_year"],
            "fiscal_quarter": kwargs["fiscal_quarter"],
            "provider_document_id": fetched.get("provider_document_id"),
            "call_date": fetched.get("call_date"),
            "publication_date": fetched.get("publication_date"),
            "as_of_cutoff_verified": fetched.get("as_of_cutoff_verified") is True,
            "provider_calls": fetched.get("provider_calls", 1),
            **self._last_provider_usage,
        }
        if provider is not None:
            result["provider"] = provider
        return result
