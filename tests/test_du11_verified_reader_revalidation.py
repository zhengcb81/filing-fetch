"""Current verified reader metadata must requalify an old query hit."""
import pytest

from transcript_companion import resolve_companion_transcript
from test_du11_transcript_reuse_contract import (
    FakeCWP, LOCAL_RAW, build, companion_request, filing, query_found, reader_entry,
)


def run_current_reader(tmp_path, monkeypatch, **manifest):
    tool = tmp_path / "offline_tool.py"
    tool.write_text("# child calls are intercepted\n", encoding="utf-8")
    entry = reader_entry(LOCAL_RAW)
    entry["receipt"]["manifest"].update(manifest)
    fake = FakeCWP(queries=[query_found(LOCAL_RAW)], reader=[entry])
    result = resolve_companion_transcript(
        request=companion_request(), filing_handle=filing(),
        transport=build(monkeypatch, fake, tool),
    )
    assert fake.kinds() == ["query", "reader"]
    assert fake.count("et") == fake.count("import") == 0
    return result


@pytest.mark.parametrize("published,reason", [
    ("2027-01-01", "publication_after_as_of"),
    ("not-a-date", "publication_date_invalid"),
    (None, "publication_date_unknown"),
])
def test_current_reader_date_cannot_inherit_query_qualification(tmp_path, monkeypatch, published, reason):
    result = run_current_reader(tmp_path, monkeypatch, published_date=published)
    assert result["status"] != "reused", result
    assert result["reason"] == reason
    assert result.get("as_of_cutoff_verified") is not True


def test_us_zero_prefixed_security_is_a_different_security(tmp_path, monkeypatch):
    result = run_current_reader(tmp_path, monkeypatch, security_id="0MSFT")
    assert result["status"] == "upstream_error", result
    assert result["reason"] == "transcript_lookup_identity_mismatch"


@pytest.mark.parametrize("published", ["2026-09-30", "2024-02-29"])
def test_current_valid_date_is_requalified_including_cutoff_boundary(tmp_path, monkeypatch, published):
    result = run_current_reader(tmp_path, monkeypatch, published_date=published)
    assert result["status"] == "reused"
    assert result["publication_date"] == published
    assert result["as_of_cutoff_verified"] is True


@pytest.mark.parametrize("published", ["2026-02-30", "20260901", "2026-09-01T00:00:00", "", 20260901, True])
def test_current_invalid_date_family_is_not_qualified(tmp_path, monkeypatch, published):
    result = run_current_reader(tmp_path, monkeypatch, published_date=published)
    assert result["status"] == "upstream_error"
    assert result["reason"] == "publication_date_invalid"


def test_missing_current_date_field_does_not_reinstate_old_date(tmp_path, monkeypatch):
    tool = tmp_path / "offline_tool.py"
    tool.write_text("# intercepted child\n", encoding="utf-8")
    entry = reader_entry(LOCAL_RAW)
    entry["receipt"]["manifest"].pop("published_date")
    fake = FakeCWP(queries=[query_found(LOCAL_RAW)], reader=[entry])
    result = resolve_companion_transcript(request=companion_request(), filing_handle=filing(),
        transport=build(monkeypatch, fake, tool))
    assert result["status"] == "unknown_publication"
    assert result["publication_date"] is None
    assert result["as_of_cutoff_verified"] is False
    assert fake.kinds() == ["query", "reader"]


def test_explicit_provider_constraint_requires_current_provider_proof(tmp_path, monkeypatch):
    tool = tmp_path / "offline_tool.py"
    tool.write_text("# intercepted child\n", encoding="utf-8")
    fake = FakeCWP(queries=[query_found(LOCAL_RAW)], reader=[reader_entry(LOCAL_RAW, provider=None)])
    result = resolve_companion_transcript(request=companion_request(provider="fmp"),
        filing_handle=filing(), transport=build(monkeypatch, fake, tool))
    assert result["status"] == "upstream_error"
    assert result["reason"] == "transcript_provider_mismatch"
    assert fake.kinds() == ["query", "reader"]


@pytest.mark.parametrize("expected,actual", [("MSFT", "0MSFT"), ("000001", "1"), ("000001", "0000001")])
def test_security_prefixes_are_not_a_generic_equivalence_rule(expected, actual):
    from transcript_tool_transport import EarningsTranscriptsTransport
    market = "US" if expected == "MSFT" else "CN"
    assert EarningsTranscriptsTransport._manifest_conflicts(
        {"manifest": {"market": market, "security_id": actual}},
        {"market": market, "security_id": expected})


@pytest.mark.parametrize("market,canonical,observed", [("HK", "09896", "9896"), ("CN", "000001", "1")])
def test_canonical_projection_is_owned_by_reader_not_renormalized_in_ff(tmp_path, monkeypatch, market, canonical, observed):
    tool = tmp_path / "offline_tool.py"
    tool.write_text("# intercepted child\n", encoding="utf-8")
    entry = reader_entry(LOCAL_RAW, market=market, security_id=observed)
    entry["receipt"]["canonical_identity"] = {
        "schema_version": "source-canonical-identity/1", "market": market, "security_id": canonical}
    fake = FakeCWP(queries=[query_found(LOCAL_RAW)], reader=[entry])
    handle = filing()
    handle["company_identity"].update(market=market, security_id=canonical)
    result = resolve_companion_transcript(request=companion_request(), filing_handle=handle,
        transport=build(monkeypatch, fake, tool))
    assert result["status"] == "reused", result
    assert "--include-canonical-identity" in fake.calls[1][1]
    assert fake.kinds() == ["query", "reader"]


def test_direct_noncanonical_verified_fixture_is_not_silently_padded():
    from transcript_tool_transport import EarningsTranscriptsTransport
    assert EarningsTranscriptsTransport._manifest_conflicts(
        {"manifest": {"market": "HK", "security_id": "9896"},
         "canonical_identity": {"schema_version": "source-canonical-identity/1", "market": "HK", "security_id": "09896"}},
        {"market": "HK", "security_id": "9896"})


@pytest.mark.parametrize("projection", [None, {}, {"schema_version": "wrong", "market": "US", "security_id": "MSFT"},
    {"schema_version": "source-canonical-identity/1", "market": "US", "security_id": "0MSFT"}])
def test_bad_current_identity_projection_cannot_fall_back_to_manifest(projection):
    from transcript_tool_transport import EarningsTranscriptsTransport
    assert EarningsTranscriptsTransport._manifest_conflicts(
        {"manifest": {"market": "US", "security_id": "MSFT"}, "canonical_identity": projection},
        {"market": "US", "security_id": "MSFT"})
