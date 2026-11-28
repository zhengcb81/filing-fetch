"""Owner delivery and reproducible, data-minimal diagnostics for ordinary filing-fetch runs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from functools import wraps
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
from ff_process_transport import ChildFailed, process_cleanup_facts
from ff_runtime_log import (
    append_runtime_issue, caller_coordinates, child_failure_details, redact_diagnostic, redact_text, safe_identity,
)

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


class OwnerArgumentParser(argparse.ArgumentParser):
    """Retain argparse's exit and usage protocol without reflecting a credential."""

    def error(self, message):
        super().error(redact_text(message))


@dataclass
class CliDiagnostics:
    surface: str
    argv: tuple[str, ...]
    code_version: str
    occurrence: str = field(default_factory=lambda: uuid.uuid4().hex)
    described_error: int | None = None
    warned_steps: set[tuple[str, ...]] = field(default_factory=set)

    def jobs_dir(self):
        for index, arg in enumerate(self.argv):
            if arg == "--jobs-dir" and index + 1 < len(self.argv):
                return self.argv[index + 1]
            if arg.startswith("--jobs-dir="):
                return arg.partition("=")[2]
        return None

    def execution(self):
        input_ref = hashlib.sha256(json.dumps(self.argv, ensure_ascii=True).encode("ascii")).hexdigest()
        return {"surface": self.surface, "code_version": self.code_version, "input_ref": input_ref}

    def note(self, error):
        if error is not None:
            self.described_error = id(error)


def implementation_version(source: str, fallback: str) -> str:
    try:
        return hashlib.sha256(Path(source).read_bytes()).hexdigest()
    except OSError:
        return fallback


def observed_cli(surface, *, local_only=False):
    """Bind one process entry, including owner-side validation after argument parsing."""
    def decorate(function):
        code_version = implementation_version(function.__code__.co_filename, "ff-cli/1")

        @wraps(function)
        def run(argv=None):
            invocation = CliDiagnostics(surface, tuple(sys.argv[1:] if argv is None else argv), code_version)
            try:
                return function(argv, diagnostics=invocation)
            except SystemExit as error:
                if error.code and id(error) != invocation.described_error:
                    _entry_failure(invocation, "argument_error", error, local_only=local_only, no_dispatch=True)
                raise
            except Exception as error:
                if id(error) != invocation.described_error:
                    _entry_failure(invocation, "fatal", error, local_only=local_only)
                raise

        return run
    return decorate


def cli_exit(entry) -> int:
    """Render the final CLI-only traceback without exception text or machine inputs."""
    try:
        return entry()
    except Exception as error:
        if sys.stderr is not None:
            try:
                sys.stderr.write("Traceback (most recent call last):\n")
                trace = error.__traceback__
                while trace is not None:
                    code = trace.tb_frame.f_code
                    filename = safe_identity(Path(code.co_filename).name)
                    sys.stderr.write(f'  File "{filename}", line {trace.tb_lineno}\n')
                    trace = trace.tb_next
                sys.stderr.write(f"{safe_identity(type(error).__name__)}\n")
            except (OSError, ValueError):
                # The ingress already retained the original cause through its own sinks.
                pass
        return 1


def _entry_failure(invocation, reason, error, *, local_only, no_dispatch=False):
    if local_only:
        record_runtime_failure(invocation.surface, reason, error, jobs_dir=invocation.jobs_dir(),
                               diagnostics=invocation)
    else:
        cli_failure(invocation.surface, reason, error, jobs_dir=invocation.jobs_dir(), no_dispatch=no_dispatch,
                    diagnostics=invocation)


def identity(run_id, attempt, step, reference, version, *, labels=None):
    if labels is None:
        labels = os.environ
    return {
        "schema_version": "feedback-observation/1",
        "owner": "filing-fetch",
        "run_id": safe_identity(labels.get(RUN_ENV) or run_id),
        "attempt_id": safe_identity(labels.get(ATTEMPT_ENV) or str(attempt)),
        "step_id": step,
        "evidence_ref": reference,
        "version": version,
    }


def retained_identity(run_id, attempt, step, reference, version, *, stored):
    """Read the original owner's coordinates, including spelling from an earlier release."""
    base = identity(run_id, attempt, step, reference, version, labels={})
    if isinstance(stored, dict):
        for name in ("run_id", "attempt_id"):
            value = stored.get(name)
            if isinstance(value, str) and value:
                base[name] = value
    return base


