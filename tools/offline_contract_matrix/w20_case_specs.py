"""W20 supplemental fault/recovery case authority (interruption counter-evidence).

These cases extend the fixed base matrix with behavioural counter-evidence for
download/import/receipt interruption (W20-FF-REPLAY). They are a *supplemental
suite*: they never join the 41 required cases, never shrink the base authority
and are only executed through the generic explicit ``--cases`` selection. The
base ``case_specs`` registry is not modified.

Every interruption is injected at a test boundary the harness already owns
(the ET test-proxy result/usage stream, or killing the real FF child process
tree); no product failpoint, environment backdoor or provider change exists.
Recovery is observed through the real CWP query/import path only.
"""

from dataclasses import dataclass
import json

from case_specs import CaseSpec, _companion, _fixture, _request, _run
from fixture_builder import CN, HK

AUTHORITY_VERSION = "w20-supplemental/1"
SUITE = "w20-supplemental"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class W20CaseSpec(CaseSpec):
    """A supplemental case: same frozen shape, its own assertion authority."""

    suite: str = SUITE

    def assertion_errors(self, case):
        return w20_assertion_errors(self, case)


def _spec(cid, handler, args, runs):
    meta = W20_METADATA[cid]
    return W20CaseSpec(
        cid,
        handler,
        _json(args),
        tuple(runs),
        meta["declared_layer"],
        meta["scope"],
        _json(meta["expected"]),
    )


_CALL_LIMITS = {"max_bytes": 1000000, "timeout_seconds": 12, "max_cost_usd": "0"}
_FILING_LIMITS = {"max_bytes": 2000000, "timeout_seconds": 20, "max_cost_usd": "0"}


def _call_request(year, quarter, *, limits=None):
    return _request(companion=_companion(year, quarter, limits=limits or _CALL_LIMITS))


def _filing_request(identity, kind, year, period=None):
    return _request(identity, kind=kind, year=year, period=period,
                    intent="fetch_if_missing", limits=_FILING_LIMITS)


def _three_run_fault(cid, handler, year, quarter, fault_scenario, content):
    """fault run → clean recovery run → pure reuse run, one fixed request."""
    request = _call_request(year, quarter)
    return _spec(cid, handler, [], [
        _run(request, _fixture(fault_scenario, content_utf8=content)),
        _run(request, _fixture(content_utf8=content)),
        _run(request, _fixture(content_utf8=content)),
    ])


def _two_run_fault(cid, handler, year, quarter, fault_scenario, content):
    """fault run → recovery run. A pure stream fault leaves nothing durable,
    so there is nothing to reuse; the durable-retry reuse proof lives in the
    interruption cases instead."""
    request = _call_request(year, quarter)
    return _spec(cid, handler, [], [
        _run(request, _fixture(fault_scenario, content_utf8=content)),
        _run(request, _fixture(content_utf8=content)),
    ])


