"""Optional feedback from the owner of a durable FF attempt."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

OUTCOME = "job-outcome"


def publish_job_observation(record: dict, *, started: bool) -> None:
    file = os.environ.get("RESEARCH_FEEDBACK_OUT")
    if not file:
        return
    job_id, attempt = record["owner_job_id"], record["attempts"]
    base = {
        "schema_version": "feedback-observation/1",
        "owner": "filing-fetch",
        "run_id": os.environ.get("RESEARCH_FEEDBACK_RUN_ID") or job_id,
        "attempt_id": os.environ.get("RESEARCH_FEEDBACK_ATTEMPT_ID") or str(attempt),
        "step_id": f"{job_id}/{attempt}",
        "evidence_ref": f"ff-job/1/{job_id}",
        "version": "ff-job/1",
    }
    if started:
        rows = [dict(base, check_id="action-started", expected="started", actual="started",
                     disposition="expected", terminal_check_id=OUTCOME)]
    else:
        outcome = record["status"] if record["status_known"] else "unknown"
        cost = record["cost_state"]
        rows = [
            dict(base, check_id=OUTCOME, expected="terminal", actual=outcome,
                 disposition="unknown" if outcome == "unknown" else "expected"),
            dict(base, check_id="job-usage", expected="accounted", actual=cost,
                 disposition="unknown" if cost == "unknown" else "expected"),
        ]
    try:
        # One caller supplies one exclusive file. When the process dies after
        # starting, the original reference has already reached the sidecar.
        with Path(file).open("ab") as stream:
            stream.write(b"".join((json.dumps(row, ensure_ascii=True) + "\n").encode("ascii") for row in rows))
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        # Diagnostics remain optional; the native owner record is authoritative.
        pass


def _digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def _record_report(root: Path, request: dict) -> dict:
    key = request["action_id"]
    payload = request.get("payload")
    if (request.get("schema_version"), request.get("owner"), request.get("kind"), request.get("method")) != (
        "feedback-action/1", "filing-fetch", "report", "submit",
    ):
        raise ValueError("not a filing-fetch report")
    names = ("occurrence_id", "original_occurrence_id", "origin_owner", "issue_ref", "fixed_version", "evidence_ref")
    if (not isinstance(payload, dict) or payload.get("verdict") not in ("verified", "regressed")
            or any(not isinstance(payload.get(name), str) or not payload[name].strip() for name in names)):
        raise ValueError("not a bound consumer replay result")
    scope = [payload["occurrence_id"], "filing-fetch", payload["issue_ref"], payload["fixed_version"], payload["verdict"]]
    if key != _digest(["report", "filing-fetch", *scope]) or request.get("request_digest") != _digest(
        ["filing-fetch", "report", key, payload],
    ):
        raise ValueError("report identity mismatch")
    root.mkdir(parents=True, exist_ok=True)
    path = root / (key + ".json")
    data = (json.dumps(request, ensure_ascii=True, sort_keys=True) + "\n").encode("ascii")
    with tempfile.NamedTemporaryFile(dir=root, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        try:
            if os.name == "nt":
                os.rename(temporary, path)
            else:
                os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise ValueError("conflicting report for the same action") from None
    finally:
        temporary.unlink(missing_ok=True)
    return {"recorded": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="Filing-fetch owner feedback receipts")
    parser.add_argument("--reports-dir", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("report")
    sub.add_parser("get-report").add_argument("action_id")
    args = parser.parse_args()
    if args.command == "report":
        request = json.load(sys.stdin)
        key = request.get("action_id") if isinstance(request, dict) else None
    else:
        key = args.action_id
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
        parser.error("invalid feedback action id")
    try:
        value = ({"result": _record_report(args.reports_dir, request)} if args.command == "report"
                 else {"report": json.loads((args.reports_dir / (key + ".json")).read_bytes())})
    except (OSError, ValueError) as error:
        print(json.dumps({"error": type(error).__name__}))
        return 1
    print(json.dumps(value, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
