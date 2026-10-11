"""Fixed executable case authority shared by runner and oracle.

Reports are observations, never case definitions. JSON strings keep nested
definitions immutable; projections return fresh copies. No authorization or
identity database is introduced. Fixed company inputs are synthetic fixtures.
"""

from dataclasses import dataclass
import importlib
import json
from fixture_builder import CN, HK, US
from matrix_outcome import Outcome, count, filing_reused, source_ref

AUTHORITY_VERSION = "w06-cases/1"


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class RunSpec:
    request_json: str
    fixture_json: str = "null"
    with_fmp_key: bool = True

    def request(self):
        return json.loads(self.request_json)

    def fixture(self):
        return json.loads(self.fixture_json)


@dataclass(frozen=True)
class CaseSpec:
    id: str
    handler: str
    arguments_json: str
    runs: tuple[RunSpec, ...]
    declared_layer: str
    scope: str
    expected_json: str

    def expected(self):
        return json.loads(self.expected_json)

    def metadata_errors(self, case):
        errors = []
        for key, wanted in (
            ("id", self.id),
            ("declared_layer", self.declared_layer),
            ("scope", self.scope),
            ("expected", self.expected()),
        ):
            if case.get(key) != wanted:
                errors.append(f"{key} differs from {AUTHORITY_VERSION}:{self.id}")
        return errors

    def request_errors(self, index, request):
        if index >= len(self.runs):
            return ["unexpected extra run"]
        wanted = self.runs[index].request()
        if request == wanted:
            return []
        return [
            f"request fields differ: {sorted(k for k in set(request) | set(wanted) if request.get(k) != wanted.get(k) or (k in request) != (k in wanted))}"
        ]

    def fixture_errors(self, index, state, with_fmp_key):
        if index >= len(self.runs):
            return ["unexpected extra run"]
        run = self.runs[index]
        expected = run.fixture()
        errors = []
        if with_fmp_key != run.with_fmp_key:
            errors.append("credential presence differs from fixed vector")
        if expected is not None:
            for key, value in expected.items():
                if state.get(key) != value:
                    errors.append(f"fixture {key} differs from fixed vector")
        return errors

    def assertion_errors(self, case):
        """Re-evaluate fixed business meaning from bound producer responses.

        A PASS label or summary boolean cannot substitute for required outcomes.
        The oracle separately verifies these response bytes against their files.
        """
        runs = (case.get("actual") or {}).get("runs") or []
        if len(runs) != len(self.runs):
            return ["required attempt count is not observed"]
        responses = [r.get("response") or {} for r in runs]
        first = responses[0]
        filing = first.get("filing") or {}
        transcript = first.get("transcript") or {}
        expected = self.expected()
        handler = self.handler.split(":")[1]
        checks = []

        def require(ok, detail):
            checks.append((bool(ok), detail))

        if handler == "case_fin_local_hit":
            require(
                first.get("status") == expected["status"]
                and filing.get("resolution_outcome") == "reused_existing"
                and count(filing.get("download_events")) == expected["download_events"]
                and source_ref(filing.get("source_ref")),
                "local filing is not an exact zero-download source reuse",
            )
            require(
                count(runs[0].get("fixture_requests")) == 0,
                "local filing invoked fixture acquisition",
            )
        elif handler == "case_fin_fetch":
            require(
                first.get("status") == "source_candidate"
                and filing_reused(
                    filing,
                    responses[1].get("filing") or {},
                    self.runs[0].request()["document_kind"],
                ),
                "new filing acquisition followed by exact source reuse is unproved",
            )
        elif handler == "case_nonperiod":
            require(
                first.get("status") == "source_candidate"
                and filing.get("document_kind") == expected["stored_kind"]
                and source_ref(filing.get("source_ref")),
                "nonperiodic document not registered under its required kind",
            )
        elif handler == "case_chain_a":
            second = responses[1].get("transcript") or {}
            require(
                transcript.get("status") == "downloaded"
                and source_ref(transcript.get("source_ref"))
                and second.get("status") in {"reused", "unknown_publication"}
                and source_ref(second.get("source_ref"))
                == source_ref(transcript.get("source_ref")),
                "transcript download then stable source reuse is unproved",
            )
            require(
                count(runs[0].get("et_fixture_requests")) == 1
                and count(runs[1].get("et_fixture_requests")) == 0,
                "transcript expected 1 then 0 GETs",
            )
        elif handler == "case_call_fy_only":
            require(
                transcript.get("status") == expected["status"]
                and transcript.get("reason") == expected["reason"],
                "FY-only unresolved-period diagnostic missing",
            )
        elif handler == "case_call_past_cutoff":
            require(Outcome.observe(transcript).rejected_cutoff(), "named cutoff rejection missing")
        elif handler == "case_call_wrong_quarter":
            require(
                Outcome.observe(transcript).rejected_quarter()
                or (
                    transcript.get("status") in {"upstream_error", "provider_unavailable"}
                    and transcript.get("reason") == "provider_identity_or_host"
                    and count(runs[0].get("et_fixture_requests")) == 1
                ),
                "named quarter/provenance rejection missing",
            )
        elif handler == "case_err_request":
            require(
                first.get("status") == expected["status"] and runs[0].get("exit_code") == 2,
                "request validation failure missing",
            )
        elif handler == "case_err_402":
            require(
                transcript.get("status") == expected["status"]
                and expected["reason_contains"] in str(transcript.get("reason")),
                "402 entitlement diagnostic missing",
            )
        elif handler == "case_err_missing_creds":
            require(
                expected["reason_contains"] in str(transcript.get("reason"))
                and count(runs[0].get("fixture_requests")) == 0,
                "credential preflight not preserved as zero-request diagnostic",
            )
        elif handler == "case_err_unknown_usage":
            require(
                Outcome.observe(transcript).preserves_unknown_usage(),
                "unknown usage not preserved as a named null failure",
            )
        elif handler == "case_local_txt":
            ref = source_ref(transcript.get("source_ref"))
            require(
                transcript.get("status") in {"reused", "unknown_publication"}
                and ref
                and ref["mime_type"] == "text/plain"
                and count(runs[0].get("fixture_requests")) == 0,
                "exact local TXT source reuse unproved",
            )
        elif handler == "case_reuse_only_gap":
            require(
                first.get("status") != "source_candidate"
                and source_ref(filing.get("source_ref")) is None
                and count(runs[0].get("fixture_requests")) == 0,
                "reuse-only gap acquired or accepted a source",
            )
        elif handler in {"_negative_transcript", "case_failure_then_retry"}:
            require(
                transcript.get("status")
                not in {None, "downloaded", "reused", "unknown_publication", "not_requested"}
                and transcript.get("reason") in expected["reasons"]
                and source_ref(transcript.get("source_ref")) is None
                and count(runs[0].get("et_fixture_requests")) == 1,
                "required attempted ET rejection is unproved",
            )
            require(
                (case.get("actual") or {}).get("worker_cleanup") is True,
                "owned ET worker artifacts not cleaned",
            )
            if handler == "case_failure_then_retry":
                second = responses[1].get("transcript") or {}
                require(
                    second.get("status") == "downloaded"
                    and source_ref(second.get("source_ref"))
                    and count(runs[1].get("et_fixture_requests")) == 1,
                    "successful retry after named failure unproved",
                )
        elif handler == "filing_negative":
            code = (filing.get("upstream_cause") or {}).get("code")
            require(
                first.get("status") != "source_candidate"
                and source_ref(filing.get("source_ref")) is None
                and count(runs[0].get("adapter_fixture_requests")) is not None
                and runs[0]["adapter_fixture_requests"] >= 2
                and code in {"acquisition_validation_failed", "acquisition_budget_exceeded"},
                "attempted invalid staged-original validation unproved",
            )
        elif handler == "case_unverified_sidecar":
            require(
                first.get("status") != "source_candidate"
                and (filing.get("upstream_cause") or {}).get("code") == "local_metadata_gap",
                "incomplete metadata diagnostic missing",
            )
        else:
            return ["case handler has no fixed business assertions"]
        return [detail for ok, detail in checks if not ok]

    def execute(self, ctx):
        module, name = self.handler.split(":")
        args = json.loads(self.arguments_json)
        args = [
            {"CN": CN, "HK": HK, "US": US}[arg["identity"]]
            if isinstance(arg, dict) and set(arg) == {"identity"}
            else arg
            for arg in args
        ]
        return getattr(importlib.import_module(module), name)(ctx, *args)


