"""Verify W20 read-back through the company-wiki public process ports."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from runtime import Deadline, _short_path, run_process, process_transport
from ff_company_wiki_connection import command_for
from matrix_outcome import source_ref


def read_source(wiki_root: Path, ref: dict, *, env: dict[str, str], deadline: Deadline) -> bytes:
    """Open one source through the binary CLI and bind bytes and receipt to the exact ref."""
    opened = run_process(
        [*command_for(wiki_root, "open"), "--exact-pair",
         "--document-id", ref["document_id"], "--source-id", ref["source_id"],
         "--content-sha256", ref["content_sha256"]],
        env=env, cwd=wiki_root, deadline=deadline,
    )
    receipt = json.loads(opened.stderr)
    if opened.returncode != 0 or receipt.get("status") != "ok":
        raise ValueError(f"open rc={opened.returncode} reason={receipt.get('reason')}")
    if receipt.get("schema_version") != "2.1" or any(
        receipt.get(key) != ref[key]
        for key in ("document_id", "source_id", "content_sha256", "byte_size")
    ):
        raise ValueError("open receipt did not bind the queried source")
    if len(opened.stdout) != ref["byte_size"] or hashlib.sha256(opened.stdout).hexdigest() != ref["content_sha256"]:
        raise ValueError("open bytes did not match the queried source")
    return opened.stdout


def probe_exact_source(
    wiki_root: Path, ref: dict[str, Any], *, env: dict[str, str], deadline: Deadline,
) -> dict[str, Any]:
    """Reopen an already observed SourceRef; no duplicate discovery is needed."""
    try:
        read_source(wiki_root, ref, env=env, deadline=deadline)
    except (OSError, ValueError, TypeError, AttributeError, process_transport.TransportError) as exc:
        return {"state": "probe_error", "ref": None, "error": f"{type(exc).__name__}: {exc}"[:300]}
    verified = {key: ref[key] for key in
                ("document_id", "source_id", "content_sha256", "byte_size", "mime_type")}
    return {"state": "confirmed", "ref": verified, "error": None}


def probe_catalog(
    *,
    wiki_root: Path,
    identity_request: dict[str, Any],
    content_sha: str,
    cwp_src: str,
    env: dict[str, str] | None = None,
    timeout_seconds: float = 30.0,
    deadline: Deadline | None = None,
) -> dict[str, Any]:
    """Distinguish a verified original, an authoritative miss and a probe fault."""
    result = {"state": "probe_error", "ref": None, "error": None}
    try:
        if env is None:
            env = {
                key: os.environ[key]
                for key in ("SystemRoot", "WINDIR", "COMSPEC", "PATH", "PATHEXT")
                if key in os.environ
            }
            owned_profile = str(wiki_root.parent / (wiki_root.name + "-probe-home"))
            env.update(
                HOME=owned_profile, USERPROFILE=owned_profile,
                APPDATA=owned_profile, LOCALAPPDATA=owned_profile, XDG_STATE_HOME=owned_profile,
                PYTHONDONTWRITEBYTECODE="1",
            )
        child_env = {**env, "PYTHONUTF8": "1"}
        existing_path = child_env.get("PYTHONPATH")
        paths = [str(_short_path(Path(cwp_src))), *(existing_path or "").split(os.pathsep)]
        child_env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(filter(None, paths)))
        # No product state belongs in the legacy project's real config or home.
        cwd = wiki_root
        limit = deadline or Deadline(timeout_seconds)
        lookup_request = {
            "schema_version": "company-wiki-transcript-import-lookup-request/1",
            "source_request": identity_request,
        }
        lookup = run_process(
            command_for(wiki_root, "query"), env=child_env, cwd=cwd, deadline=limit,
            input=json.dumps(lookup_request, ensure_ascii=False).encode("utf-8"),
        )
        data = json.loads(lookup.stdout)
        status = data.get("status")
        reason = data.get("reason")
        if lookup.returncode != 0 or data.get("schema_version") != "2.0":
            return {**result, "error": f"query rc={lookup.returncode} status={status} reason={reason}"}
        matches = data.get("matches")
        if status == "not_found" and matches == []:
            return {**result, "state": "not_found", "error": reason}
        if status not in {"found", "unknown_publication"} or not isinstance(matches, list) or len(matches) != 1:
            return {**result, "error": f"lookup did not return one source: {status} ({reason})"}
        ref = source_ref(matches[0])
        if ref is None:
            return {**result, "error": "query returned an incomplete source reference"}
        if ref["content_sha256"] != content_sha:
            return {**result, "state": "not_found", "error": "another original matched the lookup"}
        return probe_exact_source(wiki_root, ref, env=child_env, deadline=limit)
    except (OSError, ValueError, TypeError, AttributeError, process_transport.TransportError) as exc:
        return {**result, "error": f"{type(exc).__name__}: {exc}"[:300]}
