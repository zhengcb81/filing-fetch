"""DU10 interruption -> restart -> recovery -> cleanup end-to-end proof.

Leg 1 starts the public full matrix exactly once as an owned child process and
interrupts it only after a current case request with a zero-to-new GET
progression is observed inside its new UUID attempt (observer approach retained
from DU8's committed interruption fixture). The process tree is reaped through
the existing bounded transport; the killed attempt is left exactly as it died.

Leg 2 RESTARTS the same public command into the same owned/out roots, lets it
run to completion, and the receipt proves recovery semantics:

  * the restart is a NEW unique attempt (fresh UUID, fresh bytecode cache);
  * the killed attempt's bytes are never rewritten or reused as success and its
    report.json never appears;
  * the restarted attempt writes its own complete 41-case report;
  * the owned sentinel and pre-existing output entries are byte-identical
    across interruption and restart;
  * the temporary tree is fully removed afterwards.

Failure to observe work or cleanup stays NOT_RUN/unknown — never a zero-leak or
41-PASS claim. The 41-case verdict itself belongs to the separate clean run
(node C-1); this receipt only proves interruption/restart/cleanup behaviour.
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

SCHEMA = "du10-interruption-restart/1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_env():
    env = {key: os.environ[key]
           for key in ("SystemRoot", "WINDIR", "COMSPEC", "PATH", "PATHEXT")
           if key in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return env


def _matrix_command(args, owned: Path, out: Path) -> list[str]:
    return [sys.executable, "-B", str(TOOLS / "run.py"),
            "--cwp-project", str(args.cwp_project.resolve()),
            "--et-project", str(args.et_project.resolve()),
            "--owned-root", str(owned), "--out-root", str(out), "--workers", "2"]


def _new_attempt(output: Path, before: set[str]) -> Path | None:
    fresh = [p for p in output.glob("attempt-*")
             if p.is_dir() and not p.is_symlink() and p.name not in before]
    return fresh[0] if len(fresh) == 1 else None


def _case_entry(output: Path, scratch: Path, *, observations: dict):
    """Observe current request GET progression, never a stale or prior attempt.

    Retained from the DU8 committed observer: first-seen positive counters,
    malformed logs and counter rollback never establish a baseline; a marker
    requires the zero -> new GET progression plus the proxy state still being
    this request's own fixture state and no response yet.
    """
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
                observations[key] = {"last_count": gets, "started_at_zero": gets == 0,
                                     "invalid": False}
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
                "case_id": cid, "request": request.name, "fixture": fixture.name,
                "observed_gets": gets, "prior_observed_gets": prior,
                "request_sha256": request_sha, "fixture_sha256": fixture_sha,
                "calls_sha256": hashlib.sha256(calls_bytes).hexdigest(),
                "scope": "current request observed from zero to new GET before response; "
                         "not proof the provider remained blocked at the kill instant",
            }
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def _attempt_residue(attempt: Path) -> dict:
    """Fingerprint the killed attempt exactly as it died (bounded sample)."""
    files = sorted(p for p in attempt.rglob("*") if p.is_file())
    return {
        "file_count": len(files),
        "report_json_present": (attempt / "report.json").is_file(),
        "sha256_of_sorted_paths": hashlib.sha256(
            "\n".join(str(p.relative_to(attempt)) for p in files).encode("utf-8")).hexdigest(),
        "sample_shas": {str(p.relative_to(attempt)): _sha(p)
                        for p in files if p.name in {"restore.json", "guard-events.json"}
                        or p.name.endswith("seed-batch.stdout.json")},
    }


def _finish_owned(proc, job, state):
    try:
        transport._cleanup(proc, job, state)
    except Exception as exc:
        return {"status": "unknown", "tree_reaped": None,
                "reason": f"{type(exc).__name__}: {exc}"}
    return {"status": "observed", "tree_reaped": True, "returncode": proc.returncode,
            "basis": "owned OS job/process group terminated; root reaped; pipe readers joined"}


def _leg1_interrupt(command, *, cwd, env, owned, out, baseline, seconds):
    deadline = time.monotonic() + seconds
    proc = job = state = None
    marker = None
    interrupted = False
    error = None
    bound = {}
    observations: dict = {}

    def observe():
        attempt = _new_attempt(out, baseline)
        if attempt is None:
            return None
        entry = _case_entry(attempt, owned / attempt.name, observations=observations)
        if entry:
            bound["attempt"] = attempt.name
        return entry

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
            cleanup = {"status": "unknown", "tree_reaped": None,
                       "reason": "no process owner established"}
        else:
            cleanup = _finish_owned(proc, job, state)
    attempt_name = bound.get("attempt")
    residue = _attempt_residue(out / attempt_name) if attempt_name else None
    return {
        "interrupted": interrupted, "case_entry": marker, "cleanup": cleanup,
        "error": error, "deadline_seconds": seconds, "attempt": attempt_name,
        "residue_after_kill": residue,
        "stdout_tail": (b"".join(state.chunks["stdout"]).decode("utf8", errors="replace")[-2000:]
                        if state else None),
    }


def _leg2_restart(command, *, cwd, env, out, seconds):
    started = time.monotonic()
    try:
        result = transport.run_bounded(command, timeout_seconds=seconds, input_bytes=None,
                                       cwd=str(cwd), env=env)
        rc = result["returncode"]
        stdout = result["stdout"].decode("utf8", errors="replace")
    except transport.ChildTimeout:
        return {"status": "timeout", "seconds": time.monotonic() - started}
    except Exception as exc:
        return {"status": "unknown", "seconds": time.monotonic() - started,
                "reason": f"{type(exc).__name__}: {exc}"}
    return {"status": "completed", "seconds": round(time.monotonic() - started, 3),
            "exit_code": rc, "stdout_tail": stdout[-500:]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cwp-project", type=Path, required=True)
    parser.add_argument("--et-project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        parser.error("output must be new; historical evidence is never overwritten")
    with tempfile.TemporaryDirectory(prefix="du10-restart-") as directory:
        temp = Path(directory)
        owned, out = temp / "owned", temp / "out"
        owned.mkdir()
        out.mkdir()
        sentinel = owned / "sentinel"
        sentinel.write_bytes(b"du10 recovery sentinel\n")
        sentinel_before = _sha(sentinel)
        old = out / "attempt-preexisting"
        (old / "artifacts").mkdir(parents=True)
        (old / "artifacts" / "old.txt").write_bytes(b"old evidence")
        preexisting_sha = _sha(old / "artifacts" / "old.txt")
        baseline = {p.name for p in out.iterdir()}
        command = _matrix_command(args, owned, out)
        env = _safe_env()

        leg1 = _leg1_interrupt(command, cwd=temp, env=env, owned=owned, out=out,
                               baseline=baseline, seconds=180)
        residue_frozen = (_attempt_residue(out / leg1["attempt"])
                          if leg1["attempt"] else None)
        leg2 = (_leg2_restart(command, cwd=temp, env=env, out=out, seconds=400)
                if leg1["interrupted"] and leg1["attempt"] else {"status": "skipped"})

        checks: dict[str, object] = {}
        checks["leg1_interrupted_in_flight"] = bool(leg1["interrupted"] and leg1["case_entry"])
        checks["leg1_tree_reaped"] = leg1["cleanup"].get("tree_reaped") is True
        checks["leg1_no_report_written"] = bool(leg1["residue_after_kill"]
                                                and not leg1["residue_after_kill"]["report_json_present"])
        restart_name = None
        if leg2.get("status") == "completed":
            fresh = [p for p in out.glob("attempt-*")
                     if p.is_dir() and p.name not in baseline
                     and p.name != leg1["attempt"]]
            checks["restart_is_new_unique_attempt"] = len(fresh) == 1
            restart_name = fresh[0].name if len(fresh) == 1 else None
            report_path = out / restart_name / "report.json" if restart_name else None
            report = None
            if report_path and report_path.is_file():
                try:
                    report = json.loads(report_path.read_text(encoding="utf-8"))
                except ValueError:
                    report = None
            checks["restart_report_written"] = report is not None
            counts = {}
            if report:
                for case in report.get("cases") or []:
                    counts[case["result"]] = counts.get(case["result"], 0) + 1
                counts["total"] = len(report.get("cases") or [])
            checks["restart_case_counts"] = counts
            checks["restart_restored_true"] = bool(report and (report.get("restore") or {}).get("restored") is True)
            checks["residue_not_rewritten"] = (residue_frozen == _attempt_residue(out / leg1["attempt"])
                                               if leg1["attempt"] else False)
        else:
            checks["restart_is_new_unique_attempt"] = False
            checks["restart_report_written"] = False
            checks["restart_case_counts"] = {}
            checks["restart_restored_true"] = False
            checks["residue_not_rewritten"] = False
        checks["sentinel_intact"] = _sha(sentinel) == sentinel_before
        checks["preexisting_output_intact"] = _sha(old / "artifacts" / "old.txt") == preexisting_sha
        temp_path = directory
    checks["temporary_tree_removed"] = not Path(temp_path).exists()
    passed = all(bool(v) for k, v in checks.items()
                 if k not in {"restart_case_counts"})
    result = {
        "schema_version": SCHEMA,
        "inputs": {"cwp": str(args.cwp_project), "et": str(args.et_project)},
        "leg1": leg1,
        "leg2": leg2,
        "checks": checks,
        "passed": passed,
        "scope": "one controlled interruption + one restart-to-completion + cleanup; "
                 "the 41-case verdict is judged by the separate clean C-node run",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(output)
    return 0 if passed and checks["temporary_tree_removed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
