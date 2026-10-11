"""Report schema ``ff-et-cwp-offline-matrix/1`` builders and emitters.

The report records, per case, the declared vs observed layer, the actual
modules/HEAD/SHA that ran, request/response/receipt refs, provider counters,
download and translation counts, expected/actual, a PASS|FAIL|NOT_RUN result,
the scope, and restore information. Unknown values stay ``null`` — never a
substituted zero.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

SCHEMA = "ff-et-cwp-offline-matrix/1"
RUNNER_VERSION = "2.1.0"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


@dataclass
class CaseResult:
    id: str
    title: str
    declared_layer: str
    observed_layer: str = ""
    result: str = "NOT_RUN"          # PASS | FAIL | PARTIAL | NOT_RUN
    scope: str = ""
    expected: dict[str, Any] = field(default_factory=dict)
    actual: dict[str, Any] = field(default_factory=dict)
    provider_counters: dict[str, Any] = field(default_factory=dict)
    request_ref: str | None = None
    response_ref: str | None = None
    receipt_refs: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Dependency:
    repository: str
    root: str
    head: str
    modules: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_report(
    *,
    dependencies: list[Dependency],
    cases: list[CaseResult],
    cost: dict[str, Any],
    scope: dict[str, Any],
    restore: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "runner": {"tool": "tools/offline_contract_matrix", "version": RUNNER_VERSION},
        "dependencies": [d.to_dict() for d in dependencies],
        "scope": scope,
        "cost": cost,
        "cases": [c.to_dict() for c in cases],
        "restore": restore,
    }


def emit(report: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
