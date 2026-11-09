"""ff-job/1 cross-process CLI tests: every step is a fresh ``ff_job.py`` process.

The durable store's contract is that state survives process boundaries, so
this suite drives the real CLI through subprocesses against one temp jobs
dir: submit (proc 1) → get_status (proc 2) → act cancel (proc 3) →
get_status (proc 4) → list_jobs (proc 5), plus exit-code and error-envelope
conventions. No engine runs here (submit/cancel/status are engine-free by
design); the engine-in-the-loop chain is proven in the real evidence runs
under planning/ff-job-facade-01/evidence/.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
FF_JOB_CLI = SKILL_ROOT / "scripts" / "ff_job.py"

_FILING_REQUEST = {
    "schema_version": "2.0",
    "company_query": "Apple Inc.",
    "document_kind": "annual_report",
    "fiscal_year": 2025,
    "as_of_date": "2026-07-18",
    "filing_intent": "reuse_only",
    "mode": "exact",
}


def _run_cli(*argv: str, jobs_dir: str, body: dict | None = None,
             timeout: float = 120.0) -> tuple[int, dict | None, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    command = [sys.executable, str(FF_JOB_CLI), "--jobs-dir", jobs_dir, *argv]
    stdin = json.dumps(body, ensure_ascii=False) if body is not None else None
    completed = subprocess.run(
        command, input=stdin, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout, env=env,
    )
    payload = None
    if completed.stdout.strip():
        try:
            payload = json.loads(completed.stdout)
        except ValueError:
            payload = None
    return completed.returncode, payload, completed.stderr


def _submit_body(*, key: str, command_id: str, request: dict | None = None) -> dict:
    return {
        "schema_version": "ff-job/1",
        "command_id": command_id,
        "kind": "filing.acquire",
        "idempotency_key": key,
        "request": request or _FILING_REQUEST,
    }


class CrossProcessFacadeTests(unittest.TestCase):
    """G-m8-FF-02: one store, separate processes, one durable state chain."""

    def test_submit_status_cancel_status_across_processes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = str(Path(tmp) / "ff_jobs")

            code1, payload1, _ = _run_cli(
                "submit", jobs_dir=jobs_dir,
                body=_submit_body(key="idem-1", command_id="dash-cmd-1"),
            )
            self.assertEqual(code1, 0, "submit must succeed")
            owner_job_id = payload1["owner_job_id"]
            self.assertTrue(owner_job_id.startswith("ffjob-"))
            view1 = payload1["job"]
            self.assertEqual(view1["status"], "queued")
            self.assertEqual(view1["status_known"], True)
            self.assertEqual(view1["allowed_actions"], ["cancel"])
            self.assertEqual(view1["command_id"], "dash-cmd-1")
            self.assertEqual(view1["owner"], "filing-fetch")
            self.assertEqual(view1["cost_state"], "not_applicable")
            self.assertEqual(view1["recovery_capability"], "durable_owner_job")

            code3, payload3, _ = _run_cli(
                "get_status", "--owner-job-id", owner_job_id, jobs_dir=jobs_dir,
            )
            self.assertEqual(code3, 0)
            self.assertEqual(payload3["job"]["owner_job_id"], owner_job_id)
            self.assertEqual(payload3["job"]["status"], "queued")

            code4, payload4, _ = _run_cli(
                "allowed_actions", "--owner-job-id", owner_job_id, jobs_dir=jobs_dir,
            )
            self.assertEqual(code4, 0)
            self.assertEqual(payload4["actions"], ["cancel"])

            code5, payload5, _ = _run_cli(
                "act", "--owner-job-id", owner_job_id, "--action", "cancel",
                "--idempotency-key", "act-1", jobs_dir=jobs_dir,
            )
            self.assertEqual(code5, 0)
            self.assertEqual(payload5["job"]["status"], "cancelled")
            # A reuse_only job has no cost dimension at all.
            self.assertEqual(payload5["job"]["cost_state"], "not_applicable")
            self.assertIsNone(payload5["job"]["cost"])

            code6, payload6, _ = _run_cli(
                "get_status", "--owner-job-id", owner_job_id, jobs_dir=jobs_dir,
            )
            self.assertEqual(code6, 0)
            self.assertEqual(payload6["job"]["status"], "cancelled")
            self.assertEqual(payload6["job"]["allowed_actions"], ["retry"])
            self.assertEqual(payload6["job"]["status_known"], True)

            code7, payload7, _ = _run_cli("list_jobs", "--limit", "10", jobs_dir=jobs_dir)
            self.assertEqual(code7, 0)
            self.assertEqual(len(payload7["items"]), 1)
            self.assertEqual(payload7["items"][0]["owner_job_id"], owner_job_id)
            # The page envelope is the frozen Dashboard PageInfo shape.
            page = payload7["page"]
            self.assertEqual(set(page), {"next_cursor", "snapshot_id", "total",
                                         "total_status"})
            self.assertIsNone(page["next_cursor"])
            self.assertTrue(page["snapshot_id"].startswith("ffjobs-"))
            self.assertEqual(page["total"], 1)
            self.assertEqual(page["total_status"], "exact")

    def test_request_errors_use_exit_2_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = str(Path(tmp) / "ff_jobs")
            code, payload, _ = _run_cli(
                "get_status", "--owner-job-id", "ffjob-000000000000", jobs_dir=jobs_dir,
            )
            self.assertEqual(code, 2)
            self.assertEqual(payload["status"], "request_error")
            self.assertEqual(payload["error"]["code"], "request_error")

    def test_help_exits_zero_for_every_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for subcommand in ("submit", "run", "get_status", "allowed_actions", "act",
                               "list_jobs"):
                code, _, _ = _run_cli(subcommand, "--help", jobs_dir=str(tmp))
                self.assertEqual(code, 0, f"--help must exit 0 for {subcommand}")


class CrossProcessIdempotencyTests(unittest.TestCase):
    """G-m8-FF-03: the same key never acquires twice across processes."""

    def test_same_key_replays_the_same_job_across_processes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = str(Path(tmp) / "ff_jobs")
            code1, payload1, _ = _run_cli(
                "submit", jobs_dir=jobs_dir,
                body=_submit_body(key="idem-1", command_id="dash-cmd-1"),
            )
            self.assertEqual(code1, 0)
            owner_job_id = payload1["owner_job_id"]
            code2, payload2, _ = _run_cli(
                "submit", jobs_dir=jobs_dir,
                body=_submit_body(key="idem-1", command_id="dash-cmd-1"),
            )
            self.assertEqual(code2, 0)
            self.assertEqual(payload2["owner_job_id"], owner_job_id)
            self.assertTrue(payload2["idempotent_replay"])

    def test_same_key_different_request_conflicts_across_processes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = str(Path(tmp) / "ff_jobs")
            conflicting = dict(_FILING_REQUEST, fiscal_year=2024)
            code1, _, _ = _run_cli("submit", jobs_dir=jobs_dir,
                                   body=_submit_body(key="idem-x", command_id="c1"))
            self.assertEqual(code1, 0)
            code2, payload2, _ = _run_cli(
                "submit", jobs_dir=jobs_dir,
                body=_submit_body(key="idem-x", command_id="c2", request=conflicting),
            )
            self.assertEqual(code2, 2)
            self.assertEqual(payload2["status"], "request_error")

    def test_abrupt_submit_exit_releases_publication_lock(self) -> None:
        child = """
