from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

MATRIX = Path(__file__).resolve().parents[1] / "tools" / "offline_contract_matrix"
if str(MATRIX) not in sys.path:
    sys.path.insert(0, str(MATRIX))

import cwp_readback_probe as proof  # noqa: E402


def _internal_imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            continue
        yield from (module for module in modules if module.split(".")[0] in {"company_wiki", "sqlite3", "tests"})


def test_matrix_readback_and_worker_do_not_import_owner_internals():
    violations = []
    for path in sorted(MATRIX.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        violations.extend(f"{path.name}: {name}" for name in _internal_imports(tree))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or "import " not in node.value:
                continue
            try:
                embedded = ast.parse(node.value)
            except SyntaxError:
                continue
            violations.extend(f"{path.name}:{node.lineno} inline: {name}" for name in _internal_imports(embedded))
        if "tests.test_" in source:  # ET worker launcher can also be an import string.
            violations.append(f"{path.name}: test-module reference")
    assert not violations, violations


def test_matrix_binding_probes_paths_without_executing_producer_modules(tmp_path):
    from cli_main import _verify_binding

    source = tmp_path / "src"
    et = tmp_path / "et"
    cwp_package = source / "company_wiki"
    cwp_package.mkdir(parents=True)
    et.mkdir()
    for path in (cwp_package / "__init__.py", et / "transcript_tool.py"):
        path.write_text("raise RuntimeError('binding imported producer implementation')\n", encoding="utf-8")
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join(map(str, [source, et])))

    value = _verify_binding(source, et, environment, cwd=tmp_path)

    assert value["verified"] is True
    assert Path(value["company_wiki"]["file"]).resolve() == (cwp_package / "__init__.py").resolve()


@pytest.mark.parametrize(
    ("lookup_change", "open_change", "expected"),
    [
        ({}, {}, "confirmed"),
        ({"status": "not_found", "matches": []}, {}, "not_found"),
        ({"status": "unavailable", "matches": []}, {}, "probe_error"),
        ({"status": "found", "matches": []}, {}, "probe_error"),
        ({"schema_version": "unrecognized"}, {}, "probe_error"),
        ({}, {"document_id": "other"}, "probe_error"),
        ({}, {"status": "unavailable"}, "probe_error"),
        ({}, {"stdout": b"another original"}, "probe_error"),
    ],
)
def test_w20_probe_uses_one_deadline_for_public_query_and_public_read(
    monkeypatch, tmp_path, lookup_change, open_change, expected,
):
    data = b"unicode manuscript \xe4\xb8\xad"
    digest = hashlib.sha256(data).hexdigest()
    ref = {
        "document_id": "document", "source_id": "source", "content_sha256": digest,
        "byte_size": len(data), "mime_type": "text/plain",
    }
    lookup = {"schema_version": "2.0", "status": "found", "matches": [{**ref, "schema_version": "2.0"}], **lookup_change}
    opened = {"schema_version": "2.1", "status": "ok", **ref, **open_change}
    content = opened.pop("stdout", data)
    calls = []

    def process(command, *, env, cwd, deadline, input=None):
        calls.append((command, deadline, input))
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 0, json.dumps(lookup).encode(), b"")
        return subprocess.CompletedProcess(command, 0, content, json.dumps(opened).encode())

    monkeypatch.setattr(proof, "run_process", process)
    result = proof.probe_catalog(
        wiki_root=tmp_path, identity_request={"provider": "fmp"},
        content_sha=digest, cwp_src=str(tmp_path),
    )

    assert result["state"] == expected
    assert "company_wiki.source_catalog.source_query_cli" in calls[0][0]
    assert json.loads(calls[0][2]) == {
        "schema_version": "company-wiki-transcript-import-lookup-request/1",
        "source_request": {"provider": "fmp"},
    }
    if expected == "confirmed":
        assert result["ref"] == ref
    if len(calls) == 2:
        assert "company_wiki.source_catalog.source_reader_cli" in calls[1][0]
        assert "--exact-pair" in calls[1][0]
        assert calls[0][1] is calls[1][1]



