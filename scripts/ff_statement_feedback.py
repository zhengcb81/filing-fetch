"""Lossless outcome and usage fields from a financial-statements response, without report contents."""

from __future__ import annotations

import hashlib
import os
import re
import uuid

from ff_financial_statements import RESPONSE_STATUSES, STATEMENT_TYPES, STATEMENTS_RESPONSE_SCHEMA_VERSION
from ff_runtime_feedback import OUT_ENV, RULE_CODES, identity, publish


ERROR_STATUS = {"request_error", "config_error", "fatal"}
COVERAGE_CODES = {
    "complete", "period_boundary", "no_data", "end_of_data", "duplicate_page", "no_progress",
    "count_changed", "max_pages", "provider_error", "budget_stopped", "historical_coverage_unverifiable",
    "historical_asof_unverifiable", "pit_verified", "current_snapshot", "observed_order",
    "legacy_observation_order_unverified",
}
PROVIDER_CODES = {
    "provider_unavailable", "http_error", "protocol_error", "forbidden", "too_many_requests",
    "timeout", "deadline_exceeded", "budget_stopped", "max_bytes", "max_http_exchanges", *RULE_CODES,
}


def _code(value, known):
    if not isinstance(value, str) or not value:
        return None
    if value in known:
        return value
    # Unrecognized provider text may contain a URL or body. Preserve distinct identities.
    return "unrecognized-" + hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()


def _usage(value):
    if not isinstance(value, dict):
        return {}
    amounts = {k: value[k] for k in ("http_requests", "response_bytes")
               if type(value.get(k)) is int and value[k] >= 0}
    cost = value.get("cost_usd")
    if type(cost) in (str, int, float) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", str(cost)):
        amounts["cost_usd"] = cost
    return amounts


def statement_snapshot(envelope):
    """Capture only the public fields needed to reproduce an incomplete response."""
    status = envelope.get("status")
    if status not in ("partial", "unavailable", *ERROR_STATUS):
        return None
    result = {"schema_version": "ff-failure-detail/1", "reason": status, "status": status,
              "statements": [], "usage": _usage(envelope.get("usage"))}
    supplied = envelope.get("statements")
    for raw in supplied if isinstance(supplied, list) else ():
        if not isinstance(raw, dict) or raw.get("statement_type") not in STATEMENT_TYPES:
            continue
        coverage = raw.get("coverage")
        coverage = coverage if isinstance(coverage, dict) else {}
        covered = {k: coverage[k] for k in ("observed_periods", "pages", "advertised_report_count")
                   if type(coverage.get(k)) is int and coverage[k] >= 0}
        table = {"statement_type": raw["statement_type"], "status": _code(raw.get("status"), RESPONSE_STATUSES)
                 or "unknown", "coverage": covered, "usage": _usage(raw.get("usage"))}
        for key in ("terminal_reason", "quality"):
            code = _code(coverage.get(key), COVERAGE_CODES)
            if code:
                covered[key] = code
        for key, allowed in (("error_code", PROVIDER_CODES), ("point_in_time_quality", COVERAGE_CODES),
                             ("version_selection_quality", COVERAGE_CODES)):
            code = _code(raw.get(key), allowed)
            if code:
                table[key] = code
        result["statements"].append(table)
    return result


def _table_row(base, table):
    status = table["status"]
    terminal = table["coverage"].get("terminal_reason")
    error = table.get("error_code")
    row = dict(base, check_id="statement-outcome/" + table["statement_type"], expected="available",
               actual=status, disposition="expected")
    if terminal == "budget_stopped" or error in RULE_CODES:
        row["refusal_code"] = error or terminal
    elif error or status == "unavailable" or terminal == "provider_error":
        row.update(disposition="deviation", issue_key=error or terminal or status)
    elif status == "partial" and terminal in {"duplicate_page", "no_progress", "count_changed"}:
        row.update(disposition="deviation", issue_key=terminal)
    elif status not in ("complete", "not_found", "partial"):
        row["disposition"] = "unknown"
    return row


def statement_rows(base, snapshot, *, summarize):
    rows = [_table_row(base, table) for table in snapshot["statements"]]
    status = snapshot["status"]
    if summarize:
        disposition = "expected"
        if status in ERROR_STATUS or any(row["disposition"] == "deviation" for row in rows):
            disposition = "deviation"
        elif not rows:
            disposition = "deviation" if status == "unavailable" else "unknown"
        elif any(row["disposition"] == "unknown" for row in rows):
            disposition = "unknown"
        summary = dict(base, check_id="execution-outcome", expected="completed", actual=status,
                       disposition=disposition)
        if disposition == "deviation":
            summary["issue_key"] = status
        rows.insert(0, summary)
    known = "cost_usd" in snapshot["usage"] and "http_requests" in snapshot["usage"]
    rows.append(dict(base, check_id="provider-usage", expected="accounted",
                     actual="known" if known else "unknown", disposition="expected" if known else "unknown"))
    return rows


def publish_statement_response(envelope):
    snapshot = statement_snapshot(envelope)
    if snapshot is None:
        return
    op = uuid.uuid4().hex
    base = identity(op, 1, f"statements/{op}", f"ff-cli/1/{op}", STATEMENTS_RESPONSE_SCHEMA_VERSION)
    publish(statement_rows(base, snapshot, summarize=True), file=os.environ.get(OUT_ENV),
            detail=snapshot, detail_for_all=True)
