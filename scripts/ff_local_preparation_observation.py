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
_FIELDS = {'schema_version', 'usage_scope', 'status', 'reason', 'blocks_download',
           'local_read_limits', 'operations', 'diagnostics', 'local_io_usage'}
_FORBIDDEN = {'body', 'content', 'text', 'raw', 'stdout', 'stderr', 'headers', 'authorization',
              'api_key', 'secret', 'password', 'prompt', 'message', 'description', 'detail', 'notes'}
_KEY = re.compile(r'[a-zA-Z][a-zA-Z0-9_]*\Z')
_TOKEN = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.:+-]*\Z')
_SCHEMA_TOKEN = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.:+/-]*\Z')
# Opaque owner namespaces (e.g. urn:owner:budget/2) are identifiers. Reject
# explicit addresses separately so their names do not become a schema whitelist.
_ADDRESS = re.compile(r'(?:[a-zA-Z]:/|file:/|[a-zA-Z][a-zA-Z0-9+.-]*://)', re.IGNORECASE)


def _machine(value: Any) -> bool:
    """Validate pathless machine facts, independent of representation size."""
    stack = [(value, "", False)]
    active: set[int] = set()
    while stack:
        current, key, leaving = stack.pop()
        if leaving:
            active.remove(id(current))
            continue
        if current is None or type(current) in (bool, int):
            continue
        if type(current) is float:
            if not math.isfinite(current):
                return False
        elif isinstance(current, str):
            if _ADDRESS.match(current) or not (
                _SCHEMA_TOKEN if key == "schema_version" else _TOKEN
            ).fullmatch(current):
                return False
        elif isinstance(current, (list, dict)):
            if id(current) in active:
                return False
            active.add(id(current))
            stack.append((current, key, True))
            if isinstance(current, dict):
                for child_key, child in current.items():
                    if (not isinstance(child_key, str) or not _KEY.fullmatch(child_key)
                            or child_key.lower() in _FORBIDDEN):
                        return False
                    stack.append((child, child_key, False))
            else:
                stack.extend((child, "", False) for child in current)
        else:
            return False
    return True


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
            or type(limits['max_candidates']) is not int or limits['max_candidates'] <= 0
            or type(limits['max_bytes']) is not int or limits['max_bytes'] <= 0
            or type(limits['timeout_seconds']) not in (int, float)
            or limits['timeout_seconds'] <= 0
            or (type(limits['timeout_seconds']) is float and not math.isfinite(limits['timeout_seconds']))):
        return None
    try:
        if not _machine(value) or contains_physical_field(value):
            return None
        encoded = json.dumps(value, allow_nan=False, separators=(',', ':')).encode('utf-8')
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
