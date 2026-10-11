"""Owned scratch, synthetic startup environment and absolute process deadlines."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


class DeadlineExceeded(TimeoutError):
    pass


class Deadline:
    def __init__(self, seconds: float = 180, *, end: float | None = None):
        self.end = time.monotonic() + seconds if end is None else end

    def remaining(self) -> float:
        remaining = self.end - time.monotonic()
        if remaining <= 0:
            raise DeadlineExceeded("absolute deadline exhausted")
        return remaining

    def case(self, seconds: float = 30) -> Deadline:
        self.remaining()
        return Deadline(end=min(self.end, time.monotonic() + seconds))


def _reparse(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def _checked_parent(path: Path, protected: tuple[Path, ...]) -> Path:
    absolute = path.absolute()
    for ancestor in (absolute, *absolute.parents):
        if ancestor.exists() and _reparse(ancestor):
            raise ValueError(f"owned parent contains a link/reparse point: {ancestor}")
    resolved = absolute.resolve()
    if resolved == Path(resolved.anchor):
        raise ValueError("owned parent cannot be a drive/filesystem root")
    for root in protected:
        root = root.resolve()
        if resolved.is_relative_to(root) or root.is_relative_to(resolved):
            raise ValueError(f"owned parent overlaps protected data/code: {root}")
    return resolved


def _children_metadata(path: Path) -> dict:
    if not path.exists():
        return {}
    # Metadata only. No old file contents or production credentials are read.
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns, p.is_dir())
            for p in path.iterdir()}


@dataclass
class OwnedAttempt:
    scratch: Path
    output: Path
    owned_parent: Path
    out_parent: Path
    before_owned: dict
    before_out: dict
    owned_existed: bool
    out_existed: bool
    created_owned_dirs: list[Path]

    @classmethod
    def create(cls, owned_parent: Path, out_parent: Path, protected: tuple[Path, ...] = ()):
        owned_parent = _checked_parent(owned_parent, protected)
        out_parent = _checked_parent(out_parent, protected)
        if owned_parent == out_parent:
            raise ValueError("scratch and retained output parents must differ")
        owned_existed, out_existed = owned_parent.exists(), out_parent.exists()
        before_owned, before_out = _children_metadata(owned_parent), _children_metadata(out_parent)
        created_owned_dirs = []
        created_out_dirs = []
        def mkdir_chain(parent, record):
            missing = []
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for item in reversed(missing):
                item.mkdir()
                record.append(item)
        token = "attempt-" + uuid.uuid4().hex
        scratch, output = owned_parent / token, out_parent / token
        created = []
        try:
            mkdir_chain(owned_parent, created_owned_dirs)
            mkdir_chain(out_parent, created_out_dirs)
            scratch.mkdir()
            created.append(scratch)
            output.mkdir()
            created.append(output)
            return cls(scratch, output, owned_parent, out_parent, before_owned, before_out, owned_existed, out_existed, created_owned_dirs)
        except Exception:
            for path in reversed(created):
                if path.parent in {owned_parent, out_parent} and not _reparse(path):
                    shutil.rmtree(path)
            for item in reversed(created_out_dirs + created_owned_dirs):
                if item.exists() and not any(item.iterdir()):
                    item.rmdir()
            raise

    def cleanup(self) -> dict:
        # Only the exact unique child created above is eligible for deletion.
        safe = (self.scratch.parent == self.owned_parent and
                self.scratch.name == self.output.name and
                self.scratch.name.startswith("attempt-") and
                not _reparse(self.scratch))
        if not safe:
            raise ValueError("owned scratch identity changed; refusing cleanup")
        shutil.rmtree(self.scratch)
        owned_after, out_after = _children_metadata(self.owned_parent), _children_metadata(self.out_parent)
        preserved = all(owned_after.get(k) == v for k, v in self.before_owned.items())
        preserved &= all(out_after.get(k) == v for k, v in self.before_out.items())
        for item in reversed(self.created_owned_dirs):
            if item.exists() and not any(item.iterdir()):
                item.rmdir()
        shape_preserved = self.owned_parent.exists() == self.owned_existed
        return {"owned_parent_shape_preserved":shape_preserved,
                "output_parent_initially_existed":self.out_existed,
                "retained_output_is_explicit_evidence":True,
                "scratch_torn_down": not self.scratch.exists(), "preexisting_parent_entries_preserved": preserved,
                "restored": preserved and shape_preserved and not self.scratch.exists(), "output": str(self.output)}


GUARD_SOURCE = r'''import builtins, json, os, socket, sys
_log = os.environ["W06_GUARD_LOG"]
def _event(op):
    with open(_log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"op":op,"pid":os.getpid()})+"\n")
def _deny(*a, **kw):
    _event("network_denied")
    raise RuntimeError("W06 offline test: network is forbidden")
socket.socket.connect = _deny
socket.socket.connect_ex = _deny
socket.create_connection = _deny
socket.getaddrinfo = _deny
_original_import = builtins.__import__
def _import(*a, **kw):
    result = _original_import(*a, **kw)
    mod = sys.modules.get("translator")
    factory = getattr(mod, "TranslatorFactory", None)
    if factory is not None and not getattr(factory, "_w06_guarded", False):
        def denied(*a, **kw):
            _event("translation_attempt")
            raise RuntimeError("W06 offline test: translation is forbidden")
        factory.create = staticmethod(denied)
        factory._w06_guarded = True
    return result
builtins.__import__ = _import
_event("guard_boot")
'''


def prepare_guard(scratch: Path) -> Path:
    guard = scratch / "startup_guard"
    guard.mkdir(parents=True, exist_ok=True)
    site = guard / "sitecustomize.py"
    if not site.exists():
        site.write_text(GUARD_SOURCE, encoding="utf-8")
    return guard


def synthetic_env(scratch: Path, cwp_root: Path, et_root: Path, *, with_fmp_key: bool = True) -> dict[str, str]:
    # Explicit launch allowlist, never copy the host environment wholesale.
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC", "PATH", "PATHEXT") if key in os.environ}
    home, temp = scratch / "home", scratch / "tmp"
    for path in (home, temp, home / "AppData/Roaming", home / "AppData/Local"):
        path.mkdir(parents=True, exist_ok=True)
    guard = prepare_guard(scratch)
    env.update({"HOME":str(home), "USERPROFILE":str(home), "APPDATA":str(home / "AppData/Roaming"),
                "LOCALAPPDATA":str(home / "AppData/Local"), "TEMP":str(temp), "TMP":str(temp),
                "PYTHONUTF8":"1", "PYTHONDONTWRITEBYTECODE":"1", "PYTHONIOENCODING":"utf-8",
                "PYTHONPATH":os.pathsep.join([str(guard), str(cwp_root / "src"), str(et_root)]),
                "W06_ET_ROOT":str(et_root), "W06_MATRIX_SCRATCH":str(scratch),
                "W06_MATRIX_STATE":str(scratch / "proxy/state.json"), "W06_GUARD_LOG":str(scratch / "guard.jsonl")})
    if with_fmp_key:
        env["FMP_API_KEY"] = "offline-w06-not-a-real-fmp-key"
    return env


def run_process(command: list[str], *, env: dict[str, str], cwd: Path,
                deadline: Deadline, input: bytes | None = None) -> subprocess.CompletedProcess:
    remaining = deadline.remaining()  # check before launching, not after completion
    kw = {} if os.name == "nt" else {"start_new_session":True}
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, cwd=cwd, **kw)
    try:
        stdout, stderr = proc.communicate(input, timeout=min(remaining, deadline.remaining()))
    except (subprocess.TimeoutExpired, DeadlineExceeded) as exc:
        # FF owns nested provider/ET workers; reap only this process tree.
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate(timeout=5)
        raise DeadlineExceeded(f"child absolute deadline expired: {Path(command[0]).name}") from exc
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def guard_events(scratch: Path) -> list[dict]:
    path = scratch / "guard.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
