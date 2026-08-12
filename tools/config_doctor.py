"""Three-repo contract compatibility doctor (FC-1202).

The single policy source is company-wiki's ``config/source_catalog.yaml``
(RootPolicySnapshot); the filing-fetch and revenue configs only locate their
upstream repos.  This doctor hardcodes NO root paths — the pre-FC-1202 CI
block hardcoded three paths and read ``allowed_handle_roots``, a config key
FC-501 removed (that block was stale and would always fail).

Checks:

1. filing-fetch ``config/company_wiki.json``: exactly {schema_version,
   company_wiki_root}; absolute after token expansion; the wiki root exists
   and carries ``config/source_catalog.yaml``; must NOT carry
   ``allowed_handle_roots`` (FC-501 / CONFIG-DBX-03).
2. company-wiki ``source_catalog.yaml``: schema_version present;
   ``reusable_root_kinds`` is a non-empty list of non-empty strings;
   ``roots`` is a list.  Structural only — no path lists duplicated.
3. revenue ``config/filing_fetch.json`` (when ``--revenue-root`` is given):
   exactly {schema_version, filing_fetch_root}; absolute after expansion;
   the root carries ``scripts/fetch_filing.py``.  An older revenue checkout
   without the config file is skipped honestly (reported as a note, never a
   fabricated green verdict).

Exit code 0 = healthy, 1 = problems found.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILING_CONFIG = SKILL_ROOT / "config" / "company_wiki.json"

_TOKEN_RE = re.compile(r"\$\{(SKILL_ROOT|USER_PROFILE)\}")


def _tokens() -> dict[str, str]:
    return {
        "SKILL_ROOT": str(SKILL_ROOT),
        "USER_PROFILE": os.environ.get("USERPROFILE") or str(Path.home()),
    }


def _expand(text: str) -> str:
    return _TOKEN_RE.sub(lambda match: _tokens()[match.group(1)], text)


def _check_filing_config(
    path: Path, problems: list[str], notes: list[str]
) -> Path | None:
    """Validate the filing-fetch config; return the resolved wiki root."""
    if not path.is_file():
        problems.append(f"filing-fetch config missing: {path}")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"filing-fetch config unreadable: {path}: {exc}")
        return None
    if not isinstance(payload, dict):
        problems.append("filing-fetch config must be an object")
        return None
    if "allowed_handle_roots" in payload:
        problems.append(
            "filing-fetch config must NOT carry allowed_handle_roots "
            "(FC-501: the policy snapshot is the single source)"
        )
    if set(payload) != {"schema_version", "company_wiki_root"}:
        problems.append(
            "filing-fetch config must contain exactly "
            "schema_version/company_wiki_root"
        )
        return None
    if payload["schema_version"] != "1.0":
        problems.append(
            f"filing-fetch config schema_version must be 1.0, got "
            f"{payload['schema_version']!r}"
        )
        return None
    configured = payload["company_wiki_root"]
    if not isinstance(configured, str) or not configured.strip():
        problems.append(
            "filing-fetch config company_wiki_root must be non-empty text"
        )
        return None
    expanded = _expand(configured)
    if "${" in expanded:
        problems.append(
            f"filing-fetch config company_wiki_root has an unsupported "
            f"token: {configured}"
        )
        return None
    root = Path(expanded).expanduser()
    if not root.is_absolute():
        problems.append(
            "filing-fetch config company_wiki_root must be absolute after "
            "token expansion"
        )
        return None
    if not root.is_dir():
        problems.append(f"configured company_wiki_root is not a directory: {root}")
        return None
    catalog = root / "config" / "source_catalog.yaml"
    if not catalog.is_file():
        problems.append(
            f"configured company_wiki_root lacks config/source_catalog.yaml: "
            f"{root}"
        )
    return root


def _check_wiki_policy(root: Path, problems: list[str]) -> None:
    """Structural checks on company-wiki's source_catalog.yaml."""
    catalog = root / "config" / "source_catalog.yaml"
    if not catalog.is_file():
        return  # already reported by the filing-config check
    raw = catalog.read_text(encoding="utf-8")
    if raw.lstrip().startswith("{") and "\n" not in raw.strip():
        problems.append(
            f"wiki source_catalog.yaml looks like a single-line JSON "
            f"fixture, not YAML: {catalog}"
        )
        return
    try:
        import yaml

        payload = yaml.safe_load(raw)
    except Exception as exc:  # noqa: BLE001 - report every failure mode
        problems.append(f"wiki source_catalog.yaml failed to parse: {exc}")
        return
    if not isinstance(payload, dict):
        problems.append("wiki source_catalog.yaml must be a mapping")
        return
    if "schema_version" not in payload:
        problems.append("wiki source_catalog.yaml lacks schema_version")
    kinds = payload.get("reusable_root_kinds")
    if (
        not isinstance(kinds, list)
        or not kinds
        or any(not isinstance(kind, str) or not kind.strip() for kind in kinds)
    ):
        problems.append(
            "wiki source_catalog.yaml reusable_root_kinds must be a "
            "non-empty list of non-empty strings"
        )
    if not isinstance(payload.get("roots"), list):
        problems.append("wiki source_catalog.yaml roots must be a list")


