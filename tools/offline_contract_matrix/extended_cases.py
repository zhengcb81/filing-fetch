"""Required offline negative boundaries and exact local transcript reuse."""
from __future__ import annotations
import json
from report import CaseResult
from fixture_builder import US, CN
from run import _mk_filing_request, _companion
from matrix_outcome import source_ref


def _receipt(ctx, tag):
    path = ctx.artifacts / f"{tag}.result.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def transcript_negative(ctx, scenario, case_id, expected_reasons, *, year=2028, quarter=1, max_bytes=1000000, seconds=5):
    calls = ctx.env.calls_file(case_id)
    ctx.write_state(scenario=scenario, calls_file=calls, receipt_tag=case_id,
                    response_bytes=2000 if scenario == "oversize" else 512)
    req = _mk_filing_request(US, document_kind="annual_report", fiscal_year=2025,
                            fiscal_period="FY", intent="reuse_only",
                            companion=_companion(year, quarter, "fetch_if_missing",
                            {"max_bytes":max_bytes, "timeout_seconds":seconds, "max_cost_usd":"0"}))
    result = ctx.run_ff(req, case_id=case_id)
    t = result["response"].get("transcript") or {}
    receipt = _receipt(ctx, case_id)
    ok = (t.get("status") not in {None, "downloaded", "reused", "unknown_publication"}
          and t.get("reason") in expected_reasons and source_ref(t.get("source_ref")) is None
          and ctx.fixture_requests(calls) == 1 and bool(receipt))
    cleanup = not any(ctx.env.et_temp_root().iterdir())
    return CaseResult(id=case_id, title=f"transcript {scenario} rejects source and cleans worker", declared_layer="ff+et",
        result="PASS" if ok and cleanup else "FAIL", scope="real FF+ET runtime; fixture session only",
        expected={"reasons":sorted(expected_reasons), "rejected_source":True},
        actual={"status":t.get("status"), "reason":t.get("reason"), "worker_cleanup":cleanup, "et_result":receipt},
        provider_counters={"fixture_requests":ctx.fixture_requests(calls)}, request_ref=result["request_ref"], response_ref=result["response_ref"])


def case_failure_then_retry(ctx):
    cid = "request_after_failure_retry"
    first = transcript_negative(ctx, "request_failure", cid, {"provider_response", "unexpected_provider_failure"}, year=2029, quarter=1)
    calls = ctx.env.calls_file(cid + "_retry")
    ctx.write_state(scenario="success", calls_file=calls, receipt_tag=cid + "_retry", content_utf8="Synthetic retry original content.")
    req = _mk_filing_request(US, document_kind="annual_report", fiscal_year=2025, fiscal_period="FY", intent="reuse_only", companion=_companion(2029, 1, "fetch_if_missing"))
    second = ctx.run_ff(req, case_id=cid, run_label="retry")
    t = second["response"].get("transcript") or {}
    first.result = "PASS" if first.result == "PASS" and t.get("status") == "downloaded" and source_ref(t.get("source_ref")) and ctx.fixture_requests(calls) == 1 else "FAIL"
    first.actual["retry_status"] = t.get("status")
    first.actual["retry_fixture_requests"] = ctx.fixture_requests(calls)
    first.id = cid
    return first


def case_local_txt(ctx):
    cid = "local_txt_exact_reuse"
    calls = ctx.env.calls_file(cid)
    ctx.write_state(scenario="worker_loss", calls_file=calls, receipt_tag=cid)
    req = _mk_filing_request(US, document_kind="annual_report", fiscal_year=2025, fiscal_period="FY", intent="reuse_only", companion=_companion(2024, 2, "reuse_only"))
    result = ctx.run_ff(req, case_id=cid)
    t = result["response"].get("transcript") or {}
    ref = source_ref(t.get("source_ref"))
    ok = t.get("status") in {"reused", "unknown_publication"} and ref and ref["mime_type"] == "text/plain" and ctx.fixture_requests(calls) == 0
    return CaseResult(id=cid, title="existing original-language TXT exact-period reuse", declared_layer="ff+cwp", result="PASS" if ok else "PARTIAL",
        scope="local synthetic TXT; no proxy retrieval permitted", expected={"local_txt_reused":True},
        actual={"status":t.get("status"), "reason":t.get("reason"), "source_ref":ref},
        provider_counters={"fixture_requests":ctx.fixture_requests(calls)}, request_ref=result["request_ref"], response_ref=result["response_ref"])


