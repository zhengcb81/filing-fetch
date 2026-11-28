"""Replay frozen native receipts from the last release without rewriting its occurrence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ff_persistence import owner_io_path
from test_ff_runtime_lifecycle import Case, _feedback_request
from test_scheduled_refresh import configure_body
from test_scheduled_refresh_public_e2e import _PUBLIC_OWNER


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
CAPTURE = Path(__file__).parent / "fixtures" / "native_labels_c72c3a1.json"
RAW_RUN = "sk-fixture-native-label-202611"
RAW_ATTEMPT = "tvly-fixture-native-attempt-202611"


def _invoke(scripts, root, program, args, *, body=None, environment=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith("RESEARCH_FEEDBACK_")}
    result = subprocess.run(
        [sys.executable, "-B", "-X", "utf8", str(scripts / (program + ".py")), *map(str, args)],
        input=json.dumps(body) if body is not None else "",
        encoding="utf-8", capture_output=True, timeout=30, cwd=root,
        env={**env, **(environment or {})}, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert (result.returncode, result.stderr) == (0, ""), (result.stdout, result.stderr)
    return json.loads(result.stdout)


def _digest_alias(label):
    return "ref-" + hashlib.sha256(label.encode()).hexdigest()


def _packet_numbers(root):
    outbox = owner_io_path(root / "outbox")
    return {path.name for path in outbox.glob("*.jsonl")}


def _snapshot(root):
    paths = ("owner/jobs", "owner/scheduled", "outbox", "owner/observations", "calls")
    result = {}
    for path in paths:
        source = owner_io_path(root / path)
        if source.is_file():
            result[path] = source.read_bytes().decode("utf-8")
            continue
        for entry in source.rglob("*"):
            if entry.is_file() and not entry.name.endswith(".lock"):
                name = Path(path) / entry.relative_to(owner_io_path(root / path))
                result[name.as_posix()] = entry.read_bytes().decode("utf-8")
    return result


def _restore(root, name, *, with_outbox=True):
    snapshot = json.loads(CAPTURE.read_text(encoding="utf-8"))[name]
    if not with_outbox:
        snapshot = {filename: value for filename, value in snapshot.items() if not filename.startswith("outbox/")}
    for filename, value in snapshot.items():
        path = owner_io_path(root / filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode("utf-8"))
    return snapshot


def _observe(root, check):
    rows = (
        json.loads(line)
        for item in owner_io_path(root / "outbox").glob("*.jsonl")
        for line in item.read_bytes().splitlines()
    )
    return next(row for row in rows if row["check_id"] == check)


def _subject(root, command, *args, body=None):
    return _invoke(SCRIPTS, root, "ff_job_feedback",
                   [command, "--jobs-dir", root / "owner", *args], body=body,
                   environment={"RESEARCH_FEEDBACK_DIR": str(root / "outbox")})


def _job_capture(root, scripts, *, invalid_config=False, interrupted=False):
    """Use the released job CLI and its transport to capture one original attempt."""
    root.mkdir(parents=True, exist_ok=True)
    case = Case(root, "park" if interrupted else "ok")
    case.scripts = scripts
    case.jobs = root / "owner"
    case.inbox = root / "outbox"
    case.env.update(RESEARCH_FEEDBACK_DIR=str(case.inbox),
                    RESEARCH_FEEDBACK_RUN_ID=RAW_RUN, RESEARCH_FEEDBACK_ATTEMPT_ID=RAW_ATTEMPT)
    if invalid_config:
        case.config.write_text("{", encoding="utf-8")
    job = case.submit()
    if interrupted:
        child = subprocess.Popen(
            case.argv("ff_job.py", "--jobs-dir", str(case.jobs), "run", "--owner-job-id", job,
                      "--config", str(case.config), "--timeout-seconds", "12"),
            env=case.env, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            case.wait_for_dispatch(child)
            assert case.calls.read_text() == "park\n" and child.poll() is None
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=8)
        return _snapshot(root)
    reply = case.run_job(job)
    assert reply.returncode == 0
    assert json.loads(reply.stdout)["job"]["status"] == ("unknown" if invalid_config else "succeeded")
    assert case.count() == (0 if invalid_config else 1)
    return _snapshot(root)


def _slot_capture(root, scripts):
    root.mkdir(parents=True, exist_ok=True)
    fixture = root / "owner_fixture"
    fixture.mkdir()
    fake = fixture / "public_owner.py"
    fake.write_text(_PUBLIC_OWNER, encoding="utf-8")
    connection = root / "connection.json"
    connection.write_text(json.dumps({
        "schema_version": "1.0",
        "connection": {"cwd": str(fixture), "commands": {
            "incremental_discover": [sys.executable, "-B", str(fake), "discover"],
            "incremental_read": [sys.executable, "-B", str(fake), "read"],
        }},
    }), encoding="utf-8")
    (root / "scheduled_refresh.json").write_text(json.dumps({
        "schema_version": "ff-scheduled-refresh-deployment/1", "pinned_rosters": "exports.json",
    }), encoding="utf-8")
    (root / "exports.json").write_text(json.dumps({"rosters": {"primary": {
        "snapshot_id": "legacy-slot-fixture", "items": [
            {"entity_id": "issuer-test", "listing_id": "listing-test", "market": "US", "ticker": "TEST"},
        ],
    }}}), encoding="utf-8")
    fixed = ["--config", connection, "--jobs-dir", root / "owner"]
    labels = {"RESEARCH_FEEDBACK_DIR": str(root / "outbox"),
              "RESEARCH_FEEDBACK_RUN_ID": RAW_RUN, "RESEARCH_FEEDBACK_ATTEMPT_ID": RAW_ATTEMPT}
    _invoke(scripts, root, "ff_scheduled_refresh", [*fixed, "configure", "--request-stdin"],
            body=configure_body(roster={"mode": "pinned", "roster_ref": "primary"},
                                transcripts_enabled=False, backlog_enabled=False),
            environment=labels)
    completed = _invoke(scripts, root, "ff_scheduled_refresh", [*fixed, "tick"], environment=labels)
    assert completed["last_run"]["state"] == "completed" and completed["last_run"]["counts"]["read"] == 1
    assert len((fixture / "calls.jsonl").read_bytes().splitlines()) == 2
    return _snapshot(root)


def capture_release(scripts, target):
    """Regenerate the frozen durable bytes from the exact c72 source archive."""
    target.mkdir(parents=True)
    captures = {
        "code_version": "c72c3a12995dec3b5acd462d805ab344f35f2712",
        "job": _job_capture(target / "job", scripts),
        "job_unknown": _job_capture(target / "job_unknown", scripts, invalid_config=True),
        "job_interrupted": _job_capture(target / "job_interrupted", scripts, interrupted=True),
        "slot": _slot_capture(target / "slot", scripts),
    }
    for name, check in (("job", "job-outcome"), ("job_unknown", "job-outcome"), ("slot", "refresh-outcome")):
        row = _observe(target / name, check)
        assert (row["run_id"], row["attempt_id"]) == (RAW_RUN, RAW_ATTEMPT)
        assert len(list((target / name / "outbox").glob("*.jsonl"))) == 1
    opened = _observe(target / "job_interrupted", "action-started")
    assert (opened["run_id"], opened["attempt_id"]) == (RAW_RUN, RAW_ATTEMPT)
    (target / CAPTURE.name).write_bytes((json.dumps(captures, indent=1) + "\n").encode("utf-8"))


def test_real_legacy_frozen_job_and_slot_packets_are_already_offered(tmp_path):
    for name, check in (("job", "job-outcome"), ("job_unknown", "job-outcome"), ("slot", "refresh-outcome")):
        root = tmp_path / name
        before = _restore(root, name)
        row = _observe(root, check)
        assert (row["run_id"], row["attempt_id"]) == (RAW_RUN, RAW_ATTEMPT)
        for _ in range(2):
            result = _subject(root, "flush-observations")
            assert result["status"] == "ok" and result["job_offers"] == result["direct_offers"] == 0
            assert _snapshot(root) == before and len(_packet_numbers(root)) == 1
        if name == "job_unknown":
            problem = _observe(root, "job-failure")
            detail = _subject(root, "get-diagnostic", problem["details_ref"])
            assert (detail["run_id"], detail["attempt_id"]) == (_digest_alias(RAW_RUN), _digest_alias(RAW_ATTEMPT))
            assert detail["causes"][0]["type"] and _snapshot(root) == before


def test_original_job_and_slot_never_echo_old_labels_when_reoffering_a_missing_packet(tmp_path):
    for name, check in (("job", "job-outcome"), ("job_unknown", "job-outcome"), ("slot", "refresh-outcome")):
        root = tmp_path / name
        originals = _restore(root, name, with_outbox=False)
        # A missing old delivery still needs one current publication.
        result = _subject(root, "flush-observations")
        assert result["status"] == "ok"
        row = _observe(root, check)
        assert (row["run_id"], row["attempt_id"]) == (_digest_alias(RAW_RUN), _digest_alias(RAW_ATTEMPT))
        assert len(_packet_numbers(root)) == 1
        after = _snapshot(root)
        assert all(after[filename] == value for filename, value in originals.items())
        assert not any(RAW_RUN in value or RAW_ATTEMPT in value for name, value in after.items()
                       if name.startswith("outbox/"))
        result = _subject(root, "flush-observations")
        assert result["status"] == "ok" and result["job_offers"] == result["direct_offers"] == 0
        assert _snapshot(root) == after


def test_modern_and_retained_slot_resolve_both_caller_coordinates(tmp_path):
    for root, current in ((tmp_path / "legacy", False), (tmp_path / "current", True)):
        before = _slot_capture(root, SCRIPTS) if current else _restore(root, "slot")
        row = _observe(root, "refresh-outcome")
        with_raw = dict(row, run_id=RAW_RUN, attempt_id=RAW_ATTEMPT)
        with_alias = dict(row, run_id=_digest_alias(RAW_RUN), attempt_id=_digest_alias(RAW_ATTEMPT))
        by_raw = _subject(root, "reconcile", body=_feedback_request(with_raw))
        by_alias = _subject(root, "reconcile", body=_feedback_request(with_alias))
        other = _subject(root, "reconcile", body=_feedback_request(dict(with_alias, attempt_id="unrelated")))
        assert other == {"state": "unknown"}
        assert by_raw == by_alias and by_raw["state"] == "done"
        facts = by_raw["result"]
        assert facts["evidence_ref"] == row["evidence_ref"] and facts["native_attempt"] == with_alias["attempt_id"]
        assert facts["counts"]["read"] == 1 and facts["counts"]["downloaded"] == 0
        assert RAW_RUN not in json.dumps(facts) and RAW_ATTEMPT not in json.dumps(facts)
        assert _snapshot(root) == before
        if current:
            assert len((root / "owner_fixture" / "calls.jsonl").read_bytes().splitlines()) == 2

@pytest.mark.parametrize("detail_state", ["missing", "corrupt"])
def test_frozen_legacy_event_stays_offered_independently_of_optional_detail(tmp_path, detail_state):
    before = _restore(tmp_path, "job_unknown")
    problem = _observe(tmp_path, "job-failure")
    name = problem["details_ref"].rsplit("/", 1)[-1]
    path = owner_io_path(tmp_path / "outbox" / (name + ".cause.json"))
    diagnostic = before.pop(f"outbox/{path.name}")
    assert RAW_RUN in diagnostic
    if detail_state == "missing":
        path.unlink()
    else:
        path.write_bytes(b"{invalid JSON")
        before[f"outbox/{path.name}"] = "{invalid JSON"
    for _ in range(2):
        result = _subject(tmp_path, "flush-observations")
        assert result["status"] == "ok" and result["job_offers"] == 0
        assert _packet_numbers(tmp_path) == {name + ".jsonl"}
        after = _snapshot(tmp_path)
        assert all(after[key] == value for key, value in before.items())
    if detail_state == "missing":
        assert RAW_RUN.encode() not in path.read_bytes() and RAW_ATTEMPT.encode() not in path.read_bytes()
        restored = _subject(tmp_path, "get-diagnostic", problem["details_ref"])
        assert restored["causes"] == json.loads(diagnostic)["causes"]
        assert restored["run_id"] == _digest_alias(RAW_RUN)


@pytest.mark.parametrize("native_outbox", [False, True])
def test_interrupted_c72_job_closes_its_actual_original_start(tmp_path, native_outbox):
    original = _restore(tmp_path, "job_interrupted", with_outbox=not native_outbox)
    if native_outbox:
        archived = json.loads(CAPTURE.read_text(encoding="utf-8"))["job_interrupted"]
        for filename, body in archived.items():
            if filename.startswith("outbox/"):
                path = owner_io_path(tmp_path / "owner" / "observations" / Path(filename).name)
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(body.encode("utf-8"))
    outbox = owner_io_path(tmp_path / ("owner/observations" if native_outbox else "outbox"))
    start, = outbox.glob("*.jsonl")
    original_start = {path.name: path.read_bytes() for path in outbox.iterdir()}
    original_files = _snapshot(tmp_path)
    start_row = json.loads(start.read_bytes().splitlines()[0])
    assert (start_row["run_id"], start_row["attempt_id"], start_row["check_id"]) == (
        RAW_RUN, RAW_ATTEMPT, "action-started",
    )
    jobs = {name: data for name, data in original.items() if name.startswith("owner/jobs/")}
    assert len(jobs) == 1 and next(iter(map(json.loads, jobs.values())))["status"] == "running"
    assert (tmp_path / "calls").read_text() == "park\n"
    answer = _subject(tmp_path, "flush-observations")
    assert answer["status"] == "ok" and answer["job_offers"] == 1
    terminal_packets = [packet for packet in outbox.glob("*.jsonl") if packet != start]
    assert len(terminal_packets) == 1
    complete = terminal_packets[0]
    assert all((outbox / name).read_bytes() == contents for name, contents in original_start.items())
    final = [json.loads(line) for line in complete.read_bytes().splitlines()]
    assert all(row["check_id"] != "action-started" for row in final)
    for row in final:
        assert row["run_id"] == _digest_alias(RAW_RUN)
        assert row["attempt_id"] == _digest_alias(RAW_ATTEMPT)
        assert all(row[key] == start_row[key] for key in ("owner", "step_id", "evidence_ref"))
    for path in outbox.iterdir():
        if path.is_file() and path.name not in original_start:
            assert RAW_RUN.encode() not in path.read_bytes() and RAW_ATTEMPT.encode() not in path.read_bytes()
    assert next(row for row in final if row["check_id"] == "job-outcome")["actual"] == "unknown"
    assert next(row for row in final if row["check_id"] == "job-usage")["actual"] == "unknown"
    assert (tmp_path / "calls").read_text() == "park\n"
    stable = _snapshot(tmp_path)
    assert all(stable[name] == data for name, data in jobs.items())
    assert all(RAW_RUN not in contents and RAW_ATTEMPT not in contents
               for name, contents in stable.items() if name not in original_files)
    assert _subject(tmp_path, "flush-observations")["job_offers"] == 0
    assert _snapshot(tmp_path) == stable
    if native_outbox:
        assert not _packet_numbers(tmp_path)


def _unique_json_fields(pairs):
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("duplicate field")
    return fields


def _stamp_packet_name(rows):
    from uuid import NAMESPACE_URL, uuid5

    key = json.dumps([*(rows[0][field] for field in ("owner", "run_id", "attempt_id", "step_id")),
                      "complete"], ensure_ascii=True, separators=(",", ":"))
    return "feedback-" + uuid5(NAMESPACE_URL, key).hex


@pytest.mark.parametrize("failure", ["receipt_without_outcome", "terminal_other_evidence",
                                     "duplicate_outcome_field", "wrong_terminal", "marker_other_origin"])
@pytest.mark.parametrize("normalized", [False, True])
def test_false_terminal_from_frozen_c72_can_be_reoffered_without_replacing_history(tmp_path, failure, normalized):
    _restore(tmp_path, "job_unknown")
    inbox = owner_io_path(tmp_path / "outbox")
    original, = inbox.glob("*.jsonl")
    decoded = [json.loads(line) for line in original.read_bytes().splitlines()]
    terminal, = [row for row in decoded if row["check_id"] == "job-outcome"]
    assert terminal["actual"] == "unknown"
    if normalized:
        for row in decoded:
            for field, label in (("run_id", RAW_RUN), ("attempt_id", RAW_ATTEMPT)):
                row[field] = _digest_alias(label)
        name = _stamp_packet_name(decoded)
        original = original.rename(inbox / (name + ".jsonl"))
    if failure == "receipt_without_outcome":
        selected = [row for row in decoded if row["check_id"] in {"action-started", "job-usage"}]
    else:
        selected = decoded
    if failure == "terminal_other_evidence":
        for row in selected:
            row["evidence_ref"] = "ff-job/1/unrelated-owner-job"
    if failure == "wrong_terminal":
        terminal["actual"] = "succeeded"
    lines = []
    for row in selected:
        line = json.dumps(row, ensure_ascii=True, sort_keys=True)
        if failure == "duplicate_outcome_field" and row is terminal:
            line = '{"actual":"started",' + line[1:]
        lines.append(line)
    original.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    if failure == "marker_other_origin":
        original.with_suffix(".ready").write_text(json.dumps({"origin_owner": "another-owner"}), encoding="ascii")
    before = _snapshot(tmp_path)
    known = next(json.loads(body) for name, body in before.items() if name.startswith("owner/jobs/"))
    result = _subject(tmp_path, "flush-observations")
    assert result["status"] == "ok" and result["job_offers"] == 1
    after = _snapshot(tmp_path)
    for key, value in before.items():
        if key == "outbox/logs/runtime-errors.jsonl":
            assert after[key].startswith(value)
            tail = after[key][len(value):]
            assert RAW_RUN not in tail and RAW_ATTEMPT not in tail
        else:
            assert after[key] == value
    published, = [path for path in inbox.glob("*.jsonl") if path != original]
    observed = [json.loads(line, object_pairs_hook=_unique_json_fields)
                for line in published.read_bytes().splitlines()]
    restored, = [row for row in observed if row["check_id"] == "job-outcome"]
    assert restored["evidence_ref"] == f"ff-job/1/{known['owner_job_id']}"
    assert restored["actual"] == known["status"] == "unknown"
    assert restored["run_id"] == _digest_alias(RAW_RUN)
    assert restored["attempt_id"] == _digest_alias(RAW_ATTEMPT)
    usage, = [row for row in observed if row["check_id"] == "job-usage"]
    assert usage["actual"] == "unknown" and usage["disposition"] == "unknown"
    assert not any(RAW_RUN in item or RAW_ATTEMPT in item for key, item in after.items() if key not in before)
    cold = _subject(tmp_path, "reconcile", body=_feedback_request(restored))
    assert cold == {"state": "unknown"}
    assert not any(key.startswith("owner/") for key in after.keys() - before.keys())
    replay = _subject(tmp_path, "flush-observations")
    assert replay["job_offers"] == 0 and _snapshot(tmp_path) == after


@pytest.mark.parametrize("fault", [
    None, "duplicate-identical-row", "observation-count", "step-ids", "packet-digest",
    "detail-count", "missing-declared-details", "wrong-detail-reference", "detail-digest",
])
def test_declared_ready_must_match_the_frozen_packet(tmp_path, fault):
    historical = _restore(tmp_path, "job_unknown")
    inbox = owner_io_path(tmp_path / "outbox")
    original, = inbox.glob("*.jsonl")
    ready = original.with_suffix(".ready")
    details = original.with_name(original.name + ".details.jsonl")
    packet_bytes = original.read_bytes()
    rows = [json.loads(line) for line in packet_bytes.splitlines()]
    refs = {row["details_ref"] for row in rows if "details_ref" in row}
    assert refs
    details_bytes = "".join(json.dumps({"details_id": ref}) + "\n" for ref in sorted(refs)).encode("ascii")
    if fault == "duplicate-identical-row":
        packet_bytes += packet_bytes.splitlines(keepends=True)[0]
        original.write_bytes(packet_bytes)
    manifest = {
        **json.loads(ready.read_bytes()),
        "schema_version": "feedback-delivery-ready/1",
        "observations": len(rows),
        "step_ids": sorted({row["step_id"] for row in rows}),
        "observations_sha256": hashlib.sha256(packet_bytes).hexdigest(),
        "details": len(refs),
    }
    if fault == "observation-count":
        manifest["observations"] += 1
    elif fault == "step-ids":
        manifest["step_ids"] = ["unrelated-step"]
    elif fault == "packet-digest":
        manifest["observations_sha256"] = "0" * 64
    elif fault == "detail-count":
        manifest["details"] += 1
    elif fault == "wrong-detail-reference":
        details_bytes = b'{"details_id":"unrelated-reference"}\n'
    if fault != "missing-declared-details":
        details.write_bytes(details_bytes)
        manifest["details_sha256"] = "0" * 64 if fault == "detail-digest" else hashlib.sha256(details_bytes).hexdigest()
    ready.write_bytes(json.dumps(manifest).encode("ascii"))
    before = _snapshot(tmp_path)
    expected_offer = int(fault not in {None, "duplicate-identical-row"})
    first = _subject(tmp_path, "flush-observations")
    assert first["status"] == "ok" and first["job_offers"] == expected_offer, first
    after = _snapshot(tmp_path)
    for name, value in before.items():
        if name == "outbox/logs/runtime-errors.jsonl":
            # Delivery can append one diagnostic while retaining the frozen log.
            assert after[name].startswith(value)
            appended = after[name][len(value):]
            assert RAW_RUN not in appended and RAW_ATTEMPT not in appended
        else:
            assert after[name] == value, name
    assert all(after[name] == value for name, value in historical.items() if name.startswith("owner/"))
    assert not (tmp_path / "calls").exists()
    if expected_offer:
        repaired, = (path for path in inbox.glob("feedback-*.jsonl") if path not in {original, details})
        terminal, = (row for row in map(json.loads, repaired.read_bytes().splitlines()) if row["check_id"] == "job-outcome")
        frozen, = (row for row in rows if row["check_id"] == "job-outcome")
        assert terminal["evidence_ref"] == frozen["evidence_ref"]
        assert terminal["actual"] == frozen["actual"] == "unknown"
        assert terminal["run_id"] == _digest_alias(RAW_RUN)
        assert terminal["attempt_id"] == _digest_alias(RAW_ATTEMPT)
        assert _subject(tmp_path, "reconcile", body=_feedback_request(terminal)) == {"state": "unknown"}
    assert _subject(tmp_path, "flush-observations")["job_offers"] == 0
    assert _snapshot(tmp_path) == after


def test_scheduled_usage_packet_cannot_acknowledge_the_frozen_slot(tmp_path):
    _restore(tmp_path, "slot")
    inbox = owner_io_path(tmp_path / "outbox")
    original, = inbox.glob("*.jsonl")
    expected = _observe(tmp_path, "refresh-outcome")
    usage = dict(expected, check_id="refresh-usage", expected="accounted", actual="known")
    prior = (json.dumps(usage) + "\n").encode()
    original.write_bytes(prior)
    before = _snapshot(tmp_path)
    result = _subject(tmp_path, "flush-observations")
    assert result["status"] == "ok"
    terminal = _observe(tmp_path, "refresh-outcome")
    assert terminal["evidence_ref"] == expected["evidence_ref"]
    assert terminal["actual"] == expected["actual"] == "completed"
    assert original.read_bytes() == prior
    after = _snapshot(tmp_path)
    assert all(after[key] == item for key, item in before.items())
    assert _subject(tmp_path, "flush-observations")["status"] == "ok"
    assert _snapshot(tmp_path) == after


def test_direct_statement_usage_packet_is_repaired_once_without_a_second_call(tmp_path):
    from test_ff_runtime_lifecycle import REQUEST

    case = Case(tmp_path, "ok")
    result = case.invoke("fetch_statements.py", "--config", str(case.config), body=REQUEST)
    assert result.returncode == 0 and case.count() == 1
    old, = case.inbox.glob("*.jsonl")
    rows = [json.loads(line) for line in old.read_bytes().splitlines()]
    terminal, = [row for row in rows if row["check_id"] == "execution-outcome"]
    prior = "".join(json.dumps(row) + "\n" for row in rows if row is not terminal).encode()
    old.write_bytes(prior)
    owner = ["--jobs-dir", str(case.jobs)]
    result = case.invoke("ff_job_feedback.py", "flush-observations", *owner)
    assert result.returncode == 0 and json.loads(result.stdout)["direct_offers"] == 1
    repaired, = [path for path in case.inbox.glob("*.jsonl") if path != old]
    recovered, = [row for row in map(json.loads, repaired.read_bytes().splitlines())
                  if row["check_id"] == "execution-outcome"]
    assert recovered["actual"] == terminal["actual"] and recovered["evidence_ref"] == terminal["evidence_ref"]
    assert old.read_bytes() == prior
    detail = case.invoke("ff_job_feedback.py", "get-diagnostic", recovered["details_ref"], *owner)
    assert detail.returncode == 0 and json.loads(detail.stdout)["reason"]
    repeated = case.invoke("ff_job_feedback.py", "flush-observations", *owner)
    assert repeated.returncode == 0 and json.loads(repeated.stdout)["direct_offers"] == 0
    assert old.read_bytes() == prior and case.count() == 1
