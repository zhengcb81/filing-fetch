"""FC-1202 — tools/config_doctor.py three-repo contract compatibility.

The single policy source is company-wiki's source_catalog.yaml; the
filing-fetch and revenue configs only locate their upstream repos.  The
doctor hardcodes NO root paths (the pre-FC-1202 CI block hardcoded three
paths and read a config key that FC-501 removed — that block was stale and
would always fail).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from config_doctor import diagnose  # noqa: E402


_WIKI_YAML = (
    'schema_version: "1.0"\n'
    'reusable_root_kinds: [company_raw, dayu_portfolio, directory]\n'
    "roots:\n"
    "  - root_id: company_raw\n"
    '    path: "${PROJECT_ROOT}/companies"\n'
)


def _write_wiki(directory: Path, yaml_text: str | None = None) -> Path:
    wiki = directory / "wiki"
    (wiki / "config").mkdir(parents=True)
    (wiki / "config" / "source_catalog.yaml").write_text(
        yaml_text if yaml_text is not None else _WIKI_YAML, encoding="utf-8"
    )
    return wiki


def _write_filing_config(directory: Path, payload: object) -> Path:
    path = directory / "company_wiki.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_fake_filing_skill(directory: Path) -> Path:
    skill = directory / "filing-skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "scripts" / "fetch_filing.py").write_text("", encoding="utf-8")
    return skill


def _write_revenue_config(directory: Path, payload: object) -> Path:
    revenue = directory / "revenue"
    (revenue / "config").mkdir(parents=True)
    (revenue / "config" / "filing_fetch.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    return revenue


def test_healthy_three_repo_config_passes(tmp_path: Path) -> None:
    wiki = _write_wiki(tmp_path)
    filing_config = _write_filing_config(
        tmp_path, {"schema_version": "1.0", "company_wiki_root": str(wiki)}
    )
    skill = _write_fake_filing_skill(tmp_path)
    revenue = _write_revenue_config(
        tmp_path, {"schema_version": "1.0", "filing_fetch_root": str(skill)}
    )
    problems, notes = diagnose(
        filing_config=filing_config, revenue_root=revenue
    )
    assert problems == [], problems
    assert notes == []


def test_filing_config_missing_fails(tmp_path: Path) -> None:
    problems, _ = diagnose(
        filing_config=tmp_path / "nope.json", revenue_root=None
    )
    assert any("config missing" in p for p in problems)


def test_filing_config_smuggled_allowlist_fails(tmp_path: Path) -> None:
    # CONFIG-DBX-03 mirror: a config smuggling back an independent
    # allowed_handle_roots is a contract violation (FC-501).
    wiki = _write_wiki(tmp_path)
    filing_config = _write_filing_config(
        tmp_path,
        {
            "schema_version": "1.0",
            "company_wiki_root": str(wiki),
            "allowed_handle_roots": ["/Dropbox/Stock"],
        },
    )
    problems, _ = diagnose(filing_config=filing_config, revenue_root=None)
    assert any("allowed_handle_roots" in p for p in problems)


def test_filing_config_relative_root_fails(tmp_path: Path) -> None:
    _write_wiki(tmp_path)
    filing_config = _write_filing_config(
        tmp_path, {"schema_version": "1.0", "company_wiki_root": "wiki"}
    )
    problems, _ = diagnose(filing_config=filing_config, revenue_root=None)
    assert any("absolute" in p for p in problems)


def test_filing_config_root_without_source_catalog_fails(tmp_path: Path) -> None:
    bare = tmp_path / "bare-wiki"
    bare.mkdir()
    filing_config = _write_filing_config(
        tmp_path, {"schema_version": "1.0", "company_wiki_root": str(bare)}
    )
    problems, _ = diagnose(filing_config=filing_config, revenue_root=None)
    assert any("source_catalog.yaml" in p for p in problems)


def test_wiki_yaml_missing_reusable_kinds_fails(tmp_path: Path) -> None:
    wiki = _write_wiki(
        tmp_path,
        yaml_text=(
            'schema_version: "1.0"\n'
            "roots:\n"
            "  - root_id: company_raw\n"
            '    path: "${PROJECT_ROOT}/companies"\n'
        ),
    )
    filing_config = _write_filing_config(
        tmp_path, {"schema_version": "1.0", "company_wiki_root": str(wiki)}
    )
    problems, _ = diagnose(filing_config=filing_config, revenue_root=None)
    assert any("reusable_root_kinds" in p for p in problems)


def test_wiki_yaml_single_line_json_fixture_fails(tmp_path: Path) -> None:
    # N-05 signature (mirrored from company-wiki's own doctor): the YAML was
    # overwritten by a single-line JSON fixture.
    wiki = _write_wiki(
        tmp_path,
        yaml_text='{"schema_version": "1.0", "roots": []}',
    )
    filing_config = _write_filing_config(
        tmp_path, {"schema_version": "1.0", "company_wiki_root": str(wiki)}
    )
    problems, _ = diagnose(filing_config=filing_config, revenue_root=None)
    assert any("JSON fixture" in p for p in problems)


def test_revenue_config_bad_root_fails(tmp_path: Path) -> None:
    wiki = _write_wiki(tmp_path)
    filing_config = _write_filing_config(
        tmp_path, {"schema_version": "1.0", "company_wiki_root": str(wiki)}
    )
    revenue = _write_revenue_config(
        tmp_path, {"schema_version": "1.0", "filing_fetch_root": "relative"}
    )
    problems, _ = diagnose(filing_config=filing_config, revenue_root=revenue)
    assert any("filing_fetch" in p for p in problems)


def test_revenue_config_missing_is_skipped_with_note(tmp_path: Path) -> None:
    # An older revenue checkout (pre-config) must be skipped honestly — the
    # doctor never fabricates a green three-repo verdict.
    wiki = _write_wiki(tmp_path)
    filing_config = _write_filing_config(
        tmp_path, {"schema_version": "1.0", "company_wiki_root": str(wiki)}
    )
    bare_revenue = tmp_path / "revenue-old"
    bare_revenue.mkdir()
    problems, notes = diagnose(
        filing_config=filing_config, revenue_root=bare_revenue
    )
    assert problems == [], problems
    assert any("skipped" in note for note in notes)


def test_user_profile_token_is_expanded(tmp_path: Path, monkeypatch) -> None:
    _write_wiki(tmp_path)
    filing_config = _write_filing_config(
        tmp_path,
        {"schema_version": "1.0", "company_wiki_root": "${USER_PROFILE}/wiki"},
    )
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    problems, _ = diagnose(filing_config=filing_config, revenue_root=None)
    assert problems == [], problems
