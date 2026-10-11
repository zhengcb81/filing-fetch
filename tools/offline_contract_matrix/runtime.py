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
    cache: Path | None = None
    cache_created: bool = False

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
        # Short shared bytecode-cache root (sibling of the attempt dir). Python's
        # PYTHONPYCACHEPREFIX mirrors full source paths under the prefix; nested
        # under the attempt scratch those mirror paths exceed Windows MAX_PATH
        # and the producer tree silently recompiles on every child launch.
        cache = owned_parent / "pc"
        cache_created = True
        created = []
        try:
            mkdir_chain(owned_parent, created_owned_dirs)
            mkdir_chain(out_parent, created_out_dirs)
            scratch.mkdir()
            created.append(scratch)
            output.mkdir()
            created.append(output)
            # Cache is always newly owned. Never import/write into a previous
            # attempt's cache; independent batches must not delete each other's.
            for name in ["pc", *(f"p{i:02x}" for i in range(256))]:
                candidate = owned_parent / name
                try:
                    candidate.mkdir()
                except FileExistsError:
                    continue
                cache = candidate
                created.append(cache)
                break
            else:
                raise FileExistsError("no free compact cache child under owned root")
            return cls(scratch, output, owned_parent, out_parent, before_owned, before_out,
                       owned_existed, out_existed, created_owned_dirs, cache, cache_created)
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
        # Only the exclusive cache created by this attempt is removed.
        # Pre-existing caches are never used and remain untouched.
        cache_torn_down = True
        if self.cache_created and self.cache is not None and self.cache.exists() and not _reparse(self.cache):
            shutil.rmtree(self.cache)
        if self.cache_created:
            cache_torn_down = self.cache is not None and not self.cache.exists()
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
                "scratch_torn_down": not self.scratch.exists(),
                "bytecode_cache_torn_down": cache_torn_down,
                "preexisting_parent_entries_preserved": preserved,
                "restored": preserved and shape_preserved and not self.scratch.exists() and cache_torn_down,
                "output": str(self.output)}


GUARD_SOURCE = r'''import atexit, builtins, json, os, socket, sys, time
_log = os.environ["W06_GUARD_LOG"]
_launch_log = os.environ.get("W06_LAUNCH_LOG")
def _event(op):
    with open(_log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"op":op,"pid":os.getpid()})+"\n")
def _launch(event):
    if not _launch_log:
        return
    with open(_launch_log, "a", encoding="utf-8") as f:
        f.write(json.dumps({"event":event,"at":time.time(),"pid":os.getpid(),"argv":sys.argv[:4]})+"\n")
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
atexit.register(_launch, "exit")
_launch("boot")
'''


def prepare_guard(scratch: Path) -> Path:
    guard = scratch / "startup_guard"
    guard.mkdir(parents=True, exist_ok=True)
    site = guard / "sitecustomize.py"
    if not site.exists():
        site.write_text(GUARD_SOURCE, encoding="utf-8")
    return guard


def _short_path(path: Path) -> Path:
    """Best-effort 8.3 short form on Windows (pure display/mirror shortening)."""
    if os.name != "nt":
        return path
    try:
        import ctypes
        from ctypes import wintypes
        fn = ctypes.windll.kernel32.GetShortPathNameW
        fn.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        fn.restype = wintypes.DWORD
        buf = ctypes.create_unicode_buffer(1024)
        if fn(str(path), buf, 1024):
            return Path(buf.value)
    except Exception:
        pass
    return path


def synthetic_env(scratch: Path, cwp_root: Path, et_root: Path, *, with_fmp_key: bool = True,
                  pycache_root: Path | None = None) -> dict[str, str]:
    # Explicit launch allowlist, never copy the host environment wholesale.
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "COMSPEC", "PATH", "PATHEXT") if key in os.environ}
    home, temp = scratch / "home", scratch / "tmp"
    # Bytecode cache root must be SHORT: PYTHONPYCACHEPREFIX mirrors the source
    # path (as loaded) under the prefix, and mirrored paths near Windows MAX_PATH
    # (260) are silently not written (the atomic write temp name overflows), which
    # recompiles the whole producer tree on every child launch. Both the prefix
    # and the module search paths are therefore used in 8.3 short form.
    pycache = Path(pycache_root) if pycache_root is not None else scratch / "pycache"
    for path in (home, temp, home / "AppData/Roaming", home / "AppData/Local", pycache):
        path.mkdir(parents=True, exist_ok=True)
    code_roots = [_short_path(Path(cwp_root) / "src"), _short_path(Path(et_root))]
    pycache = _short_path(pycache)
    guard = prepare_guard(scratch)
    env.update({"HOME":str(home), "USERPROFILE":str(home), "APPDATA":str(home / "AppData/Roaming"),
                "LOCALAPPDATA":str(home / "AppData/Local"), "TEMP":str(temp), "TMP":str(temp),
                "PYTHONUTF8":"1", "PYTHONIOENCODING":"utf-8",
                # Bytecode cache lives in owned scratch only: producer code roots
                # stay pristine while repeated child imports stop recompiling the
                # full company_wiki/ET trees on every launch.
                "PYTHONPYCACHEPREFIX":str(pycache),
                "PYTHONPATH":os.pathsep.join([str(guard), *(str(p) for p in code_roots)]),
                "W06_ET_ROOT":str(code_roots[1]), "W06_MATRIX_SCRATCH":str(scratch),
                "W06_MATRIX_STATE":str(scratch / "proxy/state.json"), "W06_GUARD_LOG":str(scratch / "guard.jsonl"),
                "W06_LAUNCH_LOG":str(scratch / "launches.jsonl")})
    if with_fmp_key:
        env["FMP_API_KEY"] = "offline-w06-not-a-real-fmp-key"
    return env


def _terminate_tree(proc: subprocess.Popen, env: dict[str, str]) -> None:
    # FF owns nested provider/ET workers; reap only this process tree. The
    # reaping must survive failures in the killer itself so no child leaks.
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def run_process(command: list[str], *, env: dict[str, str], cwd: Path,
                deadline: Deadline, input: bytes | None = None) -> subprocess.CompletedProcess:
    remaining = deadline.remaining()  # check before launching, not after completion
    kw = {} if os.name == "nt" else {"start_new_session":True}
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, cwd=cwd, **kw)
    try:
        stdout, stderr = proc.communicate(input, timeout=min(remaining, deadline.remaining()))
    except (subprocess.TimeoutExpired, DeadlineExceeded) as exc:
        _terminate_tree(proc, env)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except Exception:
            stdout, stderr = b"", b""
        finally:
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        raise DeadlineExceeded(f"child absolute deadline expired: {Path(command[0]).name}") from exc
    except Exception:
        # Unexpected transport errors must not leave orphaned children either.
        _terminate_tree(proc, env)
        try:
            proc.communicate(timeout=5)
        except Exception:
            pass
        finally:
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        raise
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def guard_events(scratch: Path) -> list[dict]:
    path = scratch / "guard.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
