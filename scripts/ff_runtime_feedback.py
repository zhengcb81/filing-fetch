"""Owner delivery and reproducible, data-minimal diagnostics for ordinary filing-fetch runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid

from ff_persistence import (
    LockBusy, acquire_file_lock, atomic_write_json, atomic_write_text, owner_io_path, separate_partial_line,
)
from ff_runtime_log import append_runtime_issue

DEFAULT_JOBS_DIR = Path(__file__).resolve().parents[1] / ".ff_jobs"
OUT_ENV = "RESEARCH_FEEDBACK_OUT"
DIR_ENV = "RESEARCH_FEEDBACK_DIR"
RUN_ENV = "RESEARCH_FEEDBACK_RUN_ID"
ATTEMPT_ENV = "RESEARCH_FEEDBACK_ATTEMPT_ID"
RULE_CODES = frozenset(
    {"budget_exceeded", "byte_budget_exceeded", "cost_budget_exceeded", "acquisition_budget_exceeded"}
)
SCRIPTS = Path(__file__).resolve().parent
_HEADER = ("owner", "run_id", "attempt_id", "step_id")


def identity(run_id, attempt, step, reference, version):
    return {
        "schema_version": "feedback-observation/1",
        "owner": "filing-fetch",
        "run_id": os.environ.get(RUN_ENV) or run_id,
        "attempt_id": os.environ.get(ATTEMPT_ENV) or str(attempt),
        "step_id": step,
        "evidence_ref": reference,
        "version": version,
    }


def cause_details(error, *, reason):
    try:
        return _cause_details(error, reason=reason)
    except Exception:
        return {"schema_version": "ff-failure-detail/1", "reason": reason, "diagnostic": "cause_unavailable"}


def _cause_details(error, *, reason):
    """Follow Python's native chains, including explicit suppression; omit messages, bodies and absolute paths."""
    from ff_process_transport import process_cleanup_facts

    causes = []
    pending = [("raised", error)] if error is not None else []
    seen = set()
    while pending:
        relation, exc = pending.pop()
        if id(exc) in seen:
            continue
        seen.add(id(exc))
        frames = []
        trace = exc.__traceback__
        while trace is not None:
            code = trace.tb_frame.f_code
            filename = Path(code.co_filename)
            frame = {"file": filename.name, "function": code.co_name, "line": trace.tb_lineno}
            if filename.parent == SCRIPTS:
                try:
                    frame["source_sha256"] = hashlib.sha256(filename.read_bytes()).hexdigest()
                except OSError:
                    pass
            frames.append(frame)
            trace = trace.tb_next
        item = {"relation": relation, "type": type(exc).__name__, "frames": frames}
        cleanup = process_cleanup_facts(exc)
        if cleanup:
            item["process_cleanup"] = cleanup
        for name in ("errno", "winerror", "lineno", "colno", "pos"):
            value = getattr(exc, name, None)
            if type(value) is int:
                item[name] = value
        causes.append(item)
        if exc.__context__ is not None and exc.__context__ is not exc.__cause__:
            pending.append(("context", exc.__context__))
        if exc.__cause__ is not None:
            pending.append(("cause", exc.__cause__))
    result = {"schema_version": "ff-failure-detail/1", "reason": reason, "causes": causes}
    if error is not None:
        from ff_provider_cause import validated_acquisition_failure, validated_cause

        failure = validated_acquisition_failure(
            getattr(error, "acquisition_failure", None)
        ) or validated_cause(getattr(error, "upstream_cause", None))
        if failure:
            result["owner_reason"] = failure["code"]
    return result


def _text(rows):
    return "".join(json.dumps(row, ensure_ascii=True) + "\n" for row in rows)


def _explicit(file, rows):
    try:
        with owner_io_path(Path(file)).open("ab+") as stream:
            separate_partial_line(stream)
            stream.write(_text(rows).encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())
        return True
    except OSError:
        return False


