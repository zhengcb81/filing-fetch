"""Real FF 2.0 and pinned CWP process contracts over isolated source and identity data."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import subprocess
import sys

import pytest

from e2e_support.cwp_runtime import WINDOW_FLAGS, isolated_environment, run_quiet
from e2e_support.isolated_wiki import IsolatedWiki, SYNTHETIC_SEEDS


pytestmark = pytest.mark.e2e_offline
NAMES = {"CN": "宁德时代", "HK": "腾讯", "US": "Apple"}
YEARS = {"CN": 2024, "HK": 2024, "US": 2025}


def request(market: str = "CN", **changes) -> dict:
    result = {
        "schema_version": "2.0", "company_query": NAMES[market], "market": market,
        "document_kind": "annual_report", "mode": "exact", "fiscal_year": YEARS[market],
        "as_of_date": "2026-07-31", "filing_intent": "reuse_only",
    }
    result.update(changes)
    return result


def call(wiki: IsolatedWiki, value: dict, *, extra_args: list[str] | None = None) -> tuple[int, dict]:
    code, out, err = wiki.run_fetch(value, timeout=30, extra_args=extra_args)
    assert out, err
    return code, json.loads(out)


def originals(wiki: IsolatedWiki) -> dict[str, bytes]:
    root = wiki.root / "companies"
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def assert_reused(wiki: IsolatedWiki, result: tuple[int, dict], market: str) -> dict:
    code, value = result
    assert code == 0, value
    assert value["schema_version"] == "2.0"
    assert value["status"] == value["filing"]["status"] == "source_candidate"
    assert value["downloads"] == 0
    assert str(wiki.root) not in json.dumps(value)
    source_ref = value["filing"]["source_ref"]
    body = SYNTHETIC_SEEDS[market]["bytes"]
    assert source_ref["content_sha256"] == hashlib.sha256(body).hexdigest()
    assert source_ref["byte_size"] == len(body)
    return source_ref


@pytest.fixture(scope="module")
def seeded(tmp_path_factory) -> IsolatedWiki:
    wiki = IsolatedWiki(tmp_path_factory.mktemp("filing-v2"))
    for market in NAMES:
        seed = wiki.seed_market(market)
        if market == "HK":
            # This v2 contract case has an explicit disclosed fiscal year.
            # The four-field legacy sidecar has its own case below.
            sidecar = seed.with_name(seed.name + ".source.json")
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
            payload["fiscal_year"] = YEARS[market]
            sidecar.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    wiki.scan()
    return wiki


@pytest.mark.parametrize("market", NAMES)
def test_e2e_current_v2_reuses_each_market_and_cwp_can_open_the_exact_original(seeded, market):
    # US uses a different display name from
    # the directory. CN uses a literal UTF-8 query through stdin.
    before = originals(seeded)
    result = call(seeded, request(market))
    source_ref = assert_reused(seeded, result, market)
    rc, content, receipt = seeded.read(source_ref)
    assert rc == 0, receipt
    assert content == SYNTHETIC_SEEDS[market]["bytes"]
    assert originals(seeded) == before


@pytest.mark.parametrize("changes", [
    {"document_kind": "quarterly_report"},
    {"fiscal_year": 1999},
    {"as_of_date": "2025-01-01"},
], ids=["kind", "year", "information-date"])
def test_e2e_scope_mismatch_cannot_reuse_a_nearby_original(seeded, changes):
    before = originals(seeded)
    code, value = call(seeded, request(**changes))
    assert code != 0
    assert value["status"] == "source_blocked", value
    assert value["filing"]["retryable"] is False
    assert "source_ref" not in value["filing"]
    assert originals(seeded) == before


def test_e2e_ambiguous_identity_is_not_auto_selected(tmp_path):
    from e2e_support.isolated_wiki import _synthetic_security_master

    wiki = IsolatedWiki(tmp_path)
    master = wiki.catalog_dir / "security_master" / "cn.json"
    payload = _synthetic_security_master("cn")
    baseline = payload["records"][0]
    payload["records"] = [
        dict(baseline, aliases=["万科"], canonical_name="深圳万科股份", security_id="000002",
             ticker="000002", source_record_id="synthetic-vi"),
        dict(baseline, aliases=["万科"], canonical_name="广州万科股份", security_id="000004",
             ticker="000004", source_record_id="synthetic-vii"),
    ]
    payload["record_count"] = len(payload["records"])
    master.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    wiki.scan()
    code, result = call(wiki, request(company_query="万科"))
    assert code != 0
    assert result["status"] == "identity_error", result
    assert result["filing"]["retryable"] is False


def test_e2e_missing_identity_cache_retains_actionable_failure(tmp_path):
    wiki = IsolatedWiki(tmp_path, with_security_master=False)
    code, value = call(wiki, request("US"))
    assert code != 0
    assert value["status"] == "fatal", value
    assert value["filing"]["status"] == "fatal"
    assert value["filing"]["retryable"] is False
    assert str(tmp_path) not in json.dumps(value)


def test_e2e_missing_producer_period_is_not_filled_from_the_consumer_request(tmp_path):
    wiki = IsolatedWiki(tmp_path)
    wiki.seed_market("HK")  # The old sidecar leaves fiscal_year out.
    wiki.scan()
    before = originals(wiki)
    code, output = call(wiki, request("HK"))
    assert code == 2
    assert output["status"] == "upstream_error", output
    assert "fiscal_year mismatch" in output["filing"]["reason"]
    assert output["downloads"] == 0
    assert originals(wiki) == before


def test_e2e_legacy_partial_provenance_is_not_capture_ready(tmp_path):
    wiki = IsolatedWiki(tmp_path)
    source = wiki.seed_market("CN")
    sidecar = source.with_name(source.name + ".source.json")
    observed = SYNTHETIC_SEEDS["CN"]["sidecar"]
    raw = {key: observed[key] for key in ("market", "security_id", "source_title", "published_date")}
    raw["source_url"] = "http://insecure.example/synthetic.pdf"
    sidecar.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    wiki.scan()
    value = request(schema_version="1.1")
    del value["filing_intent"]
    del value["mode"]
    code, result = call(wiki, value)
    assert code != 0
    assert result["status"] == "not_found", result
    assert "handle" not in result


def test_e2e_cwp_origin_owner_rejects_corrupted_bytes_after_selection(tmp_path):
    wiki = IsolatedWiki(tmp_path)
    source = wiki.seed_market("CN")
    wiki.scan()
    ref = assert_reused(wiki, call(wiki, request()), "CN")
    original = source.read_bytes()
    source.write_bytes(original[:-1] + b"!")
    code, body, receipt = wiki.read(ref)
    assert code != 0, receipt
    assert body == b""
    assert json.loads(receipt)["reason"] == "no_verified_location"
    errors = (wiki.root / "logs" / "runtime_errors.log").read_text(encoding="utf-8")
    assert "content_sha256_mismatch" in errors
    assert source.read_bytes() == original[:-1] + b"!"


LOCK_OWNER = r"""
from pathlib import Path
import sys