def _build():
    rows = [
        _three_run_fault(
            "w20_call_kill_before_durable",
            "w20_fault_cases:case_call_kill_before_durable",
            2034, 1, "stall",
            "Synthetic W20 pre-durable interrupt transcript FY2034 Q1.",
        ),
        _three_run_fault(
            "w20_call_kill_after_import",
            "w20_fault_cases:case_call_kill_after_import",
            2034, 2, "success",
            "Synthetic W20 durable-interrupt transcript FY2034 Q2.",
        ),
        _three_run_fault(
            "w20_call_kill_after_durable",
            "w20_fault_cases:case_call_kill_after_durable",
            2036, 1, "success",
            "Synthetic W20 durable-interrupt transcript FY2036 Q1.",
        ),
        _two_run_fault(
            "w20_call_et_truncated",
            "w20_fault_cases:case_et_fault",
            2034, 3, "truncated_json",
            "Synthetic W20 truncated-result transcript FY2034 Q3.",
        ),
        _two_run_fault(
            "w20_call_et_exit_nonzero",
            "w20_fault_cases:case_et_fault",
            2034, 4, "crash_after_result",
            "Synthetic W20 exit-after-result transcript FY2034 Q4.",
        ),
        _three_run_fault(
            "w20_call_hash_lie",
            "w20_fault_cases:case_hash_lie",
            2035, 1, "hash_lie",
            "Synthetic W20 hash-lie transcript FY2035 Q1.",
        ),
    ]
    # Receipt binding: two independent downloads whose usage receipts are stale
    # (other request id) and truncated; the third run replays the first request.
    stale_req, trunc_req = _call_request(2035, 2), _call_request(2035, 3)
    rows.append(_spec(
        "w20_call_receipt_binding",
        "w20_fault_cases:case_receipt_binding",
        [],
        [
            _run(stale_req, _fixture("stale_usage",
                                     content_utf8="Synthetic W20 stale-receipt transcript FY2035 Q2.")),
            _run(trunc_req, _fixture("truncated_usage",
                                     content_utf8="Synthetic W20 truncated-receipt transcript FY2035 Q3.")),
            _run(stale_req, _fixture("stale_usage",
                                     content_utf8="Synthetic W20 stale-receipt transcript FY2035 Q2.")),
        ],
    ))
    # Same company/period requested by two concurrent FF processes, then a
    # sequential replay: three identical run vectors (run1a, run1b, reuse).
    concurrent_req = _call_request(2035, 4)
    rows.append(_spec(
        "w20_call_concurrent_same",
        "w20_fault_cases:case_concurrent_same",
        [],
        [
            _run(concurrent_req, _fixture(content_utf8="Synthetic W20 concurrent transcript FY2035 Q4.")),
            _run(concurrent_req, _fixture(content_utf8="Synthetic W20 concurrent transcript FY2035 Q4.")),
            _run(concurrent_req, _fixture(content_utf8="Synthetic W20 concurrent transcript FY2035 Q4.")),
        ],
    ))
    # Filing-side kill during the CWP import window (adapter fetch completed)
    # for a CN issuance document, then recovery and pure reuse.
    filing_req = _filing_request(CN, "prospectus", 2035)
    rows.append(_spec(
        "w20_filing_kill_recovery",
        "w20_fault_cases:case_filing_kill_recovery",
        [],
        [
            _run(filing_req, _fixture()),
            _run(filing_req, _fixture()),
            _run(filing_req, _fixture()),
        ],
    ))
    # Concurrent CN and HK annual reports for the same fiscal year: four run
    # vectors (CN, HK concurrent; then CN reuse, HK reuse).
    cn_req = _filing_request(CN, "annual_report", 2036, "FY")
    hk_req = _filing_request(HK, "annual_report", 2036, "FY")
    rows.append(_spec(
        "w20_filing_concurrent_cross_company",
        "w20_fault_cases:case_filing_concurrent_cross_company",
        [],
        [_run(cn_req, _fixture()), _run(hk_req, _fixture()),
         _run(cn_req, _fixture()), _run(hk_req, _fixture())],
    ))
    return tuple(rows)