def _packet_name(marker_key, phase):
    key = json.dumps([*marker_key, phase], separators=(",", ":"), ensure_ascii=True)
    return "feedback-" + uuid.uuid5(uuid.NAMESPACE_URL, key).hex


def owner_child_environment():
    """Each downstream owner publishes in its own outbox, never into the caller's exclusive files."""
    return {
        key: value for key, value in os.environ.items() if key not in {OUT_ENV, DIR_ENV, RUN_ENV, ATTEMPT_ENV}
    }


def _feedback_targets(default):
    override = os.environ.get(DIR_ENV)
    return list(dict.fromkeys([Path(override), default] if override else [default]))


def observation_directories(jobs_dir=None):
    return _feedback_targets(Path(jobs_dir or DEFAULT_JOBS_DIR) / "observations")


def _runtime_roots(jobs_dir):
    return _feedback_targets(Path(jobs_dir or DEFAULT_JOBS_DIR))


def record_runtime_failure(surface, reason, error=None, *, jobs_dir=None, run_id=None, detail=None, base=None):
    """Record an owner CLI/control failure locally, without creating F4 work for itself."""
    try:
        if base is None:
            occurrence = uuid.uuid4().hex
            base = identity(run_id or occurrence, 1, f"{surface}/{occurrence}", f"ff-cli/1/{occurrence}", "ff-cli/1")
        row = dict(base, check_id="execution-outcome", expected="completed", actual=reason,
                   disposition="deviation", issue_key=reason)
        append_runtime_issue(_runtime_roots(jobs_dir), [row], detail or cause_details(error, reason=reason))
    except Exception:
        return


def read_native_diagnostic(name, directories):
    """Return the first readable diagnostic bound to this occurrence."""
    unreadable = None
    for root in directories:
        try:
            value = json.loads(owner_io_path(root / (name + ".cause.json")).read_bytes())
            if not isinstance(value, dict) or value.get("schema_version") != "ff-failure-detail/1":
                raise ValueError("invalid diagnostic schema")
            key = tuple(value.get(field) for field in _HEADER)
            if (key[0] != "filing-fetch" or not all(isinstance(part, str) and part for part in key)
                    or name not in {_packet_name(key, "started"), _packet_name(key, "complete")}):
                raise ValueError("diagnostic occurrence does not match reference")
            return value, None
        except FileNotFoundError:
            continue
        except (OSError, ValueError, RecursionError) as error:
            unreadable = error
    return None, unreadable


def read_cli_failure(observation, directories):
    """Project only the occurrence and usage that the original CLI left at its owner."""
    operation, _, invocation = observation["step_id"].partition("/")
    if (not invocation or observation.get("evidence_ref") != f"ff-cli/1/{invocation}"
            or observation.get("check_id") != "execution-outcome"):
        return None
    name = _packet_name(tuple(observation[field] for field in _HEADER), "complete")
    reference = f"ff-diagnostic/1/{name}"
    if observation.get("details_ref") != reference:
        return None
    for root in directories:
        detail, _ = read_native_diagnostic(name, [root])
        if detail is None or detail.get("reason") != observation.get("actual"):
            continue
        known = _recorded_no_dispatch(root, name, observation)
        return {
            "operation": operation, "outcome": detail["reason"], "diagnostic_ref": reference,
            "invocation_usage": {"provider_started": False if known else None,
                                 "cost_state": "not_applicable" if known else "unknown"},
            "target_job_cost_state": "unknown",
        }
    return None


def _recorded_no_dispatch(root, name, observation):
    pairs = {"provider-start": set(), "provider-usage": set()}
    scope = (*_HEADER, "evidence_ref")
    try:
        packet = owner_io_path(root / (name + ".jsonl"))
        for line in packet.read_bytes().splitlines():
            row = json.loads(line)
            if (isinstance(row, dict) and row.get("schema_version") == "feedback-observation/1"
                    and all(row.get(field) == observation[field] for field in scope)):
                check, actual = row.get("check_id"), row.get("actual")
                if isinstance(check, str) and check in pairs and isinstance(actual, str):
                    pairs[check].add(actual)
    except (OSError, ValueError, RecursionError):
        return False
    return pairs == {"provider-start": {"not_started"}, "provider-usage": {"not_applicable"}}