def _request(
    identity=US,
    *,
    kind="annual_report",
    year=2025,
    period="FY",
    intent="reuse_only",
    asof="2026-12-31",
    companion=None,
    limits=None,
):
    request = {
        "schema_version": "2.0",
        "company_query": identity.canonical_name,
        "market": identity.market,
        "document_kind": kind,
        "fiscal_year": year,
        "as_of_date": asof,
        "filing_intent": intent,
    }
    if period is not None:
        request["fiscal_period"] = period
    if intent == "fetch_if_missing":
        request["acquisition_limits"] = limits or {
            "max_bytes": 2000000,
            "timeout_seconds": 25,
            "max_cost_usd": "0",
        }
    if companion is not None:
        request["companion_transcript"] = companion
    return request


def _companion(year, quarter, intent="fetch_if_missing", limits=None):
    row = {"intent": intent, "fiscal_year": year, "provider": "fmp"}
    if quarter is not None:
        row["fiscal_quarter"] = quarter
    if intent == "fetch_if_missing":
        row["acquisition_limits"] = limits or {
            "max_bytes": 1000000,
            "timeout_seconds": 25,
            "max_cost_usd": "0",
        }
    return row


def _fixture(scenario="success", provider="serve", **values):
    return {
        "scenario": scenario,
        "provider_scenario": provider,
        "call_date": "2025-12-01",
        "response_bytes": 512,
        "content_utf8": "",
        **values,
    }