def test_fresh_proof_uses_public_export_and_original_language_open(monkeypatch, tmp_path):
    import source_proofs

    text = "Analyst Q&A.\n原语言内容。"
    original = json.dumps([{"content": text}], ensure_ascii=False).encode()
    ref = {
        "document_id": "exact-document", "source_id": "exact-source",
        "content_sha256": hashlib.sha256(original).hexdigest(),
        "byte_size": len(original), "mime_type": "application/json",
    }
    unrelated = {**ref, "document_id": "different-document", "source_id": "other-source"}
    manifest = {**ref, "document_kind": "investor_call_transcript", "provider": "fmp"}
    exports = []
    opens = []

    def export(wiki_root, refs, *, env, deadline):
        exports.append(list(refs))
        return [manifest.copy()]

    def read(wiki_root, ref, *, env, deadline):
        opens.append(ref)
        return original

    monkeypatch.setattr(source_proofs, "export_sources", export)
    monkeypatch.setattr(source_proofs, "read_source", read)
    result = source_proofs.prove_sources(
        tmp_path, [ref, ref, unrelated], env={}, deadline=proof.Deadline(),
    )

    assert exports == [[ref, unrelated]]
    assert opens == [ref]
    assert result["schema_version"] == "w06-fresh-source-proofs/2"
    verified = result["proofs"]["exact-document"]
    assert verified["verified"] is True
    assert verified["reference"] == ref
    assert verified["manifest"] == manifest
    assert verified["original_language_content_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert "physical_originals" not in verified
    assert result["proofs"]["different-document"]["verified"] is False


@pytest.mark.parametrize(("market", "security_id"), [("CN", "300750"), ("HK", "00700"), ("US", "AAPL")])
def test_discovery_fixture_supplies_the_requested_source_identity(market, security_id):
    from fixture_provider_adapter import _discover

    outcome = _discover({
        "market": market, "security_id": security_id,
        "entity": "Synthetic Issuer", "document_kind": "annual_report",
    })
    candidate, = outcome["candidates"]
    assert candidate["market"] == market
    assert candidate["security_id"] == security_id


def test_public_failure_type_is_shared_without_importing_filing_or_candidate_contracts():
    root = MATRIX.parents[1]
    program = """
import sys
sys.path.insert(0, sys.argv[1])
import ff_errors
assert "filing_contracts" not in sys.modules
assert "ff_source_candidate" not in sys.modules
from filing_contracts import FilingFetchError
from fetch_filing import FilingFetchError as cli_error
assert FilingFetchError is cli_error is ff_errors.FilingFetchError
error = FilingFetchError("owner is busy", code="catalog_busy", stage="resolve", attempts=2)
assert (error.code, error.retryable, error.stage, error.attempts) == ("catalog_busy", True, "resolve", 2)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", program, str(root / "scripts")],
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_mid_import_signal_binds_provider_original_and_rejects_a_bad_digest(tmp_path):
    import base64
    from w20_fault_cases import import_receipt_digest

    canonical = b"spoken words"
    provider_original = json.dumps([{"content": canonical.decode()}]).encode()
    provider_sha = hashlib.sha256(provider_original).hexdigest()
    receipt = tmp_path / "owned-result.json"
    value = {
        "status": "fetched",
        "provider_payload_base64": base64.b64encode(provider_original).decode(),
        "provider_payload_sha256": provider_sha,
        "canonical_content_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    assert import_receipt_digest(receipt) is None
    receipt.write_text(json.dumps(value), encoding="utf-8")
    assert import_receipt_digest(receipt) == provider_sha
    value["provider_payload_sha256"] = value["canonical_content_sha256"]
    receipt.write_text(json.dumps(value), encoding="utf-8")
    assert import_receipt_digest(receipt) is None


def _w20_context(tmp_path, deadline):
    from types import SimpleNamespace
    from measurement import PhaseTimer

    spec = SimpleNamespace(id="fixture", request_errors=lambda *a: [],
                           fixture_errors=lambda *a: [],
                           runs=[SimpleNamespace(request=lambda: {"fixture": True})])
    (tmp_path / "state.fixture.run1.json").write_text("{}", encoding="utf-8")
    return SimpleNamespace(
        env=SimpleNamespace(proxy_state=tmp_path, ff_config=tmp_path / "config.json"),
        ff_root=tmp_path, active_case_spec=spec, traces={}, artifacts=tmp_path,
        scratch=tmp_path, deadline=deadline, phases=PhaseTimer(),
        adapter_records=lambda: [], child_env=dict,
    )


def test_w20_spent_case_never_starts_a_new_process(tmp_path, monkeypatch):
    import w20_fault_cases as w20
    from runtime import Deadline, DeadlineExceeded

    ctx = _w20_context(tmp_path, Deadline(end=0))
    monkeypatch.setattr(w20.subprocess, "Popen", lambda *a, **k: pytest.fail("expired case spawned FF"))
    with pytest.raises(DeadlineExceeded):
        w20.launch_ff_run(ctx, case_id="fixture", run_label="run1", request={"fixture": True})
    assert not list(tmp_path.glob("*.stdout.bin"))
    assert not ctx.traces


@pytest.mark.parametrize("point", [
    "job_assignment", "deadline_at_release", "interrupt_observer", "job_close_failure", "terminate_failure",
])
def test_w20_reaps_held_child_and_keeps_failure_trace(tmp_path, monkeypatch, point):
    from io import BytesIO
    from types import SimpleNamespace
    import w20_fault_cases as w20

    from runtime import DeadlineExceeded

    deadline = proof.Deadline()
    ctx = _w20_context(tmp_path, SimpleNamespace(case=lambda _: deadline))
    operations = []
    state = {"returncode": None}

    def kill():
        operations.append("kill")
        state["returncode"] = 1

    def wait(*, timeout):
        operations.append("reap")
        child.returncode = state["returncode"]
        return child.returncode

    child = SimpleNamespace(pid=123, stdin=BytesIO(), returncode=None,
                            poll=lambda: state["returncode"], kill=kill, wait=wait)

    def assign(_proc):
        operations.append("assign")
        assert child.stdin.getvalue() == b""
        if point == "job_assignment":
            raise OSError("fixture job assignment failed")
        if point == "deadline_at_release":
            deadline.end = 0
        return SimpleNamespace(terminate=terminate, close=close)

    def terminate():
        if point == "terminate_failure":
            operations.append("terminate")
            raise OSError("private terminate detail")
        kill()

    def close():
        operations.append("close")
        if point == "job_close_failure":
            raise OSError("private close detail")
        # Windows Job close kills the owned tree if explicit terminate failed.
        state["returncode"] = 1

    def observe():
        operations.append("observe")
        raise ValueError("fixture observer failed")

    monkeypatch.setattr(w20, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(w20.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setattr(w20.subprocess, "Popen", lambda *a, **kw: child)
    monkeypatch.setattr(w20.ff_process_tree, "assign_windows_job", assign)
    failures = {"job_assignment": OSError, "deadline_at_release": DeadlineExceeded,
                "interrupt_observer": ValueError, "job_close_failure": ValueError,
                "terminate_failure": ValueError}
    failure = failures[point]
    with pytest.raises(failure):
        w20.launch_ff_run(ctx, case_id="fixture", run_label="run1", request={"fixture": True},
                          kill_when=observe)

    assert operations == {
        "job_assignment": ["assign", "kill", "reap"],
        "deadline_at_release": ["assign", "kill", "reap", "close"],
        "interrupt_observer": ["assign", "observe", "kill", "reap", "close"],
        "job_close_failure": ["assign", "observe", "kill", "reap", "close"],
        "terminate_failure": ["assign", "observe", "terminate", "close", "reap"],
    }[point]
    assert child.stdin.closed
    trace, = ctx.traces["fixture"]
    assert trace["exit_code"] == 1
    assert trace["launch_error"]["type"] == failure.__name__
    assert trace["elapsed_seconds"] >= 0
    assert trace["et_fixture_requests"] == 0
    if point in {"job_close_failure", "terminate_failure"}:
        assert trace["cleanup_errors"] == [{
            "stage": "job_close" if point == "job_close_failure" else "process_terminate", "type": "OSError",
        }]
        assert "private" not in json.dumps(trace)
