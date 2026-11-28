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
    header = tuple(observation[field] for field in _HEADER)
    canonical = _packet_name(header, "complete")
    reference = observation.get("details_ref")
    if not isinstance(reference, str) or not re.fullmatch(r"ff-diagnostic/1/feedback-[a-f0-9]{32}", reference):
        return None
    name = reference.rsplit("/", 1)[-1]
    for root in directories:
        if name != canonical:
            packet = _read_packet(root, name)
            if (packet is None or packet.header != header or not _matches_phase(packet, observation, started=False)):
                continue
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
    packet = _read_packet(root, name)
    if packet is None or not _matches_phase(packet, observation, started=False):
        return False
    for row in packet.rows:
        check = row["check_id"]
        if check in pairs and all(row.get(field) == observation[field] for field in scope):
            pairs[check].add(row["actual"])
    return pairs == {"provider-start": {"not_started"}, "provider-usage": {"not_applicable"}}


@dataclass(frozen=True)
class _DeliveredPacket:
    root: Path
    name: str
    header: tuple
    rows: list[dict]
    started: bool


_OBSERVATION_REQUIRED = (*_HEADER, "check_id", "expected", "actual")
_OBSERVATION_OPTIONAL = (
    "origin_owner", "issue_key", "version", "evidence_ref", "details_ref", "parent_step_id",
    "disposition", "original_occurrence_id", "terminal_check_id",
)
_DISPOSITIONS = {"expected", "unknown", "deviation"}
_REFUSAL_CODE = re.compile(r"[a-z][a-z0-9_-]{0,80}")