from company_wiki.source_catalog import SourceCatalog, load_catalog_config

catalog = SourceCatalog(load_catalog_config(Path(sys.argv[1])))
try:
    with catalog.operation_lock(operation="ff-integration-held-writer"):
        sys.stdout.buffer.write(b"locked\n")
        sys.stdout.buffer.flush()
        # Only the test owns the write end. Closing it releases the lock,
        # including when an assertion or the test process fails.
        sys.stdin.buffer.read(1)
finally:
    catalog.close()
"""


@contextmanager
def hold_catalog_lock(wiki):
    with subprocess.Popen(
        [sys.executable, "-B", "-c", LOCK_OWNER, str(wiki.config_path)],
        cwd=wiki.root, env=isolated_environment(wiki.root, wiki.src),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=WINDOW_FLAGS,
    ) as owner, ThreadPoolExecutor(max_workers=1) as waiter:
        assert owner.stdout is not None and owner.stdin is not None
        ready = waiter.submit(owner.stdout.readline)
        try:
            assert ready.result(timeout=40) == b"locked\n"
            yield owner
        finally:
            if not ready.done():
                owner.stdin.close()
                try:
                    owner.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    owner.kill()
                    owner.wait(timeout=10)
            else:
                try:
                    _, stderr = owner.communicate(input=b"", timeout=15)
                except subprocess.TimeoutExpired:
                    owner.kill()
                    owner.communicate(timeout=10)
                    raise
                assert owner.returncode == 0, stderr.decode("utf-8", "replace")


TRACE_CATALOG = r"""
import json
from pathlib import Path
import subprocess
import sys

