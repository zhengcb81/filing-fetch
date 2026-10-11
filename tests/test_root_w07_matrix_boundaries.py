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
    class Child:
        pid=123
        returncode=None
        waited=False
        def communicate(self,*a,**kw):
            raise RuntimeError("pipe broken")
        def kill(self):
            self.returncode=-9
        def wait(self,timeout=None):
            self.waited=True
            return self.returncode
    child=Child()
    monkeypatch.setattr(runtime.subprocess,"Popen",lambda *a,**kw:child)
    monkeypatch.setattr(runtime,"_terminate_tree",lambda proc,env:proc.kill())
    with pytest.raises(RuntimeError):
        runtime.run_process(["python"],env={},cwd=tmp_path,deadline=runtime.Deadline(1))
    assert child.waited

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