def _was_offered(row, jobs_dir, *, started, require_detail=False):
    name = _packet_name(tuple(row[k] for k in _HEADER), "started" if started else "complete")
    directories = observation_directories(jobs_dir)
    if require_detail and read_native_diagnostic(name, directories)[0] is None:
        return False
    for directory in directories:
        try:
            data = owner_io_path(directory / (name + ".jsonl")).read_bytes()
            if not data.endswith(b"\n"):
                continue
            rows = [json.loads(line) for line in data.splitlines()]
            if (rows and all(
                isinstance(item, dict) and item.get("schema_version") == "feedback-observation/1"
                and all(item.get(k) == row[k] for k in _HEADER)
                and all(isinstance(item.get(k), str) and item[k] for k in ("check_id", "expected", "actual"))
                for item in rows
            ) and all(item["check_id"] == "action-started" for item in rows) == started):
                return True
        except (OSError, ValueError, RecursionError):
            continue
    return False


def terminal_was_offered(row, jobs_dir, *, require_detail=False):
    return _was_offered(row, jobs_dir, started=False, require_detail=require_detail)


def start_was_offered(row, jobs_dir):
    return _was_offered(row, jobs_dir, started=True)


def _write_packet(root, name, marker_key, marker, content, frozen, closes_start, *, started):
    root = owner_io_path(root)
    root.mkdir(parents=True, exist_ok=True)
    packet = root / (name + ".jsonl")
    sent = packet.with_suffix(".sent")
    # Serialize publication against the runner and maintenance inside each native outbox.
    with acquire_file_lock(root / ".delivery.lock", 0.7):
        if started and (root / (_packet_name(marker_key, "complete") + ".jsonl")).is_file():
            return
        if packet.is_file() and packet.read_text(encoding="utf-8") == content:
            return
        atomic_write_text(packet, content)
        atomic_write_json(packet.with_suffix(".ready"), marker)
        if frozen:
            atomic_write_text(sent, "")
        if closes_start:
            initial = root / (_packet_name(marker_key, "started") + ".ready")
            initial.unlink(missing_ok=True)
            initial.with_suffix(".jsonl").unlink(missing_ok=True)


def warn_diagnostic_unavailable(component: str, error: Exception) -> None:
    """Report a failed diagnostics channel without changing the business protocol."""
    error_type = type(error).__name__
    if not re.fullmatch(r"[A-Za-z_]\w{0,95}", error_type, re.ASCII):
        error_type = "Exception"
    try:
        if sys.stderr is not None:  # pythonw.exe has no stderr.
            print(f"warning: filing-fetch {component} unavailable ({error_type})", file=sys.stderr)
    except Exception:
        # The diagnostic stream can itself be unavailable or be a host adapter.
        pass