def _run(request, fixture=None, key=True):
    return RunSpec(_json(request), _json(fixture), key)


def _spec(cid, handler, args, runs):
    meta = _METADATA[cid]
    return CaseSpec(
        cid,
        handler,
        _json(args),
        tuple(runs),
        meta["declared_layer"],
        meta["scope"],
        _json(meta["expected"]),
    )


def _build():
    rows = [
        _spec(
            "chainA_download_reuse",
            "matrix_cases:case_chain_a",
            [],
            [
                _run(
                    _request(companion=_companion(2025, 1)),
                    _fixture(
                        content_utf8="Synthetic original-language AAPL FY2025 Q1 earnings call transcript."
                    ),
                ),
                _run(_request(companion=_companion(2025, 1)), _fixture()),
            ],
        )
    ]
    kinds = (
        ("annual_report", "annual", "FY"),
        ("semi_annual_report", "semi", "S1"),
        ("quarterly_report", "quarterly", "Q1"),
    )
    for identity in (CN, HK, US):
        for kind, short, period in kinds:
            cid = f"fin_{identity.market.lower()}_{short}_hit"
            rows.append(
                _spec(
                    cid,
                    "matrix_cases:case_fin_local_hit",
                    [{"identity": identity.market}, kind, 2024, period, cid],
                    [_run(_request(identity, kind=kind, year=2024, period=period))],
                )
            )
    for identity in (CN, HK, US):
        for kind, short, period in kinds:
            cid = f"fin_{identity.market.lower()}_{short}_fetch"
            request = _request(
                identity, kind=kind, year=2026, period=period, intent="fetch_if_missing"
            )
            rows.append(
                _spec(
                    cid,
                    "matrix_cases:case_fin_fetch",
                    [{"identity": identity.market}, kind, 2026, cid, period],
                    [_run(request, _fixture()), _run(request, _fixture())],
                )
            )
    for cid, identity, kind in (
        ("nonperiod_prospectus", US, "prospectus"),
        ("nonperiod_equity_offering", US, "equity_offering_prospectus"),
        ("nonperiod_convertible_bond", US, "convertible_bond_prospectus"),
        ("nonperiod_investor_relations", HK, "investor_relations"),
    ):
        rows.append(
            _spec(
                cid,
                "matrix_cases:case_nonperiod",
                [{"identity": identity.market}, kind, cid],
                [
                    _run(
                        _request(identity, kind=kind, period=None, intent="fetch_if_missing"),
                        _fixture(),
                    )
                ],
            )
        )
    rows.extend(
        [
            _spec(
                "call_fy_only_no_q",
                "matrix_cases:case_call_fy_only",
                [],
                [_run(_request(companion=_companion(2025, None)))],
            ),
            _spec(
                "call_past_cutoff",
                "matrix_cases:case_call_past_cutoff",
                [],
                [
                    _run(
                        _request(companion=_companion(2025, 2)),
                        _fixture(
                            call_date="2027-06-01",
                            content_utf8="Synthetic transcript dated after cutoff.",
                        ),
                    )
                ],
            ),
            _spec(
                "call_wrong_quarter",
                "matrix_cases:case_call_wrong_quarter",
                [],
                [
                    _run(
                        _request(companion=_companion(2025, 3)),
                        _fixture(
                            "wrong_quarter",
                            content_utf8="Synthetic transcript with mismatched quarter.",
                        ),
                    )
                ],
            ),
            _spec(
                "err_request_error",
                "matrix_cases:case_err_request",
                [],
                [
                    _run(
                        {
                            "schema_version": "2.0",
                            "company_query": "Apple Inc.",
                            "market": "US",
                            "document_kind": "annual_report",
                            "as_of_date": "2026-01-01",
                            "filing_intent": "reuse_only",
                        }
                    )
                ],
            ),
            _spec(
                "err_402_entitlement",
                "matrix_cases:case_err_402",
                [],
                [_run(_request(companion=_companion(2025, 4)), _fixture("entitlement_402"))],
            ),
            _spec(
                "err_missing_creds",
                "matrix_cases:case_err_missing_creds",
                [],
                [_run(_request(companion=_companion(2026, 1)), key=False)],
            ),
            _spec(
                "err_unknown_usage",
                "matrix_cases:case_err_unknown_usage",
                [],
                [_run(_request(companion=_companion(2026, 2)), _fixture("worker_loss"))],
            ),
            _spec(
                "local_txt_exact_reuse",
                "extended_cases:case_local_txt",
                [],
                [
                    _run(
                        _request(companion=_companion(2024, 2, "reuse_only")),
                        _fixture("worker_loss"),
                    )
                ],
            ),
            _spec(
                "reuse_only_missing_period",
                "extended_cases:case_reuse_only_gap",
                [],
                [_run(_request(CN, year=2030), _fixture("worker_loss"))],
            ),
        ]
    )
    for cid, scenario, reasons, quarter, max_bytes, seconds in (
        ("call_wrong_symbol", "wrong_symbol", ["provider_identity_or_host"], 1, 1000000, 5),
        ("call_wrong_mime", "wrong_mime", ["provider_identity_or_host"], 2, 1000000, 5),
        ("call_max_bytes", "oversize", ["byte_limit"], 3, 256, 5),
        ("call_hard_timeout", "stall", ["provider_deadline"], 4, 1000000, 1),
    ):
        # Dedicated runner reads its arguments from this same definition.
        rows.append(
            _spec(
                cid,
                "case_specs:_negative_transcript",
                [scenario, cid, reasons, 2028, quarter, max_bytes, seconds],
                [
                    _run(
                        _request(
                            companion=_companion(
                                2028,
                                quarter,
                                limits={
                                    "max_bytes": max_bytes,
                                    "timeout_seconds": seconds,
                                    "max_cost_usd": "0",
                                },
                            )
                        ),
                        _fixture(scenario, response_bytes=2000 if scenario == "oversize" else 512),
                    )
                ],
            )
        )
    rows.append(
        _spec(
            "request_after_failure_retry",
            "extended_cases:case_failure_then_retry",
            [],
            [
                _run(
                    _request(
                        companion=_companion(
                            2029,
                            1,
                            limits={
                                "max_bytes": 1000000,
                                "timeout_seconds": 5,
                                "max_cost_usd": "0",
                            },
                        )
                    ),
                    _fixture("request_failure"),
                ),
                _run(
                    _request(companion=_companion(2029, 1)),
                    _fixture(content_utf8="Synthetic retry original content."),
                ),
            ],
        )
    )
    for cid, scenario in (
        ("original_wrong_sha", "bad_sha"),
        ("original_wrong_mime", "bad_mime"),
        ("original_max_bytes", "oversize"),
    ):
        rows.append(
            _spec(
                cid,
                "extended_cases:filing_negative",
                [scenario, cid],
                [
                    _run(
                        _request(
                            CN,
                            kind="prospectus",
                            year=2031,
                            period=None,
                            intent="fetch_if_missing",
                            limits={
                                "max_bytes": 50 if scenario == "oversize" else 2000000,
                                "timeout_seconds": 5,
                                "max_cost_usd": "0",
                            },
                        ),
                        _fixture(provider=scenario),
                    )
                ],
            )
        )
    rows.append(
        _spec(
            "incomplete_sidecar_metadata_gap",
            "extended_cases:case_unverified_sidecar",
            [],
            [_run(_request(CN, year=2032, asof="2033-12-31"))],
        )
    )
    return tuple(rows)


