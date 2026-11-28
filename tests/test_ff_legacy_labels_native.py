"""Replay frozen native receipts from the last release without rewriting its occurrence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

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
    paths = ("owner/jobs", "owner/scheduled", "outbox")
    result = {}
    for path in paths:
        for entry in owner_io_path(root / path).rglob("*"):
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


def _job_capture(root, scripts, *, invalid_config=False):
    """Use the released job CLI and its transport to capture one original attempt."""
    root.mkdir(parents=True, exist_ok=True)
    case = Case(root, "ok")
    case.scripts = scripts
    case.jobs = root / "owner"
    case.inbox = root / "outbox"
    case.env.update(RESEARCH_FEEDBACK_DIR=str(case.inbox),
                    RESEARCH_FEEDBACK_RUN_ID=RAW_RUN, RESEARCH_FEEDBACK_ATTEMPT_ID=RAW_ATTEMPT)
    if invalid_config:
        case.config.write_text("{", encoding="utf-8")
    job = case.submit()
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
        "slot": _slot_capture(target / "slot", scripts),
    }
    for name, check in (("job", "job-outcome"), ("job_unknown", "job-outcome"), ("slot", "refresh-outcome")):
        row = _observe(target / name, check)
        assert (row["run_id"], row["attempt_id"]) == (RAW_RUN, RAW_ATTEMPT)
        assert len(list((target / name / "outbox").glob("*.jsonl"))) == 1
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
