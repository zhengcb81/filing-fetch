"""ROOT independent boundaries for concurrent offline matrix ownership/evidence."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools/offline_contract_matrix"))
import runtime
import cli_main
from run import Context

def test_attempt_caches_do_not_share_between_independent_batches(tmp_path):
    first = runtime.OwnedAttempt.create(tmp_path/"owned",tmp_path/"out")
    second = runtime.OwnedAttempt.create(tmp_path/"owned",tmp_path/"out")
    try:
        assert first.cache != second.cache
    finally:
        second.cleanup()
        first.cleanup()

def test_existing_cache_is_never_used_for_new_attempt(tmp_path):
    original = tmp_path/"owned"/"pc"
    original.mkdir(parents=True)
    sentinel = original/"sentinel.pyc"
    sentinel.write_bytes(b"original")
    before = {p.relative_to(original).as_posix():p.read_bytes() for p in original.rglob("*") if p.is_file()}
    attempt = runtime.OwnedAttempt.create(tmp_path/"owned",tmp_path/"out")
    try:
        env = runtime.synthetic_env(attempt.scratch,tmp_path/"cwp",tmp_path/"et",pycache_root=attempt.cache)
        active = Path(env["PYTHONPYCACHEPREFIX"]).resolve()
        assert active != original.resolve()
        (active/"new.pyc").write_bytes(b"new")
    finally:
        restore = attempt.cleanup()
    assert before == {p.relative_to(original).as_posix():p.read_bytes() for p in original.rglob("*") if p.is_file()}
    assert restore["restored"]

@pytest.mark.parametrize("first,second",[(False,True),(True,False)])
def test_colliding_document_proofs_do_not_hide_failed_worker(first,second):
    combined = {"proofs":{},"catalog_snapshot":[]}
    cli_main._merge_source_proofs(combined,{"proofs":{"same-doc":{"verified":first,"content_sha256":"a","byte_size":3}},"catalog_snapshot":[]},"g1")
    cli_main._merge_source_proofs(combined,{"proofs":{"same-doc":{"verified":second,"content_sha256":"a","byte_size":3}},"catalog_snapshot":[]},"g2")
    assert combined["proofs"]["same-doc"]["verified"] is False
    assert len(combined["worker_groups"]) == 2

def test_verified_collisions_keep_all_worker_evidence():
    combined = {"proofs":{},"catalog_snapshot":[]}
    proof = {"verified":True,"content_sha256":"a","byte_size":3,"source_versions":1,"physical_originals":1}
    for group in ("g1","g2"):
        cli_main._merge_source_proofs(combined,{"proofs":{"same-doc":proof},"catalog_snapshot":[]},group)
    assert combined["proofs"]["same-doc"]["verified"] is True
    assert set(combined["worker_groups"]) == {"g1","g2"}

def test_incompatible_verified_collision_is_not_green():
    combined = {"proofs":{},"catalog_snapshot":[]}
    for group, digest in [("g1","a"),("g2","b")]:
        cli_main._merge_source_proofs(combined,{"proofs":{"doc":{"verified":True,"content_sha256":digest,"byte_size":3}},"catalog_snapshot":[]},group)
    assert combined["proofs"]["doc"]["verified"] is False

def test_measurement_failure_still_restores_attempt(tmp_path,monkeypatch):
    monkeypatch.setattr(cli_main,"_verify_binding",lambda *a,**kw:{"verified":False})
    def broken(*a):
        raise RuntimeError("metrics unavailable")
    monkeypatch.setattr(cli_main,"cache_stats",broken)
    with pytest.raises(Exception):
        cli_main.main(["--cwp-project",str(tmp_path/"cwp"),"--et-project",str(tmp_path/"et"),"--owned-root",str(tmp_path/"owned"),"--out-root",str(tmp_path/"out")])
    assert not (tmp_path/"owned").exists()

def test_dead_child_is_reaped_after_second_communicate_error(tmp_path,monkeypatch):
    # Cleanup must also work if I/O setup fails after real reader threads start.
    import os
    import threading
    transport = runtime.process_transport
    original_start = transport._IOState.start
    captured = []

    def broken_start(state, proc, *args):
        captured.append(proc)
        original_start(state, proc, *args)
        raise RuntimeError("pipe broken")

    monkeypatch.setattr(transport._IOState, "start", broken_start)
    with pytest.raises(RuntimeError, match="pipe broken"):
        runtime.run_process(
            [sys.executable, "-B", "-S", "-c", "import threading;threading.Event().wait()"],
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), cwd=tmp_path,
            deadline=runtime.Deadline(5),
        )
    assert len(captured) == 1
    assert captured[0].poll() is not None
    assert captured[0].stdout is not None and captured[0].stderr is not None
    assert all(
        pipe.closed
        for pipe in (captured[0].stdin, captured[0].stdout, captured[0].stderr)
        if pipe is not None
    )
    assert not [t for t in threading.enumerate() if t.name.startswith("ff-process")]


@pytest.mark.parametrize("kind",["missing","extra","reordered"])
def test_seed_response_cardinality_and_order_are_validated(tmp_path,monkeypatch,kind):
    
    ctx=Context(ff_root=tmp_path/"ff",cwp_root=tmp_path/"cwp",et_root=tmp_path/"et",scratch=tmp_path/"scratch",out_root=tmp_path/"out")
    seeds=[(SimpleNamespace(market="US",canonical_name="Apple Inc.",security_id="US:AAPL"),"annual_report",2025,"FY")]
    def fake(command,**kw):
        payload=json.loads(kw["input"])
        row={"tag":payload["requests"][0]["tag"],"request_argv":payload["requests"][0]["argv"],"exit_code":0,"response":{},"response_ref":"x","response_sha256":"a","source_ref":{},"counts":{}}
        rows=[] if kind=="missing" else [row,row] if kind=="extra" else [dict(row,tag="other")]
        return SimpleNamespace(returncode=0,stdout=json.dumps({"schema_version":"w07-seed-batch/1","requests":rows}).encode(),stderr=b"")
    monkeypatch.setattr(sys.modules["run"],"run_process",fake)
    with pytest.raises(ValueError):
        ctx.warm_seed_batch(seeds)

def test_independent_catalog_alias_counts_are_not_byte_identity():
    target={"proofs":{},"catalog_snapshot":[]}
    for group, aliases in [("g1",1),("g2",2)]:
        proof={"verified":True,"content_sha256":"a","byte_size":3,"source_versions":1,"physical_originals":1,"original_locations":aliases}
        cli_main._merge_source_proofs(target,{"proofs":{"doc":proof},"catalog_snapshot":[]},group)
    assert target["proofs"]["doc"]["verified"] is True
    assert target["worker_groups"]["g1"]["proofs"]["doc"]["original_locations"] == 1
    assert target["worker_groups"]["g2"]["proofs"]["doc"]["original_locations"] == 2


@pytest.mark.parametrize("boundary", ["lifetime", "partial_io_start"])
def test_unexpected_cleanup_accepts_absent_stdin_on_any_platform(tmp_path, monkeypatch, boundary):
    """Exercise both actual error tests with POSIX's optional-stdin shape.

    Real public transport still starts and reaps its child. Only after its
    cleanup completes do we hide an already-closed Windows bootstrap stdin,
    matching POSIX input=None without changing global os.name or production.
    """
    transport = runtime.process_transport
    original_spawn = transport._spawn
    original_bounded = transport.run_bounded
    children = []

    def record_spawn(*args, **kwargs):
        proc, job = original_spawn(*args, **kwargs)
        children.append(proc)
        return proc, job

    def public_transport_with_optional_stdin(*args, **kwargs):
        assert kwargs.get("input_bytes") is None
        try:
            return original_bounded(*args, **kwargs)
        finally:
            assert len(children) == 1
            proc = children[0]
            assert proc.poll() is not None
            assert proc.stdout is not None and proc.stderr is not None
            assert proc.stdout.closed and proc.stderr.closed
            if proc.stdin is not None:
                assert proc.stdin.closed
                proc.stdin = None

    monkeypatch.setattr(transport, "_spawn", record_spawn)
    monkeypatch.setattr(transport, "run_bounded", public_transport_with_optional_stdin)
    if boundary == "lifetime":
        from test_w07_matrix_efficiency import (
            test_run_process_reaps_child_when_communicate_raises_other_error as exercise_error,
        )

        exercise_error(tmp_path)
    else:
        test_dead_child_is_reaped_after_second_communicate_error(tmp_path, monkeypatch)
    assert children[0].stdin is None