def feedback_wire(row):
    """Project safe coordinates for newly emitted evidence or a public diagnostic reply."""
    run_id, attempt_id = caller_coordinates(row["run_id"], row["attempt_id"])
    return dict(row, run_id=run_id, attempt_id=attempt_id)


def cause_details(error, *, reason):
    try:
        return _cause_details(error, reason=reason)
    except Exception:
        return {"schema_version": "ff-failure-detail/1", "reason": reason, "diagnostic": "cause_unavailable"}


def _cause_details(error, *, reason):
    """Follow Python's native chains, including explicit suppression; omit messages, bodies and absolute paths."""
    child = None
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
        if child is None and isinstance(exc, ChildFailed):
            child = child_failure_details(exc.returncode, exc.stderr, truncated=exc.stderr_truncated)
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
    if child is not None:
        result["child_process"] = child
    if error is not None:
        from ff_provider_cause import validated_acquisition_failure, validated_cause

        failure = validated_acquisition_failure(
            getattr(error, "acquisition_failure", None)
        ) or validated_cause(getattr(error, "upstream_cause", None))
        if failure:
            result["owner_reason"] = failure["code"]
    return redact_diagnostic(result)


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


def record_runtime_failure(
    surface, reason, error=None, *, jobs_dir=None, run_id=None, detail=None, base=None,
    diagnostics=None, execution=None,
) -> bool:
    """Record locally without creating F4 work. Return whether the journal was written."""
    try:
        if diagnostics:
            diagnostics.note(error)
        if base is None:
            occurrence = diagnostics.occurrence if diagnostics else uuid.uuid4().hex
            base = identity(run_id or occurrence, 1, f"{surface}/{occurrence}", f"ff-cli/1/{occurrence}", "ff-cli/1")
        row = dict(base, check_id="execution-outcome", expected="completed", actual=reason,
                   disposition="deviation", issue_key=reason)
        notice = _SinkNotice(base, diagnostics)
        _write_runtime_issue(
            _runtime_roots(jobs_dir), [row], detail or cause_details(error, reason=reason),
            execution=diagnostics.execution() if diagnostics else execution, notice=notice,
        )
        notice.emit()
        return notice.failure is None
    except Exception as failure:
        warn_diagnostic_unavailable("runtime log", failure, scope=base, diagnostics=diagnostics)
        return False


def read_native_diagnostic(name, directories):
    """Return the first readable diagnostic bound to this occurrence."""
    unreadable = None
    for root in directories:
        try:
            value = json.loads(owner_io_path(root / (name + ".cause.json")).read_bytes())
            if not isinstance(value, dict) or value.get("schema_version") != "ff-failure-detail/1":
                raise ValueError("invalid diagnostic schema")
            key = tuple(value.get(field) for field in _HEADER)
            if key[0] != "filing-fetch" or not all(isinstance(part, str) and part for part in key):
                raise ValueError("diagnostic occurrence does not match reference")
            if name not in {_packet_name(key, "started"), _packet_name(key, "complete")}:
                packet = _read_packet(root, name)
                if (packet is None or packet.started or not _packet_links_detail(packet)
                        or feedback_wire(dict(zip(_HEADER, packet.header))) != dict(zip(_HEADER, key))):
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


@dataclass(frozen=True)
class _DeliveredPacket:
    root: Path
    name: str
    header: tuple
    rows: list[dict]
    started: bool


def _read_packet(root, name):
    try:
        body = owner_io_path(root / (name + ".jsonl")).read_bytes()
        if not body.endswith(b"\n"):
            return None
        rows = [json.loads(line) for line in body.splitlines()]
    except (OSError, ValueError, RecursionError):
        return None
    if not rows or not isinstance(rows[0], dict):
        return None
    header = tuple(rows[0].get(key) for key in _HEADER)
    if header[0] != "filing-fetch" or not all(isinstance(part, str) and part for part in header):
        return None
    if not all(
        isinstance(row, dict) and row.get("schema_version") == "feedback-observation/1"
        and tuple(row.get(key) for key in _HEADER) == header
        and all(isinstance(row.get(key), str) and row[key] for key in ("check_id", "expected", "actual"))
        for row in rows
    ):
        return None
    started = all(row["check_id"] == "action-started" for row in rows)
    if name != _packet_name(header, "started" if started else "complete"):
        return None
    return _DeliveredPacket(root, name, header, rows, started)


