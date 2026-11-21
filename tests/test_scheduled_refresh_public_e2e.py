from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import io
import os
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

import pytest

from ff_persistence import atomic_write_json
import ff_refresh_owners as owners
from test_scheduled_refresh import SCRIPT, configure_body


_PUBLIC_OWNER = """
import json
from pathlib import Path
import sys
import time

operation = sys.argv[1]
request = json.load(sys.stdin)
with Path("calls.jsonl").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"operation": operation, "request": request}) + "\\n")
if operation == "discover":
    time.sleep(0.2)
    identity = request["identity"]
    market = identity["market"]
    ref = {
        "schema_version": "2.0",
        "document_id": "public-source-" + market,
        "source_id": "native-source-" + market,
        "content_sha256": {"CN": "a", "HK": "b", "US": "c"}[market] * 64,
        "byte_size": 200,
        "mime_type": "application/pdf",
    }
    response = {
        "schema_version": "cwp-incremental-discovery/1",
        "request_id": request["request_id"], "next_cursor": None, "coverage": "complete",
        "scope": {"identity": identity, "source_market": market},
        "usage": {"http_requests": 1, "response_bytes": 302},
        "candidates": [{
            "provider_document_id": "accession-" + market,
            "provider": "fixture-" + market, "source_market": market, "document_kind": "annual_report",
            "published_at": request["as_of_date"], "source_ref": ref,
        }],
    }
elif operation == "read":
    response = {
        "schema_version": "cwp-incremental-read/1", "run_id": request["run_id"],
        "items": [{
            "state": "read", "source_ref": ref, "result_ref": "result-" + ref["document_id"],
            "reused": False,
        } for ref in request["sources"]],
    }
else:
    raise AssertionError(operation)
print(json.dumps(response))
"""


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_two_real_cli_ticks_share_one_scope_and_read_each_source_once(tmp_path):
    cwp = tmp_path / "owner"
    cwp.mkdir()
    fake = cwp / "public_owner.py"
    fake.write_text(_PUBLIC_OWNER, encoding="utf-8")
    connection = tmp_path / "connection.json"
    _write(connection, {
        "schema_version": "1.0",
        "connection": {"cwd": str(cwp), "commands": {
            "incremental_discover": [sys.executable, "-B", str(fake), "discover"],
            "incremental_read": [sys.executable, "-B", str(fake), "read"],
        }},
    })
    deployment = tmp_path / "scheduled_refresh.json"
    _write(deployment, {
        "schema_version": "ff-scheduled-refresh-deployment/1", "pinned_rosters": "exports.json",
    })
    _write(tmp_path / "exports.json", {"rosters": {"primary": {
        "snapshot_id": "three-market-owner-2026", "items": [
            {"entity_id": "issuer-" + code, "listing_id": "listing-" + code,
             "market": code, "ticker": symbol}
            for code, symbol in (("CN", "600001"), ("HK", "01234"), ("US", "TEST"))
        ],
    }}})
    store = tmp_path / "store"
    fixed = [sys.executable, "-B", str(SCRIPT), "--config", str(connection), "--jobs-dir", str(store)]

    def run(*args, body=None):
        result = subprocess.run(
            [*fixed, *args], input=json.dumps(body) if body is not None else "", encoding="utf-8",
            capture_output=True, timeout=60,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        return json.loads(result.stdout)

    run("configure", "--request-stdin", body=configure_body(
        roster={"mode": "pinned", "roster_ref": "primary"}, transcripts_enabled=False, backlog_enabled=False,
    ))
    assert not (cwp / "calls.jsonl").exists()
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(run, "tick") for _ in range(2)]
        for future in futures:
            future.result()
    after = run("tick")
    assert after["last_run"]["counts"]["reused"] == after["last_run"]["counts"]["read"] == 3
    assert after["last_run"]["counts"]["downloaded"] == 0
    assert after["last_run"]["roster_snapshot_id"] == "three-market-owner-2026"
    assert after["last_run"]["usage"]["metadata_requests"] == 3
    assert len(run("runs")["items"]) == 1
    calls = [json.loads(line) for line in (cwp / "calls.jsonl").read_text().splitlines()]
    assert [row["operation"] for row in calls] == ["discover"] * 3 + ["read"] * 3
    reads = [row["request"] for row in calls if row["operation"] == "read"]
    assert len({request["run_id"] for request in reads}) == 3
    assert {request["sources"][0]["document_id"] for request in reads if len(request["sources"]) == 1} == {
        "public-source-CN", "public-source-HK", "public-source-US",
    }
    assert not (store / "jobs").exists()


