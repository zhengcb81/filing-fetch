"""Prove the final matrix sources through the real public CWP export/read ports."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

from cwp_readback_probe import read_source
from runtime import Deadline, run_process


PROOF_SCHEMA = "w06-fresh-source-proofs/2"
REF_FIELDS = ("document_id", "source_id", "content_sha256", "byte_size", "mime_type")


def export_sources(wiki_root, refs, *, env, deadline):
    command = [
        sys.executable, "-m", "company_wiki.source_catalog.source_export_v2_cli",
        "--config", str(wiki_root / "config/source_catalog.yaml"),
    ]
    request = {
        "schema_version": "2.0",
        "source_refs": [
            {"schema_version": "2.0", **{key: ref[key] for key in REF_FIELDS}} for ref in refs
        ],
        "evidence_spans": [],
    }
    proc = run_process(
        command, input=json.dumps(request).encode("utf-8"),
        env=env, cwd=wiki_root, deadline=deadline,
    )
    if proc.returncode != 0:
        raise ValueError(f"CWP source export rc={proc.returncode}: {proc.stderr.decode('utf-8', 'replace').strip()}")
    result = json.loads(proc.stdout)
    if result.get("schema_version") != "2.0.0" or not isinstance(result.get("manifests"), list):
        raise ValueError("CWP returned an unrecognized SourceExport receipt")
    return result["manifests"]


def _language_content_sha256(wiki_root, ref, *, env, deadline):
    raw = read_source(wiki_root, ref, env=env, deadline=deadline)
    if ref["mime_type"] == "application/json":
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            parsed = parsed[0] if parsed else None
        text = parsed.get("content") if isinstance(parsed, dict) else None
    else:
        text = raw.decode("utf-8")
    return (hashlib.sha256(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()
            if isinstance(text, str) else None)


def proves_reference(manifest, ref):
    return isinstance(manifest, dict) and all(manifest.get(key) == ref[key] for key in REF_FIELDS)


def prove_sources(wiki_root, references, *, env, deadline):
    # A single owner export verifies the original bytes and returns bound,
    # pathless manifests. Only transcripts need the binary port as well, to
    # check the original-language body independently of the manifest.
    refs = {}
    for reference in references:
        refs.setdefault(reference["document_id"], reference)
    findings = {}
    manifests = export_sources(wiki_root, refs.values(), env=env, deadline=deadline) if refs else []
    by_document = {row["document_id"]: row for row in manifests}
    for key, ref in refs.items():
        manifest = by_document.get(key)
        if not proves_reference(manifest, ref):
            findings[key] = {"verified": False, "error": "owner export did not attest to this exact reference"}
            continue
        try:
            language_sha = None
            if manifest.get("document_kind") == "investor_call_transcript" and ref["mime_type"] in {
                "application/json", "text/plain",
            }:
                language_sha = _language_content_sha256(wiki_root, ref, env=env, deadline=deadline)
            findings[key] = {
                "verified": True,
                "reference": ref,
                "manifest": manifest,
                "content_sha256": manifest["content_sha256"],
                "byte_size": manifest["byte_size"],
                "document_kind": manifest.get("document_kind"),
                "original_language_content_sha256": language_sha,
            }
        except (ValueError, OSError, TypeError) as exc:
            findings[key] = {"verified": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"schema_version": PROOF_SCHEMA, "proofs": findings}


def main():
    payload = json.load(sys.stdin)
    result = prove_sources(
        Path(payload["wiki"]), payload["refs"], env=dict(os.environ),
        deadline=Deadline(end=payload["deadline_end"]),
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
