"""Isolated CWP public read-back probe (return R2, FF-R2-2).

One bounded subprocess per probe call: the parent's ``sys.stdin``/``sys.stdout``
are never touched, exceptions stay inside this process, and the result carries
an EXPLICIT state — ``confirmed`` (this request's Ref read back byte-for-byte
through the public query + verified open), ``not_found`` (the public query
answered and this request's Ref is not durably readable), or ``probe_error``
(the probe itself failed; NEVER usable as a not-durable negative).

stdin JSON : {"wiki": abs, "cwp_src": abs, "identity_request": {...},
              "content_sha": hex}
stdout JSON: {"state": "confirmed|not_found|probe_error",
              "ref": {...}|null, "error": str|null}
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
from dataclasses import fields as dc_fields
from pathlib import Path


def main() -> int:
    payload = json.load(sys.stdin)
    wiki = Path(payload["wiki"])
    cwp_src = Path(payload["cwp_src"])
    content_sha = payload["content_sha"]
    identity_request = payload["identity_request"]
    if str(cwp_src) not in sys.path:
        sys.path.insert(0, str(cwp_src))
    result: dict = {"state": "probe_error", "ref": None, "error": None}
    try:
        from company_wiki.source_catalog.config import load_catalog_config
        from company_wiki.source_catalog.service import SourceCatalog
        from company_wiki.source_catalog.source_query_cli import main as query_main
        from company_wiki.source_catalog.source_reader import SourceRef, SourceVersionReader

        # The provider-scoped transcript-import lookup envelope — the same
        # public path FF's duplicate-suppression reuse uses. It includes
        # unknown-publication sources and is not subject to the plain
        # query's as-of eligibility exclusion (a stored future-period
        # original must still be readable back).
        lookup = {
            "schema_version": "company-wiki-transcript-import-lookup-request/1",
            "source_request": identity_request,
        }
        out = io.StringIO()
        saved_stdin = sys.stdin
        sys.stdin = io.TextIOWrapper(
            io.BytesIO(json.dumps(lookup, ensure_ascii=False).encode("utf-8")),
            encoding="utf-8")
        try:
            with contextlib.redirect_stdout(out):
                code = query_main(["--config", str(wiki / "config" / "source_catalog.yaml")])
        finally:
            sys.stdin = saved_stdin
        if code != 0:
            result["error"] = f"query rc={code} out={out.getvalue()[:200]}"
        else:
            data = json.loads(out.getvalue())
            status = data.get("status")
            if status not in ("found", "unknown_publication") or len(data.get("matches") or []) != 1:
                result["state"] = "not_found"
                result["error"] = (f"status={status} reason={data.get('reason')} "
                                   f"matches={len(data.get('matches') or [])}")
            else:
                ref = data["matches"][0]
                if ref.get("content_sha256") != content_sha:
                    result["state"] = "not_found"
                    result["error"] = (f"sha mismatch {str(ref.get('content_sha256'))[:16]} "
                                       f"!= {content_sha[:16]} (another source matched)")
                else:
                    catalog = SourceCatalog(load_catalog_config(
                        wiki / "config" / "source_catalog.yaml", project_root=wiki))
                    try:
                        reader = SourceVersionReader(catalog)
                        kwargs = {f.name: ref[f.name]
                                  for f in dc_fields(SourceRef) if f.name in ref}
                        verified = reader.open_version(SourceRef(**kwargs))
                        digest = hashlib.sha256(verified.data).hexdigest()
                        if digest != content_sha or len(verified.data) != ref.get("byte_size"):
                            result["state"] = "not_found"
                            result["error"] = (f"readback mismatch digest={digest[:16]} "
                                               f"len={len(verified.data)}")
                        else:
                            result["state"] = "confirmed"
                            result["ref"] = {
                                "document_id": ref["document_id"],
                                "source_id": ref["source_id"],
                                "content_sha256": digest,
                                "byte_size": len(verified.data),
                                "mime_type": ref.get("mime_type"),
                            }
                    finally:
                        catalog.close()
    except Exception as exc:  # noqa: BLE001 — the probe owns and reports its own failure
        result["state"] = "probe_error"
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
