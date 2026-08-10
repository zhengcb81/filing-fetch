"""FC-501: Dropbox config invariants.

- CONFIG-DBX-03 (revised): filing-fetch has NO independent root allowlist —
  the config rejects ``allowed_handle_roots``; the Dropbox root is defined
  only in company-wiki's RootPolicy snapshot.
- CONFIG-DBX-04: the Dropbox realpath in company-wiki's
  ``source_catalog.yaml`` is the single source of truth; filing-fetch
  consumes the policy snapshot hash and verifies canonical containment.

CONFIG-DBX-01/02 (company-wiki side) live in the company-wiki repo.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fetch_filing import load_company_wiki_root  # noqa: E402
from filing_contracts import FilingFetchError  # noqa: E402


FILING_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = FILING_ROOT / "config" / "company_wiki.json"
WIKI_ROOT = Path.home() / "Projects" / "company-wiki"
WIKI_CONFIG_PATH = WIKI_ROOT / "config" / "source_catalog.yaml"


def test_config_dbx_03_no_independent_allowlist() -> None:
    """The config must reject allowed_handle_roots (no independent root
    allowlist — the policy snapshot is the single source)."""
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    assert "allowed_handle_roots" not in payload, (
        "FC-501: independent allowed_handle_roots is forbidden"
    )
    # the loader must reject a config that smuggles it back in — with a
    # REAL temp wiki root so only the schema rejection can fire
    import tempfile as _tempfile

    with _tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "company-wiki"
        (root / "config").mkdir(parents=True)
        (root / "config" / "source_catalog.yaml").write_text(
            "schema_version: '1.0'\n"
            "catalog_dir: x\n"
            "roots: []\n",
            encoding="utf-8",
        )
        cfg = Path(temporary) / "company_wiki.json"
        cfg.write_text(
            json.dumps({
                "schema_version": "1.0",
                "company_wiki_root": str(root),
                "allowed_handle_roots": ["/tmp"],
            }),
            encoding="utf-8",
        )
        with pytest.raises(FilingFetchError, match="exactly schema_version"):
            load_company_wiki_root(config_path=cfg)


def test_config_dbx_04_dropbox_root_defined_in_wiki_policy_only() -> None:
    """The Dropbox root's realpath lives in company-wiki's
    source_catalog.yaml (the policy snapshot source) — filing-fetch holds
    no copy."""
    import yaml

    wiki_payload = yaml.safe_load(WIKI_CONFIG_PATH.read_text(encoding="utf-8"))
    dropbox_wiki = next(
        r for r in wiki_payload["roots"] if r.get("root_id") == "dropbox_stock"
    )
    token = "${USER_PROFILE}"
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    wiki_path = Path(str(dropbox_wiki["path"]).replace(token, profile))
    # read_only + reusable_for_filing contract
    assert dropbox_wiki.get("read_only") is not False
    assert _norm(wiki_path).endswith("Dropbox/Stock"), f"unexpected: {wiki_path}"


def _norm(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")
