"""Offline FF↔ET↔CWP contract-matrix runner (explicit manual entry point).

Run::

    python -B tools/offline_contract_matrix/run.py \
        --cwp-project <explicit-code-root> \
        --et-project  <explicit-code-root> \
        --owned-root  <new-root> \
        --out-root    <new-attempt-root>

The runner builds a fully isolated scratch (owned fixture wiki + configs), binds
the supplied CWP/ET code read-only via child PYTHONPATH, exercises the real
three-layer transcript chain and the coverage matrix, writes a
``ff-et-cwp-offline-matrix/1`` report plus per-case artifacts, runs the failure
vector oracle, and restores the pre-placed sentinel and baseline.

Every child runs with a minimal synthetic environment; there is no real network
and no real charge. Provider requests are fixture requests and are reported
separately from the real-cost ledger. Unknown usage/cost stays ``null``.
"""

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

# Older local test/fixture callers can import these names from the launcher.
from matrix_context import (  # noqa: E402
    BATCH_DEADLINE as BATCH_DEADLINE,
    CASE_TIMEOUT as CASE_TIMEOUT,
    Context as Context,
    FAKE_FMP_KEY as FAKE_FMP_KEY,
    ProductionGuard as ProductionGuard,
    PROOF_RESERVE_SECONDS as PROOF_RESERVE_SECONDS,
    SENTINEL_CONTENT as SENTINEL_CONTENT,
    SENTINEL_NAME as SENTINEL_NAME,
    _companion as _companion,
    _mk_filing_request as _mk_filing_request,
)

if __name__ == "__main__":
    from cli_main import main as _main

    raise SystemExit(_main())
