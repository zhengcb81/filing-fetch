"""Owner delivery and reproducible, data-minimal diagnostics for ordinary filing-fetch runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

from ff_persistence import atomic_write_json, atomic_write_text, owner_io_path

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
            stream.seek(0, os.SEEK_END)
            if stream.tell():
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    stream.write(b"\n")
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


def observation_directories(jobs_dir=None):
    default = Path(jobs_dir or DEFAULT_JOBS_DIR) / "observations"
    override = os.environ.get(DIR_ENV)
    return list(dict.fromkeys([Path(override), default] if override else [default]))


def terminal_was_offered(row, jobs_dir):
    name = _packet_name(tuple(row[k] for k in _HEADER), "complete")
    return any(
        owner_io_path(directory / (name + ".sent")).is_file()
        for directory in observation_directories(jobs_dir)
    )


def publish(rows, *, jobs_dir=None, file=None, context=(), detail=None):
    """Explicit sidecars keep append semantics. Native packets use one immutable occurrence identity.

    The .ready signal follows a complete same-directory atomic write. On a cold revisit an
    already-delivered identical packet remains acknowledged. A failed sidecar falls back to
    the registered owner state, even when an additional outbox path is unavailable.
    """
    try:
        groups = {}
        for row in rows:
            groups.setdefault(tuple(row[k] for k in _HEADER), []).append(row)
        directories = observation_directories(jobs_dir)
        for marker_key, group in groups.items():
            marker = dict(zip(_HEADER, marker_key))
            only_start = all(row["check_id"] == "action-started" for row in group)
            name = _packet_name(marker_key, "started" if only_start else "complete")
            local_detail = detail is not None and group[0] is rows[0]
            if local_detail:
                for item in group:
                    if item.get("disposition") == "deviation" or "refusal_code" in item:
                        item["details_ref"] = "ff-diagnostic/1/" + name
            # Prefer a published native detail, and never point to a missing diagnostic.
            if local_detail:
                for root in directories:
                    try:
                        atomic_write_json(root / (name + ".cause.json"), {**marker, **detail})
                        break
                    except OSError:
                        continue
                else:
                    for item in group:
                        item.pop("details_ref", None)
            if file and _explicit(file, group):
                continue
            prefix = [r for r in context if all(r[k] == marker[k] for k in _HEADER)]
            content = _text([*prefix, *group])
            for root in directories:
                try:
                    packet = owner_io_path(root / (name + ".jsonl"))
                    if packet.exists() and packet.read_text(encoding="utf8") == content:
                        # Identical source occurrence has already been offered or acknowledged.
                        # The delivery witness also distinguishes a crash before first .ready.
                        if packet.with_suffix(".sent").exists():
                            break
                    atomic_write_text(packet, content)
                    atomic_write_json(packet.with_suffix(".ready"), marker)
                    if not only_start and any(r["check_id"] == "job-outcome" for r in group):
                        # Only the durable job port can replay a terminal native record.
                        atomic_write_text(packet.with_suffix(".sent"), "")
                    if prefix:
                        # A drain acknowledging the start can only unlink its own marker.
                        initial = owner_io_path(root / (_packet_name(marker_key, "started") + ".ready"))
                        initial.unlink(missing_ok=True)
                        initial.with_suffix(".jsonl").unlink(missing_ok=True)
                    break
                except OSError:
                    continue
    except Exception:
        # The owner result and fee record take precedence over optional diagnostics.
        return


def cli_failure(surface, reason, error=None, *, jobs_dir=None, no_dispatch=False):
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
    publish(rows, file=os.environ.get(OUT_ENV), jobs_dir=jobs_dir, detail=cause_details(error, reason=reason))


def parse_arguments(parser: argparse.ArgumentParser, argv, surface):
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
            cli_failure(surface, "argument_error", error, jobs_dir=root, no_dispatch=True)
        raise