def _existing_packet(row, directories, *, started):
    original = tuple(row[key] for key in _HEADER)
    normalized = feedback_wire(row)
    current = tuple(normalized[key] for key in _HEADER)
    for header in dict.fromkeys((original, current)):
        name = _packet_name(header, "started" if started else "complete")
        for root in directories:
            packet = _read_packet(root, name)
            if packet is not None and packet.header == header and packet.started == started:
                return packet
    return None


def _packet_links_detail(packet):
    return any(row.get("details_ref") == "ff-diagnostic/1/" + packet.name for row in packet.rows)


def _restore_terminal_detail(packet, detail):
    # A detail is optional. It can be restored at its existing locator, but
    # neither an unavailable detail nor a failed repair reopens the event.
    if not isinstance(detail, dict) or not _packet_links_detail(packet):
        return
    marker = feedback_wire(dict(zip(_HEADER, packet.header)))
    root = owner_io_path(packet.root)
    destination = root / (packet.name + ".cause.json")
    try:
        with acquire_file_lock(root / ".delivery.lock", 0.7):
            try:
                destination.lstat()
            except FileNotFoundError:
                atomic_write_json(destination, {**redact_diagnostic(detail), **marker})
    except (OSError, ValueError, TypeError) as error:
        warn_diagnostic_unavailable("feedback detail", error, scope=marker)


def terminal_was_offered(row, jobs_dir, *, detail=None):
    packet = _existing_packet(row, observation_directories(jobs_dir), started=False)
    if packet is None:
        return False
    _restore_terminal_detail(packet, detail)
    return True


def start_was_offered(row, jobs_dir):
    return _existing_packet(row, observation_directories(jobs_dir), started=True) is not None

def _write_packet(root, name, marker_key, marker, content, frozen, closes_start, *, started):
    root = owner_io_path(root)
    root.mkdir(parents=True, exist_ok=True)
    packet = root / (name + ".jsonl")
    sent = packet.with_suffix(".sent")
    # Serialize publication against the runner and maintenance inside each native outbox.
    with acquire_file_lock(root / ".delivery.lock", 0.7):
        if started and _read_packet(root, _packet_name(marker_key, "complete")) is not None:
            return
        if _read_packet(root, name) is not None:
            return
        atomic_write_text(packet, content)
        atomic_write_json(packet.with_suffix(".ready"), marker)
        if frozen:
            atomic_write_text(sent, "")
        if closes_start:
            initial = root / (_packet_name(marker_key, "started") + ".ready")
            initial.unlink(missing_ok=True)
            initial.with_suffix(".jsonl").unlink(missing_ok=True)


def warn_diagnostic_unavailable(
    component: str, error: Exception, *, scope: dict | None = None, diagnostics: CliDiagnostics | None = None,
) -> None:
    """Report a failed diagnostics channel without changing the business protocol."""
    error_type = type(error).__name__
    if not re.fullmatch(r"[A-Za-z_]\w{0,95}", error_type, re.ASCII):
        error_type = "Exception"
    facts = []
    if scope:
        for name in ("run_id", "attempt_id", "step_id"):
            value = scope.get(name)
            if isinstance(value, str):
                safe = safe_identity(value)
                if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", safe) or ":/" in safe or safe.startswith("/"):
                    safe = "ref-" + hashlib.sha256(safe.encode("utf-8", errors="surrogatepass")).hexdigest()
                facts.append(f"{name}={safe}")
    warning_scope = tuple(facts)
    if diagnostics and warning_scope in diagnostics.warned_steps:
        return
    if diagnostics:
        diagnostics.warned_steps.add(warning_scope)
    suffix = " " + " ".join(facts) if facts else ""
    stream = sys.stderr  # pythonw.exe may have no attached diagnostic stream.
    if stream is None:
        return
    try:
        stream.write(f"warning: filing-fetch {component} unavailable{suffix} ({error_type})\n")
        stream.flush()
    except (OSError, ValueError, TypeError, RuntimeError, AttributeError):
        # An unavailable host diagnostic stream cannot change the business result.
        return


@dataclass
class _SinkNotice:
    scope: dict
    diagnostics: CliDiagnostics | None
    failure: tuple[str, Exception] | None = None

    def note(self, component, error):
        if error is not None:
            self.failure = component, error

    def emit(self):
        if self.failure is not None:
            component, error = self.failure
            warn_diagnostic_unavailable(component, error, scope=self.scope, diagnostics=self.diagnostics)


