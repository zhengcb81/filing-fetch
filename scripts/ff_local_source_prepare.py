"""Thin bounded transport for CWP-owned local intake after an explicit reuse miss."""
from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

import ff_process_transport
from ff_provider_cause import condition_cause, source_condition
from ff_v2_envelope import _reference
from filing_contracts import FilingFetchError

_RESULT_FIELDS = frozenset({
    "schema_version", "status", "reason", "source_ref", "blocks_download",
    "operations", "diagnostics", "download_events",
})


def _validated(payload: Any, physical_fields: Callable[[object], bool]) -> bool:
    if (not isinstance(payload, dict) or set(payload) != _RESULT_FIELDS
            or payload.get("schema_version") != "local-source-prepare/1"
            or type(payload.get("download_events")) is not int or payload["download_events"] != 0
            or type(payload.get("blocks_download")) is not bool
            or not isinstance(payload.get("operations"), list)
            or not isinstance(payload.get("diagnostics"), list)
            or not isinstance(payload.get("reason"), str)
            or physical_fields(payload)):
        raise FilingFetchError("invalid local preparation receipt", code="upstream_error",
                               stage="local_prepare", upstream_cause=source_condition("local_prepare", "invalid_producer_schema"))
    status = payload["status"]
    if status == "ready":
        _reference(payload["source_ref"])
        if payload["blocks_download"]:
            raise FilingFetchError("contradictory local preparation result",
                                   code="upstream_error", stage="local_prepare")
        return True
    errors = {"not_found": "not_found", "blocked": "source_blocked",
              "unavailable": "upstream_error", "ambiguous": "ambiguous"}
    if status not in errors or payload["source_ref"] is not None:
        raise FilingFetchError("invalid local preparation status", code="upstream_error",
                               stage="local_prepare")
    cause = source_condition("local_prepare", payload["reason"])
    raise FilingFetchError(f"local source preparation {status}: {cause['code']}",
                           code=errors[status], stage="local_prepare",
                           upstream_cause=cause)


def prepare_existing_local_source(
    *, root: Path, source_request: dict[str, Any], deadline: float,
    stats: dict[str, int], transport: Callable[..., tuple[bytes, bytes, int]],
    physical_fields: Callable[[object], bool],
) -> None:
    """No filesystem interpretation or provider fallback lives in this consumer."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise FilingFetchError("deadline exceeded before local preparation",
                               code="upstream_error", stage="local_prepare")
    request = {
        "schema_version": "local-source-prepare-request/1",
        "source_request": {**source_request, "schema_version": "1.0", "allow_download": False},
        "limits": {"max_candidates": 64, "max_bytes": 128 * 1024 * 1024,
                   "timeout_seconds": min(remaining, 600)},
    }
    command = [sys.executable, "-m", "company_wiki.source_catalog.local_prepare_cli",
               "--config", str(root / "config" / "source_catalog.yaml"), "--request", "-"]
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    stats["calls"] += 1
    try:
        stdout, _, returncode = transport(
            command, timeout_seconds=remaining,
            input_bytes=json.dumps(request, ensure_ascii=False).encode("utf-8"),
            cwd=str(root), env=environment,
        )
    except ff_process_transport.ChildTimeout as exc:
        raise FilingFetchError("local preparation exceeded deadline", code="upstream_error", stage="local_prepare",
                               upstream_cause=condition_cause("local_prepare", "producer_deadline_exceeded")[1]) from exc
    except ff_process_transport.OutputLimitExceeded as exc:
        raise FilingFetchError("local preparation exceeded output limit", code="upstream_error", stage="local_prepare",
                               upstream_cause=condition_cause("local_prepare", "producer_output_exceeded")[1]) from exc
    except ff_process_transport.ChildStartFailed as exc:
        raise FilingFetchError("local preparation failed to start", code="upstream_error", stage="local_prepare",
                               upstream_cause=condition_cause("local_prepare", "producer_start_failed")[1]) from exc
    except (ff_process_transport.TransportError, OSError) as exc:
        raise FilingFetchError("local preparation transport failed", code="upstream_error",
                               stage="local_prepare", upstream_cause=condition_cause("local_prepare", "producer_transport_failure")[1]) from exc
    try:
        payload = json.loads(stdout.decode("utf-8", errors="strict"))
    except (UnicodeError, ValueError) as exc:
        raise FilingFetchError("invalid local preparation receipt", code="upstream_error", stage="local_prepare",
                               upstream_cause=source_condition("local_prepare", "invalid_producer_schema")) from exc
    _validated(payload, physical_fields)
    if returncode != 0:
        raise FilingFetchError("ready local preparation returned nonzero exit",
                               code="upstream_error", stage="local_prepare")
