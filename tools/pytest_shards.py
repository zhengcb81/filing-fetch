"""Deterministic partitions of the complete FF test inventory."""

from __future__ import annotations

from argparse import ArgumentTypeError
from hashlib import sha256

import pytest


def parse_shard(value: str) -> tuple[int, int]:
    try:
        index, count = map(int, value.split("/"))
        if 0 <= index < count:
            return index, count
    except ValueError:
        pass
    raise ArgumentTypeError("expected zero-based SHARD/COUNT")


def shard_for(nodeid: str, count: int) -> int:
    return int.from_bytes(sha256(nodeid.encode("utf-8")).digest()[:8], "big") % count


def pytest_addoption(parser) -> None:
    parser.addoption("--ff-shard", metavar="SHARD/COUNT", type=parse_shard)


def pytest_collection_modifyitems(config, items) -> None:
    shard = config.getoption("--ff-shard")
    if shard is None:
        return
    if config.getoption("collectonly"):
        raise pytest.UsageError("the canonical FF inventory cannot be sharded")
    index, count = shard
    included, excluded = [], []
    for item in items:
        bucket = included if shard_for(item.nodeid, count) == index else excluded
        bucket.append(item)
    config.hook.pytest_deselected(items=excluded)
    items[:] = included
