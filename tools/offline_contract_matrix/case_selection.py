"""Explicit generic case selection for the offline contract matrix CLI (W20).

A selected run executes an explicitly named subset of the known case
registries. It is a *supplemental* observation, never a full-matrix
certification:

* the fixed required-case authority never shrinks — ``required_cases`` in the
  report stays the complete base registry;
* every unselected known case stays an honest ``NOT_RUN`` row carrying the
  named selection reason;
* the run's exit code speaks only for the selected cases, and the report says
  so via ``scope.selection`` (``selected``/``completed``/``skipped``).

This module is deliberately pure: parsing, validation and summary only. It
knows nothing about processes, deadlines or repositories, so it is trivially
testable and adds no scheduling authority of its own.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

SCHEMA = "w20-case-selection/1"
NOT_SELECTED_REASON = (
    "not selected — supplemental explicit-case run; the required-case "
    "authority is unchanged and this row was deliberately not executed"
)


class SelectionError(ValueError):
    """The requested explicit case selection is not a valid subset."""


def parse_case_ids(values: Iterable[str | None]) -> list[str]:
    """Split repeated ``--cases`` values into a flat ordered id list.

    Comma-separated ids inside one value and repeated flags are both allowed;
    whitespace is stripped. Empty ids, duplicated ids and an empty overall
    selection are refused: a selection that names nothing or names a case
    twice is a caller mistake, not a meaningful subset.
    """
    ids: list[str] = []
    for value in values:
        if value is None:
            continue
        for part in str(value).split(","):
            name = part.strip()
            if not name:
                continue
            if name in ids:
                raise SelectionError(f"duplicate case id in selection: {name}")
            ids.append(name)
    if not ids:
        raise SelectionError("case selection is empty")
    return ids


def validate_selection(ids: Sequence[str], known: Sequence[str]) -> dict[str, Any]:
    """Validate ``ids`` against the known union registry ids."""
    known_set = set(known)
    unknown = [cid for cid in ids if cid not in known_set]
    if unknown:
        raise SelectionError(
            "unknown case id(s) in selection: "
            f"{sorted(unknown)}; known ids are the fixed required registry plus "
            "registered supplemental suites"
        )
    return {"schema_version": SCHEMA, "mode": "selected", "selected": list(ids)}


def select_entries(entries: Sequence[tuple[str, Any]], selection: dict[str, Any]):
    """Project the run registry onto the selected ids, preserving id order."""
    wanted = list(selection.get("selected") or ())
    by_id = dict(entries)
    missing = [cid for cid in wanted if cid not in by_id]
    if missing:
        raise SelectionError(f"selection names cases outside the registry: {missing}")
    return [(cid, by_id[cid]) for cid in wanted]


def summarize(selection: dict[str, Any], *, results: Sequence[dict[str, Any]],
              known_ids: Sequence[str]) -> dict[str, Any]:
    """Honest selection summary for ``scope.selection``.

    ``completed`` lists selected ids that produced an executed result row
    (PASS/FAIL/PARTIAL — a deadline NOT_RUN of a selected case is *not*
    completed and stays visible as such); ``skipped`` lists every known id that
    was not selected. The summary never rewrites case results.
    """
    selected = list(selection.get("selected") or [])
    selected_set = set(selected)
    observed = {row.get("id") for row in results}
    executed = {
        row.get("id") for row in results if row.get("result") in {"PASS", "FAIL", "PARTIAL"}
    }
    completed = [cid for cid in selected if cid in executed]
    skipped = [cid for cid in known_ids if cid not in selected_set]
    return {
        "schema_version": SCHEMA,
        "mode": "selected",
        "selected": selected,
        "completed": completed,
        "skipped": skipped,
        "selected_not_executed": [cid for cid in selected if cid not in executed],
        "unselected_rows_reported": sorted(observed - selected_set),
        "certifies": (
            "selected cases only; this run is supplemental/partial and never "
            "certifies the full required-case matrix"
        ),
    }
