"""Owner receipts for direct requests and their independent feedback delivery."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from ff_persistence import atomic_write_json, now_iso, owner_io_path
from ff_process_tree import pid_is_alive
from ff_runtime_feedback import (
    identity, observation_directories, publish, start_was_offered, terminal_was_offered, warn_diagnostic_unavailable,
)


@dataclass(frozen=True)
class Surface:
    prefix: str
    step: str
    terminal_check: str
    sources: tuple[str, ...]

    @property
    def schema(self) -> str:
        return self.prefix.removesuffix("/")


STATEMENTS = Surface("ff-statement-run/1/", "statements", "execution-outcome", (
    "fetch_statements.py", "ff_financial_statements.py", "ff_statement_feedback.py",
))
SHORT = Surface("ff-short/1/", "short-filing", "request-outcome", ("fetch_filing.py", "ff_short_feedback.py"))
_SURFACES = (STATEMENTS, SHORT)
_OWNER_SOURCE = Path(__file__).resolve().parent
_OPERATION = re.compile(r"[0-9a-f]{32}")


@lru_cache(maxsize=None)
def _version(surface: Surface) -> str:
    digest = hashlib.sha256()
    for name in (*surface.sources, "ff_direct_run.py", "ff_run_input.py", "ff_process_transport.py",
                 "ff_company_wiki_connection.py"):
        try:
            digest.update(hashlib.sha256((_OWNER_SOURCE / name).read_bytes()).digest())
        except OSError:
            return surface.schema
    return "sha256-" + digest.hexdigest()


class DirectRun:
    def __init__(self, surface: Surface, *, run_id=None, attempt_id=None, operation_id=None, jobs_dir=None):
        operation = operation_id or uuid.uuid4().hex
        self.base = identity(run_id or operation, attempt_id or 1, f"{surface.step}/{operation}",
                             surface.prefix + operation, _version(surface))
        self._jobs_dir = jobs_dir
        self._paths = [_receipt_root(root) / (operation + ".json") for root in observation_directories(jobs_dir)]
        self._record = {
            **self.base, "schema_version": surface.schema, "implementation_version": self.base["version"],
            "pid": os.getpid(), "external_effect": "not_started", "cost_state": "not_applicable", "steps": [],
            "start": _start_row(self.base, surface),
        }
        self.mark("started")

    @property
    def start_row(self) -> dict:
        return self._record["start"]

    @property
    def external_effect(self) -> str:
        return self._record["external_effect"]

    @property
    def producer_exit_code(self) -> int | None:
        return self._record.get("producer_exit_code")

    def child_exited(self, exit_code: int, received: bool) -> None:
        self.mark("producer_exited", producer_exit_code=exit_code,
                  external_effect="response_received" if received else self.external_effect)

    def mark(self, phase: str, **facts) -> None:
        self._record.update(facts)
        self._record["steps"].append({"phase": phase, "at": now_iso()})
        last_error = None
        for path in self._paths:
            try:
                atomic_write_json(path, self._record)
                return
            except (OSError, ValueError, TypeError) as exc:
                last_error = exc
        if last_error is not None:
            warn_diagnostic_unavailable(f"direct run {self.base['evidence_ref']}", last_error)

    def finish(self, *, outcome, effect, cost, rows, start, file=None, detail_for_all=False):
        delivery = {"rows": rows, "start": start, "detail_for_all": detail_for_all}
        self.mark("finished", external_effect=effect, cost_state=cost, outcome=outcome, delivery=delivery)
        _offer(self._record, file=file, jobs_dir=self._jobs_dir)


def _offer(record: dict, *, jobs_dir=None, file=None) -> None:
    delivery = record["delivery"]
    detail = record["outcome"].get("diagnostic")
    publish(delivery["rows"], file=file, jobs_dir=jobs_dir, context=delivery["start"], detail=detail,
            recoverable=True, detail_for_all=delivery["detail_for_all"])


def _receipt_root(outbox: Path) -> Path:
    """Owner receipts are siblings of delivery files, so an outbox failure is independent."""
    return outbox.parent / (outbox.name + "-direct-runs")


def _start_row(base: dict, surface: Surface) -> dict:
    identity_fields = ("owner", "run_id", "attempt_id", "step_id", "evidence_ref", "version")
    return {
        **{field: base[field] for field in identity_fields},
        "schema_version": "feedback-observation/1", "check_id": "action-started",
        "expected": "started", "actual": "started", "disposition": "expected",
        "terminal_check_id": surface.terminal_check,
    }


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(owner_io_path(path).read_bytes())
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(value, dict) or not _OPERATION.fullmatch(path.stem):
        return None
    if not any(value.get("schema_version") == surface.schema
               and value.get("evidence_ref") == surface.prefix + path.stem
               and value.get("step_id") == f"{surface.step}/{path.stem}" for surface in _SURFACES):
        return None
    if (value.get("owner") != "filing-fetch" or not isinstance(value.get("steps"), list)
            or type(value.get("pid")) is not int or value["pid"] <= 0
            or value.get("external_effect") not in ("not_started", "possible", "response_received")
            or value.get("cost_state") not in ("not_applicable", "known", "unknown")
            or not all(isinstance(value.get(field), str) for field in ("run_id", "attempt_id"))):
        return None
    result = value.get("outcome")
    if "outcome" in value and (not isinstance(result, dict) or type(result.get("exit_code")) is not int):
        return None
    return value


def supports_reference(reference: object) -> bool:
    return isinstance(reference, str) and any(reference.startswith(surface.prefix) for surface in _SURFACES)


def _original(reference: str, directories: list[Path], observation=None) -> dict | None:
    operation = reference.rsplit("/", 1)[-1]
    if not supports_reference(reference) or not _OPERATION.fullmatch(operation):
        return None
    candidates = [
        candidate for root in directories
        if (candidate := _read(_receipt_root(root) / (operation + ".json")))
        and candidate["evidence_ref"] == reference
        and (observation is None or _bound(candidate, observation))
    ]
    return max(candidates, key=lambda item: len(item["steps"]), default=None)


def _bound(record: dict, observation: dict) -> bool:
    if any(observation.get(key) != record[key] for key in ("run_id", "attempt_id")):
        return False
    if observation.get("step_id") == record["step_id"]:
        return True
    rows = (record.get("delivery") or {}).get("rows", [])
    return any(row.get("parent_step_id") == record["step_id"]
               and row.get("step_id") == observation.get("step_id")
               and row.get("check_id") == observation.get("check_id") for row in rows)


def _view(record: dict | None) -> dict:
    if record is None:
        return {"state": "unknown"}
    result = {key: value for key, value in record.items() if key not in ("pid", "delivery", "start")}
    if "outcome" in result:
        state = "done"
    else:
        state = "pending" if pid_is_alive(record["pid"]) else "unknown"
        result["outcome"] = None
        if state == "unknown":
            if result["external_effect"] == "not_started":
                # A failed phase write cannot prove the dead process stayed before dispatch.
                result["external_effect"] = "unknown"
            result["cost_state"] = "unknown"
    return {"state": state, "result": result}


def lookup_direct_run(
    directories: list[Path], *, reference=None, run_id=None, attempt_id=None, surface=None,
) -> dict:
    """A public query can use either the returned reference or the caller's original coordinates."""
    if reference is not None:
        if surface is not None and not reference.startswith(surface.prefix):
            return {"state": "unknown"}
        return _view(_original(reference, directories))
    records = [record for record in _durable_runs(directories).values()
               if record["run_id"] == run_id and record["attempt_id"] == attempt_id
               and (surface is None or record["schema_version"] == surface.schema)]
    if len(records) > 1:
        return {"state": "ambiguous", "references": sorted(item["evidence_ref"] for item in records)}
    return _view(next(iter(records), None))


