"""FF is a bounded CWP client; it owns neither provider nor storage code."""
import ast
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
FORBIDDEN = {"company_wiki", "httpx", "requests", "urllib", "sqlite3", "pymupdf",
             "fitz", "docling", "sina_provider", "canonical_writer", "repository"}


def forbidden_imports(source):
    tree = ast.parse(source)
    aliases = {}
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = item.name
                imports.append(item.name)
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                name = (node.module or "") + "." + item.name
                aliases[item.asname or item.name] = name
                imports.append(name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        if isinstance(function, ast.Name):
            name = aliases.get(function.id, function.id)
        elif isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
            name = aliases.get(function.value.id, function.value.id) + "." + function.attr
        else:
            continue
        if name in {"__import__", "importlib.import_module"}:
            argument = node.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                imports.append(argument.value)
    return [name for name in imports if set(name.split(".")) & FORBIDDEN]


@pytest.mark.parametrize("filename", ["fetch_statements.py", "ff_financial_statements.py"])
def test_entrypoints_use_bounded_public_cwp_transport(filename):
    assert not forbidden_imports((SCRIPTS / filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize("source", [
    "import httpx as disguised", "from company_wiki.source_catalog import canonical_writer",
    "import importlib as i; i.import_module('sqlite3')",
    "from importlib import import_module as load; load('docling')",
    "__import__('sina_provider')",
])
def test_guard_detects_bypasses(source):
    assert forbidden_imports(source)


def test_request_files_and_public_module_name_are_allowed():
    assert not forbidden_imports("from pathlib import Path; import json; "
        "module='company_wiki.source_catalog.financial_statements.cli'")