W20_METADATA = {
    "w20_call_kill_before_durable": {
        "declared_layer": "ff+et",
        "scope": "real FF+ET chain; FF child tree killed while the provider GET "
                 "is in flight (pre-durable); recovery re-acquires exactly once "
                 "through the real CWP import, then reuses with zero requests",
        "expected": {"interruption": "pre_durable_kill", "recovery_downloads": 1,
                     "final_reuse_zero_requests": True},
    },
    "w20_call_kill_after_import": {
        "declared_layer": "ff+et",
        "scope": "real FF+ET chain; mid-import interruption observed: the FF "
                 "child tree is killed when THIS request's canonical original "
                 "bytes appear (request-bound trigger), the durable-or-not "
                 "state at kill is observed through the public CWP interface "
                 "and cross-checked against the recovery branch. This case is "
                 "explicitly NOT a durable-pass proxy; the strict post-durable "
                 "proof is w20_call_kill_after_durable",
        "expected": {"interruption_phase": "mid_import_observed",
                     "recovery_branch_observed": True},
    },
    "w20_call_kill_after_durable": {
        "declared_layer": "ff+et",
        "scope": "real FF+ET chain; deterministic post-durable interruption: "
                 "the kill fires only after THIS request's source is readable "
                 "back through CWP's public interfaces (public transcript "
                 "query + verified open) and hashes to this request's "
                 "content; an unrelated-period original is pre-placed on disk "
                 "as a control and can never fire the trigger. Recovery must "
                 "reuse with ZERO extra provider GETs and the same Ref/SHA; "
                 "the final replay reuses with zero GETs",
        "expected": {"interruption_phase": "post_durable",
                     "recovery_zero_requests": True},
    },
    "w20_call_et_truncated": {
        "declared_layer": "ff+et",
        "scope": "ET result stream truncated mid-JSON at the test-proxy "
                 "boundary; named failure, nothing durable (no reuse target "
                 "can exist), no blind replay, then one clean recovery "
                 "download",
        "expected": {"failure_reason": "provider_result_invalid", "recovery_downloads": 1},
    },
    "w20_call_et_exit_nonzero": {
        "declared_layer": "ff+et",
        "scope": "ET exits nonzero after emitting a complete result; named "
                 "failure, nothing durable, no blind replay, then one clean "
                 "recovery. The real-subprocess transport projects a nonzero "
                 "exit onto the shared transport-failure reason "
                 "provider_result_oversized (ChildFailed is a TransportError); "
                 "the offline seam path reports provider_tool_failed — both "
                 "are named, call-preserving rejections",
        "expected": {"failure_reason": "provider_result_oversized", "recovery_downloads": 1},
    },
    "w20_call_hash_lie": {
        "declared_layer": "ff+et",
        "scope": "ET result claims a payload sha that differs from the actual "
                 "bytes; the lie must surface as a named rejection (never a "
                 "false success) and the recovery run records whether anything "
                 "durable survived; final run reuses with zero requests",
        "expected": {"failure_reasons": ["transcript_import_rejected",
                                          "transcript_import_failed",
                                          "transcript_import_hash_mismatch",
                                          "provider_result_invalid"],
                     "final_reuse_zero_requests": True},
    },
    "w20_call_receipt_binding": {
        "declared_layer": "ff+et",
        "scope": "usage receipts that belong to another request id, or are "
                 "truncated, are never misread as this request's usage: usage "
                 "stays unknown (null, not zero) while the call itself is "
                 "preserved; the replay reuses the durable original",
        "expected": {"usage_stays_unknown": True, "final_reuse_zero_requests": True},
    },
    "w20_call_concurrent_same": {
        "declared_layer": "ff+et",
        "scope": "two concurrent FF processes request the same company/period; "
                 "no false success, no duplicate durable version, and the next "
                 "sequential request reuses with zero requests (no exactly-once "
                 "download promise is made for the concurrent window itself)",
        "expected": {"concurrent_honest": True, "single_durable_version": True,
                     "final_reuse_zero_requests": True},
    },
    "w20_filing_kill_recovery": {
        "declared_layer": "ff+cwp",
        "scope": "real CWP ensure/import via the fixture provider boundary; FF "
                 "child tree killed after the supplier response returns but "
                 "before the import is durable; recovery acquires exactly once "
                 "and the next request reuses with zero supplier requests",
        "expected": {"interruption": "post_response_pre_durable",
                     "recovery_downloads": 1, "final_reuse_zero_requests": True},
    },
    "w20_filing_concurrent_cross_company": {
        "declared_layer": "ff+cwp",
        "scope": "concurrent CN and HK annual reports for the same fiscal year "
                 "through the fixture provider boundary; each answer binds its "
                 "own company identity and period (never cross-company reuse) "
                 "and later requests reuse with zero supplier requests",
        "expected": {"cross_company_isolated": True, "final_reuse_zero_requests": True},
    },
}

_SPECS = _build()


def w20_case_specs():
    return _SPECS


def get_w20_spec(cid):
    return next((spec for spec in _SPECS if spec.id == cid), None)


# ── supplemental assertion authority ───────────────────────────────────────


def _runs(case):
    return (case.get("actual") or {}).get("runs") or []


def _t(run):
    return (run.get("response") or {}).get("transcript") or {}


def _f(run):
    return (run.get("response") or {}).get("filing") or {}


def _accepted(ref):
    return ref is not None


def _reason_in(t, reasons):
    return t.get("reason") in reasons


