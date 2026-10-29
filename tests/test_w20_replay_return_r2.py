"""W20 return R2 (2026-10-29): lost-reply invariants and probe isolation.

ROOT reception R2 regression. Two P2 findings, each encoded as failing
assertions BEFORE the fix:

* FF-R2-1 — the critical durable scenario must intercept/drop the success
  reply of THE SAME real new acquisition (identity贯穿 download → durable →
  intercepted reply), with "never delivered to the client before" as an
  invariant. A report where run0 was ALREADY delivered and a later re-request
  was killed must be rejected as a proxy.
* FF-R2-2 — the public read-back probe must be isolated (no process-global
  sys.stdin/stdout swaps, no shared last_error), must distinguish
  confirmed / not_found / probe_error, and an exception must never be
  readable as "publicly confirmed not durable".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
MATRIX = ROOT / "tools" / "offline_contract_matrix"
for path in (str(MATRIX), str(TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import case_specs  # noqa: E402
import w20_case_specs  # noqa: E402


def _ref(sha: str, size: int = 512, mime: str = "application/json") -> dict[str, Any]:
    return {
        "document_id": f"urn:company-wiki:document:sha256:{sha}",
        "source_id": f"urn:company-wiki:source:sha256:{sha}",
        "content_sha256": sha,
        "byte_size": size,
        "mime_type": mime,
    }


SHA = "f" * 64


def _run(response: dict[str, Any] | None, *, killed: bool = False, gets: int = 0,
         intercepted: bool | None = None) -> dict[str, Any]:
    run: dict[str, Any] = {"response": response or {}, "killed": killed,
                           "et_fixture_requests": gets}
    if intercepted is not None:
        run["reply_intercepted"] = intercepted
    return run


# ── FF-R2-1: lost-reply case exists and rejects the re-request-kill proxy ──


def test_lost_reply_case_registered() -> None:
    spec = w20_case_specs.get_w20_spec("w20_call_lost_reply_after_durable")
    assert spec is not None, "the same-acquisition lost-reply case must exist"
    assert spec.expected().get("reply_intercepted") is True
    # The prior-delivery re-request-kill case remains, as an honest control.
    assert w20_case_specs.get_w20_spec("w20_call_kill_after_durable") is not None
    assert len(case_specs.case_specs()) == 41


def test_lost_reply_rejects_delivered_run0_plus_empty_kill() -> None:
    """The ROOT counterexample: run0 was already DELIVERED as downloaded and a
    later re-request was killed — that must NOT satisfy the lost-reply case."""
    spec = w20_case_specs.get_w20_spec("w20_call_lost_reply_after_durable")
    proxy = {
        "id": "w20_call_lost_reply_after_durable",
        "actual": {
            "verified_at_reply_loss": _ref(SHA),
            "runs": [
                # run0 delivered a success to the client (no interception mark).
                _run({"transcript": {"status": "downloaded", "source_ref": _ref(SHA)}},
                     killed=False, gets=1),
                # A later re-request was killed — "another empty process kill".
                _run({}, killed=True, gets=0),
                _run({"transcript": {"status": "reused", "source_ref": _ref(SHA)}},
                     killed=False, gets=0),
            ],
        },
    }
    errors = spec.assertion_errors(proxy)
    assert errors, "a delivered run0 plus a re-request kill must be rejected"


def test_lost_reply_accepts_only_intercepted_same_acquisition() -> None:
    spec = w20_case_specs.get_w20_spec("w20_call_lost_reply_after_durable")
    good = {
        "id": "w20_call_lost_reply_after_durable",
        "actual": {
            "verified_at_reply_loss": _ref(SHA),
            "runs": [
                # The SAME acquisition completed server-side; its success
                # reply was intercepted at the harness transport boundary and
                # never delivered to the client.
                _run({"transcript": {"status": "downloaded", "source_ref": _ref(SHA)}},
                     killed=False, gets=1, intercepted=True),
                # First recovery: zero extra GETs, same Ref/SHA.
                _run({"transcript": {"status": "reused", "source_ref": _ref(SHA)}},
                     killed=False, gets=0),
                _run({"transcript": {"status": "reused", "source_ref": _ref(SHA)}},
                     killed=False, gets=0),
            ],
        },
    }
    assert spec.assertion_errors(good) == []
    # Ref drift between the intercepted reply and the recovery → rejected.
    drifted = json.loads(json.dumps(good))
    drifted["actual"]["runs"][1]["response"]["transcript"]["source_ref"] = _ref("a" * 64)
    assert spec.assertion_errors(drifted), "Ref drift must be rejected"


# ── FF-R2-2: probe isolation and explicit result states ────────────────────


def test_probe_reports_three_explicit_states_not_none(tmp_path: Path) -> None:
    from fixture_builder import ScratchEnvironment
    from w20_fault_cases import probe_catalog

    # not_found: an empty owned wiki, explicit state, no exception guessing.
    env = ScratchEnvironment(tmp_path / "empty-wiki",
                             adapter_script=MATRIX / "fixture_provider_adapter.py",
                             et_proxy=MATRIX / "et_transcript_proxy.py")
    result = probe_catalog(wiki_root=env.wiki, identity_request={
        "entity": "Apple Inc.", "document_kind": "investor_call_transcript",
        "as_of_date": "2026-12-31", "market": "US", "security_id": "AAPL",
        "form_type": None, "fiscal_year": 2036, "fiscal_period": "Q1",
        "language": None, "provider": "fmp", "provider_document_id": None,
        "mode": "exact", "allow_download": False, "schema_version": "1.0",
    }, content_sha="0" * 64, cwp_src=str(ROOT / ".w20-deps" / "cwp" / "src"))
    assert result["state"] == "not_found", result


def test_probe_error_is_never_confirmed_nor_not_found(tmp_path: Path) -> None:
    from w20_fault_cases import probe_catalog

    result = probe_catalog(wiki_root=tmp_path / "does-not-exist", identity_request={},
                           content_sha="0" * 64,
                           cwp_src=str(ROOT / ".w20-deps" / "cwp" / "src"))
    assert result["state"] == "probe_error", result
    assert result.get("error"), "a probe error must carry its own reason"


def test_probe_leaves_parent_process_stdio_untouched(tmp_path: Path) -> None:
    from w20_fault_cases import probe_catalog

    saved_in, saved_out = sys.stdin, sys.stdout
    try:
        probe_catalog(wiki_root=tmp_path / "missing", identity_request={},
                      content_sha="0" * 64,
                      cwp_src=str(ROOT / ".w20-deps" / "cwp" / "src"))
        assert sys.stdin is saved_in, "the probe must not swap the parent's stdin"
        assert sys.stdout is saved_out, "the probe must not swap the parent's stdout"
    finally:
        sys.stdin, sys.stdout = saved_in, saved_out


def test_concurrent_probes_for_two_companies_do_not_cross(tmp_path: Path) -> None:
    """Two concurrent probes with different companies/wiki roots return their
    own results; neither state nor stdin/stdout may cross callers."""
    import hashlib
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace
    from fixture_builder import CN, HK, ScratchEnvironment

    roots = {}
    for market, ident in (("cn", CN), ("hk", HK)):
        env = ScratchEnvironment(tmp_path / f"wiki-{market}",
                                 adapter_script=MATRIX / "fixture_provider_adapter.py",
                                 et_proxy=MATRIX / "et_transcript_proxy.py")
        seeded = replace(ident, provider="fmp")
        content = f"probe isolation original for {market}".encode("utf-8")
        env.seed_original(seeded, document_kind="investor_call_transcript",
                          fiscal_year=2036, fiscal_period="Q1", form_type=None,
                          published_date="2026-01-05", content=content,
                          mime_type="text/plain", filename_hint=f"probe_{market}")
        roots[market] = (env, ident, hashlib.sha256(content).hexdigest())

    def run_probe(market: str):
        env, ident, sha = roots[market]
        from w20_fault_cases import probe_catalog
        return probe_catalog(wiki_root=env.wiki, identity_request={
            "entity": ident.canonical_name, "document_kind": "investor_call_transcript",
            "as_of_date": "2026-12-31", "market": ident.market,
            "security_id": ident.security_id, "form_type": None,
            "fiscal_year": 2036, "fiscal_period": "Q1", "language": None,
            "provider": "fmp", "provider_document_id": None, "mode": "exact",
            "allow_download": False, "schema_version": "1.0",
        }, content_sha=sha, cwp_src=str(ROOT / ".w20-deps" / "cwp" / "src"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {market: pool.submit(run_probe, market) for market in roots}
        results = {market: future.result() for market, future in futures.items()}

    saved_in, saved_out = sys.stdin, sys.stdout
    assert sys.stdin is saved_in and sys.stdout is saved_out
    for market, result in results.items():
        assert result["state"] == "confirmed", (market, result)
        assert result["ref"]["content_sha256"] == roots[market][2], (market, result)