@pytest.mark.parametrize("accession", ["amd-2025-10k", "different-revision"])
def test_native_scheduled_job_requires_the_requested_accession(accession, tmp_path, monkeypatch):
    fixture = Path(__file__).parent / "fixtures" / "short_feedback" / "connector.py"
    connection = tmp_path / "connection.json"
    log = tmp_path / "catalog-calls.jsonl"
    monkeypatch.setenv("FF_SHORT_SCENARIO", "download")
    monkeypatch.setenv("FF_SHORT_CALL_LOG", str(log))
    _write(connection, {
        "schema_version": "1.0",
        "connection": {"cwd": str(tmp_path), "commands": {
            "catalog": [sys.executable, "-B", str(fixture), "catalog"],
        }},
    })
    ports = owners.OwnerPorts(connection, tmp_path / "jobs", owners.Deployment())
    request = {
        "schema_version": "2.0", "company_query": "AMD", "market": "US", "mode": "exact",
        "document_kind": "annual_report", "fiscal_year": 2025, "as_of_date": "2026-11-23",
        "provider": "sec", "provider_document_id": accession, "filing_intent": "fetch_if_missing",
        "acquisition_limits": {"max_bytes": 16384, "timeout_seconds": 9, "max_cost_usd": "0.01"},
    }
    job = ports.acquire("sr-exact-accession", "filing.acquire", request, timeout=15, run_id="sr-first")
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    capture = calls[-1]["argv"]
    assert "ensure" in capture
    assert capture[capture.index("--provider-document-id") + 1] == accession
    assert capture[capture.index("--max-download-bytes") + 1] == "16384"
    assert float(capture[capture.index("--max-download-seconds") + 1]) == 9
    assert capture[capture.index("--max-download-cost-usd") + 1] == "0.01"
    if accession == "different-revision":
        assert job["status"] == "unknown"
        assert job["cost_state"] == "unknown" and job["result"] is None
        return
    assert job["status"] == "succeeded" and job["result"]["downloads"] == 1
    assert job["cost_state"] == "known" and job["cost"]["value"] == "0.0004"
    observed = ports.acquire("sr-exact-accession", "filing.acquire", request, timeout=15, run_id="sr-restart")
    assert observed["owner_job_id"] == job["owner_job_id"] and observed["reused_job"]
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.skipif(os.name != "nt", reason="schtasks uses the Windows OEM code page")
@pytest.mark.parametrize("encoding", ["oem", "utf-16"])
def test_windows_query_accepts_task_xml_from_redirected_native_command(tmp_path, monkeypatch, encoding):
    import ff_scheduled_windows as launcher

    name = "FilingRefresh résumé 财报".encode(encoding, errors="replace").decode(encoding)
    definition = launcher.task_definition(
        sid="S-1-5-21-123", task_name=name, launcher=Path(sys.executable),
        arguments=["-B", str(tmp_path / name / "refresh.py")],
    )
    payload = ('<?xml version="1.0" encoding="UTF-16"?>\r\n' + definition).encode(encoding)

    def query(args, **kwargs):
        assert args == ["schtasks.exe", "/Query", "/TN", name, "/XML"]
        return subprocess.CompletedProcess(args, 0, stdout=payload)

    monkeypatch.setattr(launcher.subprocess, "run", query)
    observed = launcher._query_task(name)
    assert launcher._registered_task(observed, name, "ignored-alias", "S-1-5-21-123")
    assert name in launcher._find(observed, "t:Actions/t:Exec/t:Arguments")