def _durable_runs(directories: list[Path]) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for root in directories:
        try:
            candidates = list(owner_io_path(_receipt_root(root)).glob("*.json"))
        except OSError:
            continue
        for path in candidates:
            record = _read(path)
            if record is None:
                continue
            key = record["evidence_ref"]
            if key not in records or len(record["steps"]) > len(records[key]["steps"]):
                records[key] = record
    return records


def reconcile_direct_run(reference: str, directories: list[Path], observation: dict) -> dict:
    original = _original(reference, directories, observation)
    answer = _view(original)
    trace = answer.get("result")
    if answer["state"] == "pending" or not trace:
        return {"state": answer["state"]}
    outcome = trace["outcome"]
    status = "interrupted" if outcome is None else "succeeded" if outcome["exit_code"] == 0 else "failed"
    cost = trace["cost_state"]
    return {"state": "done", "result": {
        "status": "cost_unknown" if cost == "unknown" else "known",
        "job_status": status, "cost_state": cost, "evidence_ref": reference,
        "native_attempt": trace["attempt_id"], "trace": trace,
        "new_provider_requests": 0, "new_downloads": 0, "new_cost_usd": "0.00",
    }}


def flush_direct_observations(jobs_dir: Path) -> list[bool]:
    """Publish only recorded owner starts and outcomes. This module has no acquisition port."""
    results = []
    for record in _durable_runs(observation_directories(jobs_dir)).values():
        if isinstance(record.get("delivery"), dict) and isinstance(record.get("outcome"), dict):
            result = _reoffer(record, jobs_dir)
            if result is not None:
                results.append(result)
        elif not start_was_offered(record, jobs_dir) and not terminal_was_offered(record, jobs_dir):
            surface = next(item for item in _SURFACES if item.schema == record["schema_version"])
            results.append(publish([_start_row(record, surface)], jobs_dir=jobs_dir, recoverable=True))
    return results


def _reoffer(record: dict, jobs_dir: Path) -> bool | None:
    delivery = record["delivery"]
    detail = record["outcome"].get("diagnostic")
    scopes = {row["step_id"]: row for row in delivery["rows"]}
    missing = {
        step for step, row in scopes.items()
        if not terminal_was_offered(row, jobs_dir, require_detail=step == record["step_id"] and detail is not None)
    }
    if not missing:
        return None
    return publish([row for row in delivery["rows"] if row["step_id"] in missing],
                   jobs_dir=jobs_dir, context=delivery["start"],
                   detail=detail if record["step_id"] in missing else None,
                   recoverable=True, detail_for_all=delivery["detail_for_all"])
