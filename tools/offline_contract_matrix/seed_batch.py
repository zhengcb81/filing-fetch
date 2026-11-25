"""Sequential warm seeds through the published CWP ``ensure`` command.

Every request keeps its response bytes, receipt refs, source ref and acquisition
counts. The helper and each CWP process share the caller's absolute deadline.

Invoke contract: ``invoke(argv) -> (exit_code, stdout_bytes, stderr_bytes)``.
"""
from __future__ import annotations

from functools import partial
import hashlib
import json
import os
import sys
from pathlib import Path

from runtime import Deadline, run_process

SCHEMA = "w07-seed-batch/1"
HELPER = "tools/offline_contract_matrix/seed_batch.py"


def _ensure(argv: list[str], *, deadline: Deadline) -> tuple[int, bytes, bytes]:
    command = [sys.executable, "-m", "company_wiki.source_catalog.cli", *argv]
    result = run_process(command, env=dict(os.environ), cwd=Path.cwd(), deadline=deadline)
    return result.returncode, result.stdout, result.stderr


def _calls_gets(path) -> int:
    if path is None or not Path(path).is_file():
        return 0
    count = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            if json.loads(line).get("op") == "get":
                count += 1
        except ValueError:
            continue
    return count


def _file_lines(path) -> int:
    if path is None or not Path(path).is_file():
        return 0
    return sum(1 for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip())


def _source_ref(response):
    if not isinstance(response, dict):
        return None
    ref = response.get("source_ref")
    if isinstance(ref, dict):
        return ref
    candidate = response.get("candidate") or {}
    ref = candidate.get("source_ref") if isinstance(candidate, dict) else None
    return ref if isinstance(ref, dict) else None


def run_batch(payload: dict, *, invoke=None) -> dict:
    """Run the ordered seed requests and record the owner's wire bytes."""
    if invoke is None:
        invoke = partial(_ensure, deadline=Deadline(end=payload["deadline_end"]))
    artifacts = Path(payload["artifacts"])
    artifacts.mkdir(parents=True, exist_ok=True)
    adapter_log = payload.get("adapter_log")
    rows = []
    for request in payload["requests"]:
        # Per-request provider state, identical to the per-CLI-ensure state the
        # fixture adapter reads at acquisition time.
        Path(request["state_file"]).write_text(
            json.dumps(request["state"], ensure_ascii=False), encoding="utf-8"
        )
        calls_path = (request.get("state") or {}).get("calls_file")
        gets_before = _calls_gets(calls_path)
        adapters_before = _file_lines(adapter_log)
        code, stdout, stderr = invoke(list(request["argv"]))
        tag = request["tag"]
        response_path = artifacts / f"{tag}.response.json"
        response_path.write_bytes(stdout)
        stderr_path = artifacts / f"{tag}.stderr.txt"
        stderr_path.write_bytes(stderr)
        try:
            response = json.loads(stdout)
        except ValueError:
            response = None
        rows.append(
            {
                "tag": tag,
                "request_argv": list(request["argv"]),
                "exit_code": code,
                "response": response,
                "response_ref": response_path.name,
                "response_sha256": hashlib.sha256(stdout).hexdigest(),
                "stderr_ref": stderr_path.name,
                "source_ref": _source_ref(response),
                "counts": {
                    "adapter_invocations": _file_lines(adapter_log) - adapters_before,
                    "fixture_requests": _calls_gets(calls_path) - gets_before,
                },
            }
        )
    return {
        "schema_version": SCHEMA,
        "helper": HELPER,
        "helper_processes": 1,
        "service": "python -m company_wiki.source_catalog.cli ensure",
        "requests": rows,
    }


def main() -> int:
    payload = json.load(sys.stdin)
    sys.stdout.write(json.dumps(run_batch(payload), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