import os
import sys

sys.path.insert(0, sys.argv.pop(1))
import ff_job
import ff_job_store

write = ff_job_store._atomic_write_json
def stop_before_record(path, value):
    if path.parent.name == "jobs":
        os._exit(73)
    write(path, value)

ff_job_store._atomic_write_json = stop_before_record
raise SystemExit(ff_job.main())
"""
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = str(Path(tmp) / "ff_jobs")
            body = _submit_body(key="interrupted", command_id="cmd-retry")
            crashed = subprocess.run(
                [sys.executable, "-B", "-c", child, str(SKILL_ROOT / "scripts"),
                 "--jobs-dir", jobs_dir, "submit"],
                input=json.dumps(body), capture_output=True, text=True, timeout=10, check=False,
            )
            self.assertEqual(crashed.returncode, 73, crashed.stderr)
            self.assertEqual(len(list((Path(jobs_dir) / "index" / "idem").glob("*.json"))), 1)
            self.assertEqual(list((Path(jobs_dir) / "jobs").glob("*.json")), [])

            first_code, first, error = _run_cli("submit", jobs_dir=jobs_dir, body=body)
            self.assertEqual(first_code, 0, error)
            self.assertIsNotNone(first)
            second_code, second, error = _run_cli("submit", jobs_dir=jobs_dir, body=body)
            self.assertEqual(second_code, 0, error)
            self.assertIsNotNone(second)
            self.assertFalse(first["idempotent_replay"])
            self.assertTrue(second["idempotent_replay"])
            self.assertEqual(first["owner_job_id"], second["owner_job_id"])
            self.assertEqual(len(list((Path(jobs_dir) / "jobs").glob("*.json"))), 1)

    def test_live_run_cannot_lose_its_lock_to_a_second_process(self) -> None:
        child = """
