"""DU10-FF41-CLOSE — behaviour reds for the confirmed duplicate preparation.

Drives the real ``cli_main.main`` with the REAL fixed 41-case registry and a
Context whose process-launching preparation (``warm_seed_batch``/``scan``) is
recorded instead of executed, then asserts the per-group warm-preparation
contract:

* each catalog's warm-seed submission is exactly the subset of the fixed warm
  list its cases reference, including legacy cases with a private catalog;
* the union across catalogs is the full fixed warm list.
"""

from __future__ import annotations

import json
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools" / "offline_contract_matrix"
sys.path[:0] = [str(TOOLS), str(ROOT / "scripts")]

import cli_main  # noqa: E402
import case_scheduling  # noqa: E402
from case_specs import case_specs, get_spec  # noqa: E402
from fixture_builder import ScratchEnvironment  # noqa: E402
from run import Context  # noqa: E402

original_seed_original = ScratchEnvironment.seed_original


def _fixed_warm_keys() -> set:
    keys = set()
    for market in ("CN", "HK", "US"):
        for kind, period in (("annual_report", "FY"), ("semi_annual_report", "S1"),
                             ("quarterly_report", "Q1")):
            keys.add((market, kind, 2024, period))
    keys.add(("US", "annual_report", 2025, "FY"))
    return keys


TXT_KEY = ("US", "investor_call_transcript", 2024, "Q2")


def _referenced_warm_keys(spec) -> set:
    """Independent derivation of a case's warm keys from the frozen authority.

    Test-side specification of the desired contract: a run whose filing (or
    companion) row carries ``reuse_only`` intent names the warm key its group
    wiki must answer. Keys outside the fixed warm list are intentional gaps.
    """
    keys = set()
    for run in spec.runs:
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
                          row.get("fiscal_year"),
                          f"Q{quarter}" if quarter is not None else None))
    return keys


def _expected_groups(workers=2):
    registry = [(spec.id, spec.execute) for spec in case_specs()]
    entries = list(enumerate(registry))
    cost = case_scheduling.static_cost(entries)
    groups = case_scheduling.assign_groups(entries, workers=workers, cost=cost)
    return [[cid for _pos, (cid, _runner) in group] for group in groups]


def _proof_stdout() -> bytes:
    return json.dumps({"schema_version": "w06-fresh-source-proofs/1",
                       "proofs": {}, "catalog_snapshot": []}).encode("utf-8")


def _drive_main(tmp_path, recorded_batches, recorded_scans, *, workers=2,
                seed_original_recorder=None):
    """Run cli_main.main on the real registry without launching any child."""

    def fake_batch(self, seeds):
        recorded_batches.append((self.artifact_prefix, [tuple(seed) for seed in seeds]))
        return [{"tag": f"{self.artifact_prefix}seed_{identity.market.lower()}_{kind}_{year}_{period}",
                 "request_argv": ["ensure"], "exit_code": 0, "response": {"status": "ok"},
                 "response_ref": "r.json", "response_sha256": "0" * 64,
                 "source_ref": None, "counts": {"adapter_invocations": 0, "fixture_requests": 0}}
                for identity, kind, year, period in seeds]

    def fake_scan(self):
        recorded_scans.append(self.artifact_prefix)

    def fake_run_process(command, *, env, cwd, deadline, input=None):
        deadline.remaining()  # same pre-launch rejection the real runtime enforces
        return SimpleNamespace(returncode=0, stdout=_proof_stdout(), stderr=b"")

    def fake_dependency(repository, root, modules, **kwargs):
        from report import Dependency
        return Dependency(repository=repository, root=str(root), head="unknown", modules=[])

    with ExitStack() as stack:
        stack.enter_context(patch.object(Context, "warm_seed_batch", fake_batch))
        stack.enter_context(patch.object(Context, "scan", fake_scan))
        if seed_original_recorder is not None:
            stack.enter_context(patch("fixture_builder.ScratchEnvironment.seed_original",
                                      seed_original_recorder))
        stack.enter_context(patch.object(cli_main, "run_process", fake_run_process))
        stack.enter_context(patch("run.run_process", fake_run_process))
        stack.enter_context(patch.object(cli_main, "_verify_binding",
                                         return_value={"verified": True}))
        stack.enter_context(patch.object(cli_main, "_dependency", fake_dependency))
        stack.enter_context(patch.object(cli_main, "_module_record", return_value={}))
        cli_main.main([
            "--cwp-project", str(tmp_path / "cwp"),
            "--et-project", str(tmp_path / "et"),
            "--owned-root", str(tmp_path / "owned"),
            "--out-root", str(tmp_path / "out"),
            "--workers", str(workers),
        ])