def _write_runtime_issue(roots, rows, detail, *, execution, notice):
    notice.note("runtime log", append_runtime_issue(roots, rows, detail, execution=execution))


def publish(
    rows, *, jobs_dir=None, file=None, context=(), detail=None, recoverable=False,
    detail_for_all=False, diagnostics=None, execution=None,
):
    """Explicit sidecars keep append semantics. Native packets use one immutable occurrence identity.

    The .ready signal follows a complete same-directory atomic write. On a cold revisit an
    already-delivered identical packet remains acknowledged. A failed sidecar falls back to
    the registered owner state, even when an additional outbox path is unavailable.
    """
    try:
        offered = True
        notices = []
        groups = {}
        if diagnostics is not None and execution is None:
            execution = diagnostics.execution()
        context = [feedback_wire(row) for row in context]
        for row in rows:
            groups.setdefault(tuple(row[k] for k in _HEADER), []).append(row)
        directories = observation_directories(jobs_dir)
        runtime_roots = _runtime_roots(jobs_dir)
        for original_key, original_group in groups.items():
            local_detail = detail is not None and tuple(rows[0][key] for key in _HEADER) == original_key
            only_start = all(row["check_id"] == "action-started" for row in original_group)
            previous = _existing_packet(original_group[0], directories, started=False)
            if previous is not None:
                if not only_start and local_detail:
                    _restore_terminal_detail(previous, detail)
                continue
            active = _existing_packet(original_group[0], directories, started=True)
            if only_start and active is not None:
                continue
            group = [feedback_wire(row) for row in original_group]
            marker_key = tuple(group[0][key] for key in _HEADER)
            legacy_start = active is not None and active.header != marker_key
            # The raw start must remain available for F4. Its terminal carries
            # the same owner/evidence/step with safe caller coordinates.
            targets = [active.root, *[root for root in directories if root != active.root]] if legacy_start else directories
            marker = dict(zip(_HEADER, marker_key))
            notice = _SinkNotice(marker, diagnostics)
            notices.append(notice)
            name = _packet_name(marker_key, "started" if only_start else "complete")
            frozen = recoverable or (not only_start and any(r["check_id"] == "job-outcome" for r in group))
            _write_runtime_issue(
                runtime_roots, group, detail if local_detail else None,
                execution=execution, notice=notice,
            )
            if local_detail:
                for item in group:
                    if detail_for_all or item.get("disposition") == "deviation" or "refusal_code" in item:
                        item["details_ref"] = "ff-diagnostic/1/" + name
            # Prefer a published native detail, and never point to a missing diagnostic.
            if local_detail:
                failed = None
                for root in targets:
                    try:
                        atomic_write_json(root / (name + ".cause.json"), {**redact_diagnostic(detail), **marker})
                        break
                    except OSError as error:
                        failed = error
                else:
                    offered = False
                    notice.note("feedback detail", failed)
                    # The owner still has the diagnostic in its original receipt.
                    # Keep this packet for recovery without offering a weaker occurrence.
                    if frozen:
                        continue
                    for item in group:
                        item.pop("details_ref", None)
            if file and not legacy_start and _explicit(file, group):
                continue
            prefix = [] if legacy_start else [r for r in context if all(r[k] == marker[k] for k in _HEADER)]
            content = _text([*prefix, *group])
            failed = None
            for root in targets:
                try:
                    _write_packet(root, name, marker_key, marker, content, frozen, bool(prefix), started=only_start)
                    break
                except LockBusy as error:
                    # A healthy primary writer is already publishing. Keep the same pending
                    # owner receipt, so maintenance retries that packet rather than cloning it.
                    offered = False
                    notice.note("feedback publication", error)
                    break
                except OSError as error:
                    failed = error
            else:
                offered = False
                notice.note("feedback publication", failed)
        for notice in notices:
            notice.emit()
        return offered
    except Exception as error:
        # The owner result and fee record take precedence over optional diagnostics.
        warn_diagnostic_unavailable("feedback publication", error, diagnostics=diagnostics)
        return False


def cli_failure(surface, reason, error=None, *, jobs_dir=None, no_dispatch=False, diagnostics=None):
    if diagnostics:
        diagnostics.note(error)
    op = diagnostics.occurrence if diagnostics else uuid.uuid4().hex
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
    publish(rows, file=os.environ.get(OUT_ENV), jobs_dir=jobs_dir, detail=detail, diagnostics=diagnostics)
    return base["evidence_ref"]
