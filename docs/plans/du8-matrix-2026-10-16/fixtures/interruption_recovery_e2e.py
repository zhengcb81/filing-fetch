"""Owned, observed interruption proof; complete 41-case acceptance is separate.

The public matrix is started exactly once and interrupted only after a current
case request, matching current fixture and zero-to-new GET progression are observed in its new UUID
attempt. No second clean matrix is silently run here. Use the separate retained
full report for that verdict. Failure to observe work/cleanup stays NOT_RUN or
unknown, never a zero-process or 41-PASS claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[4]
TOOLS = ROOT / "tools/offline_contract_matrix"
sys.path[:0] = [str(TOOLS), str(ROOT / "scripts")]
import ff_process_transport as transport  # noqa: E402
from case_specs import case_specs  # noqa: E402


def _safe_env():
    env = {
        key: os.environ[key]
        for key in ("SystemRoot", "WINDIR", "COMSPEC", "PATH", "PATHEXT")
        if key in os.environ
    }
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return env


def _new_attempt(output, before):
    fresh = [
        p
        for p in output.glob("attempt-*")
        if p.is_dir() and not p.is_symlink() and p.name not in before
    ]
    return fresh[0] if len(fresh) == 1 else None


def _case_entry(output, scratch, *, observations=None):
    """Observe current request GET progression, not an exact blocked instant.

    First-seen positive counters, malformed logs and counter rollback never
    establish a zero baseline. Requiring zero -> new GET plus current proxy
    state avoids certifying a previous run or a stale timed-out request.
    """
    if observations is None:
        return None
    artifacts = output / "artifacts"
    ids = {s.id for s in case_specs()}
    for request in sorted(artifacts.glob("*.request.json")):
        cid = request.name.split(".", 1)[0]
        if cid not in ids:
            continue
        stem = request.name.removesuffix(".request.json")
        response = artifacts / f"{stem}.response.json"
        if response.exists():
            continue
        fixture = artifacts / f"{stem}.fixture.json"
        try:
            fixture_bytes = fixture.read_bytes()
            request_bytes = request.read_bytes()
            fixture_sha = hashlib.sha256(fixture_bytes).hexdigest()
            request_sha = hashlib.sha256(request_bytes).hexdigest()
            key = (request.name, request_sha, fixture_sha)
            state = json.loads(fixture_bytes)["state"]
            calls = Path(state["calls_file"])
            if not calls.resolve().is_relative_to(scratch.resolve()):
                continue
            if calls.parent.name != "calls":
                continue
            active = json.loads((calls.parent.parent / "state.json").read_bytes())
            if active != state:
                if key in observations:
                    observations[key]["invalid"] = True
                continue
            try:
                calls_bytes = calls.read_bytes()
            except FileNotFoundError:
                calls_bytes = b""
            rows = [json.loads(line) for line in calls_bytes.splitlines() if line.strip()]
            if any(not isinstance(row, dict) for row in rows):
                continue
            gets = sum(row.get("op") == "get" for row in rows)
            previous = observations.get(key)
            if previous is None:
                observations[key] = {
                    "last_count": gets,
                    "started_at_zero": gets == 0,
                    "invalid": False,
                }
                continue
            prior = previous["last_count"]
            previous["last_count"] = gets
            if gets < prior:
                previous["invalid"] = True
            if previous["invalid"] or not previous["started_at_zero"] or gets <= prior:
                continue
            if response.exists():
                continue
            return {
                "case_id": cid,
                "request": request.name,
                "fixture": fixture.name,
                "observed_gets": gets,
                "prior_observed_gets": prior,
                "request_sha256": request_sha,
                "fixture_sha256": fixture_sha,
                "calls_sha256": hashlib.sha256(calls_bytes).hexdigest(),
                "scope": "current request observed from zero to new GET before response; not proof provider remained blocked at kill instant",
            }
        except (OSError, ValueError, KeyError, TypeError):
            # Partial concurrent JSON is unobserved, never a zero measurement.
            continue
    return None


def _finish_owned(proc, job, state):
    try:
        # Reuse the transport's already-established OS tree owner, bounded reap
        # and pipe/thread cleanup. No WMIC, whole-machine scan or PID guessing.
        transport._cleanup(proc, job, state)
    except Exception as exc:
        return {"status": "unknown", "tree_reaped": None, "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "status": "observed",
        "tree_reaped": True,
        "returncode": proc.returncode,
        "basis": "owned OS job/process group terminated; root reaped; pipe readers joined",
    }


def _interrupt_owned(command, *, cwd, env, observe, seconds):
    deadline = time.monotonic() + seconds
    proc = job = state = None
    marker = None
    interrupted = False
    error = None
    try:
        proc, job = transport._spawn(command, None, str(cwd), env)
        state = transport._IOState()
        state.start(proc, None, 32 * 1024 * 1024, 64 * 1024)
        while time.monotonic() < deadline and proc.poll() is None:
            _, io_error = state.snapshot() if hasattr(state, "snapshot") else (False, None)
            if io_error:
                raise io_error
            marker = observe()
            if marker:
                interrupted = True
                break
            time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if proc is None:
            cleanup = {
                "status": "unknown",
                "tree_reaped": None,
                "reason": "no process owner established",
            }
        else:
            cleanup = _finish_owned(proc, job, state)
    return {
        "interrupted": interrupted,
        "case_entry": marker,
        "cleanup": cleanup,
        "error": error,
        "deadline_seconds": seconds,
        "stdout": b"".join(state.chunks["stdout"]).decode("utf8", errors="replace")
        if state
        else None,
        "stderr": b"".join(state.chunks["stderr"]).decode("utf8", errors="replace")
        if state
        else None,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwp-project", type=Path, required=True)
    parser.add_argument("--et-project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        parser.error("output must be new; historical evidence is never overwritten")
    with tempfile.TemporaryDirectory(prefix="du8-interrupt-") as directory:
        temp = Path(directory)
        owned, out = temp / "owned", temp / "out"
        owned.mkdir()
        out.mkdir()
        sentinel = owned / "sentinel"
        sentinel.write_bytes(b"preexisting fixture sentinel\n")
        before = sentinel.read_bytes()
        old = out / "attempt-preexisting"
        (old / "artifacts").mkdir(parents=True)
        (old / "artifacts" / "old.txt").write_bytes(b"old evidence")
        baseline = {p.name for p in out.iterdir()}
        bound = {}
        observations = {}

        def observe():
            attempt = _new_attempt(out, baseline)
            if attempt is None:
                return None
            marker = _case_entry(attempt, owned / attempt.name, observations=observations)
            if marker:
                bound["attempt"] = attempt.name
            return marker

        command = [
            sys.executable,
            "-B",
            str(TOOLS / "run.py"),
            "--cwp-project",
            str(args.cwp_project.resolve()),
            "--et-project",
            str(args.et_project.resolve()),
            "--owned-root",
            str(owned),
            "--out-root",
            str(out),
            "--workers",
            "2",
        ]
        result = _interrupt_owned(command, cwd=temp, env=_safe_env(), observe=observe, seconds=180)
        result.update(
            attempt=bound.get("attempt"),
            sentinel_intact=sentinel.read_bytes() == before,
            preexisting_output_intact=(old / "artifacts" / "old.txt").read_bytes()
            == b"old evidence",
            scope="one controlled interruption; full 41-case clean run is separate",
            schema="du8-interruption-recovery/2",
        )
        result["passed"] = bool(
            result["interrupted"]
            and result["case_entry"]
            and result["cleanup"]["tree_reaped"] is True
            and not result["error"]
            and result["sentinel_intact"]
            and result["preexisting_output_intact"]
        )
        temp_path = directory
    result["temporary_tree_removed"] = not Path(temp_path).exists()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(output)
    return 0 if result["passed"] and result["temporary_tree_removed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
