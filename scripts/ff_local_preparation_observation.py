"""Bounded pathless local-IO observations, distinct from provider fee usage.

This validates wire size/types, not source identity or business eligibility.
Unknown machine-token diagnostics can pass unchanged without a second enum map.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

from ff_source_candidate import contains_physical_field

SCHEMA = 'filing-local-preparation-observation/1'
MAX_BYTES = 128 * 1024
_FIELDS = {'schema_version', 'usage_scope', 'status', 'reason', 'blocks_download',
           'local_read_limits', 'operations', 'diagnostics', 'local_io_usage'}
_FORBIDDEN = {'body', 'content', 'text', 'raw', 'stdout', 'stderr', 'headers', 'authorization',
              'api_key', 'secret', 'password', 'prompt', 'message', 'description', 'detail', 'notes'}
_KEY = re.compile(r'[a-zA-Z][a-zA-Z0-9_]{0,63}\Z')
_TOKEN = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.:+-]{0,255}\Z')
_SCHEMA_TOKEN = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.:+/-]{0,255}\Z')
# Opaque owner namespaces (e.g. urn:owner:budget/2) are identifiers. Reject
# explicit addresses separately so their names do not become a schema whitelist.
_ADDRESS = re.compile(r'(?:[a-zA-Z]:/|file:/|[a-zA-Z][a-zA-Z0-9+.-]*://)', re.IGNORECASE)


def _machine(value: Any, depth: int = 0, *, key: str = '') -> bool:
    if depth > 8:
        return False
    if value is None or type(value) in (bool, int):
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, str):
        return not _ADDRESS.match(value) and bool(
            (_SCHEMA_TOKEN if key == 'schema_version' else _TOKEN).fullmatch(value))
    if isinstance(value, list):
        return len(value) <= 1024 and all(_machine(v, depth+1) for v in value)
    if isinstance(value, dict):
        return len(value) <= 32 and all(isinstance(k, str) and _KEY.fullmatch(k)
            and k.lower() not in _FORBIDDEN and _machine(v, depth+1, key=k) for k, v in value.items())
    return False


def validated_local_preparation_observation(value: Any) -> dict[str, Any] | None:
    """Copy a finite optional observation; malformed diagnostics never gain trust."""
    if not isinstance(value, dict) or set(value) != _FIELDS:
        return None
    if (value['schema_version'] != SCHEMA or value['usage_scope'] != 'local_original_verification'
            or not isinstance(value['reason'], str)
            or value['status'] not in ('ready', 'not_found', 'blocked', 'unavailable', 'ambiguous')
            or type(value['blocks_download']) is not bool or value['local_io_usage'] is not None
            or not isinstance(value['operations'], list) or not isinstance(value['diagnostics'], list)
            or any(not isinstance(row, dict) for row in value['operations'] + value['diagnostics'])):
        return None
    limits = value['local_read_limits']
    if (not isinstance(limits, dict) or set(limits) != {'max_candidates', 'max_bytes', 'timeout_seconds'}
            or type(limits['max_candidates']) is not int or not 1 <= limits['max_candidates'] <= 256
            or type(limits['max_bytes']) is not int or not 1 <= limits['max_bytes'] <= 1073741824
            or type(limits['timeout_seconds']) not in (int, float)
            or not 0 < limits['timeout_seconds'] <= 600 or not math.isfinite(limits['timeout_seconds'])):
        return None
    try:
        if contains_physical_field(value) or not _machine(value):
            return None
        encoded = json.dumps(value, allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(encoded) > MAX_BYTES:
            return None
        return json.loads(encoded)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return None


def local_preparation_observation(payload: dict, limits: dict) -> dict[str, Any] | None:
    """Retain existing producer facts and the exact local-read request ceilings.

    The producer has not exposed a standalone local usage aggregate. Do not
    substitute provider usage zero or infer which bound caused budget_exceeded.
    Versioned owner budget operations, when present, stay verbatim in operations.
    """
    return validated_local_preparation_observation({
        'schema_version': SCHEMA, 'usage_scope': 'local_original_verification',
        **{key: payload[key] for key in ('status', 'reason', 'blocks_download', 'operations', 'diagnostics')},
        'local_read_limits': limits, 'local_io_usage': None,
    })
