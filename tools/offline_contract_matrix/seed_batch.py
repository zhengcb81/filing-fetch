"""Bounded seed-batch helper: ONE process, sequential real CWP ensure writes.

W07-FF-PERF converges the ten warm-seed CWP ``ensure`` acquisitions into a
single bounded helper process that calls the SAME real ``company_wiki.source_
catalog.cli`` service sequentially, in the same order, with the same argv each
CLI launch used. No SQLite is fabricated and no source record is substituted
for the real writer: every request keeps its response bytes, receipt refs,
source-ref and acquisition counts. The helper is always launched through the
existing absolute batch Deadline; it never resets or extends it.

Invoke contract: ``invoke(argv) -> (exit_code, stdout_text, stderr_text)``.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path

SCHEMA = "w07-seed-batch/1"
HELPER = "tools/offline_contract_matrix/seed_batch.py"


def _cli_service(argv: list[str]) -> tuple[int, str, str]:
    """Execute one request through the real CWP CLI service entry point."""
    out, err = io.StringIO(), io.StringIO()
    code = 1
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            from company_wiki.source_catalog import cli

            try:
                code = cli.main(list(argv))
            except SystemExit as exc:  # cli error paths exit instead of returning
                code = exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:  # keep the failure as a per-request record
        err.write(f"{type(exc).__name__}: {exc}\n")
        code = 1
    return code, out.getvalue(), err.getvalue()


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
    """Run every seed request sequentially in this process and record each one."""
    invoke = invoke or _cli_service
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
        code, out_text, err_text = invoke(list(request["argv"]))
        tag = request["tag"]
        response_path = artifacts / f"{tag}.response.json"
        response_path.write_bytes(out_text.encode("utf-8"))
        stderr_path = artifacts / f"{tag}.stderr.txt"
        stderr_path.write_bytes(err_text.encode("utf-8"))
        try:
            response = json.loads(out_text)
        except ValueError:
            response = None
        rows.append(
            {
                "tag": tag,
                "request_argv": list(request["argv"]),
                "exit_code": code,
                "response": response,
                "response_ref": response_path.name,
                "response_sha256": hashlib.sha256(response_path.read_bytes()).hexdigest(),
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
        "service": "company_wiki.source_catalog.cli.main (same real ensure writer)",
        "requests": rows,
    }


def main() -> int:
    payload = json.load(sys.stdin)
    sys.stdout.write(json.dumps(run_batch(payload), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