def case_reuse_only_gap(ctx):
    cid = "reuse_only_missing_period"
    calls = ctx.env.calls_file(cid)
    ctx.write_state(scenario="worker_loss", calls_file=calls, receipt_tag=cid)
    req = _mk_filing_request(CN, document_kind="annual_report", fiscal_year=2030, fiscal_period="FY", intent="reuse_only")
    result = ctx.run_ff(req, case_id=cid)
    f = result["response"].get("filing") or {}
    ok = result["response"].get("status") != "source_candidate" and not source_ref(f.get("source_ref")) and ctx.fixture_requests(calls) == 0
    return CaseResult(id=cid, title="reuse_only gap does not discover/download", declared_layer="ff+cwp", result="PASS" if ok else "FAIL",
        scope="missing exact period must stay a gap", expected={"no_acquisition":True}, actual={"response":result["response"]},
        provider_counters={"fixture_requests":ctx.fixture_requests(calls)}, request_ref=result["request_ref"], response_ref=result["response_ref"])


def filing_negative(ctx, scenario, cid):
    ctx.write_state(scenario="success", provider_scenario=scenario, calls_file=ctx.env.calls_file(cid), receipt_tag=cid)
    limits = {"max_bytes":50 if scenario == "oversize" else 2000000, "timeout_seconds":5, "max_cost_usd":"0"}
    req = _mk_filing_request(CN, document_kind="prospectus", fiscal_year=2031, fiscal_period=None, intent="fetch_if_missing", limits=limits)
    run = ctx.run_ff(req, case_id=cid)
    f = run["response"].get("filing") or {}
    # A schema/config failure is not evidence that the staged original was checked.
    logs = ctx.adapter_records()
    attempted = any(row.get("receipt_tag") == cid and row.get("action") == "fetch" for row in logs)
    rejected = run["response"].get("status") != "source_candidate" and not source_ref(f.get("source_ref"))
    return CaseResult(id=cid, title=f"CWP original {scenario} validation", declared_layer="ff+cwp", result="PASS" if attempted and rejected else "PARTIAL" if not attempted else "FAIL",
        scope="fixture supplier bytes; actual CWP ingestion", expected={"supplier_fetch_attempted":True, "invalid_original_rejected":True},
        actual={"attempted":attempted, "response":run["response"]}, provider_counters={"fixture_requests":sum(row.get("receipt_tag") == cid for row in logs)}, request_ref=run["request_ref"], response_ref=run["response_ref"])


def case_unverified_sidecar(ctx):
    cid = "incomplete_sidecar_metadata_gap"
    from fixture_builder import make_valid_pdf
    original = ctx.env.seed_original(CN, document_kind="annual_report", fiscal_year=2032, fiscal_period="FY", form_type=None,
                          published_date="2033-03-14", content=make_valid_pdf("Synthetic CATL 300750 annual 2032"),
                          mime_type="application/pdf", filename_hint="unverified_catl_2032")
    sidecar = original.with_name(original.name + ".source.json")
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    metadata.pop("published_date")
    metadata.pop("fiscal_period")
    sidecar.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    ctx.scan()
    req = _mk_filing_request(CN, document_kind="annual_report", fiscal_year=2032, fiscal_period="FY", intent="reuse_only", as_of_date="2033-12-31")
    run = ctx.run_ff(req, case_id=cid)
    f = run["response"].get("filing") or {}
    ok = run["response"].get("status") != "source_candidate" and f.get("upstream_cause", {}).get("code") == "local_metadata_gap"
    return CaseResult(id=cid, title="incomplete scanned sidecar is a diagnosed local metadata gap", declared_layer="ff+cwp", result="PASS" if ok else "FAIL",
        scope="explicit legacy/unverified fixture; not interchangeable with importer-verified warm state", expected={"diagnosed_gap":True},
        actual={"response":run["response"]}, request_ref=run["request_ref"], response_ref=run["response_ref"])