def _negative_transcript(ctx, scenario, cid, reasons, year, quarter, max_bytes, seconds):
    from extended_cases import transcript_negative

    return transcript_negative(
        ctx,
        scenario,
        cid,
        set(reasons),
        year=year,
        quarter=quarter,
        max_bytes=max_bytes,
        seconds=seconds,
    )


def case_specs():
    return _SPECS


def get_spec(cid):
    return next((spec for spec in _SPECS if spec.id == cid), None)


def audit_coverage(cases):
    wanted = {s.id for s in _SPECS}
    observed = [c.get("id") for c in cases]
    missing = wanted - set(observed)
    extra = set(observed) - wanted
    duplicate = {cid for cid in observed if observed.count(cid) > 1}
    return (
        [
            f"missing={sorted(missing)}, unknown={sorted(str(x) for x in extra)}, duplicate={sorted(str(x) for x in duplicate)}"
        ]
        if missing or extra or duplicate
        else []
    )


# Reviewed fixed input/expected definitions; not loaded from a runtime report.
_METADATA = {
    "chainA_download_reuse": {
        "declared_layer": "real-3layer",
        "scope": "chain-A transcript three-layer; test-proxy replaces only worker HTTP",
        "expected": {"run_twice": True},
    },
    "fin_cn_annual_hit": {
        "declared_layer": "ff+cwp",
        "scope": "periodic financial report local reuse, zero provider requests",
        "expected": {"status": "source_candidate", "download_events": 0},
    },
    "fin_cn_semi_hit": {
        "declared_layer": "ff+cwp",
        "scope": "periodic financial report local reuse, zero provider requests",
        "expected": {"status": "source_candidate", "download_events": 0},
    },
    "fin_cn_quarterly_hit": {
        "declared_layer": "ff+cwp",
        "scope": "periodic financial report local reuse, zero provider requests",
        "expected": {"status": "source_candidate", "download_events": 0},
    },
    "fin_hk_annual_hit": {
        "declared_layer": "ff+cwp",
        "scope": "periodic financial report local reuse, zero provider requests",
        "expected": {"status": "source_candidate", "download_events": 0},
    },
    "fin_hk_semi_hit": {
        "declared_layer": "ff+cwp",
        "scope": "periodic financial report local reuse, zero provider requests",
        "expected": {"status": "source_candidate", "download_events": 0},
    },
    "fin_hk_quarterly_hit": {
        "declared_layer": "ff+cwp",
        "scope": "periodic financial report local reuse, zero provider requests",
        "expected": {"status": "source_candidate", "download_events": 0},
    },
    "fin_us_annual_hit": {
        "declared_layer": "ff+cwp",
        "scope": "periodic financial report local reuse, zero provider requests",
        "expected": {"status": "source_candidate", "download_events": 0},
    },
    "fin_us_semi_hit": {
        "declared_layer": "ff+cwp",
        "scope": "periodic financial report local reuse, zero provider requests",
        "expected": {"status": "source_candidate", "download_events": 0},
    },
    "fin_us_quarterly_hit": {
        "declared_layer": "ff+cwp",
        "scope": "periodic financial report local reuse, zero provider requests",
        "expected": {"status": "source_candidate", "download_events": 0},
    },
    "fin_cn_annual_fetch": {
        "declared_layer": "ff+cwp",
        "scope": "financial report download at the configured fixture provider "
        "boundary; real CWP ensure/import, only the supplier response is "
        "simulated",
        "expected": {"run_twice": True},
    },
    "fin_cn_semi_fetch": {
        "declared_layer": "ff+cwp",
        "scope": "financial report download at the configured fixture provider boundary; "
        "real CWP ensure/import, only the supplier response is simulated",
        "expected": {"run_twice": True},
    },
    "fin_cn_quarterly_fetch": {
        "declared_layer": "ff+cwp",
        "scope": "financial report download at the configured fixture provider "
        "boundary; real CWP ensure/import, only the supplier response is "
        "simulated",
        "expected": {"run_twice": True},
    },
    "fin_hk_annual_fetch": {
        "declared_layer": "ff+cwp",
        "scope": "financial report download at the configured fixture provider "
        "boundary; real CWP ensure/import, only the supplier response is "
        "simulated",
        "expected": {"run_twice": True},
    },
    "fin_hk_semi_fetch": {
        "declared_layer": "ff+cwp",
        "scope": "financial report download at the configured fixture provider boundary; "
        "real CWP ensure/import, only the supplier response is simulated",
        "expected": {"run_twice": True},
    },
    "fin_hk_quarterly_fetch": {
        "declared_layer": "ff+cwp",
        "scope": "financial report download at the configured fixture provider "
        "boundary; real CWP ensure/import, only the supplier response is "
        "simulated",
        "expected": {"run_twice": True},
    },
    "fin_us_annual_fetch": {
        "declared_layer": "ff+cwp",
        "scope": "financial report download at the configured fixture provider "
        "boundary; real CWP ensure/import, only the supplier response is "
        "simulated",
        "expected": {"run_twice": True},
    },
    "fin_us_semi_fetch": {
        "declared_layer": "ff+cwp",
        "scope": "financial report download at the configured fixture provider boundary; "
        "real CWP ensure/import, only the supplier response is simulated",
        "expected": {"run_twice": True},
    },
    "fin_us_quarterly_fetch": {
        "declared_layer": "ff+cwp",
        "scope": "financial report download at the configured fixture provider "
        "boundary; real CWP ensure/import, only the supplier response is "
        "simulated",
        "expected": {"run_twice": True},
    },
    "nonperiod_prospectus": {
        "declared_layer": "ff+cwp",
        "scope": "non-periodic kind imported from its correct tool/class, never as annual/FY",
        "expected": {"supported": True, "stored_kind": "prospectus"},
    },
    "nonperiod_equity_offering": {
        "declared_layer": "ff+cwp",
        "scope": "non-periodic kind imported from its correct tool/class, never as annual/FY",
        "expected": {"supported": True, "stored_kind": "equity_offering_prospectus"},
    },
    "nonperiod_convertible_bond": {
        "declared_layer": "ff+cwp",
        "scope": "non-periodic kind imported from its correct tool/class, never as annual/FY",
        "expected": {"supported": True, "stored_kind": "convertible_bond_prospectus"},
    },
    "nonperiod_investor_relations": {
        "declared_layer": "ff+cwp",
        "scope": "non-periodic kind imported from its correct tool/class, never as annual/FY",
        "expected": {"supported": True, "stored_kind": "investor_relations"},
    },
    "call_fy_only_no_q": {
        "declared_layer": "ff-only",
        "scope": "exact FY without quarter must not be guessed as Q4",
        "expected": {"status": "period_unresolved", "reason": "exact_fy_q_required"},
    },
    "call_past_cutoff": {
        "declared_layer": "ff+et",
        "scope": "publication/call after as_of_date is never reported historical-eligible",
        "expected": {"past_cutoff": True},
    },
    "call_wrong_quarter": {
        "declared_layer": "ff+et",
        "scope": "quarter provenance is enforced; a mismatch is not silently accepted",
        "expected": {"quarter_provenance": True},
    },
    "err_request_error": {
        "declared_layer": "ff-only",
        "scope": "request validation diagnostics preserved",
        "expected": {"status": "request_error"},
    },
    "err_402_entitlement": {
        "declared_layer": "ff+et",
        "scope": "HTTP 402 → provider_entitlement_required diagnostic",
        "expected": {"status": "provider_unavailable", "reason_contains": "entitlement"},
    },
    "err_missing_creds": {
        "declared_layer": "ff+et",
        "scope": "missing credential is a named diagnostic with zero provider requests",
        "expected": {"reason_contains": "credentials"},
    },
    "err_unknown_usage": {
        "declared_layer": "ff+et",
        "scope": "unknown usage is null (never 0); the failed call is preserved",
        "expected": {"unknown_usage": True},
    },
    "local_txt_exact_reuse": {
        "declared_layer": "ff+cwp",
        "scope": "local synthetic TXT; no proxy retrieval permitted",
        "expected": {"local_txt_reused": True},
    },
    "reuse_only_missing_period": {
        "declared_layer": "ff+cwp",
        "scope": "missing exact period must stay a gap",
        "expected": {"no_acquisition": True},
    },
    "call_wrong_symbol": {
        "declared_layer": "ff+et",
        "scope": "real FF+ET runtime; fixture session only",
        "expected": {"reasons": ["provider_identity_or_host"], "rejected_source": True},
    },
    "call_wrong_mime": {
        "declared_layer": "ff+et",
        "scope": "real FF+ET runtime; fixture session only",
        "expected": {"reasons": ["provider_identity_or_host"], "rejected_source": True},
    },
    "call_max_bytes": {
        "declared_layer": "ff+et",
        "scope": "real FF+ET runtime; fixture session only",
        "expected": {"reasons": ["byte_limit"], "rejected_source": True},
    },
    "call_hard_timeout": {
        "declared_layer": "ff+et",
        "scope": "real FF+ET runtime; fixture session only",
        "expected": {"reasons": ["provider_deadline"], "rejected_source": True},
    },
    "request_after_failure_retry": {
        "declared_layer": "ff+et",
        "scope": "real FF+ET runtime; fixture session only",
        "expected": {
            "reasons": ["provider_response", "unexpected_provider_failure"],
            "rejected_source": True,
        },
    },
    "original_wrong_sha": {
        "declared_layer": "ff+cwp",
        "scope": "fixture supplier bytes; actual CWP ingestion",
        "expected": {"supplier_fetch_attempted": True, "invalid_original_rejected": True},
    },
    "original_wrong_mime": {
        "declared_layer": "ff+cwp",
        "scope": "fixture supplier bytes; actual CWP ingestion",
        "expected": {"supplier_fetch_attempted": True, "invalid_original_rejected": True},
    },
    "original_max_bytes": {
        "declared_layer": "ff+cwp",
        "scope": "fixture supplier bytes; actual CWP ingestion",
        "expected": {"supplier_fetch_attempted": True, "invalid_original_rejected": True},
    },
    "incomplete_sidecar_metadata_gap": {
        "declared_layer": "ff+cwp",
        "scope": "explicit legacy/unverified fixture; not interchangeable "
        "with importer-verified warm state",
        "expected": {"diagnosed_gap": True},
    },
}
_SPECS = _build()