def _unique_fields(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate observation field")
        result[name] = value
    return result


def _observed_row(line):
    value = json.loads(line.decode("utf-8"), object_pairs_hook=_unique_fields)
    if not isinstance(value, dict) or value.get("schema_version") != "feedback-observation/1":
        raise ValueError("unsupported observation")
    row = {}
    for key in (*_OBSERVATION_REQUIRED, *_OBSERVATION_OPTIONAL):
        item = value.get(key)
        if key in _OBSERVATION_OPTIONAL and item is None:
            continue
        if not isinstance(item, str) or not item.strip():
            raise ValueError("invalid observation field")
        row[key] = item
    row.setdefault("origin_owner", row["owner"])
    if "disposition" not in row:
        row["disposition"] = ("unknown" if "unknown" in (row["expected"], row["actual"]) else
                              "expected" if row["expected"] == row["actual"] else "deviation")
    if row["disposition"] not in _DISPOSITIONS:
        raise ValueError("invalid observation disposition")
    code = value.get("refusal_code")
    if isinstance(code, str) and _REFUSAL_CODE.fullmatch(code):
        row["refusal_code"] = code
    return row


def _marker_matches(content, rows):
    marker = json.loads(content, object_pairs_hook=_unique_fields)
    if not isinstance(marker, dict):
        return False
    identity_fields = ("owner", "origin_owner", "run_id", "attempt_id", "step_id", "check_id")
    if any(marker.get(field, row[field]) != row[field] for row in rows for field in identity_fields):
        return False
    if "occurrence_id" in marker:
        identities = {
            hashlib.sha256(json.dumps([row[field] for field in identity_fields], ensure_ascii=True,
                                      separators=(",", ":")).encode("ascii")).hexdigest()
            for row in rows
        }
        return identities == {marker["occurrence_id"]} if isinstance(marker["occurrence_id"], str) else False
    return True


def _read_packet(root, name):
    try:
        body = owner_io_path(root / (name + ".jsonl")).read_bytes()
        if not body.endswith(b"\n"):
            return None
        rows = [_observed_row(line) for line in body.splitlines() if line.strip()]
        if not rows or rows[0]["owner"] != "filing-fetch":
            return None
        header = tuple(rows[0][key] for key in _HEADER)
        observed = {}
        for row in rows:
            if tuple(row[key] for key in _HEADER) != header:
                return None
            occurrence = row["origin_owner"], row["check_id"]
            prior = observed.setdefault(occurrence, row)
            if row != prior:
                return None
        ready = owner_io_path(root / (name + ".ready"))
        try:
            content = ready.read_bytes()
        except FileNotFoundError:
            content = b""
        if content and not _marker_matches(content, rows):
            return None
    except (OSError, ValueError, RecursionError):
        return None
    started = all(row["check_id"] == "action-started" for row in rows)
    return _DeliveredPacket(root, name, header, rows, started)


def _matches_phase(packet, source, *, started):
    if packet is None or packet.started != started:
        return False
    evidence = source.get("evidence_ref")
    origin = source.get("origin_owner", source["owner"])
    if not evidence or any(row.get("evidence_ref") != evidence or row["origin_owner"] != origin for row in packet.rows):
        return False
    check_id = source["check_id"]
    if started:
        return any(
            row["check_id"] == "action-started" and row["expected"] == row["actual"] == "started"
            and row["disposition"] == "expected" and "refusal_code" not in row
            and row.get("terminal_check_id") == source.get("terminal_check_id")
            for row in packet.rows
        )
    if check_id == "action-started":
        return any(
            row["check_id"] == source.get("terminal_check_id") and row["expected"] in {"completed", "terminal"}
            and row["actual"] not in {"started", "pending", "running", "unconfirmed"}
            for row in packet.rows
        )
    return any(
        (row["check_id"], row["expected"], row["actual"]) ==
        (check_id, source["expected"], source["actual"])
        for row in packet.rows
    )


def _occupied(root, name, header):
    for extension in (".jsonl", ".pending", ".process"):
        try:
            owner_io_path(root / (name + extension)).lstat()
        except FileNotFoundError:
            continue
        return True
    # A same-scope FF marker can survive loss of its packet. Reopen its
    # original slot while leaving genuinely conflicting history untouched.
    try:
        marker = owner_io_path(root / (name + ".ready")).read_bytes()
        return bool(marker) and json.loads(marker, object_pairs_hook=_unique_fields) != dict(zip(_HEADER, header))
    except FileNotFoundError:
        return False
    except (OSError, ValueError, RecursionError):
        return True


def _packet_slot(root, header, source, *, started):
    phase = "started" if started else "complete"
    number = 0
    while True:
        name = _packet_name(header, phase if not number else f"{phase}/recovery/{number}")
        packet = _read_packet(root, name)
        if packet is not None and packet.header == header and _matches_phase(packet, source, started=started):
            return name, packet
        if not _occupied(root, name, header):
            return name, None
        number += 1


def _existing_packet(row, directories, *, started):
    original = tuple(row[key] for key in _HEADER)
    normalized = feedback_wire(row)
    current = tuple(normalized[key] for key in _HEADER)
    for header in dict.fromkeys((original, current)):
        for root in directories:
            try:
                _, packet = _packet_slot(root, header, row, started=started)
            except OSError:
                continue
            if packet is not None:
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


def _with_detail(rows, name, *, detail_for_all):
    return [
        dict(row, details_ref="ff-diagnostic/1/" + name)
        if detail_for_all or row.get("disposition") == "deviation" or "refusal_code" in row else row
        for row in rows
    ]


def _save_detail(root, name, marker, detail):
    destination = owner_io_path(root / (name + ".cause.json"))
    value = {**redact_diagnostic(detail), **marker}
    try:
        original = json.loads(destination.read_bytes(), object_pairs_hook=_unique_fields)
    except FileNotFoundError:
        atomic_write_json(destination, value)
        return True
    except (ValueError, RecursionError):
        return False
    return original == value


class _DetailUnavailable(OSError):
    """A new terminal may retry a different diagnostics destination."""


def _write_packet(root, marker_key, marker, group, prefix, frozen, *, detail, detail_for_all, started):
    root = owner_io_path(root)
    root.mkdir(parents=True, exist_ok=True)
    # The lock covers classification and the name choice. A corrupt file reserves
    # its historical name but cannot acknowledge a different phase or outcome.
    with acquire_file_lock(root / ".delivery.lock", 0.7):
        if started and _packet_slot(root, marker_key, group[0], started=False)[1] is not None:
            return
        name, previous = _packet_slot(root, marker_key, group[0], started=started)
        if previous is not None:
            return
        packet = root / (name + ".jsonl")
        if detail is not None:
            try:
                saved = _save_detail(root, name, marker, detail)
            except OSError as error:
                raise _DetailUnavailable("native diagnostic could not be saved") from error
            if not saved:
                raise _DetailUnavailable("native diagnostic slot already contains history")
            group = _with_detail(group, name, detail_for_all=detail_for_all)
        atomic_write_text(packet, _text([*prefix, *group]))
        ready = packet.with_suffix(".ready")
        if not ready.exists():
            atomic_write_json(ready, marker)
        sent = packet.with_suffix(".sent")
        if frozen and not sent.exists():
            atomic_write_text(sent, "")
        if prefix:
            _, initial = _packet_slot(root, marker_key, prefix[0], started=True)
            if initial is not None:
                start = root / initial.name
                start.with_suffix(".ready").unlink(missing_ok=True)
                start.with_suffix(".jsonl").unlink(missing_ok=True)


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


def _publish_native(targets, marker_key, marker, group, prefix, frozen, *, detail, detail_for_all, started, notice):
    failed = None
    detail_failure = None
    for root in targets:
        try:
            _write_packet(root, marker_key, marker, group, prefix, frozen, detail=detail,
                          detail_for_all=detail_for_all, started=started)
            return True
        except _DetailUnavailable as error:
            detail_failure = error.__cause__ or error
        except LockBusy as error:
            # A concurrent writer is already publishing to this same native destination.
            notice.note("feedback publication", error)
            return False
        except OSError as error:
            failed = error
    if detail_failure is not None:
        notice.note("feedback detail", detail_failure)
        if not frozen:
            return _publish_native(targets, marker_key, marker, group, prefix, frozen, detail=None,
                                   detail_for_all=detail_for_all, started=started, notice=notice)
    else:
        notice.note("feedback publication", failed)
    return False


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
            group = [feedback_wire(row) for row in original_group]
            marker_key = tuple(group[0][key] for key in _HEADER)
            prefix = [r for r in context if tuple(r[key] for key in _HEADER) == marker_key]
            native_start = original_group[0] if only_start else (
                dict(prefix[0], **dict(zip(_HEADER, original_key))) if prefix else None
            )
            active = _existing_packet(native_start, directories, started=True) if native_start else None
            if only_start and active is not None:
                continue
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
            if file and not legacy_start:
                explicit = group
                diagnostic_available = not local_detail
                if local_detail:
                    for root in targets:
                        try:
                            root = owner_io_path(root)
                            root.mkdir(parents=True, exist_ok=True)
                            with acquire_file_lock(root / ".delivery.lock", 0.7):
                                if not _occupied(root, name, marker_key) and _save_detail(root, name, marker, detail):
                                    explicit = _with_detail(group, name, detail_for_all=detail_for_all)
                                    diagnostic_available = True
                                    break
                        except (OSError, LockBusy) as error:
                            notice.note("feedback detail", error)
                if (diagnostic_available or not frozen) and _explicit(file, explicit):
                    continue
            if legacy_start:
                prefix = []
            offered = _publish_native(targets, marker_key, marker, group, prefix, frozen,
                                      detail=detail if local_detail else None, detail_for_all=detail_for_all,
                                      started=only_start, notice=notice) and offered
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
