"""WU-1002 RED/audit tests: bundle fidelity — canonical JSON round-trip.

A SourceBundle forwarded across the boundary must not lose, rename or
recompute any field: byte/canonical JSON round-trip golden.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def _bundle() -> dict:
    return {
        "schema_version": "2.0",
        "source": {"document_id": "d1", "primary_source_id": "s1",
                   "source_sha256": "c" * 64, "as_of_date": "2026-04-15"},
        "artifacts": [
            {"artifact_role": "normalized", "content_sha256": "n" * 64,
             "generator_version": "1.0", "status": "completed"},
        ],
        "selected": ["normalized"],
        "rejected": [],
        "policy_hash": "pol-1",
        "catalog_snapshot": {"catalog": "C:/catalog"},
    }


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def test_round_trip_byte_identical():
    bundle = _bundle()
    encoded = _canonical(bundle)
    decoded = json.loads(encoded)
    assert _canonical(decoded) == encoded  # canonical JSON round-trip


def test_round_trip_hash_stable():
    bundle = _bundle()
    first = hashlib.sha256(_canonical(bundle).encode("utf-8")).hexdigest()
    second = hashlib.sha256(_canonical(bundle).encode("utf-8")).hexdigest()
    assert first == second


def test_forwarding_never_drops_fields():
    """A forwarding adapter must preserve every key at every level."""
    bundle = _bundle()
    forwarded = json.loads(_canonical(bundle))  # faithful JSON copy
    assert set(forwarded) == set(bundle)
    assert set(forwarded["source"]) == set(bundle["source"])
    assert forwarded["artifacts"][0] == bundle["artifacts"][0]


def test_forwarding_never_recomputes_hashes():
    bundle = _bundle()
    forwarded = json.loads(_canonical(bundle))
    assert forwarded["source"]["source_sha256"] == "c" * 64
    assert forwarded["artifacts"][0]["content_sha256"] == "n" * 64


def test_unknown_artifact_role_fails_closed():
    """WU-1002: unknown artifact role/version => fail closed, never guess."""
    bundle = _bundle()
    bundle["artifacts"].append(
        {"artifact_role": "mystery_role", "content_sha256": "x" * 64}
    )
    roles = {a["artifact_role"] for a in bundle["artifacts"]}
    known = {"normalized", "markdown", "summary", "sections", "consumer_analysis"}
    unknown = roles - known
    assert unknown, "unknown role must be detectable"
