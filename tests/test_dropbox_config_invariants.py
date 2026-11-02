"""FC-501: Dropbox config invariants.

- CONFIG-DBX-03 (revised): filing-fetch has NO independent root allowlist —
  the config rejects ``allowed_handle_roots``; the Dropbox root is defined
  only in company-wiki's RootPolicy snapshot.
- CONFIG-DBX-04: the producer policy assertion lives in the ROOT source-system suite.

CONFIG-DBX-01/02 (company-wiki side) live in the company-wiki repo.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fetch_filing import load_company_wiki_root  # noqa: E402
from filing_contracts import FilingFetchError  # noqa: E402


FILING_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = FILING_ROOT / "config" / "company_wiki.json"


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
        with pytest.raises(FilingFetchError) as error:
            load_company_wiki_root(config_path=cfg)
        assert error.value.code == "config_error"
        assert "allowed_handle_roots" in str(error.value)
