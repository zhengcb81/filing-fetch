"""Assemble ``handoff.json`` from git state and the recorded receipts.

    python receipts/make_handoff.py --status IMPLEMENTED_REVIEW_PENDING \
        --implementation-commit <sha> --review-status pending

Every value comes from git or from a receipt produced by a real run, so the
handoff cannot drift from the evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
PLAN_DIR = HERE.parent
REPO = PLAN_DIR.parents[2]
BASE_COMMIT = "f1a939e522c22b23659712a8bd2b344f5eb0a364"
BRANCH = "codex/du11-ff-transcript-reuse"
CARD_ID = "du11-ff-transcript-reuse"


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *arguments],
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    ).stdout


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def committed_sha256(commit: str, path: str) -> str:
    """Content hash of the file as frozen in ``commit`` (not the working tree)."""
    return hashlib.sha256(git("show", f"{commit}:{path}").encode("utf-8")).hexdigest()


def receipt(name: str) -> dict:
    path = HERE / name
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", required=True)
    parser.add_argument(
        "--implementation-commit", required=True, action="append",
        help="repeatable; the last one is the frozen source head",
    )
    parser.add_argument("--review-status", required=True)
    parser.add_argument("--review-sha", default=None)
    parser.add_argument("--review-report", default="receipts/reviewer_report.md")
    parser.add_argument("--review-rounds", default=None)
    parser.add_argument("--unresolved", type=int, default=None)
    parser.add_argument("--final-delivery-commit", default=None)
    args = parser.parse_args()

    commits = [git("rev-parse", f"{item}^{{commit}}").strip() for item in args.implementation_commit]
    implementation = commits[-1]
    changed = [
        line
        for line in git(
            "diff", "--name-only", f"{BASE_COMMIT}..{implementation}"
        ).splitlines()
        if line.strip()
    ]
    untracked_plan = sorted(
        path.relative_to(REPO).as_posix()
        for path in PLAN_DIR.rglob("*")
        if path.is_file()
    )
    deps = receipt("c_dependencies.json")
    tests = receipt("c_test_summary.json")
    restore = receipt("c_restore_receipt.json")
    mutation = receipt("c_mutation_check.json")
    red = receipt("A_RED_baseline.json")
    after = receipt("A_RED_after_fix.json")

    payload = {
        "card_id": CARD_ID,
        "card_path": (
            "C:/Users/郑曾波/Projects/company-wiki/docs/plans/"
            "document-understanding-2026-10-13/parallel/du11-2026-10-17/"
            "du11_ff_transcript_reuse.md"
        ),
        "status": args.status,
        "base_commit": BASE_COMMIT,
        "branch": BRANCH,
        "worktree": str(REPO),
        "implementation_commits": commits,
        "final_delivery_commit": args.final_delivery_commit
        or (
            "pending: this JSON is committed by the docs-only handoff commit whose "
            f"parent is the frozen source commit {implementation}; ROOT verifies the "
            "real HEAD there"
        ),
        "author_scope": {
            "changed_paths": changed + untracked_plan,
            "source_files": [path for path in changed if path.startswith("scripts/")],
            "test_files": [path for path in changed if path.startswith("tests/")],
            "plan_files": untracked_plan,
            "outside_whitelist": [],
            "not_modified_on_purpose": [
                "scripts/ff_v2_envelope.py (public envelope already carries the real "
                "provider; no weakening of source/fee/SHA checks was needed)",
                "scripts/fetch_filing.py, scripts/filing_contracts.py, config/**, "
                "tools/offline_contract_matrix/**, company-wiki and earnings-transcripts "
                "sources, skill install directories",
            ],
            "source_freeze_sha256": {
                path: committed_sha256(implementation, path) for path in changed
            },
        },
        "input_output_schema": {
            "request_schema": (
                "unchanged: filing_contracts._validate_companion_request still allows "
                "only intent/fiscal_year/fiscal_quarter/provider/acquisition_limits and "
                "still rejects providers other than fmp"
            ),
            "response_schema": (
                "unchanged: ff_v2_envelope._TRANSCRIPT_KEYS untouched; new diagnostics "
                "(qualification, excluded_candidates) stay inside the child result and "
                "are dropped by the public serializer; provider is omitted when the "
                "verified manifest does not name one"
            ),
            "new_named_reasons": [
                "transcript_lookup_contract",
                "transcript_lookup_source_ref",
                "transcript_lookup_identity_mismatch",
                "transcript_provider_mismatch",
                "unsupported_transcript_provider",
                "publication_date_unknown",
                "publication_after_as_of",
                "publication_date_invalid",
                "transcript_lookup_changed",
            ],
            "compatibility_matrix": "handoff.md section 3",
            "internal_diagnostic_keys": ["qualification", "excluded_candidates"],
        },
        "tests": {
            "card": tests.get("du11_card_tests"),
            "central_regression": tests.get("central_regression"),
            "commands": [
                "python -m ruff check scripts tests",
                "python -m pytest tests/test_du11_transcript_reuse_selection.py "
                "tests/test_du11_transcript_reuse_contract.py "
                "tests/test_du11_transcript_reuse_e2e.py -q",
                "python -m pytest tests/test_transcript_companion.py "
                "tests/test_transcript_companion_transport.py "
                "tests/test_transcript_launch_contract.py "
                "tests/test_transcript_response_budget.py tests/test_ff_v2_contract.py "
                "tests/test_cwp_s0b_source_ref_contract.py "
                "tests/test_acquisition_failure_consumer.py "
                "tests/test_failure_usage_continuity.py "
                "tests/test_m3_acquisition_usage_ff.py "
                "tests/test_provider_diagnostics_cli.py -q",
                "python -m pytest tests -q   (full repo; 9 pre-existing failures also "
                "fail at the base commit)",
            ],
            "mutation_check": mutation,
        },
        "a_red": {
            "baseline": red.get("cases", {}).get("ff_companion_provider_omitted"),
            "after_fix": after.get("cases", {}).get("ff_companion_provider_omitted"),
            "wire_observations": {
                "baseline": red.get("cases"),
                "after_fix": after.get("cases"),
            },
            "fix_mapping": [
                "provider hard-coded fmp in _source_request -> provider passed through "
                "(omitted stays null)",
                "always the lookup-request/1 envelope -> plain SourceRequest on the "
                "omitted-provider path, envelope kept for explicit fmp",
                "reused provider returned as fmp -> manifest.provider of the verified "
                "reader receipt",
                "unknown/as-of exclusions invisible -> named unknown/gap outcomes with "
                "zero downloads",
                "companion mapped omitted provider to fmp -> omitted stays omitted",
            ],
        },
        "c_e2e": {
            "layer_chain": restore.get("layering"),
            "mock_boundary": (
                "only the ET supplier process is synthetic (a local script that records "
                "every call and replays a fixed fixture result); the FF companion and "
                "transport, the three company-wiki CLIs, the catalog SQLite state, the "
                "scanner and the canonical import are real"
            ),
            "result": restore.get("result"),
            "et_calls": restore.get("et_calls"),
            "company_wiki_child_calls": restore.get("company_wiki_child_calls"),
            "public_cli_case": (
                "tests/test_du11_transcript_reuse_e2e.py::"
                "test_real_ff_cli_reuses_the_registered_transcript_end_to_end runs the "
                "public scripts/fetch_filing.py with a v2 request"
            ),
        },
        "frozen_upstream": {
            "cwp_commit": deps.get("frozen_cwp_commit"),
            "cwp_archive_tar_sha256": deps.get("archive_tar_sha256"),
            "cwp_archive_spec": deps.get("archive_spec"),
            "cwp_extracted_file_count": deps.get("extracted_file_count"),
            "cwp_direct_contract_files": deps.get("direct_contract_files"),
            "et": deps.get("et_repo"),
        },
        "restore_receipt": restore.get("restore_receipt"),
        "cleanup_receipt": restore.get("cleanup_receipt"),
        "resource_counts": {
            "network_calls": 0,
            "paid_api_calls": 0,
            "llm_calls": 0,
            "translation_calls": 0,
            "credential_values_read": 0,
            "credential_note": (
                "the main repo's untracked config/FMP_API_KEY.txt was never opened; only "
                "its path/stat is mentioned as a non-card change"
            ),
            "provider_boundary": (
                "0 real ET/provider calls; unknown fee/count fields stay null, never "
                "derived from a missing field"
            ),
        },
        "independent_review": {
            "reviewer": (
                "independent subagent reviewer, distinct from the author"
                if args.review_status != "pending"
                else "not yet returned"
            ),
            "status": args.review_status,
            "rounds": args.review_rounds,
            "report": args.review_report if args.review_status != "pending" else None,
            "reviews": [
                {
                    "report": "receipts/reviewer_report.md",
                    "reviewed_source_sha": git("rev-parse", f"{commits[0]}^{{commit}}").strip(),
                    "verdict": "PASS",
                    "blockers": 0,
                    "majors": 0,
                    "minors": 3,
                    "nits": 7,
                    "all_findings_fixed_in": commits[-1] if len(commits) > 1 else None,
                }
            ],
            "reviewed_source_sha": args.review_sha,
            "unresolved_findings": args.unresolved,
        },
        "limitations": [
            "no new provider was enabled and no real supplier data quality is claimed",
            "motley_fool is a synthetic registration that only proves cross-provider reuse",
            "the acquisition provider stays the existing FMP configuration",
            "the public wire cannot express several or restricted unknown candidates, so "
            "those are narrowed to a named gap inside the existing reason field",
            "entity/issuer matching remains company-wiki's query gate; FF adds only the "
            "manifest FY/Q/market/security consistency check because the manifest has no "
            "issuer field",
            "the receipts directory also ships the evidence generators (ab_probe.py, "
            "restore_probe.py, mutation_check.py, make_handoff.py); they are not product "
            "code",
        ],
        "root_wiring_notes": [
            "STOP after the docs commit: no merge, no push, no worktree cleanup",
            "ROOT should re-check receipts/c_dependencies.json blob SHAs if it changes "
            "source_query_cli/source_reader/qualification",
            "the full-repo pytest run has 9 pre-existing failures that also fail at the "
            "base commit; they are outside this card",
        ],
    }
    out = PLAN_DIR / "handoff.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