def publish(rows, *, jobs_dir=None, file=None, context=(), detail=None, recoverable=False, detail_for_all=False):
    """Explicit sidecars keep append semantics. Native packets use one immutable occurrence identity.

    The .ready signal follows a complete same-directory atomic write. On a cold revisit an
    already-delivered identical packet remains acknowledged. A failed sidecar falls back to
    the registered owner state, even when an additional outbox path is unavailable.
    """
    try:
        publication_error = None
        detail_error = None
        groups = {}
        for row in rows:
            groups.setdefault(tuple(row[k] for k in _HEADER), []).append(dict(row))
        directories = observation_directories(jobs_dir)
        runtime_roots = _runtime_roots(jobs_dir)
        for marker_key, group in groups.items():
            marker = dict(zip(_HEADER, marker_key))
            only_start = all(row["check_id"] == "action-started" for row in group)
            name = _packet_name(marker_key, "started" if only_start else "complete")
            local_detail = detail is not None and all(rows[0][key] == marker[key] for key in _HEADER)
            frozen = recoverable or (not only_start and any(r["check_id"] == "job-outcome" for r in group))
            append_runtime_issue(runtime_roots, group, detail if local_detail else None)
            if local_detail:
                for item in group:
                    if detail_for_all or item.get("disposition") == "deviation" or "refusal_code" in item:
                        item["details_ref"] = "ff-diagnostic/1/" + name
            # Prefer a published native detail, and never point to a missing diagnostic.
            if local_detail:
                failed = None
                for root in directories:
                    try:
                        atomic_write_json(root / (name + ".cause.json"), {**marker, **detail})
                        break
                    except OSError as error:
                        failed = error
                else:
                    detail_error = failed
                    # The owner still has the diagnostic in its original receipt.
                    # Keep this packet for recovery without offering a weaker occurrence.
                    if frozen:
                        continue
                    for item in group:
                        item.pop("details_ref", None)
            if file and _explicit(file, group):
                continue
            prefix = [r for r in context if all(r[k] == marker[k] for k in _HEADER)]
            content = _text([*prefix, *group])
            failed = None
            for root in directories:
                try:
                    _write_packet(root, name, marker_key, marker, content, frozen, bool(prefix), started=only_start)
                    break
                except LockBusy as error:
                    # A healthy primary writer is already publishing. Keep the same pending
                    # owner receipt, so maintenance retries that packet rather than cloning it.
                    publication_error = error
                    break
                except OSError as error:
                    failed = error
            else:
                publication_error = failed
        if publication_error is not None:
            warn_diagnostic_unavailable("feedback publication", publication_error)
        elif detail_error is not None:
            warn_diagnostic_unavailable("feedback detail", detail_error)
        return publication_error is None and detail_error is None
    except Exception as error:
        # The owner result and fee record take precedence over optional diagnostics.
        warn_diagnostic_unavailable("feedback publication", error)
        return False


def cli_failure(surface, reason, error=None, *, jobs_dir=None, no_dispatch=False, child_process=None):
    op = uuid.uuid4().hex
    base = identity(op, 1, f"{surface}/{op}", f"ff-cli/1/{op}", "ff-cli/1")
    row = dict(
        base,
        check_id="execution-outcome",
        expected="completed",
        actual=reason,
        disposition="deviation",
        issue_key=reason,
    )
    rows = [row]
    if no_dispatch:
        rows.append(
            dict(
                base,
                check_id="provider-start",
                expected="not_started",
                actual="not_started",
                disposition="expected",
            )
        )
        rows.append(
            dict(
                base,
                check_id="provider-usage",
                expected="accounted",
                actual="not_applicable",
                disposition="expected",
            )
        )
    detail = cause_details(error, reason=reason)
    if child_process is not None:
        detail["child_process"] = child_process
    publish(rows, file=os.environ.get(OUT_ENV), jobs_dir=jobs_dir, detail=detail)
    return base["evidence_ref"]


def parse_arguments(parser: argparse.ArgumentParser, argv, surface, *, local_only=False):
    try:
        return parser.parse_args(argv)
    except SystemExit as error:
        if error.code:
            args = list(sys.argv[1:] if argv is None else argv)
            root = None
            for index, arg in enumerate(args):
                if arg == "--jobs-dir" and index + 1 < len(args):
                    root = args[index + 1]
                    break
                if arg.startswith("--jobs-dir="):
                    root = arg.partition("=")[2]
                    break
            if local_only:
                record_runtime_failure(surface, "argument_error", error, jobs_dir=root)
            else:
                cli_failure(surface, "argument_error", error, jobs_dir=root, no_dispatch=True)
        raise