argv = sys.argv[2:]
with Path(sys.argv[1]).open("a", encoding="utf-8") as log:
    log.write(json.dumps(argv) + "\n")
result = subprocess.run([sys.executable, "-B", "-m", "company_wiki.source_catalog.cli", *argv],
                        capture_output=True, stdin=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
raise SystemExit(result.returncode)
"""


def test_e2e_reuse_does_not_call_busy_catalog_write_operations(tmp_path):
    wiki = IsolatedWiki(tmp_path)
    original = wiki.seed_market("CN")
    wiki.scan()
    launcher = tmp_path / "trace-catalog.py"
    launcher.write_text(TRACE_CATALOG, encoding="utf-8")
    log = tmp_path / "catalog-argv.jsonl"
    catalog = [sys.executable, "-B", str(launcher), str(log), "--config", str(wiki.config_path)]
    root_config = {
        "schema_version": "1.0",
        "connection": {
            "cwd": str(wiki.root),
            "commands": {
                "catalog": catalog,
                "query": [sys.executable, "-B", "-m", "company_wiki.source_catalog.source_query_cli",
                          "--config", str(wiki.config_path)],
            },
        },
    }
    (wiki.root / "company_wiki.json").write_text(json.dumps(root_config), encoding="utf-8")
    writer = [sys.executable, "-B", "-m", "company_wiki.source_catalog.cli",
              "--config", str(wiki.config_path), "scan", "--root-id", "company_raw"]
    before = originals(wiki)
    with hold_catalog_lock(wiki) as owner:
        denied = run_quiet(writer, cwd=wiki.root, env=isolated_environment(wiki.root, wiki.src))
        assert denied.returncode == 1, (denied.stdout, denied.stderr)
        reason = json.loads(denied.stderr)
        assert reason["error_type"] == "catalog_locked" and reason["retryable"] is True
        ref = assert_reused(wiki, call(wiki, request()), "CN")
        code, content, receipt = wiki.read(ref)
        assert code == 0, receipt
        assert content == original.read_bytes()
        assert owner.poll() is None  # The real writer was still holding the lease.
    assert owner.returncode == 0
    wiki.scan()  # An independent writer can proceed after the lease is released.
    assert originals(wiki) == before
    launches = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(launches) == 1 and "identify" in launches[0]


@pytest.mark.parametrize(("state", "extra"), [
    ("paused", None), ("paused", ["--no-pause-worker"]), ("enabled", None),
], ids=["paused", "legacy-flag", "enabled"])
def test_e2e_legacy_worker_state_does_not_gate_bounded_request(tmp_path, state, extra):
    wiki = IsolatedWiki(tmp_path)
    wiki.set_worker_state(state)
    wiki.scan()
    control = wiki.catalog_dir / "worker_control.json"
    before = control.read_bytes()
    code, value = call(wiki, request(
        document_kind="quarterly_report", filing_intent="fetch_if_missing",
        acquisition_limits={"max_bytes": 50_000, "timeout_seconds": 20, "max_cost_usd": "0"},
    ), extra_args=extra)
    assert code != 0
    assert value["status"] == "not_found", value
    assert value["filing"]["retryable"] is False
    assert control.read_bytes() == before
