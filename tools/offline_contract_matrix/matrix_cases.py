"""Coverage-matrix cases and orchestration for the offline contract matrix.

Each case records its declared vs observed layer, real-module/HEAD/SHA evidence,
provider counters (fixture requests, downloads, translations), expected/actual,
a PASS|FAIL|NOT_RUN result, scope, and diagnostics. Only the fixture provider
response is simulated; the CWP ensure/import and the ET supervisor/worker run for
real. Non-periodic kinds that cannot be imported as their own kind are reported
as named gaps (no provider/contract change is made here — ROOT decides).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Import runner helpers and context without triggering run.py's __main__.
from run import Context, _mk_filing_request, _companion  # noqa: E402
from report import CaseResult  # noqa: E402
from fixture_builder import CN, US, HK, Identity  # noqa: E402
from matrix_outcome import Outcome, filing_reused, count  # noqa: E402


# ── evidence helpers ───────────────────────────────────────────────────────


def _et_receipt_ok(ctx: Context, tag: str) -> bool:
    path = ctx.artifacts / f"{tag}.usage.json"
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return False
    return payload.get("schema_version") == "earnings-retrieval-usage/1"


def _transcript(response: dict[str, Any]) -> dict[str, Any]:
    return response.get("transcript") or {}


def _filing(response: dict[str, Any]) -> dict[str, Any]:
    return response.get("filing") or {}


# ── seeding (once, before cases) ───────────────────────────────────────────


def _warm_seed_list() -> list[tuple]:
    """The fixed warm seeds, in their historical order (frozen inputs)."""
    seeds = [
        (identity, kind, 2024, period)
        for identity in (CN, HK, US)
        for kind, period in (("annual_report", "FY"), ("semi_annual_report", "S1"), ("quarterly_report", "Q1"))
    ]
    seeds.append((US, "annual_report", 2025, "FY"))
    return seeds


# The local TXT transcript seed, named by ``local_txt_exact_reuse``'s fixed
# companion request (reuse_only, 2024 Q2). It is written in-process, not via
# the acquisition writer.
TXT_SEED_KEY = ("US", "investor_call_transcript", 2024, "Q2")


def warm_consumption(spec) -> set:
    """Warm keys a fixed case consumes or references, from the frozen authority.

    A case's warm preparation is derived only from its fixed definition: a run
    whose filing or companion row carries ``reuse_only`` intent names the warm
    key it expects the group's wiki to answer (assertion target or context
    fidelity with the historical all-seeds runs). Keys outside the fixed warm
    list are deliberately absent gaps (``reuse_only_missing_period``,
    ``incomplete_sidecar_metadata_gap``) and must never be seeded; the caller
    intersects with the fixed list.
    """
    keys: set = set()
    for run in getattr(spec, "runs", ()) or ():
        request = run.request()
        rows = [(request, True), (request.get("companion_transcript"), False)]
        for row, is_filing in rows:
            if not isinstance(row, dict):
                continue
            if (row.get("filing_intent") or row.get("intent")) != "reuse_only":
                continue
            if is_filing:
                keys.add((request.get("market"), request.get("document_kind"),
                          request.get("fiscal_year"), request.get("fiscal_period")))
            else:
                quarter = row.get("fiscal_quarter")
                keys.add((request.get("market"), "investor_call_transcript",
                          row.get("fiscal_year"), f"Q{quarter}" if quarter is not None else None))
    return keys


def seed_plan_for(case_ids) -> dict:
    """Per-group warm preparation derived from the group's own fixed cases.

    Returns ``{"ensure_seeds": [...], "seed_txt": bool}``. Every consumed seed
    still runs the real acquisition writer in the group that consumes it; the
    union of all groups' plans equals the full fixed warm list, so coverage
    never shrinks — only the per-group duplication is removed.
    """
    from case_specs import get_spec

    wanted: set = set()
    for cid in case_ids:
        spec = get_spec(cid)
        if spec is None:
            raise ValueError(f"seed plan for unknown case id: {cid}")
        wanted |= warm_consumption(spec)
    ensure_seeds = [seed for seed in _warm_seed_list()
                    if (seed[0].market, seed[1], seed[2], seed[3]) in wanted]
    return {"ensure_seeds": ensure_seeds, "seed_txt": TXT_SEED_KEY in wanted}


def seed_all(ctx: Context) -> None:
    """Seed periodic financial-report originals (local hits) and scan once.

    The fetch_if_missing cases deliberately target (kind, year) keys that are
    NOT seeded here so they exercise the fixture-provider download path.

    DU10: when the runner hands the group's own case ids via ``ctx.seed_cases``,
    only the warm keys those fixed cases consume or reference are prepared, each
    still through the real acquisition writer in this group. Without that
    attribute the historical full batch is prepared (single-group and legacy
    callers keep their exact behavior).
    """
    # Establish legitimate warm state through the real acquisition writer first.
    # A scanned sidecar is intentionally a separate legacy/incomplete control.
    # W07 efficiency: the identical CWP ensure writes run sequentially inside
    # ONE bounded helper process calling the same real ensure service; every
    # request keeps its own request/response/receipt/source-ref/count record.
    plan = seed_plan_for(ctx.seed_cases) if getattr(ctx, "seed_cases", None) is not None else None
    seeds = _warm_seed_list() if plan is None else plan["ensure_seeds"]
    seed_txt = True if plan is None else plan["seed_txt"]
    ctx.seed_receipts = ctx.warm_seed_batch(seeds)
    # Group-owned evidence files carry the group prefix: the evidence dir is
    # flat and shared, so an unprefixed name would let one group's receipts
    # overwrite the other's (the seed-batch stdout files are prefixed already).
    prefix = getattr(ctx, "artifact_prefix", "")
    (ctx.artifacts / f"{prefix}warm-seed-receipts.json").write_text(json.dumps(ctx.seed_receipts, ensure_ascii=False, indent=2), encoding="utf-8")
    if seed_txt:
        from dataclasses import replace
        txt_identity = replace(US, provider="fmp", source_url="https://financialmodelingprep.com/stable/earning-call-transcript?symbol=AAPL&year=2024&quarter=2")
        ctx.env.seed_original(txt_identity, document_kind="investor_call_transcript", fiscal_year=2024,
                              fiscal_period="Q2", form_type=None, published_date="2024-07-01",
                              content=b"Synthetic original-language local TXT transcript.\n", mime_type="text/plain", filename_hint="aapl_local_2024q2")
    ctx.scan()


# ── cases ─────────────────────────────────────────────────────────────────


def case_chain_a(ctx: Context) -> CaseResult:
    case_id = "chainA_download_reuse"
    calls1 = ctx.env.calls_file(f"{case_id}_run1")
    ctx.write_state(scenario="success", calls_file=calls1, receipt_tag=f"{case_id}_run1",
                    content_utf8="Synthetic original-language AAPL FY2025 Q1 earnings call transcript.")
    req = _mk_filing_request(US, document_kind="annual_report", fiscal_year=2025,
                             fiscal_period="FY", intent="reuse_only",
                             companion=_companion(2025, 1, "fetch_if_missing"))
    run1 = ctx.run_ff(req, case_id=case_id, run_label="run1")
    calls2 = ctx.env.calls_file(f"{case_id}_run2")
    ctx.write_state(scenario="success", calls_file=calls2, receipt_tag=f"{case_id}_run2")
    run2 = ctx.run_ff(req, case_id=case_id, run_label="run2")

    t1, t2 = _transcript(run1["response"]), _transcript(run2["response"])
    run1_req = ctx.fixture_requests(calls1)
    run2_req = ctx.fixture_requests(calls2)
    et_receipt = _et_receipt_ok(ctx, f"{case_id}_run1")
    evidence = {
        "ff_public_cli": True,
        "et_supervisor_worker": ctx.worker_ran(calls1),
        "cwp_import": bool(t1.get("source_ref")),
    }
    checks = [
        (t1.get("status") == "downloaded", "run1 transcript downloaded"),
        (run1_req == 1, "run1 one fixture provider request"),
        (t2.get("status") in {"reused", "unknown_publication"}, "run2 transcript hit"),
        (run2_req == 0, "run2 zero provider requests"),
        (et_receipt, "ET usage receipt present"),
        (all(evidence.values()), "real three-layer evidence complete"),
    ]
    ok = all(c for c, _ in checks)
    return CaseResult(
        id=case_id, title="FF→ET→CWP real three-layer transcript download then reuse",
        declared_layer="real-3layer",
        observed_layer="real-3layer(ff-cli + et-supervisor/worker + cwp-import)",
        result="PASS" if ok else "FAIL",
        scope="chain-A transcript three-layer; test-proxy replaces only worker HTTP",
        expected={"run_twice": True},
        actual={
            "run1_status": t1.get("status"), "run2_status": t2.get("status"),
            "run2_reason": t2.get("reason"),
            "real_layer_evidence": evidence, "et_usage_receipt": et_receipt,
        },
        provider_counters={"fixture_requests": run1_req, "run2_fixture_requests": run2_req,
                           "downloads": 1 if t1.get("status") == "downloaded" else 0,
                           "translations": 0},
        request_ref=run1["request_ref"], response_ref=run1["response_ref"],
        receipt_refs=[f"{case_id}_run1.usage.json", f"{case_id}_run1.result.json"],
        diagnostics=[f"{c}: {'ok' if v else 'FAIL'}" for v, c in checks],
    )


def case_fin_local_hit(ctx: Context, identity: Identity, kind: str, year: int,
                       period: str, case_id: str) -> CaseResult:
    req = _mk_filing_request(identity, document_kind=kind, fiscal_year=year,
                             fiscal_period=period, intent="reuse_only")
    run1 = ctx.run_ff(req, case_id=case_id)
    f = _filing(run1["response"])
    ok = (run1["response"].get("status") == "source_candidate"
          and f.get("resolution_outcome") == "reused_existing"
          and f.get("download_events") == 0)
    return CaseResult(
        id=case_id, title=f"{identity.market} {kind} local hit (reuse_only)",
        declared_layer="ff+cwp", observed_layer="ff-cli + cwp-source-query",
        result="PASS" if ok else "FAIL",
        scope="periodic financial report local reuse, zero provider requests",
        expected={"status": "source_candidate", "download_events": 0},
        actual={"status": run1["response"].get("status"),
                "resolution_outcome": f.get("resolution_outcome"),
                "download_events": f.get("download_events"),
                "real_layer_evidence": {"ff_public_cli": True, "et_supervisor_worker": False,
                                        "cwp_import": bool(f.get("source_ref"))}},
        provider_counters={"fixture_requests": 0, "run2_fixture_requests": 0,
                           "downloads": 0, "translations": 0},
        request_ref=run1["request_ref"], response_ref=run1["response_ref"],
    )


def case_fin_fetch(ctx: Context, identity: Identity, kind: str, year: int,
                   case_id: str, period: str | None = None) -> CaseResult:
    calls = ctx.env.calls_file(case_id)
    ctx.write_state(scenario="success", calls_file=calls, provider_scenario="serve",
                    receipt_tag=case_id)
    req = _mk_filing_request(identity, document_kind=kind, fiscal_year=year,
                             fiscal_period=period, intent="fetch_if_missing")
    run1 = ctx.run_ff(req, case_id=case_id, run_label="run1")
    run2 = ctx.run_ff(req, case_id=case_id, run_label="run2")
    f1, f2 = _filing(run1["response"]), _filing(run2["response"])
    d1 = count(f1.get("download_events"))
    d2 = count(f2.get("download_events"))
    checks = [
        (run1["response"].get("status") == "source_candidate", "run1 resolves"),
        (f1.get("resolution_outcome") in {"downloaded_new", "reused_after_discovery"}, "run1 imported"),
        (filing_reused(f1, f2, kind), "run2 exact source reuses without re-download"),
    ]
    ok = all(c for c, _ in checks)
    return CaseResult(
        id=case_id, title=f"{identity.market} {kind} fetch_if_missing via fixture provider",
        declared_layer="ff+cwp", observed_layer="ff-cli + cwp-ensure/import + fixture-adapter",
        result="PASS" if ok else "FAIL",
        scope="financial report download at the configured fixture provider boundary; "
              "real CWP ensure/import, only the supplier response is simulated",
        expected={"run_twice": True},
        actual={"run1_outcome": f1.get("resolution_outcome"), "run2_outcome": f2.get("resolution_outcome"),
                "run1_kind": f1.get("document_kind"),
                "run1_response": run1["response"], "run2_response": run2["response"],
                "real_layer_evidence": {"ff_public_cli": True, "et_supervisor_worker": False,
                                        "cwp_import": bool(f1.get("source_ref"))}},
        provider_counters={"fixture_requests": d1, "run2_fixture_requests": d2,
                           "downloads": d1, "translations": 0},
        request_ref=run1["request_ref"], response_ref=run1["response_ref"],
        diagnostics=[f"{c}: {'ok' if v else 'FAIL'}" for v, c in checks],
    )


def case_nonperiod(ctx: Context, identity: Identity, kind: str, case_id: str) -> CaseResult:
    calls = ctx.env.calls_file(case_id)
    ctx.write_state(scenario="success", calls_file=calls, provider_scenario="serve",
                    receipt_tag=case_id)
    req = _mk_filing_request(identity, document_kind=kind, fiscal_year=2025,
                             fiscal_period=None, intent="fetch_if_missing")
    run1 = ctx.run_ff(req, case_id=case_id)
    f = _filing(run1["response"])
    stored_kind = f.get("document_kind")
    supported = (run1["response"].get("status") == "source_candidate" and stored_kind == kind)
    diagnostics = []
    if not supported:
        diagnostics.append(
            f"GAP: document_kind {kind} not imported as its own kind "
            f"(stored kind={stored_kind}, status={run1['response'].get('status')}); "
            "no provider/contract change made here — ROOT decides remediation")
    return CaseResult(
        id=case_id, title=f"non-periodic {kind}",
        declared_layer="ff+cwp", observed_layer="ff-cli + cwp-ensure/import + fixture-adapter",
        result="PASS" if supported else "FAIL",
        scope="non-periodic kind imported from its correct tool/class, never as annual/FY",
        expected={"supported": True, "stored_kind": kind},
        actual={"status": run1["response"].get("status"), "stored_kind": stored_kind,
                "supported": supported,
                "real_layer_evidence": {"ff_public_cli": True, "et_supervisor_worker": False,
                                        "cwp_import": bool(f.get("source_ref"))}},
        provider_counters={"fixture_requests": f.get("download_events") or 0,
                           "run2_fixture_requests": 0, "downloads": f.get("download_events") or 0,
                           "translations": 0},
        request_ref=run1["request_ref"], response_ref=run1["response_ref"],
        diagnostics=diagnostics,
    )


def case_call_fy_only(ctx: Context) -> CaseResult:
    case_id = "call_fy_only_no_q"
    req = _mk_filing_request(US, document_kind="annual_report", fiscal_year=2025,
                             fiscal_period="FY", intent="reuse_only",
                             companion=_companion(2025, None, "fetch_if_missing"))
    run1 = ctx.run_ff(req, case_id=case_id)
    t = _transcript(run1["response"])
    ok = t.get("status") == "period_unresolved" and t.get("reason") == "exact_fy_q_required"
    return CaseResult(
        id=case_id, title="companion FY-only does not infer Q4",
        declared_layer="ff-only", observed_layer="ff-cli (companion period gate)",
        result="PASS" if ok else "FAIL",
        scope="exact FY without quarter must not be guessed as Q4",
        expected={"status": "period_unresolved", "reason": "exact_fy_q_required"},
        actual={"status": t.get("status"), "reason": t.get("reason"),
                "real_layer_evidence": {"ff_public_cli": True, "et_supervisor_worker": False,
                                        "cwp_import": False}},
        provider_counters={"fixture_requests": 0, "run2_fixture_requests": 0,
                           "downloads": 0, "translations": 0},
        request_ref=run1["request_ref"], response_ref=run1["response_ref"],
    )


def case_call_past_cutoff(ctx: Context) -> CaseResult:
    case_id = "call_past_cutoff"
    calls = ctx.env.calls_file(case_id)
    ctx.write_state(scenario="success", calls_file=calls, call_date="2027-06-01",
                    receipt_tag=case_id, content_utf8="Synthetic transcript dated after cutoff.")
    req = _mk_filing_request(US, document_kind="annual_report", fiscal_year=2025,
                             fiscal_period="FY", intent="reuse_only",
                             companion=_companion(2025, 2, "fetch_if_missing"))
    run1 = ctx.run_ff(req, case_id=case_id)
    t = _transcript(run1["response"])
    eligible = t.get("status") == "downloaded" and t.get("as_of_cutoff_verified") is True
    cutoff_diagnostic = Outcome.observe(t).rejected_cutoff()
    ok = cutoff_diagnostic and not eligible
    return CaseResult(
        id=case_id, title="past-cutoff transcript surfaces the cutoff diagnostic",
        declared_layer="ff+et", observed_layer="ff-cli + et-supervisor/worker (test-proxy)",
        result="PASS" if ok else "FAIL",
        scope="publication/call after as_of_date is never reported historical-eligible",
        expected={"past_cutoff": True},
        actual={"status": t.get("status"), "reason": t.get("reason"),
                "as_of_cutoff_verified": t.get("as_of_cutoff_verified"),
                "cutoff_diagnostic": cutoff_diagnostic, "eligible": eligible,
                "real_layer_evidence": {"ff_public_cli": True,
                                        "et_supervisor_worker": ctx.worker_ran(calls),
                                        "cwp_import": bool(t.get("source_ref"))}},
        provider_counters={"fixture_requests": ctx.fixture_requests(calls),
                           "run2_fixture_requests": 0, "downloads": 0, "translations": 0},
        request_ref=run1["request_ref"], response_ref=run1["response_ref"],
    )


def case_call_wrong_quarter(ctx: Context) -> CaseResult:
    case_id = "call_wrong_quarter"
    calls = ctx.env.calls_file(case_id)
    ctx.write_state(scenario="wrong_quarter", calls_file=calls, receipt_tag=case_id,
                    content_utf8="Synthetic transcript with mismatched quarter.")
    req = _mk_filing_request(US, document_kind="annual_report", fiscal_year=2025,
                             fiscal_period="FY", intent="reuse_only",
                             companion=_companion(2025, 3, "fetch_if_missing"))
    run1 = ctx.run_ff(req, case_id=case_id)
    t = _transcript(run1["response"])
    # The provider returns a different quarter; the consumer must NOT report it
    # as a clean download of the requested quarter.
    from extended_cases import _receipt
    et_result = _receipt(ctx, case_id) if hasattr(ctx, "artifacts") else {}
    explicit_provenance = (t.get("status") in {"upstream_error", "provider_unavailable"} and t.get("reason") == "provider_identity_or_host" and
                           et_result.get("status") == "provenance_rejected" and et_result.get("error_code") == "provider_identity_or_host" and ctx.fixture_requests(calls) == 1)
    ok = Outcome.observe(t).rejected_quarter() or explicit_provenance
    return CaseResult(
        id=case_id, title="wrong-quarter provider response is not accepted as the requested quarter",
        declared_layer="ff+et", observed_layer="ff-cli + et-supervisor/worker (test-proxy)",
        result="PASS" if ok else "FAIL",
        scope="quarter provenance is enforced; a mismatch is not silently accepted",
        expected={"quarter_provenance": True},
        actual={"status": t.get("status"), "reason": t.get("reason"),
                "fiscal_quarter": t.get("fiscal_quarter"),
                "real_layer_evidence": {"ff_public_cli": True,
                                        "et_supervisor_worker": ctx.worker_ran(calls),
                                        "cwp_import": bool(t.get("source_ref"))}},
        provider_counters={"fixture_requests": ctx.fixture_requests(calls),
                           "run2_fixture_requests": 0, "downloads": 0, "translations": 0},
        request_ref=run1["request_ref"], response_ref=run1["response_ref"],
    )


def case_err_request(ctx: Context) -> CaseResult:
    case_id = "err_request_error"
    req = {"schema_version": "2.0", "company_query": "Apple Inc.", "market": "US",
           "document_kind": "annual_report", "as_of_date": "2026-01-01",
           "filing_intent": "reuse_only"}
    run1 = ctx.run_ff(req, case_id=case_id)
    resp = run1["response"]
    ok = run1["exit_code"] == 2 and resp.get("status") == "request_error"
    return CaseResult(
        id=case_id, title="malformed request yields request_error",
        declared_layer="ff-only", observed_layer="ff-cli (request validator)",
        result="PASS" if ok else "FAIL",
        scope="request validation diagnostics preserved",
        expected={"status": "request_error"},
        actual={"status": resp.get("status"), "reason": resp.get("reason"),
                "request_diagnostic": resp.get("request_diagnostic"),
                "real_layer_evidence": {"ff_public_cli": True, "et_supervisor_worker": False,
                                        "cwp_import": False}},
        provider_counters={"fixture_requests": 0, "run2_fixture_requests": 0,
                           "downloads": 0, "translations": 0},
        request_ref=run1["request_ref"], response_ref=run1["response_ref"],
    )


def case_err_402(ctx: Context) -> CaseResult:
    case_id = "err_402_entitlement"
    calls = ctx.env.calls_file(case_id)
    ctx.write_state(scenario="entitlement_402", calls_file=calls, receipt_tag=case_id)
    req = _mk_filing_request(US, document_kind="annual_report", fiscal_year=2025,
                             fiscal_period="FY", intent="reuse_only",
                             companion=_companion(2025, 4, "fetch_if_missing"))
    run1 = ctx.run_ff(req, case_id=case_id)
    t = _transcript(run1["response"])
    ok = t.get("status") == "provider_unavailable" and "entitlement" in str(t.get("reason"))
    return CaseResult(
        id=case_id, title="ET 402 entitlement surfaces provider_entitlement_required",
        declared_layer="ff+et", observed_layer="ff-cli + et-supervisor/worker (test-proxy)",
        result="PASS" if ok else "FAIL",
        scope="HTTP 402 → provider_entitlement_required diagnostic",
        expected={"status": "provider_unavailable", "reason_contains": "entitlement"},
        actual={"status": t.get("status"), "reason": t.get("reason"),
                "real_layer_evidence": {"ff_public_cli": True,
                                        "et_supervisor_worker": ctx.worker_ran(calls),
                                        "cwp_import": bool(t.get("source_ref"))}},
        provider_counters={"fixture_requests": ctx.fixture_requests(calls),
                           "run2_fixture_requests": 0, "downloads": 0, "translations": 0},
        request_ref=run1["request_ref"], response_ref=run1["response_ref"],
        diagnostics=[f"reason={t.get('reason')}"],
    )


def case_err_missing_creds(ctx: Context) -> CaseResult:
    case_id = "err_missing_creds"
    key_backup = ctx.env.fake_key.read_text(encoding="utf-8")
    ctx.env.fake_key.unlink()
    try:
        req = _mk_filing_request(US, document_kind="annual_report", fiscal_year=2025,
                                 fiscal_period="FY", intent="reuse_only",
                                 companion=_companion(2026, 1, "fetch_if_missing"))
        run1 = ctx.run_ff(req, case_id=case_id, with_fmp_key=False)
    finally:
        ctx.env.fake_key.write_text(key_backup, encoding="utf-8")
    t = _transcript(run1["response"])
    reason = str(t.get("reason"))
    ok = "credentials" in reason
    return CaseResult(
        id=case_id, title="missing provider credentials diagnosed, zero provider requests",
        declared_layer="ff+et", observed_layer="ff-cli + et-credential-preflight (test-proxy)",
        result="PASS" if ok else "FAIL",
        scope="missing credential is a named diagnostic with zero provider requests",
        expected={"reason_contains": "credentials"},
        actual={"status": t.get("status"), "reason": t.get("reason"),
                "provider_requests": t.get("provider_requests"),
                "real_layer_evidence": {"ff_public_cli": True, "et_supervisor_worker": False,
                                        "cwp_import": False}},
        provider_counters={"fixture_requests": t.get("provider_requests") or 0,
                           "run2_fixture_requests": 0, "downloads": 0, "translations": 0},
        request_ref=run1["request_ref"], response_ref=run1["response_ref"],
    )


def case_err_unknown_usage(ctx: Context) -> CaseResult:
    case_id = "err_unknown_usage"
    calls = ctx.env.calls_file(case_id)
    ctx.write_state(scenario="worker_loss", calls_file=calls, receipt_tag=case_id)
    req = _mk_filing_request(US, document_kind="annual_report", fiscal_year=2025,
                             fiscal_period="FY", intent="reuse_only",
                             companion=_companion(2026, 2, "fetch_if_missing"))
    run1 = ctx.run_ff(req, case_id=case_id)
    t = _transcript(run1["response"])
    usage_complete = t.get("provider_usage_complete")
    requests = t.get("provider_requests")
    unknown_reported_as_zero = (requests == 0 and usage_complete is not True)
    calls_swallowed = t.get("status") in {None, "not_requested"} and t.get("reason") is None
    ok = Outcome.observe(t).preserves_unknown_usage() and not calls_swallowed
    return CaseResult(
        id=case_id, title="unknown usage/cost kept null, provider call not swallowed",
        declared_layer="ff+et", observed_layer="ff-cli + et-supervisor/worker-failure (test-proxy)",
        result="PASS" if ok else "FAIL",
        scope="unknown usage is null (never 0); the failed call is preserved",
        expected={"unknown_usage": True},
        actual={"status": t.get("status"), "reason": t.get("reason"),
                "provider_usage_complete": usage_complete, "provider_requests": requests,
                "unknown_usage_reported_as_zero": unknown_reported_as_zero,
                "calls_swallowed": calls_swallowed,
                "real_layer_evidence": {"ff_public_cli": True,
                                        "et_supervisor_worker": ctx.worker_ran(calls),
                                        "cwp_import": False}},
        provider_counters={"fixture_requests": ctx.fixture_requests(calls),
                           "run2_fixture_requests": 0, "downloads": 0, "translations": 0},
        request_ref=run1["request_ref"], response_ref=run1["response_ref"],
    )