@pytest.mark.skipif(os.name != "nt", reason="native Windows task installation protocol")
@pytest.mark.parametrize("operation,registered", [("install", True), ("remove", False)])
def test_windows_task_mutation_keeps_its_stdout_for_the_json_receipt(
    tmp_path, monkeypatch, capsys, operation, registered,
):
    import ff_scheduled_windows as launcher

    name, sid = "FilingRefresh-fixture", "S-1-5-21-123"
    task = ElementTree.fromstring(launcher.task_definition(
        sid=sid, task_name=name, launcher=Path(sys.executable), arguments=[],
    ))
    observations = iter([None, task] if registered else [task])
    monkeypatch.setattr(launcher, "_identity", lambda: ("user", sid))
    monkeypatch.setattr(launcher, "_query_task", lambda _: next(observations))

    def mutate(args, **kwargs):
        assert args[1] == ("/Create" if registered else "/Delete")
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(args, 0, stdout=b"localized scheduler success")

    monkeypatch.setattr(launcher.subprocess, "run", mutate)
    assert launcher.run([operation, "--task-name", name, "--jobs-dir", str(tmp_path)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["task_name"] == name and receipt["registered"] is registered


@pytest.mark.skipif(os.name != "nt", reason="native Windows Task Scheduler inputs")
def test_windows_preview_produces_hidden_user_task_without_installing(tmp_path):
    helper = SCRIPT.with_name("ff_scheduled_windows.py")
    result = subprocess.run([
        sys.executable, "-B", str(helper), "preview", "--python", sys.executable,
        "--config", str(tmp_path / "space in config.json"), "--jobs-dir", str(tmp_path / "space in store"),
    ], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, (result.stdout, result.stderr)
    task = ElementTree.fromstring(json.loads(result.stdout)["definition"])
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert task.findtext(".//t:LogonType", namespaces=ns) == "InteractiveToken"
    assert task.findtext(".//t:MultipleInstancesPolicy", namespaces=ns) == "IgnoreNew"
    assert task.findtext(".//t:TimeTrigger/t:Repetition/t:Interval", namespaces=ns) == "PT30M"
    arguments = task.findtext(".//t:Exec/t:Arguments", namespaces=ns)
    launcher = task.findtext(".//t:Exec/t:Command", namespaces=ns)
    assert Path(launcher).name == "pythonw.exe"
    assert ' run --python ' in arguments and '"'+str(tmp_path / "space in store")+'"' in arguments
    started = subprocess.run(
        [launcher, "-B", str(helper), "run", "--python", sys.executable,
         "--jobs-dir", str(tmp_path / "space in store")], timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert started.returncode == 0
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(os.name != "nt", reason="Windows owner-record sharing semantics")
def test_atomic_publication_reuses_the_same_temporary_bytes_after_a_share_conflict(tmp_path, monkeypatch):
    replace = os.replace
    seen = []

    def busy_once(source, target):
        seen.append(source)
        if len(seen) == 1:
            error = PermissionError("simulated temporary sharing conflict")
            error.winerror = 32
            raise error
        return replace(source, target)

    monkeypatch.setattr(os, "replace", busy_once)
    target = tmp_path / "state.json"
    atomic_write_json(target, {"active_action": "existing-owner-job"})
    assert len(seen) == 2 and seen[0] == seen[1]
    assert json.loads(target.read_text()) == {"active_action": "existing-owner-job"}
    assert list(tmp_path.iterdir()) == [target]


def test_native_universe_envelope_uses_the_selected_stockwiki_workspace(tmp_path, monkeypatch):
    request_paths = []
    bridge_args = []
    roster = {"universe": {"universe_id": "tracked"}, "member_count": 1, "members": [
        {"entity_id": "r25-entity", "membership_status": "active"},
    ]}

    class Reply(io.BytesIO):
        status = 200

    class Connection:
        sock = None

        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, path, **kwargs):
            request_paths.append((method, path))

        def getresponse(self):
            return Reply(json.dumps({"ok": True, "data": roster}).encode())

        def close(self):
            pass

    def bridge(command, **kwargs):
        bridge_args.append(command)
        body = {"authority": "stockwiki", "resolution_status": "resolved", "entity": {
            "entity_id": "r25-entity", "selected_listing_id": "r25-listing", "listings": [{
                "entity_id": "r25-entity", "listing_id": "r25-listing", "market": "HK",
                "ticker": "01234", "listing_status": "active",
            }],
        }}
        return json.dumps(body).encode(), b"", 0

    monkeypatch.setattr(owners.http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(owners, "run_bounded_json", bridge)
    workspace = tmp_path / "original-workspace"
    options = owners.Deployment(universe_origin="http://127.0.0.1:8766",
                                identity=owners.IdentityDeployment(tmp_path, workspace, sys.executable))
    result = owners.OwnerPorts(tmp_path / "config", tmp_path, options).roster(
        {"mode": "universe", "universe_id": "tracked"}, None, None, timeout=10,
    )
    assert request_paths == [("GET", "/api/product/universe?universe_id=tracked")]
    assert bridge_args[0][-2:] == ["--root", str(workspace)]
    assert result["items"] == [{
        "entity_id": "r25-entity", "listing_id": "r25-listing", "market": "HK", "ticker": "01234",
    }]