def w20_assertion_errors(spec, case):
    """Re-evaluate the fixed W20 business meaning from bound run evidence."""
    from matrix_outcome import source_ref

    runs = _runs(case)
    if len(runs) != len(spec.runs):
        return ["required attempt count is not observed"]
    errors = []
    cid = spec.id
    refs = [source_ref(_t(run).get("source_ref")) for run in runs]
    gets = [run.get("et_fixture_requests") for run in runs]

    def require(ok, detail):
        if not ok:
            errors.append(detail)

    if cid == "w20_call_kill_before_durable":
        require(runs[0].get("killed") is True, "pre-durable interruption did not happen")
        require(gets[0] == 1, f"interrupted run expected 1 in-flight GET, got {gets[0]}")
        require(refs[0] is None and _t(runs[0]).get("status") not in
                {"downloaded", "reused", "unknown_publication"},
                "interrupted run must not report a success or a source")
        require((case.get("actual") or {}).get("durable_at_kill") is False,
                "no transcript original may be durable at kill time")
        require(_t(runs[1]).get("status") == "downloaded" and _accepted(refs[1]),
                "recovery after pre-durable interruption must download exactly once")
        require(gets[1] == 1, f"recovery run expected 1 GET, got {gets[1]}")
        require(_t(runs[2]).get("status") in {"reused", "unknown_publication"}
                and refs[2] == refs[1] and gets[2] == 0,
                "final run must reuse the recovered source with zero requests")
        require(sum(get for get in gets if isinstance(get, int)) == 2,
                "exactly one interrupted GET plus one successful GET is allowed")
    elif cid == "w20_call_kill_after_import":
        require((case.get("actual") or {}).get("interruption_phase") == "mid_import_observed",
                "this case must declare its observed mid-import phase, never a durable pass")
        require(runs[0].get("killed") is True, "interruption did not happen")
        require(gets[0] == 1, f"interrupted run expected 1 GET, got {gets[0]}")
        durable_at_kill = (case.get("actual") or {}).get("durable_at_kill_public_readback")
        require(isinstance(durable_at_kill, bool),
                "durable state at kill must be observed through the public CWP interface")
        # The trigger (this request's own ET result receipt) fires BEFORE the
        # CWP import starts, so the kill is deterministically pre-durable.
        require(durable_at_kill is False,
                "the mid-import kill must be observed as NOT durable (import not started)")
        require(_t(runs[1]).get("status") == "downloaded" and gets[1] == 1,
                "recovery after a pre-durable interruption must download exactly once "
                f"(observed {_t(runs[1]).get('status')}, {gets[1]} GETs)")
        require(_t(runs[2]).get("status") in {"reused", "unknown_publication"}
                and refs[2] == refs[1] and gets[2] == 0,
                "final run must reuse the recovered source with zero requests")
        require(sum(get for get in gets if isinstance(get, int)) <= 2,
                "at most one interrupted GET plus one recovery GET is allowed")
    elif cid == "w20_call_kill_after_durable":
        actual = case.get("actual") or {}
        require(actual.get("interruption_phase") == "post_durable",
                "the durable case must declare the post_durable phase")
        verified = actual.get("verified_at_kill") or {}
        require(source_ref(verified) is not None,
                "a public-interface read-back proof must exist for the killed run")
        require(verified.get("content_sha256") == runs[0].get("expected_original_content_sha256"),
                "the read-back proof must be THIS request's content, not another period's")
        require(runs[0].get("killed") is True, "post-durable interruption did not happen")
        require(gets[0] == 1, f"interrupted run expected exactly 1 GET, got {gets[0]}")
        t0 = _t(runs[0])
        require(t0.get("status") not in {"downloaded", "reused", "unknown_publication"}
                and source_ref(t0.get("source_ref")) is None,
                "the killed run must not carry a success envelope or a source")
        require(_t(runs[1]).get("status") in {"reused", "unknown_publication"}
                and gets[1] == 0,
                "recovery after a durable interruption must reuse with ZERO extra GETs "
                f"(observed {_t(runs[1]).get('status')}, {gets[1]} GETs)")
        require(refs[1] is not None and refs[1] == verified,
                "recovery must return the same Ref/SHA as the pre-kill read-back")
        require(_t(runs[2]).get("status") in {"reused", "unknown_publication"}
                and refs[2] == refs[1] and gets[2] == 0,
                "the final replay must reuse the same source with zero requests")
    elif cid in {"w20_call_et_truncated", "w20_call_et_exit_nonzero"}:
        reason = spec.expected()["failure_reason"]
        t0 = _t(runs[0])
        require(t0.get("status") not in {None, "downloaded", "reused", "unknown_publication"}
                and t0.get("reason") == reason and refs[0] is None,
                f"first run must be the named failure {reason}")
        require(gets[0] == 1, f"failed attempt expected 1 GET, got {gets[0]}")
        require((case.get("actual") or {}).get("durable_after_fault") is False,
                "a rejected ET result must leave nothing durable")
        require(_t(runs[1]).get("status") == "downloaded" and _accepted(refs[1]) and gets[1] == 1,
                "recovery must download exactly once")
    elif cid == "w20_call_hash_lie":
        t0 = _t(runs[0])
        require(t0.get("status") not in {None, "downloaded", "reused", "unknown_publication"}
                and _reason_in(t0, spec.expected()["failure_reasons"]) and refs[0] is None,
                "a lying payload sha must surface as a named rejection, never a success")
        require(gets[0] == 1, f"rejected attempt expected 1 GET, got {gets[0]}")
        if _t(runs[1]).get("status") == "downloaded" and gets[1] == 1:
            require((case.get("actual") or {}).get("recovery_branch") == "not_durable_at_rejection",
                    "a recovery download implies the rejection left nothing durable")
        else:
            require(_t(runs[1]).get("status") in {"reused", "unknown_publication"} and gets[1] == 0,
                    "recovery must either reuse the durable original or download exactly once")
        require(_t(runs[2]).get("status") in {"reused", "unknown_publication"}
                and refs[2] == refs[1] and gets[2] == 0,
                "final run must reuse with zero requests")
        require(sum(get for get in gets if isinstance(get, int)) <= 2,
                "no blind replay: at most one rejected GET plus one recovery GET")
    elif cid == "w20_call_receipt_binding":
        for index, label in ((0, "stale"), (1, "truncated")):
            run = runs[index]
            t = _t(run)
            require(t.get("status") == "downloaded" and _accepted(refs[index]),
                    f"{label}-receipt run must still download and import")
            require(t.get("provider_requests") is None
                    and t.get("provider_usage_complete") is False,
                    f"{label} usage receipt must stay unknown, never a fake zero")
            require(t.get("provider_calls") == 1,
                    f"{label}-receipt run must preserve the provider call")
        require(_t(runs[2]).get("status") in {"reused", "unknown_publication"}
                and refs[2] == refs[0] and gets[2] == 0,
                "replay must reuse the first run's durable source with zero requests")
    elif cid == "w20_call_concurrent_same":
        honest = [run for run in runs[:2]
                  if _t(run).get("source_ref") or (_t(run).get("status") not in
                   {None, "downloaded", "reused", "unknown_publication"}
                   and _t(run).get("reason"))]
        require(len(honest) == 2, "every concurrent answer must be a source or a named failure")
        present = [ref for ref in refs[:2] if ref]
        require(present, "at least one concurrent answer must import the source")
        require(all(ref == present[0] for ref in present),
                "concurrent answers for identical requests must agree on one source")
        require(sum(get for get in gets[:2] if isinstance(get, int)) >= 1,
                "the concurrent window must have performed at least one real GET")
        require(_t(runs[2]).get("status") in {"reused", "unknown_publication"}
                and refs[2] == present[0] and gets[2] == 0,
                "the sequential replay must reuse with zero requests")
    elif cid == "w20_filing_kill_recovery":
        fetches = [run.get("adapter_fetch_requests") for run in runs]
        require(runs[0].get("killed") is True, "post-response interruption did not happen")
        require(isinstance(fetches[0], int) and fetches[0] >= 1,
                "the supplier response must have returned before the kill")
        require(_f(runs[0]).get("source_ref") is None and runs[0]["response"].get("status")
                != "source_candidate",
                "the interrupted run must not report a success")
        require((case.get("actual") or {}).get("durable_at_kill") is False,
                "no canonical original may be durable at kill time")
        require(runs[1]["response"].get("status") == "source_candidate"
                and _f(runs[1]).get("source_ref") and fetches[1] == 1,
                "recovery must fetch from the supplier exactly once and import")
        require(_f(runs[2]).get("resolution_outcome") == "reused_existing"
                and _f(runs[2]).get("source_ref") == _f(runs[1]).get("source_ref")
                and fetches[2] == 0,
                "final run must reuse with zero supplier fetches")
    elif cid == "w20_filing_concurrent_cross_company":
        fetches = [run.get("adapter_fetch_requests") for run in runs]
        cn_ref = _f(runs[0]).get("source_ref")
        hk_ref = _f(runs[1]).get("source_ref")
        require(runs[0]["response"].get("status") == "source_candidate"
                and runs[1]["response"].get("status") == "source_candidate",
                "both concurrent acquisitions must resolve")
        require(cn_ref and hk_ref and cn_ref != hk_ref,
                "same-year different-company answers must bind different sources")
        require(_f(runs[0]).get("document_kind") == "annual_report"
                and _f(runs[1]).get("document_kind") == "annual_report",
                "both answers must be stored as their requested kind")
        require(_f(runs[2]).get("resolution_outcome") == "reused_existing"
                and _f(runs[2]).get("source_ref") == cn_ref and fetches[2] == 0,
                "CN replay must reuse its own source with zero fetches")
        require(_f(runs[3]).get("resolution_outcome") == "reused_existing"
                and _f(runs[3]).get("source_ref") == hk_ref and fetches[3] == 0,
                "HK replay must reuse its own source with zero fetches")
        require((case.get("actual") or {}).get("cross_company_source_counts") == {
            "cn": 1, "hk": 1},
                "each company must end with exactly one durable source")
    else:
        return ["case handler has no fixed business assertions"]
    return errors