def _check_revenue_config(
    revenue_root: Path, problems: list[str], notes: list[str]
) -> None:
    """Validate revenue's config/filing_fetch.json when present."""
    config = revenue_root / "config" / "filing_fetch.json"
    if not config.is_file():
        notes.append(
            f"NOTE: revenue config/filing_fetch.json not present at "
            f"{revenue_root} — revenue-filing check skipped (older checkout?)"
        )
        return
    try:
        payload = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"revenue config unreadable: {config}: {exc}")
        return
    if not isinstance(payload, dict):
        problems.append("revenue config must be an object")
        return
    if set(payload) != {"schema_version", "filing_fetch_root"}:
        problems.append(
            "revenue config must contain exactly schema_version/"
            "filing_fetch_root"
        )
        return
    if payload["schema_version"] != "1.0":
        problems.append(
            f"revenue config schema_version must be 1.0, got "
            f"{payload['schema_version']!r}"
        )
        return
    configured = payload["filing_fetch_root"]
    if not isinstance(configured, str) or not configured.strip():
        problems.append(
            "revenue config filing_fetch_root must be non-empty text"
        )
        return
    expanded = _expand(configured)
    if "${" in expanded:
        problems.append(
            f"revenue config filing_fetch_root has an unsupported token: "
            f"{configured}"
        )
        return
    root = Path(expanded).expanduser()
    if not root.is_absolute():
        problems.append(
            "revenue config filing_fetch_root must be absolute after token "
            "expansion"
        )
        return
    if not (root / "scripts" / "fetch_filing.py").is_file():
        problems.append(
            f"revenue config filing_fetch_root lacks scripts/fetch_filing.py: "
            f"{root}"
        )


def diagnose(
    filing_config: Path | None = None,
    revenue_root: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Return (problems, notes); healthy when problems is empty."""
    problems: list[str] = []
    notes: list[str] = []
    wiki_root = _check_filing_config(
        filing_config or DEFAULT_FILING_CONFIG, problems, notes
    )
    if wiki_root is not None:
        _check_wiki_policy(wiki_root, problems)
    if revenue_root is not None:
        _check_revenue_config(revenue_root, problems, notes)
    return problems, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Three-repo contract compatibility doctor (FC-1202)."
    )
    parser.add_argument(
        "--filing-config",
        type=Path,
        default=None,
        help="filing-fetch config/company_wiki.json "
        "(default: <skill-root>/config/company_wiki.json)",
    )
    parser.add_argument(
        "--revenue-root",
        type=Path,
        default=None,
        help="revenue-forecast checkout to check config/filing_fetch.json "
        "(skipped when absent)",
    )
    args = parser.parse_args(argv)
    problems, notes = diagnose(
        filing_config=args.filing_config, revenue_root=args.revenue_root
    )
    for note in notes:
        print(note)
    for problem in problems:
        print(f"CONFIG-PROBLEM: {problem}")
    if not problems:
        print("OK: three-repo configs healthy")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
