"""One public request's deployment configuration snapshot.

The context is a pure value object.  It is created once by a composition root
(the CLI, or a caller that already resolved a deployment config) and injected
into the business stages that need the same connection, so a single request
cannot observe two different ``WikiConnection`` snapshots for one config.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ff_company_wiki_connection import WikiEndpoint


@dataclass(frozen=True)
class RequestContext:
    """The config path and connection resolved for exactly one request."""

    config_path: Path
    connection: WikiEndpoint


__all__ = ["RequestContext"]
