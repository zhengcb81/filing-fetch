# Changelog

## v1.0.0 — 2026-07-22

- Extracted the on-demand, market-routed filing fetch out of `revenue-forecast` (`company_wiki_source.py`) into a standalone, reusable skill.
- Thin client over company-wiki's acquisition engine: identify → resolve (reuse) → ensure (download only with `--allow-download`); routing CN→StockInfo/cninfo, HK/US→dayu is owned by company-wiki.
- Fixed the unreachable CLI: added the `if __name__ == "__main__"` guard so `python scripts/fetch_filing.py` actually runs.
- Revenue-specific capture-record building (`build_revenue_source_record`) remains in revenue-forecast; this skill returns a generic capture-ready handle.
- Ported 12 fetch contracts from revenue-forecast's test suite.
