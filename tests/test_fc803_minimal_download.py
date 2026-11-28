"""Real FF/CWP acquisition smoke, using a localhost provider and owned originals."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from threading import Thread

import pytest

from e2e_support.isolated_wiki import IsolatedWiki


pytestmark = pytest.mark.e2e_offline
ADAPTER = Path(__file__).with_name("e2e_support") / "loopback_provider.py"

@cache
def annual_pdf(year: int) -> bytes:
    # Use the actual PDF reader format. A %PDF magic-prefix stub cannot
    # establish an older local fiscal scope before a download decision.
    import pymupdf

    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((48, 65), f"宁德时代\n证券代码：300750\n{year}年年度报告",
                         fontname="china-s", fontsize=13)
        return document.tobytes(no_new_id=True)


def seed_old_period(wiki: IsolatedWiki) -> Path:
    original = wiki.seed_market("CN")
    original.write_bytes(annual_pdf(2024))
    return original


@dataclass
class Provider:
    candidates: list[dict] = field(default_factory=list)
    calls: list[tuple[str, dict]] = field(default_factory=list)
    unavailable: bool = False

    def call_count(self, operation: str) -> int:
        return sum(action == operation for action, _ in self.calls)


@pytest.fixture
def provider(tmp_path):
    state = Provider()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            operation = self.path.lstrip("/")
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.calls.append((operation, request))
            if state.unavailable:
                self.send_error(503)
                return
            data = (json.dumps(state.candidates).encode() if operation == "discover"
                    else annual_pdf(request["fiscal_year"]))
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_: object) -> None:
            pass

    wiki = IsolatedWiki(tmp_path)
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as listener:
        command = [sys.executable, "-B", str(ADAPTER), f"http://127.0.0.1:{listener.server_port}"]
        config = {
            "schema_version": "1.1", "staging_root": str(wiki.catalog_dir / "staging"),
            "timeout_seconds": 15,
            "adapters": {
                market: {
                    "name": "ff-loopback-fixture", "version": "1.0.0",
                    "interface": "json_command_v1" if market == "cn" else "dayu_sdk_bounded_v1",
                    "supports_acquisition_budget": True,
                    "project_root": str(wiki.root), "config_root": None,
                    "command": command,
                }
                for market in ("cn", "hk", "us")
            },
        }
        (wiki.root / "config" / "source_acquisition.yaml").write_text(json.dumps(config), encoding="utf-8")
        server = Thread(target=listener.serve_forever, daemon=True)
        server.start()
        try:
            yield wiki, state
        finally:
            listener.shutdown()
            server.join(timeout=5)
            assert not server.is_alive()


def candidate(accession: str, fiscal_year: int, *, filing_date: str = "2026-04-15") -> dict:
    return {
        "candidate_id": accession, "provider": "cninfo", "provider_document_id": accession,
        "entity": "宁德时代", "market": "CN", "security_id": "300750",
        "title": f"宁德时代{fiscal_year}年年度报告", "source_url": f"https://example.invalid/{accession}.pdf",
        "document_kind": "annual_report", "form_type": "FY", "fiscal_year": fiscal_year,
        "fiscal_period": "FY", "filing_date": filing_date, "amended": False, "language": "zh",
    }


def fetch(wiki: IsolatedWiki, *, fiscal_year: int | None = 2025,
          intent: str = "fetch_if_missing") -> tuple[int, dict]:
    request = {
        "schema_version": "2.0", "company_query": "宁德时代", "market": "CN",
        "document_kind": "annual_report", "mode": "exact" if fiscal_year else "latest_as_of",
        "as_of_date": "2026-07-31", "filing_intent": intent,
    }
    if fiscal_year is not None:
        request["fiscal_year"] = fiscal_year
    if intent == "fetch_if_missing":
        request["acquisition_limits"] = {"max_bytes": 80_000, "timeout_seconds": 30, "max_cost_usd": "0"}
    code, stdout, stderr = wiki.run_fetch(request)
    assert stdout, stderr
    return code, json.loads(stdout)


def published(reply: tuple[int, dict], *, content: bytes, downloads: int) -> dict:
    code, output = reply
    assert code == 0, output
    assert output["status"] == output["filing"]["status"] == "source_candidate"
    assert output["downloads"] == downloads
    ref = output["filing"]["source_ref"]
    assert ref["content_sha256"] == hashlib.sha256(content).hexdigest()
    return ref


def companies(wiki: IsolatedWiki) -> dict[str, str]:
    root = wiki.root / "companies"
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def test_lt09_second_request_adds_no_provider_dispatch_or_writes(provider):
    wiki, state = provider
    wiki.scan()
    state.candidates = [candidate("fixture-2025", 2025)]
    ref = published(fetch(wiki), content=annual_pdf(2025), downloads=1)
    first = companies(wiki)
    assert len(first) == 2  # original and its provenance sidecar
    assert published(fetch(wiki), content=annual_pdf(2025), downloads=0) == ref
    assert companies(wiki) == first
    assert state.call_count("discover") == state.call_count("fetch") == 1


def seed_verified_period(wiki: IsolatedWiki, state: Provider) -> dict:
    wiki.scan()
    state.candidates = [candidate("fixture-2024", 2024, filing_date="2025-03-14")]
    ref = published(fetch(wiki, fiscal_year=2024), content=annual_pdf(2024), downloads=1)
    assert state.call_count("discover") == state.call_count("fetch") == 1
    return ref


def test_lt02_fetches_only_the_new_period_and_keeps_the_old_original(provider):
    wiki, state = provider
    old = seed_verified_period(wiki, state)
    before = companies(wiki)
    start = len(state.calls)
    state.candidates = [candidate("fixture-2025", 2025)]
    published(fetch(wiki), content=annual_pdf(2025), downloads=1)
    assert published(fetch(wiki, fiscal_year=2024, intent="reuse_only"),
                     content=annual_pdf(2024), downloads=0) == old
    after = companies(wiki)
    assert len(after) == len(before) + 2
    assert all(after[path] == digest for path, digest in before.items())
    assert [request.get("fiscal_year") for op, request in state.calls[start:] if op == "fetch"] == [2025]


def test_lt01_latest_existing_original_adds_no_download(provider):
    wiki, state = provider
    old = seed_verified_period(wiki, state)
    before = companies(wiki)
    assert published(fetch(wiki, fiscal_year=None), content=annual_pdf(2024), downloads=0) == old
    assert companies(wiki) == before
    assert state.call_count("fetch") == 1


def test_lt05_provider_failure_does_not_mutate_or_occlude_the_cached_period(provider):
    wiki, state = provider
    old = seed_verified_period(wiki, state)
    before = companies(wiki)
    state.unavailable = True
    code, first = fetch(wiki)
    assert code == 2 and first["status"] != "source_candidate", first
    assert first["downloads"] == 0
    assert state.call_count("discover") == 2 and state.call_count("fetch") == 1
    assert published(fetch(wiki, fiscal_year=2024, intent="reuse_only"),
                     content=annual_pdf(2024), downloads=0) == old
    assert state.call_count("discover") == 2 and companies(wiki) == before


def test_lt07_future_filing_is_not_dispatched_or_relabelled(provider):
    wiki, state = provider
    seed_old_period(wiki)
    wiki.scan()
    before = companies(wiki)
    state.candidates = [candidate("fixture-future", 2025, filing_date="2027-03-15")]
    code, output = fetch(wiki)
    assert code == 2 and output["status"] != "source_candidate", output
    assert output["downloads"] == 0 and "source_ref" not in output["filing"]
    assert state.call_count("discover") == 1 and state.call_count("fetch") == 0
    assert companies(wiki) == before
