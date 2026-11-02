"""Configured public CWP commands; only this deployment adapter knows legacy layout."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Mapping


OPERATIONS = frozenset({"catalog", "query", "local_prepare", "open", "transcript_import", "financial_statements"})
_MODULES = {"catalog": "cli", "query": "source_query_cli", "local_prepare": "local_prepare_cli",
            "open": "source_reader_cli", "transcript_import": "transcript_import_cli",
            "financial_statements": "financial_statements.cli"}


@dataclass(frozen=True)
class WikiConnection:
    workdir: Path
    commands: Mapping[str, tuple[str, ...]]
    acquisition_config: Path | None = None

    def __post_init__(self):
        directory = self.workdir.resolve(strict=True)
        if not directory.is_dir():
            raise ValueError("connection cwd must be a directory")
        if not isinstance(self.commands, Mapping):
            raise TypeError("connection commands must be a mapping")
        commands = {}
        for operation, command in self.commands.items():
            if operation not in OPERATIONS or not isinstance(command, (tuple, list)) or not command:
                raise ValueError("invalid connection operation/command")
            if any(not isinstance(arg, str) or not arg.strip() for arg in command):
                raise ValueError("invalid connection command argument")
            commands[operation] = tuple(command)
        object.__setattr__(self, "workdir", directory)
        object.__setattr__(self, "commands", MappingProxyType(commands))


def connection_cwd(endpoint: Path | WikiConnection) -> Path:
    return endpoint.workdir if isinstance(endpoint, WikiConnection) else endpoint


def command_for(endpoint: Path | WikiConnection, operation: str) -> list[str]:
    if operation not in OPERATIONS:
        raise ValueError("unknown connection operation")
    if isinstance(endpoint, WikiConnection):
        if operation not in endpoint.commands:
            raise ValueError("connection operation is not configured: " + operation)
        return list(endpoint.commands[operation])
    command = [sys.executable, "-m", "company_wiki.source_catalog." + _MODULES[operation]]
    if operation in {"transcript_import", "financial_statements"}:
        return [*command, "--wiki-root", str(endpoint)]
    return [*command, "--config", str(endpoint / "config/source_catalog.yaml")]


def acquisition_arguments(endpoint: Path | WikiConnection) -> list[str]:
    path = endpoint.acquisition_config if isinstance(endpoint, WikiConnection) else endpoint / "config/source_acquisition.yaml"
    return ["--allow-download", *(["--acquisition-config", str(path)] if path is not None else [])]


def connection_environment(endpoint: Path | WikiConnection) -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONUTF8"] = "1"
    if not isinstance(endpoint, WikiConnection):
        src = str(endpoint / "src")
        prior = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = src + (os.pathsep + prior if prior else "")
    return environment

WikiEndpoint = Path | WikiConnection
