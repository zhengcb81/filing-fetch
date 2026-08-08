"""WU-2A.1: Dropbox config-only invariants (CONFIG-DBX-03/04).

- CONFIG-DBX-03: the expanded ``allowed_handle_roots`` is EXACTLY the three
  realpaths (companies, dayu portfolio, Dropbox Stock) — no parent dir,
  no wildcard, no similar prefix.
- CONFIG-DBX-04: the Dropbox realpath here equals the realpath resolved
  from company-wiki's ``source_catalog.yaml``; either side missing, typo'd,
  or pointing to a different case/link target fails.

CONFIG-DBX-01/02 (company-wiki side) live in the company-wiki repo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


FILING_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = FILING_ROOT / "config" / "company_wiki.json"
WIKI_ROOT = Path.home() / "Projects" / "company-wiki"
WIKI_CONFIG_PATH = WIKI_ROOT / "config" / "source_catalog.yaml"


@pytest.fixture()
def allowance() -> tuple[Path, ...]:
    import sys

    sys.path.insert(0, str(FILING_ROOT / "scripts"))
    from fetch_filing import load_handle_allowance

    return load_handle_allowance(config_path=CONFIG_PATH, wiki_root=WIKI_ROOT)


def _norm(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def test_config_dbx_03_allowance_exactly_three_roots(allowance) -> None:
    normalized = [_norm(p) for p in allowance]
    expected = [
        _norm(WIKI_ROOT / "companies"),
        _norm(Path.home() / "Projects" / "dayu-agent" / "workspace" / "portfolio"),
        _norm(Path.home() / "Dropbox" / "Stock"),
    ]
    assert normalized == expected, f"allowance mismatch: {normalized} != {expected}"


def test_config_dbx_03_no_parent_dir_no_wildcard_no_prefix() -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    raw = payload["allowed_handle_roots"]
    assert isinstance(raw, list)
    for entry in raw:
        assert "*" not in entry, f"wildcard not allowed: {entry}"
        assert "?" not in entry, f"wildcard not allowed: {entry}"
        assert not entry.rstrip("/").endswith("Dropbox"), (
            f"parent dir Dropbox not allowed (must be Dropbox/Stock): {entry}"
        )
        assert not entry.rstrip("/").endswith("portfolio/"), (
            f"prefix-like entry not allowed: {entry}"
        )


def test_config_dbx_04_cross_repo_realpath_identical(allowance) -> None:
    import yaml

    wiki_payload = yaml.safe_load(WIKI_CONFIG_PATH.read_text(encoding="utf-8"))
    dropbox_wiki = next(
        r for r in wiki_payload["roots"] if r.get("root_id") == "dropbox_stock"
    )
    token = "${USER_PROFILE}"
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    wiki_path = Path(str(dropbox_wiki["path"]).replace(token, profile))
    allowance_dropbox = next(
        p for p in allowance if _norm(p).endswith("Dropbox/Stock")
    )
    assert _norm(wiki_path) == _norm(allowance_dropbox), (
        f"Dropbox realpath drift: wiki={wiki_path} filing={allowance_dropbox}"
    )