def _seed_key(seed_tuple):
    identity, kind, year, period = seed_tuple
    return (identity.market, kind, year, period)


def _expected_catalog_cases(workers):
    # Independent test requirement. Marking an additional test as private in
    # the registry cannot accidentally weaken the owner seed assertions.
    private = {"local_txt_exact_reuse", "incomplete_sidecar_metadata_gap"}
    owned = {}
    for index, members in enumerate(_expected_groups(workers), start=1):
        prefix = f"g{index}."
        owned[prefix] = [cid for cid in members if cid not in private]
        owned.update({f"{prefix}{cid}.": [cid] for cid in members if cid in private})
    return owned


@pytest.mark.parametrize("workers", [1, 2])
def test_each_catalog_warm_seed_batch_covers_only_its_consumed_keys(tmp_path, workers):
    recorded_batches, recorded_scans = [], []
    _drive_main(tmp_path, recorded_batches, recorded_scans, workers=workers)

    fixed = _fixed_warm_keys()
    observed = {prefix: {_seed_key(seed) for seed in seeds}
                for prefix, seeds in recorded_batches}
    expected = {}
    for prefix, case_ids in _expected_catalog_cases(workers).items():
        wanted = set().union(*(_referenced_warm_keys(get_spec(cid)) for cid in case_ids))
        if wanted & fixed:
            expected[prefix] = wanted & fixed
    assert len(recorded_batches) == len(expected)
    assert observed == expected
    assert set().union(*observed.values()) == fixed


def test_txt_transcript_seed_lands_only_in_its_own_catalog(tmp_path):
    recorded_batches, recorded_scans, txt_seeded = [], [], []

    def recording_seed_original(self, identity, *args, **kwargs):
        if kwargs.get("document_kind") == "investor_call_transcript":
            txt_seeded.append(self.scratch)
        return original_seed_original(self, identity, *args, **kwargs)

    _drive_main(tmp_path, recorded_batches, recorded_scans,
                seed_original_recorder=recording_seed_original)
    owning_group = next(f"g{i}" for i, case_ids in enumerate(_expected_groups(), start=1)
                        if "local_txt_exact_reuse" in case_ids)
    assert len(txt_seeded) == 1
    assert txt_seeded[0].parent.name == owning_group
    assert txt_seeded[0].name.startswith("c")
    assert recorded_scans.count(f"{owning_group}.local_txt_exact_reuse.") == 1


def test_gap_keys_are_never_seeded_even_when_referenced(tmp_path):
    recorded_batches, _ = [], []
    _drive_main(tmp_path, recorded_batches, [])
    fixed_tags = {f"seed_{market.lower()}_{kind}_{year}_{period}"
                  for market, kind, year, period in _fixed_warm_keys()}
    for _prefix, seeds in recorded_batches:
        for identity, kind, year, period in seeds:
            tag = f"seed_{identity.market.lower()}_{kind}_{year}_{period}"
            assert tag in fixed_tags, (
                f"{tag} is not a fixed warm seed; intentional gaps must never be prepared"
            )
    tags = {f"seed_{identity.market.lower()}_{kind}_{year}_{period}"
            for _prefix, seeds in recorded_batches
            for identity, kind, year, period in seeds}
    assert tags == fixed_tags, "the union of groups still prepares every fixed warm seed"


def test_seed_plan_for_rejects_unknown_case_ids():
    import matrix_cases

    with pytest.raises(ValueError, match="unknown case id"):
        matrix_cases.seed_plan_for(["not_a_fixed_case"])
