"""Union of the frozen base case authority and registered supplemental suites.

The base registry in ``case_specs`` remains the only required-case authority
and is what a full run executes. Supplemental suites (currently the W20
interruption/recovery suite) join the *known id universe* so the generic
explicit case selection, the seed planner and the static cost model can
resolve them — nothing here promotes a supplemental case into the required
set, and a run without an explicit selection never sees them.
"""

from __future__ import annotations

from typing import Any

import case_specs
import w20_case_specs


def base_entries() -> list[tuple[str, Any]]:
    return [(spec.id, spec.execute) for spec in case_specs.case_specs()]


def supplemental_entries() -> list[tuple[str, Any]]:
    return [(spec.id, spec.execute) for spec in w20_case_specs.w20_case_specs()]


def union_entries() -> list[tuple[str, Any]]:
    """Base first (stable authority order), then supplemental suites."""
    entries = base_entries() + supplemental_entries()
    ids = [cid for cid, _ in entries]
    duplicates = sorted({cid for cid in ids if ids.count(cid) > 1})
    if duplicates:
        raise ValueError(f"case id collision across registries: {duplicates}")
    return entries


def resolve_spec(cid: str):
    """One spec by id across every known registry; ``None`` when unknown."""
    spec = case_specs.get_spec(cid)
    return spec if spec is not None else w20_case_specs.get_w20_spec(cid)


def is_supplemental(cid: str) -> bool:
    return w20_case_specs.get_w20_spec(cid) is not None