import os
from pathlib import Path
import sys

sys.path.insert(0, sys.argv.pop(1))
mode = sys.argv.pop(1)
ready = Path(sys.argv.pop(1))
import ff_job
from ff_job_store import JobStore
from ff_job_contracts import FFJobError

if mode == "park":
    original = JobStore.append_log
    def append(self, owner_job_id, entry):
        if entry["event"] == "run_started":
            ready.touch()
            sys.stdin.read(1)
            os._exit(73)
        original(self, owner_job_id, entry)
    JobStore.append_log = append
else:
    acquire = JobStore.acquire_lock
    JobStore.acquire_lock = lambda self, job, timeout_seconds: acquire(
        self, job, min(timeout_seconds, 0.3),
    )
    import ff_job_runner
    def engine(*args, **kwargs):
        raise FFJobError("test engine was invoked", code="upstream_error")
    ff_job_runner._run_filing_engine = engine
raise SystemExit(ff_job.main())
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jobs_dir = str(root / "jobs")
            body = _submit_body(key="contested-run", command_id="cmd-contended")
            code, queued, error = _run_cli("submit", jobs_dir=jobs_dir, body=body)
            self.assertEqual(code, 0, error)
            self.assertIsNotNone(queued)
            job_id = queued["owner_job_id"]
            ready = root / "ready"
            command = [sys.executable, "-B", "-c", child, str(SKILL_ROOT / "scripts")]
            args = [str(ready), "--jobs-dir", jobs_dir, "run", "--owner-job-id", job_id]
            with subprocess.Popen([*command, "park", *args], stdin=subprocess.PIPE,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as first:
                try:
                    deadline = time.monotonic() + 5
                    while not ready.exists() and first.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(ready.is_file())
                    lock = Path(jobs_dir) / "locks" / f"{job_id}.lock"
                    stale = time.time() - 2 * 86400
                    os.utime(lock, (stale, stale))
                    second = subprocess.run(
                        [*command, "compete", *args], capture_output=True, text=True,
                        encoding="utf-8", timeout=10, check=False,
                    )
                    self.assertEqual(second.returncode, 2, second.stdout)
                    self.assertEqual(json.loads(second.stdout)["error"]["code"], "request_error")
                finally:
                    try:
                        first.communicate(input=b"x", timeout=10)
                    except subprocess.TimeoutExpired:
                        first.kill()
                        first.communicate(timeout=5)
                        raise
                self.assertEqual(first.returncode, 73)
            recovered = subprocess.run(
                [*command, "compete", *args], capture_output=True, text=True,
                encoding="utf-8", timeout=10, check=False,
            )
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            self.assertTrue(json.loads(recovered.stdout)["engine_executed"])

    def test_bad_idempotency_key_is_a_request_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = str(Path(tmp) / "ff_jobs")
            code, payload, _ = _run_cli(
                "submit", jobs_dir=jobs_dir,
                body=_submit_body(key="bad key", command_id="c"),
            )
            self.assertEqual(code, 2)
            self.assertEqual(payload["status"], "request_error")

    def test_fetch_intent_cancel_projects_known_zero_cost(self) -> None:
        """A queued fetch job cancelled before the engine starts spent nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            jobs_dir = str(Path(tmp) / "ff_jobs")
            fetch_request = dict(_FILING_REQUEST, filing_intent="fetch_if_missing",
                                 acquisition_limits={"max_bytes": 20000000,
                                                    "timeout_seconds": 120,
                                                    "max_cost_usd": "0.50"})
            code1, payload1, _ = _run_cli(
                "submit", jobs_dir=jobs_dir,
                body=_submit_body(key="idem-fetch", command_id="dash-cmd-2",
                                  request=fetch_request),
            )
            self.assertEqual(code1, 0)
            owner_job_id = payload1["owner_job_id"]
            self.assertEqual(payload1["job"]["cost_state"], "not_applicable")
            code2, payload2, _ = _run_cli(
                "act", "--owner-job-id", owner_job_id, "--action", "cancel",
                "--idempotency-key", "act-fetch", jobs_dir=jobs_dir,
            )
            self.assertEqual(code2, 0)
            self.assertEqual(payload2["job"]["status"], "cancelled")
            self.assertEqual(payload2["job"]["cost_state"], "known")
            self.assertEqual(payload2["job"]["cost"]["value"], "0.00")
            self.assertEqual(payload2["job"]["cost"]["currency"], "USD")


if __name__ == "__main__":
    unittest.main()
