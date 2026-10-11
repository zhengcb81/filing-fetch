"""Runtime countermodels. Synthetic fixtures only; no producer or HTTP calls."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1] / "tools/offline_contract_matrix"
sys.path.insert(0, str(HERE))
import run as runner  # noqa: E402
import cli_main  # noqa: E402

def test_production_guard_does_not_read_even_synthetic_key(tmp_path):
    roots = [tmp_path / n for n in ("ff", "cwp", "et")]
    for root in roots:
        (root / "config").mkdir(parents=True)
    key = roots[0] / "config/FMP_API_KEY.txt"
    key.write_text("synthetic-not-a-secret", encoding="utf-8")
    with patch.object(runner, "sha256_file", side_effect=AssertionError("byte read forbidden")):
        guard = runner.ProductionGuard(*roots)
        assert guard.unchanged(guard.snapshot())
    assert "sha256" not in guard.before[str(key)]

def test_context_does_not_inherit_host_credentials_or_endpoints(tmp_path):
    ctx = object.__new__(runner.Context)
    ctx.cwp_root = tmp_path / "cwp"
    ctx.et_root = tmp_path / "et"
    ctx.scratch = tmp_path / "scratch"
    ctx.env = SimpleNamespace(proxy_state=tmp_path / "proxy")
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY":"synthetic-marker", "OPENAI_API_KEY":"synthetic-marker", "API_BASE_URL":"https://synthetic.invalid", "FMP_API_KEY_FILE":"synthetic-file"}, clear=True):
        child = ctx.child_env()
    assert not ({"DEEPSEEK_API_KEY", "OPENAI_API_KEY", "API_BASE_URL", "FMP_API_KEY_FILE"} & child.keys())
    assert child["FMP_API_KEY"] == runner.FAKE_FMP_KEY
    assert Path(child["HOME"]).is_relative_to(ctx.scratch)

def _unbound_cli(tmp_path):
    owned = tmp_path / "owned"
    out = tmp_path / "out"
    (owned / "scratch").mkdir(parents=True)
    out.mkdir()
    existing = owned / "scratch/existing.txt"
    existing.write_text("old baseline", encoding="utf-8")
    sentinel = owned / runner.SENTINEL_NAME
    sentinel.write_text("old sentinel", encoding="utf-8")
    report = out / "report.json"
    report.write_text("old report", encoding="utf-8")
    class Context:
        def __init__(self, **kwargs): self.__dict__.update(kwargs)
        def child_env(self): return {}
    with patch.object(cli_main, "Context", Context), patch.object(cli_main, "_verify_binding", return_value={"verified":False}), patch.object(cli_main, "seed_all"), patch.object(cli_main, "_case_registry", return_value=[]), patch.object(cli_main, "_dependency", return_value=SimpleNamespace(to_dict=lambda: {})), patch.object(cli_main, "_module_record", return_value={}):
        rc = cli_main.main(["--cwp-project", str(tmp_path / "cwp"), "--et-project", str(tmp_path / "et"), "--owned-root", str(owned), "--out-root", str(out)])
    return rc, existing, sentinel, report

def test_unbound_cli_never_reports_success(tmp_path):
    rc, *_ = _unbound_cli(tmp_path)
    assert rc != 0

def test_cli_preserves_existing_scratch_sentinel_and_report(tmp_path):
    _, existing, sentinel, report = _unbound_cli(tmp_path)
    assert existing.read_text(encoding="utf-8") == "old baseline"
    assert sentinel.read_text(encoding="utf-8") == "old sentinel"
    assert report.read_text(encoding="utf-8") == "old report"


def test_absolute_case_budget_is_shared_not_reset():
    import runtime
    with patch.object(runtime.time, "monotonic", side_effect=[0, 1, 1, 2, 2, 30.1]):
        batch = runtime.Deadline(30)
        first = batch.case(30)
        second = first.case(30)
        assert second.end == 30
        import pytest
        with pytest.raises(runtime.DeadlineExceeded):
            second.remaining()

def test_expired_deadline_prevents_launch(tmp_path):
    import runtime
    import pytest
    with patch.object(runtime.subprocess, "Popen") as launch:
        with pytest.raises(runtime.DeadlineExceeded):
            runtime.run_process([sys.executable], env={}, cwd=tmp_path, deadline=runtime.Deadline(end=-1))
        launch.assert_not_called()

def test_startup_denies_network_before_import_and_records_translation(tmp_path):
    import runtime
    env = runtime.synthetic_env(tmp_path, tmp_path / "cwp", tmp_path / "et")
    fake_module = tmp_path / "translator.py"
    fake_module.write_text("class TranslatorFactory:\n    @staticmethod\n    def create(*args): return 'unprotected'\n", encoding="utf-8")
    script = "import socket, translator;\ntry: socket.create_connection(('example.invalid', 443))\nexcept RuntimeError: pass\ntry: translator.TranslatorFactory.create({})\nexcept RuntimeError: pass"
    proc = runtime.run_process([sys.executable, "-B", "-c", script], env=env, cwd=tmp_path, deadline=runtime.Deadline(5))
    assert proc.returncode == 0, proc.stderr
    ops = [e["op"] for e in runtime.guard_events(tmp_path)]
    assert ops == ["guard_boot", "network_denied", "translation_attempt"]

def test_hard_deadline_reaps_child_without_long_wait(tmp_path):
    import runtime
    import pytest
    import time
    env = runtime.synthetic_env(tmp_path, tmp_path / "cwp", tmp_path / "et")
    start = time.monotonic()
    with pytest.raises(runtime.DeadlineExceeded):
        runtime.run_process([sys.executable, "-B", "-c", "import threading; threading.Event().wait()"], env=env, cwd=tmp_path, deadline=runtime.Deadline(0.2))
    assert time.monotonic() - start < 5

def test_bound_evidence_rejects_bool_only_fake_pass():
    import oracle
    report = {"schema_version":"ff-et-cwp-offline-matrix/1", "runner":{"version":"test"},
              "required_cases":["fake"], "cases":[{"id":"fake", "result":"PASS", "actual":{"elapsed_seconds":1, "real_layer_evidence":{"ff_public_cli":True}}}],
              "code_binding":{"verified":True}, "restore":{"restored":True},
              "scope":{"batch_elapsed_seconds":1, "network_guard_boots":1, "network_attempts_denied":0, "translation_attempts":0}}
    assert "missing_bound_evidence" in {f.vector for f in oracle.audit(report)}


def test_owned_absent_and_existing_empty_parent_shapes_restore(tmp_path):
    import runtime
    absent = tmp_path / "absent/nested"
    out = tmp_path / "retained"
    first = runtime.OwnedAttempt.create(absent, out)
    restore = first.cleanup()
    assert restore["restored"]
    assert not absent.exists() and not absent.parent.exists()
    assert first.output.is_dir()
    empty = tmp_path / "existing-empty"
    empty.mkdir()
    second = runtime.OwnedAttempt.create(empty, out)
    assert second.cleanup()["restored"]
    assert empty.is_dir() and not list(empty.iterdir())

def test_initialization_failure_restores_only_created_items(tmp_path):
    import runtime
    import pytest
    owned = tmp_path / "existing-empty"
    owned.mkdir()
    out = tmp_path / "new-output"
    original_mkdir = Path.mkdir
    def fail_output(path, *args, **kwargs):
        if path.parent == out and path.name.startswith("attempt-"):
            raise OSError("synthetic output initialization failure")
        return original_mkdir(path, *args, **kwargs)
    with patch.object(Path, "mkdir", fail_output):
        with pytest.raises(OSError):
            runtime.OwnedAttempt.create(owned, out)
    assert owned.is_dir() and not list(owned.iterdir())
    assert not out.exists()


def test_physical_original_count_separates_alias_rows_from_copies(tmp_path):
    from source_proofs import physical_originals
    one = tmp_path / "one.pdf"
    two = tmp_path / "two.pdf"
    one.write_bytes(b"synthetic-original")
    two.write_bytes(b"synthetic-original")
    assert physical_originals([{"absolute_path":str(one)}, {"absolute_path":str(one.parent / "." / one.name)}]) == 1
    assert physical_originals([{"absolute_path":str(one)}, {"absolute_path":str(two)}]) == 2


def test_catalog_snapshot_uses_document_status_not_source_status():
    import sqlite3
    from source_proofs import catalog_snapshot
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("CREATE TABLE sources(source_id TEXT,content_sha256 TEXT,byte_size INTEGER,mime_type TEXT); CREATE TABLE documents(document_id TEXT,document_kind TEXT,published_date TEXT,metadata_json TEXT,primary_source_id TEXT,source_status TEXT);")
    db.execute("INSERT INTO sources VALUES (?,?,?,?)", ("source", "a"*64, 3, "application/pdf"))
    db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)", ("document", "annual_report", "2025-01-01", '{"acquisition":{"fiscal_year":2024}}', "source", "active"))
    class Reader:
        def fetchall(self, sql): return db.execute(sql).fetchall()
    try:
        result = catalog_snapshot(Reader())
        assert result[0]["source_status"] == "active"
        assert result[0]["metadata"] == {"fiscal_year":2024}
    finally:
        db.close()


def test_fixture_originals_distinguish_issuer_market_and_period(tmp_path):
    import fixture_provider_adapter as adapter
    from unittest.mock import patch
    hashes = []
    with patch.object(adapter, "_state", return_value={"provider_scenario":"serve"}):
        for market, security in (("CN", "300750"), ("HK", "00700"), ("US", "AAPL")):
            payload = {"market":market, "security_id":security, "document_kind":"annual_report", "fiscal_year":2024, "fiscal_period":"FY"}
            discovered = adapter._discover(payload)["candidates"][0]
            returned = adapter._fetch(["--staging-dir", str(tmp_path / market)], discovered)
            hashes.append(returned["receipt"]["content_sha256"])
        annual = adapter._discover({"market":"CN", "security_id":"300750", "document_kind":"annual_report", "fiscal_year":2024})["candidates"][0]
        quarterly = adapter._discover({"market":"CN", "security_id":"300750", "document_kind":"quarterly_report", "fiscal_year":2024, "fiscal_period":"Q1"})["candidates"][0]
    assert len(set(hashes)) == 3, "fixture company originals collided in immutable SHA store"
    assert annual["provider_document_id"] != quarterly["provider_document_id"]
